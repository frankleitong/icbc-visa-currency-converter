#!/usr/bin/env python3
"""Local UI for the ICBC Visa TRY -> USD -> RMB converter."""

from __future__ import annotations

import datetime as dt
import json
import sys
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from icbc_visa_currency_converter import (  # noqa: E402
    ConverterError,
    ICBC_FX_PAGE,
    VISA_API_HOSTS,
    VISA_CALCULATOR_PAGE,
    fetch_icbc_usd_row,
    fetch_visa_or_market_usd_amount,
    money,
)


DEFAULT_PORT = 8766
ICBC_FIELDS = {
    "foreignSell": "Bank selling rate / 银行卖出价",
    "foreignBuy": "Bank buying rate / 银行买入价",
    "cashSell": "Cash selling rate / 现钞卖出价",
    "cashBuy": "Cash buying rate / 现钞买入价",
    "reference": "Reference rate / 中间价",
}


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ICBC Visa Currency Converter</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --surface: #ffffff;
      --line: #d8dde5;
      --text: #18202b;
      --muted: #5e6b7b;
      --accent: #b31b2c;
      --accent-2: #245d63;
      --focus: #0f6ca6;
      --warn-bg: #fff6df;
      --warn-line: #e0bf67;
      --error-bg: #fff0f0;
      --error-line: #d67b7b;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 15px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }

    main {
      width: min(1180px, calc(100vw - 32px));
      margin: 24px auto 40px;
    }

    header {
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 24px;
      margin-bottom: 18px;
    }

    h1 {
      margin: 0;
      font-size: 28px;
      font-weight: 700;
      letter-spacing: 0;
    }

    .subtitle {
      margin: 4px 0 0;
      color: var(--muted);
    }

    .source-links {
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }

    a {
      color: var(--focus);
      text-decoration: none;
    }

    a:hover { text-decoration: underline; }

    .layout {
      display: grid;
      grid-template-columns: minmax(320px, 420px) minmax(0, 1fr);
      gap: 18px;
      align-items: start;
    }

    .panel {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
    }

    .panel h2 {
      margin: 0 0 14px;
      font-size: 16px;
      letter-spacing: 0;
    }

    .form-grid {
      display: grid;
      gap: 14px;
    }

    label {
      display: grid;
      gap: 6px;
      color: var(--muted);
      font-size: 13px;
    }

    input,
    select {
      width: 100%;
      height: 38px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 0 10px;
      color: var(--text);
      background: #fff;
      font: inherit;
    }

    input:focus,
    select:focus,
    button:focus {
      outline: 2px solid color-mix(in srgb, var(--focus) 35%, transparent);
      outline-offset: 1px;
    }

    .two-col {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
    }

    .mode-fields {
      display: none;
    }

    .mode-fields.active {
      display: grid;
      gap: 12px;
    }

    .actions {
      display: flex;
      gap: 10px;
      align-items: center;
      margin-top: 4px;
    }

    button {
      height: 38px;
      border: 1px solid var(--accent);
      border-radius: 6px;
      padding: 0 14px;
      background: var(--accent);
      color: #fff;
      font: inherit;
      font-weight: 650;
      cursor: pointer;
    }

    button.secondary {
      background: #fff;
      color: var(--accent);
    }

    button:disabled {
      opacity: .6;
      cursor: wait;
    }

    .result-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }

    .metric {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      min-height: 104px;
      background: #fff;
    }

    .metric.primary {
      border-color: color-mix(in srgb, var(--accent) 45%, var(--line));
      background: #fff8f8;
    }

    .metric strong {
      display: block;
      margin-bottom: 8px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 600;
    }

    .metric .value {
      font-size: 28px;
      font-weight: 760;
      line-height: 1.05;
      word-break: break-word;
    }

    .metric .small {
      margin-top: 8px;
      color: var(--muted);
      font-size: 12px;
    }

    .status {
      margin-top: 14px;
      padding: 12px;
      border-radius: 8px;
      border: 1px solid var(--line);
      color: var(--muted);
      background: #fff;
      min-height: 45px;
    }

    .status.warning {
      color: #6f5310;
      background: var(--warn-bg);
      border-color: var(--warn-line);
    }

    .status.error {
      color: #8d2323;
      background: var(--error-bg);
      border-color: var(--error-line);
    }

    .meta {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px 14px;
      margin-top: 14px;
      color: var(--muted);
      font-size: 13px;
    }

    .meta b {
      color: var(--text);
      font-weight: 650;
    }

    @media (max-width: 850px) {
      header,
      .layout {
        display: block;
      }

      .source-links {
        justify-content: flex-start;
        margin-top: 10px;
      }

      .panel {
        margin-bottom: 14px;
      }
    }

    @media (max-width: 560px) {
      main {
        width: min(100vw - 20px, 1180px);
        margin-top: 12px;
      }

      .two-col,
      .result-grid,
      .meta {
        grid-template-columns: 1fr;
      }

      h1 {
        font-size: 23px;
      }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>ICBC Visa Currency Converter</h1>
        <p class="subtitle">TRY purchase -> USD settlement estimate -> RMB repayment with ICBC bank selling rate.</p>
      </div>
      <div class="source-links">
        <a href="__VISA_PAGE__" target="_blank" rel="noreferrer">Visa calculator</a>
        <a href="__ICBC_PAGE__" target="_blank" rel="noreferrer">ICBC FX quotes</a>
      </div>
    </header>

    <section class="layout">
      <form id="converter-form" class="panel">
        <h2>Inputs</h2>
        <div class="form-grid">
          <label>
            Lira amount (TRY)
            <input id="amount-try" name="amount_try" type="number" min="0" step="0.01" value="1000" required>
          </label>

          <div class="two-col">
            <label>
              TRY tax rate %
              <input name="try_tax_rate" type="number" min="0" step="0.01" value="3.3">
            </label>
            <label>
              Taxed TRY amount
              <input id="taxed-try-preview" type="text" value="--" readonly>
            </label>
          </div>

          <div class="two-col">
            <label>
              Purchase date
              <input id="purchase-date" name="purchase_date" type="date" required>
            </label>
            <label>
              ICBC quote date
              <input id="icbc-date" name="icbc_date" type="date" required>
            </label>
          </div>

          <label>
            Visa conversion source
            <select id="visa-mode" name="visa_mode">
              <option value="auto">Automatic: Visa first, market fallback</option>
              <option value="usdAmount">Manual USD amount from Visa</option>
              <option value="rate">Manual TRY -> USD rate</option>
            </select>
          </label>

          <div id="visa-auto-fields" class="mode-fields active">
            <div class="two-col">
              <label>
                Visa bank fee %
                <input name="visa_fee" type="number" min="0" step="0.01" value="0">
              </label>
              <label>
                Market fallback buffer %
                <input name="market_buffer" type="number" min="0" step="0.01" value="0.8">
              </label>
            </div>
            <div class="two-col">
              <label>
                Visa host
                <select name="visa_host">
                  __VISA_HOST_OPTIONS__
                </select>
              </label>
            </div>
          </div>

          <div id="visa-usd-fields" class="mode-fields">
            <label>
              USD amount shown by Visa
              <input name="visa_usd_amount" type="number" min="0" step="0.01" placeholder="e.g. 25.00">
            </label>
          </div>

          <div id="visa-rate-fields" class="mode-fields">
            <label>
              TRY -> USD rate
              <input name="visa_rate" type="number" min="0" step="0.000001" placeholder="e.g. 0.025000">
            </label>
          </div>

          <div class="two-col">
            <label>
              ICBC rate field
              <select name="icbc_field">
                <option value="foreignSell" selected>银行卖出价 / foreignSell</option>
                <option value="foreignBuy">银行买入价 / foreignBuy</option>
                <option value="cashSell">现钞卖出价 / cashSell</option>
                <option value="cashBuy">现钞买入价 / cashBuy</option>
                <option value="reference">中间价 / reference</option>
              </select>
            </label>
            <label>
              Manual ICBC rate
              <input name="icbc_rate" type="number" min="0" step="0.01" placeholder="RMB per 100 USD">
            </label>
          </div>

          <div class="actions">
            <button id="calculate-button" type="submit">Calculate</button>
            <button class="secondary" id="reset-button" type="button">Reset</button>
          </div>
        </div>
      </form>

      <section class="panel">
        <h2>Result</h2>
        <div class="result-grid">
          <div class="metric">
            <strong>USD settlement</strong>
            <div id="usd-amount" class="value">--</div>
            <div class="small">TRY converted into USD</div>
          </div>
          <div class="metric">
            <strong>TRY -> USD rate</strong>
            <div id="try-usd-rate" class="value">--</div>
            <div class="small">1 TRY in USD</div>
          </div>
          <div class="metric">
            <strong>ICBC USD -> RMB</strong>
            <div id="usd-rmb-rate" class="value">--</div>
            <div id="rmb-usd-rate" class="small">1 RMB = -- USD</div>
          </div>
          <div class="metric primary">
            <strong>Estimated RMB repayment</strong>
            <div id="rmb-total" class="value">--</div>
            <div class="small">Uses ICBC bank selling rate by default</div>
          </div>
        </div>
        <div id="status" class="status">Ready.</div>
        <div class="meta">
          <div>TRY after tax: <b id="taxed-try">--</b></div>
          <div>TRY tax rate: <b id="try-tax-rate">3.3%</b></div>
          <div>Visa source: <b id="visa-source">--</b></div>
          <div>ICBC source: <b id="icbc-source">--</b></div>
          <div>ICBC field: <b id="icbc-field">foreignSell</b></div>
          <div>ICBC publish time: <b id="icbc-publish">--</b></div>
        </div>
      </section>
    </section>
  </main>

  <script>
    const form = document.querySelector("#converter-form");
    const visaMode = document.querySelector("#visa-mode");
    const calculateButton = document.querySelector("#calculate-button");
    const statusBox = document.querySelector("#status");

    const fields = {
      usdAmount: document.querySelector("#usd-amount"),
      tryUsdRate: document.querySelector("#try-usd-rate"),
      usdRmbRate: document.querySelector("#usd-rmb-rate"),
      rmbUsdRate: document.querySelector("#rmb-usd-rate"),
      rmbTotal: document.querySelector("#rmb-total"),
      taxedTry: document.querySelector("#taxed-try"),
      tryTaxRate: document.querySelector("#try-tax-rate"),
      visaSource: document.querySelector("#visa-source"),
      icbcSource: document.querySelector("#icbc-source"),
      icbcField: document.querySelector("#icbc-field"),
      icbcPublish: document.querySelector("#icbc-publish"),
    };

    function today() {
      const now = new Date();
      const offset = now.getTimezoneOffset() * 60000;
      return new Date(now.getTime() - offset).toISOString().slice(0, 10);
    }

    function setDefaultDates() {
      const current = today();
      document.querySelector("#purchase-date").value = current;
      document.querySelector("#icbc-date").value = current;
    }

    function updateVisaMode() {
      document.querySelectorAll(".mode-fields").forEach((node) => node.classList.remove("active"));
      const mode = visaMode.value;
      if (mode === "usdAmount") document.querySelector("#visa-usd-fields").classList.add("active");
      else if (mode === "rate") document.querySelector("#visa-rate-fields").classList.add("active");
      else document.querySelector("#visa-auto-fields").classList.add("active");
    }

    function updateTaxPreview() {
      const amount = Number(document.querySelector("#amount-try").value || 0);
      const taxRate = Number(document.querySelector('input[name="try_tax_rate"]').value || 0);
      const taxed = amount * (1 + taxRate / 100);
      document.querySelector("#taxed-try-preview").value = `${taxed.toFixed(2)} TRY`;
    }

    function setStatus(message, kind = "") {
      statusBox.textContent = message;
      statusBox.className = kind ? `status ${kind}` : "status";
    }

    function setResult(data) {
      fields.usdAmount.textContent = `${data.visa_usd_amount} USD`;
      fields.tryUsdRate.textContent = data.visa_usd_per_try;
      fields.usdRmbRate.textContent = `${data.icbc_rate_rmb_per_usd} RMB`;
      fields.rmbUsdRate.textContent = `1 RMB = ${data.icbc_rate_usd_per_rmb} USD`;
      fields.rmbTotal.textContent = `${data.estimated_rmb_repayment} RMB`;
      fields.taxedTry.textContent = `${data.taxed_amount_try} TRY`;
      fields.tryTaxRate.textContent = `${data.try_tax_rate}%`;
      fields.visaSource.textContent = data.visa_source;
      fields.icbcSource.textContent = data.icbc_source_label;
      fields.icbcField.textContent = data.icbc_field;
      fields.icbcPublish.textContent = data.icbc_publish_date
        ? `${data.icbc_publish_date} ${data.icbc_publish_time || ""}`.trim()
        : "manual";
    }

    async function calculate() {
      const params = new URLSearchParams(new FormData(form));
      calculateButton.disabled = true;
      setStatus("Calculating...");
      try {
        const response = await fetch(`/api/convert?${params.toString()}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Calculation failed");
        setResult(data);
        setStatus(data.warning || "Calculated with current options.", data.warning ? "warning" : "");
      } catch (error) {
        setStatus(error.message, "error");
      } finally {
        calculateButton.disabled = false;
      }
    }

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      calculate();
    });
    visaMode.addEventListener("change", updateVisaMode);
    document.querySelector("#amount-try").addEventListener("input", updateTaxPreview);
    document.querySelector('input[name="try_tax_rate"]').addEventListener("input", updateTaxPreview);
    document.querySelector("#reset-button").addEventListener("click", () => {
      form.reset();
      setDefaultDates();
      updateVisaMode();
      updateTaxPreview();
      setStatus("Ready.");
    });

    setDefaultDates();
    updateVisaMode();
    updateTaxPreview();
    calculate();
  </script>
</body>
</html>
"""


def parse_decimal(params: dict[str, list[str]], name: str, default: str | None = None) -> Decimal:
    value = params.get(name, [default])[0]
    if value in (None, ""):
        raise ConverterError(f"{name} is required")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ConverterError(f"{name} must be a number") from exc
    if parsed < 0:
        raise ConverterError(f"{name} must be non-negative")
    return parsed


def parse_date_param(params: dict[str, list[str]], name: str) -> dt.date:
    value = params.get(name, [dt.date.today().isoformat()])[0]
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ConverterError(f"{name} must be YYYY-MM-DD") from exc


def decimal_text(value: Decimal, places: str = "0.000001") -> str:
    return str(value.quantize(Decimal(places), rounding=ROUND_HALF_UP))


def calculate(params: dict[str, list[str]]) -> dict[str, object]:
    amount_try = parse_decimal(params, "amount_try")
    try_tax_rate = parse_decimal(params, "try_tax_rate", "3.3")
    tax_multiplier = Decimal("1") + (try_tax_rate / Decimal("100"))
    taxed_amount_try = amount_try * tax_multiplier
    purchase_date = parse_date_param(params, "purchase_date")
    icbc_date = parse_date_param(params, "icbc_date")
    visa_mode = params.get("visa_mode", ["auto"])[0]
    icbc_field = params.get("icbc_field", ["foreignSell"])[0]
    if icbc_field not in ICBC_FIELDS:
        raise ConverterError("unsupported ICBC rate field")

    if visa_mode == "usdAmount":
        visa_usd = parse_decimal(params, "visa_usd_amount")
        visa_source = "Manual Visa USD amount"
        warning = None
    elif visa_mode == "rate":
        visa_rate = parse_decimal(params, "visa_rate")
        visa_usd = taxed_amount_try * visa_rate
        visa_source = "Manual TRY -> USD rate"
        warning = None
    elif visa_mode == "auto":
        visa_fee = parse_decimal(params, "visa_fee", "0")
        market_buffer = parse_decimal(params, "market_buffer", "0.8")
        visa_host = params.get("visa_host", [""])[0] or None
        visa_usd, visa_source, warning = fetch_visa_or_market_usd_amount(
            taxed_amount_try, purchase_date, visa_fee, visa_host, market_buffer
        )
    else:
        raise ConverterError("unsupported Visa conversion source")

    manual_icbc_rate = params.get("icbc_rate", [""])[0]
    if manual_icbc_rate:
        icbc_rate_per_100 = parse_decimal(params, "icbc_rate")
        icbc_row = {"publishDate": None, "publishTime": None}
        icbc_source = "Manual ICBC rate"
        icbc_source_label = "manual"
    else:
        quote_date = None if icbc_date == dt.date.today() else icbc_date
        icbc_row, icbc_source = fetch_icbc_usd_row(quote_date)
        icbc_rate_per_100 = Decimal(str(icbc_row[icbc_field]).replace(",", ""))
        icbc_source_label = "official latest" if quote_date is None else "official history"

    usd_per_try = visa_usd / taxed_amount_try if taxed_amount_try else Decimal("0")
    rmb_per_usd = icbc_rate_per_100 / Decimal("100")
    usd_per_rmb = Decimal("1") / rmb_per_usd if rmb_per_usd else Decimal("0")
    rmb_repayment = visa_usd * rmb_per_usd

    return {
        "amount_try": str(amount_try),
        "try_tax_rate": str(try_tax_rate),
        "taxed_amount_try": str(money(taxed_amount_try)),
        "purchase_date": purchase_date.isoformat(),
        "visa_usd_amount": str(money(visa_usd)),
        "visa_usd_per_try": decimal_text(usd_per_try),
        "visa_source": visa_source,
        "icbc_field": f"{icbc_field} ({ICBC_FIELDS[icbc_field]})",
        "icbc_rate_rmb_per_100_usd": str(icbc_rate_per_100),
        "icbc_rate_rmb_per_usd": decimal_text(rmb_per_usd, "0.0001"),
        "icbc_rate_usd_per_rmb": decimal_text(usd_per_rmb, "0.000001"),
        "icbc_publish_date": icbc_row.get("publishDate"),
        "icbc_publish_time": icbc_row.get("publishTime"),
        "icbc_source": icbc_source,
        "icbc_source_label": icbc_source_label,
        "estimated_rmb_repayment": str(money(rmb_repayment)),
        "warning": warning,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return

    def send_json(self, status: int, payload: dict[str, object]) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            host_options = "".join(
                f'<option value="{host}">{host}</option>' for host in VISA_API_HOSTS
            )
            html = (
                INDEX_HTML.replace("__VISA_PAGE__", VISA_CALCULATOR_PAGE)
                .replace("__ICBC_PAGE__", ICBC_FX_PAGE)
                .replace("__VISA_HOST_OPTIONS__", host_options)
            )
            raw = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return

        if parsed.path == "/api/convert":
            try:
                self.send_json(200, calculate(parse_qs(parsed.query)))
            except ConverterError as exc:
                self.send_json(400, {"error": str(exc)})
            return

        self.send_json(404, {"error": "not found"})


def main(argv: list[str]) -> int:
    port = int(argv[0]) if argv else DEFAULT_PORT
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Currency converter UI: http://127.0.0.1:{port}")
    print("Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
