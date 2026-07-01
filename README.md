# ICBC Visa TRY to RMB Converter

A small local web app and CLI for estimating the RMB repayment amount for an
ICBC-issued Visa credit-card purchase made in Turkish lira.

The flow modeled by this tool is:

1. You pay in TRY.
2. TRY is converted to USD for the Visa card balance.
3. You repay the USD balance with RMB using ICBC's USD bank selling rate
   (`银行卖出价`, `foreignSell`).

## Features

- Browser UI at `http://127.0.0.1:8766`
- CLI mode for quick calculations
- Purchase date defaults to today
- ICBC quote date defaults to today
- Configurable TRY tax rate, default `3.3%`
- Configurable market fallback buffer, default `0.8%`
- Configurable ICBC rate field, default `foreignSell`
- Manual fallback inputs for Visa USD amount or TRY-to-USD rate
- Live ICBC official FX quote fetching
- Browser charts for TRY -> USD, USD -> CNY, and the combined TRY -> CNY trend

## Rate Sources

The app tries these sources for TRY to USD:

1. Visa official calculator endpoint
2. Google Finance TRY/USD market rate
3. Frankfurter TRY/USD API
4. ExchangeRate API

Visa often blocks automated access. When that happens, the app falls back to a
market TRY/USD rate and adds the configurable market fallback buffer. The default
buffer is `0.8%` because Visa card settlement rates are usually less favorable
than mid-market data.

ICBC USD to RMB is fetched from ICBC's official RMB FX quote API:

- Official page: <https://www.icbc.com.cn/column/1438058341489590354.html>
- Default field: `foreignSell` / `银行卖出价`

The trend charts use market TRY/USD history and ICBC USD/CNY history. The
combined chart multiplies the two series to show CNY per 1 TRY for dates where
both sources returned data. All three charts are drawn as percentage change from
their own first visible point and share the same percentage y-axis scale, making
relative movement easier to compare across rates with very different raw values.

## Requirements

- Python 3.10 or newer
- No third-party Python packages are required

## Run the Web UI

From this repository:

```bash
python3 currency_converter_server.py
```

Then open:

```text
http://127.0.0.1:8766
```

To use a different port:

```bash
python3 currency_converter_server.py 8770
```

## Use the CLI

Example using automatic Visa-first, market-fallback behavior:

```bash
python3 icbc_visa_currency_converter.py 1000
```

Example using a manual TRY-to-USD rate:

```bash
python3 icbc_visa_currency_converter.py 1000 \
  --visa-rate 0.02161 \
  --try-tax-rate 3.3 \
  --market-fallback-buffer 0.8
```

Example using a manual Visa USD amount:

```bash
python3 icbc_visa_currency_converter.py 1000 \
  --visa-usd-amount 22.32
```

JSON output:

```bash
python3 icbc_visa_currency_converter.py 1000 --json
```

## Calculation Notes

For automatic and manual-rate modes:

```text
taxed_try = try_amount * (1 + try_tax_rate / 100)
usd_estimate = taxed_try * try_to_usd_rate
rmb_estimate = usd_estimate * icbc_rmb_per_usd
```

For manual Visa USD amount mode, the entered USD amount is treated as already
final, so the TRY tax rate is not applied again.

## Create and Publish to GitHub

Initialize the repository locally:

```bash
git init
git add .
git commit -m "Initial currency converter app"
```

Create an empty repository on GitHub, for example:

```text
https://github.com/<your-user>/icbc-visa-currency-converter
```

Then connect and push:

```bash
git branch -M main
git remote add origin git@github.com:<your-user>/icbc-visa-currency-converter.git
git push -u origin main
```

If you prefer HTTPS instead of SSH:

```bash
git remote add origin https://github.com/<your-user>/icbc-visa-currency-converter.git
git push -u origin main
```

If `git push` asks for authentication, use a GitHub personal access token for
HTTPS, or configure an SSH key for SSH pushes.

## Disclaimer

This tool is an estimate. Visa card settlement, ICBC credit-card repayment, bank
fees, taxes, posting dates, and official quote timing can all change the final
amount shown on your statement.
