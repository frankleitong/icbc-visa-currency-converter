#!/usr/bin/env python3
"""Convert a TRY Visa purchase to an estimated RMB repayment via ICBC rates."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


VISA_CALCULATOR_PAGE = (
    "https://usa.visa.com/support/consumer/travel-support/"
    "exchange-rate-calculator.html"
)
VISA_API_HOSTS = (
    "www.visa.co.uk",
    "www.visa.com.hk",
    "www.visa.ca",
    "www.visa.com.au",
    "www.visa.co.nz",
)
ICBC_FX_PAGE = "https://www.icbc.com.cn/column/1438058341489590354.html"
ICBC_LATEST_API = "https://papi.icbc.com.cn/exchanges/ns/getLatest"
ICBC_HISTORY_API = "https://papi.icbc.com.cn/exchanges/ns/history"
GOOGLE_FINANCE_TRY_USD = "https://www.google.com/finance/quote/TRY-USD"
FRANKFURTER_API = "https://api.frankfurter.app"
EXCHANGERATE_API_TRY = "https://open.er-api.com/v6/latest/TRY"


class ConverterError(RuntimeError):
    pass


def request_headers() -> dict[str, str]:
    return {
        "Accept": "application/json,text/plain,text/html,*/*",
        "Content-Type": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0 Safari/537.36"
        ),
    }


def decimal_arg(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"invalid decimal: {value}") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("amount/rate must be non-negative")
    return parsed


def money(value: Decimal, places: str = "0.01") -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: int = 20,
) -> dict[str, Any]:
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    last_error: urllib.error.URLError | None = None
    for attempt in range(3):
        request = urllib.request.Request(url, data=body, headers=request_headers(), method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                content_type = response.headers.get("content-type", "")
                break
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            text = raw.decode("utf-8", errors="replace")
            if exc.code in (403, 429) or "Just a moment" in text or "cloudflare" in text.lower():
                raise ConverterError(
                    f"official endpoint blocked automated access with HTTP {exc.code}: {url}"
                ) from exc
            raise ConverterError(f"request failed: {url}: HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.4 * (attempt + 1))
                continue
            raise ConverterError(f"request failed: {url}: {last_error}") from exc

    text = raw.decode("utf-8", errors="replace").strip()
    if "application/json" not in content_type and not text.startswith(("{", "[")):
        if "Just a moment" in text or "cloudflare" in text.lower():
            raise ConverterError(
                "official Visa endpoint returned a Cloudflare challenge. "
                "Open the source URL in a browser or pass --visa-usd-amount "
                "or --visa-rate manually."
            )
        raise ConverterError(f"expected JSON from {url}, got {content_type or 'unknown'}")

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConverterError(f"could not parse JSON from {url}") from exc
    if not isinstance(data, dict):
        raise ConverterError(f"unexpected JSON shape from {url}")
    return data


def request_text(url: str, *, timeout: int = 20) -> str:
    last_error: urllib.error.URLError | None = None
    for attempt in range(3):
        request = urllib.request.Request(url, headers=request_headers(), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                break
        except urllib.error.HTTPError as exc:
            raise ConverterError(f"request failed: {url}: HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.4 * (attempt + 1))
                continue
            raise ConverterError(f"request failed: {url}: {last_error}") from exc
    return raw.decode("utf-8", errors="replace")


def visa_api_url(host: str, amount: Decimal, purchase_date: dt.date, fee: Decimal) -> str:
    date_text = purchase_date.strftime("%m/%d/%Y")
    params = {
        "amount": str(amount),
        "fee": str(fee),
        "utcConvertedDate": date_text,
        "exchangedate": date_text,
        "fromCurr": "TRY",
        "toCurr": "USD",
    }
    return f"https://{host}/cmsapi/fx/rates?{urllib.parse.urlencode(params)}"


def extract_visa_converted_amount(data: dict[str, Any]) -> Decimal:
    candidates = [data]
    nested = data.get("data")
    if isinstance(nested, dict):
        candidates.insert(0, nested)

    keys = (
        "convertedAmount",
        "destinationAmount",
        "toAmount",
        "amountConverted",
        "conversionAmount",
    )
    for candidate in candidates:
        for key in keys:
            value = candidate.get(key)
            if value is not None:
                return Decimal(str(value).replace(",", ""))

    raise ConverterError(
        "Visa JSON did not contain a recognized converted amount field. "
        f"Keys seen: {sorted(data.keys())}"
    )


def fetch_visa_usd_amount(
    amount_try: Decimal, purchase_date: dt.date, fee: Decimal, host: str | None
) -> tuple[Decimal, str]:
    hosts = (host,) if host else VISA_API_HOSTS
    errors: list[str] = []
    for api_host in hosts:
        url = visa_api_url(api_host, amount_try, purchase_date, fee)
        try:
            data = request_json(url)
            return extract_visa_converted_amount(data), url
        except ConverterError as exc:
            errors.append(str(exc))
    raise ConverterError(
        "Visa official endpoints could not be fetched automatically. "
        "Use the official Visa calculator page, then rerun with "
        "--visa-usd-amount or --visa-rate. "
        f"Calculator: {VISA_CALCULATOR_PAGE}. "
        f"Last error: {errors[-1] if errors else 'none'}"
    )


def fetch_google_finance_try_usd_rate() -> tuple[Decimal, str]:
    text = request_text(GOOGLE_FINANCE_TRY_USD)
    matches = re.findall(r"([0-9]+\.[0-9]+),\"TRY / USD\"", text)
    if not matches:
        raise ConverterError("Google Finance TRY/USD rate was not found in the page")
    return Decimal(matches[-1]), GOOGLE_FINANCE_TRY_USD


def fetch_frankfurter_try_usd_rate(rate_date: dt.date) -> tuple[Decimal, str]:
    date_part = "latest" if rate_date == dt.date.today() else rate_date.isoformat()
    url = f"{FRANKFURTER_API}/{date_part}?{urllib.parse.urlencode({'from': 'TRY', 'to': 'USD'})}"
    data = request_json(url)
    rates = data.get("rates")
    if not isinstance(rates, dict) or rates.get("USD") is None:
        raise ConverterError("Frankfurter response did not include TRY/USD")
    return Decimal(str(rates["USD"])), url


def fetch_exchangerate_try_usd_rate() -> tuple[Decimal, str]:
    data = request_json(EXCHANGERATE_API_TRY)
    rates = data.get("rates")
    if data.get("result") != "success" or not isinstance(rates, dict) or rates.get("USD") is None:
        raise ConverterError("ExchangeRate response did not include TRY/USD")
    return Decimal(str(rates["USD"])), EXCHANGERATE_API_TRY


def fetch_market_try_usd_rate(rate_date: dt.date) -> tuple[Decimal, str, str]:
    errors: list[str] = []
    if rate_date == dt.date.today():
        try:
            rate, source = fetch_google_finance_try_usd_rate()
            return rate, "Google Finance TRY/USD market rate", source
        except ConverterError as exc:
            errors.append(str(exc))

    try:
        rate, source = fetch_frankfurter_try_usd_rate(rate_date)
        return rate, "Frankfurter TRY/USD market rate", source
    except ConverterError as exc:
        errors.append(str(exc))

    if rate_date == dt.date.today():
        try:
            rate, source = fetch_exchangerate_try_usd_rate()
            return rate, "ExchangeRate TRY/USD market rate", source
        except ConverterError as exc:
            errors.append(str(exc))

    raise ConverterError(
        "No TRY/USD fallback market source could be fetched. "
        f"Last error: {errors[-1] if errors else 'none'}"
    )


def fetch_visa_or_market_usd_amount(
    amount_try: Decimal,
    purchase_date: dt.date,
    fee: Decimal,
    host: str | None,
    market_buffer_percent: Decimal = Decimal("0.8"),
) -> tuple[Decimal, str, str | None]:
    try:
        visa_usd, source = fetch_visa_usd_amount(amount_try, purchase_date, fee, host)
        return visa_usd, source, None
    except ConverterError:
        rate, label, source = fetch_market_try_usd_rate(purchase_date)
        buffer_multiplier = Decimal("1") + (market_buffer_percent / Decimal("100"))
        adjusted_rate = rate * buffer_multiplier
        usd_amount = amount_try * adjusted_rate
        return (
            usd_amount,
            f"{label} + {market_buffer_percent}% Visa estimate buffer: {source}",
            "Visa blocked automatic access, so this uses a market TRY/USD rate "
            f"plus a {market_buffer_percent}% buffer to approximate Visa's less "
            "favorable card-settlement rate. The final statement amount may "
            "still differ from Visa/ICBC billing.",
        )


def extract_icbc_usd_row(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("code") != 0:
        raise ConverterError(f"ICBC API returned code={data.get('code')}: {data.get('message')}")
    rows = data.get("data")
    if not isinstance(rows, list):
        raise ConverterError("ICBC API response has no data list")
    for row in rows:
        if isinstance(row, dict) and row.get("currencyENName") == "USD":
            return row
    raise ConverterError("ICBC API response did not include USD")


def fetch_icbc_usd_row(quote_date: dt.date | None) -> tuple[dict[str, Any], str]:
    if quote_date is None:
        return extract_icbc_usd_row(request_json(ICBC_LATEST_API, method="POST")), ICBC_LATEST_API

    payload = {
        "date": quote_date.isoformat(),
        "currType": "014",
        "serverType": "1",
    }
    return (
        extract_icbc_usd_row(request_json(ICBC_HISTORY_API, method="POST", payload=payload)),
        ICBC_HISTORY_API,
    )


def parse_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must be YYYY-MM-DD") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Estimate RMB repayment for an ICBC-issued Visa purchase made in TRY. "
            "Visa converts TRY to USD; ICBC's bank selling rate prices the USD "
            "you need to buy for repayment."
        )
    )
    parser.add_argument("amount_try", type=decimal_arg, help="purchase amount in Turkish lira")
    parser.add_argument(
        "--purchase-date",
        type=parse_date,
        default=dt.date.today(),
        help="Visa exchange date, YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--visa-bank-fee",
        type=decimal_arg,
        default=Decimal("0"),
        help="bank fee percentage used by Visa calculator (default: 0)",
    )
    parser.add_argument(
        "--try-tax-rate",
        type=decimal_arg,
        default=Decimal("3.3"),
        help="tax percentage added to TRY before conversion (default: 3.3)",
    )
    parser.add_argument(
        "--visa-host",
        choices=VISA_API_HOSTS,
        help="official Visa regional host to try first",
    )
    parser.add_argument(
        "--market-fallback-buffer",
        type=decimal_arg,
        default=Decimal("0.8"),
        help="extra percentage added when Visa is blocked and market FX fallback is used",
    )
    parser.add_argument(
        "--visa-usd-amount",
        type=decimal_arg,
        help="manual USD amount from Visa calculator; skips Visa fetch",
    )
    parser.add_argument(
        "--visa-rate",
        type=decimal_arg,
        help="manual Visa rate as USD per 1 TRY; skips Visa fetch",
    )
    parser.add_argument(
        "--icbc-date",
        type=parse_date,
        help="ICBC quote date, YYYY-MM-DD (default: latest)",
    )
    parser.add_argument(
        "--icbc-field",
        choices=("foreignBuy", "foreignSell", "cashBuy", "cashSell", "reference"),
        default="foreignSell",
        help=(
            "ICBC USD quote field to use (default: foreignSell, "
            "银行卖出价 for buying USD with RMB)"
        ),
    )
    parser.add_argument(
        "--icbc-rate",
        type=decimal_arg,
        help="manual ICBC RMB-per-100-USD rate; skips ICBC fetch",
    )
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.visa_usd_amount is not None and args.visa_rate is not None:
        parser.error("use only one of --visa-usd-amount or --visa-rate")

    amount_try: Decimal = args.amount_try
    tax_multiplier = Decimal("1") + (args.try_tax_rate / Decimal("100"))
    taxed_amount_try = amount_try * tax_multiplier
    if args.visa_usd_amount is not None:
        visa_usd = args.visa_usd_amount
        visa_source = "manual --visa-usd-amount"
        warning = None
    elif args.visa_rate is not None:
        visa_usd = taxed_amount_try * args.visa_rate
        visa_source = "manual --visa-rate"
        warning = None
    else:
        visa_usd, visa_source, warning = fetch_visa_or_market_usd_amount(
            taxed_amount_try,
            args.purchase_date,
            args.visa_bank_fee,
            args.visa_host,
            args.market_fallback_buffer,
        )

    if args.icbc_rate is not None:
        icbc_rate_per_100 = args.icbc_rate
        icbc_row = {
            "currencyENName": "USD",
            "publishDate": None,
            "publishTime": None,
            args.icbc_field: str(args.icbc_rate),
        }
        icbc_source = "manual --icbc-rate"
    else:
        icbc_row, icbc_source = fetch_icbc_usd_row(args.icbc_date)
        icbc_rate_per_100 = Decimal(str(icbc_row[args.icbc_field]).replace(",", ""))

    usd_per_try = visa_usd / taxed_amount_try if taxed_amount_try else Decimal("0")
    rmb_per_usd = icbc_rate_per_100 / Decimal("100")
    rmb_repayment = visa_usd * rmb_per_usd

    result = {
        "amount_try": str(amount_try),
        "try_tax_rate": str(args.try_tax_rate),
        "taxed_amount_try": str(money(taxed_amount_try)),
        "purchase_date": args.purchase_date.isoformat(),
        "visa_usd_amount": str(money(visa_usd)),
        "visa_usd_per_try": str(usd_per_try.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)),
        "visa_source": visa_source,
        "icbc_field": args.icbc_field,
        "icbc_rate_rmb_per_100_usd": str(icbc_rate_per_100),
        "icbc_rate_rmb_per_usd": str(rmb_per_usd),
        "icbc_publish_date": icbc_row.get("publishDate"),
        "icbc_publish_time": icbc_row.get("publishTime"),
        "icbc_source": icbc_source,
        "estimated_rmb_repayment": str(money(rmb_repayment)),
        "warning": warning,
        "official_pages": {
            "visa_calculator": VISA_CALCULATOR_PAGE,
            "icbc_fx_quotes": ICBC_FX_PAGE,
        },
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"TRY purchase: {amount_try} TRY")
    print(f"TRY after tax: {money(taxed_amount_try)} TRY ({args.try_tax_rate}% tax)")
    print(f"Visa TRY -> USD: {money(visa_usd)} USD ({result['visa_usd_per_try']} USD/TRY)")
    print(f"Visa source: {visa_source}")
    print(
        "ICBC USD rate: "
        f"{icbc_rate_per_100} RMB / 100 USD "
        f"({args.icbc_field}, {icbc_row.get('publishDate') or 'manual'} "
        f"{icbc_row.get('publishTime') or ''})"
    )
    print(f"ICBC source: {icbc_source}")
    print(f"Estimated RMB repayment: {money(rmb_repayment)} RMB")
    if warning:
        print(f"Warning: {warning}")
    print()
    print(f"Official Visa calculator: {VISA_CALCULATOR_PAGE}")
    print(f"Official ICBC FX quotes: {ICBC_FX_PAGE}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except ConverterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
