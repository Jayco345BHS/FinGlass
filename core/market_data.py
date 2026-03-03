import json
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

ALPHA_VANTAGE_BASE_URL = "https://www.alphavantage.co/query"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "market_data.json"
SYMBOL_SUFFIXES = (".TO", ".TRT", ".V", ".NE")


class MarketDataError(Exception):
    pass


def _canonical_symbol(symbol):
    raw = str(symbol or "").strip().upper()
    if not raw:
        return ""
    for suffix in SYMBOL_SUFFIXES:
        if raw.endswith(suffix) and len(raw) > len(suffix):
            return raw[: -len(suffix)]
    return raw


def _candidate_symbols(symbol):
    raw = str(symbol or "").strip().upper()
    canonical = _canonical_symbol(raw)
    candidates = []

    for value in (raw, canonical):
        if value and value not in candidates:
            candidates.append(value)

    if canonical:
        for suffix in SYMBOL_SUFFIXES:
            candidate = f"{canonical}{suffix}"
            if candidate not in candidates:
                candidates.append(candidate)

    return candidates


def _request(params):
    query = urlencode({**params, "apikey": _api_key()})
    url = f"{ALPHA_VANTAGE_BASE_URL}?{query}"

    try:
        with urlopen(url, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise MarketDataError("Market data request failed") from exc

    if payload.get("Error Message"):
        raise MarketDataError(payload["Error Message"])

    if payload.get("Note"):
        raise MarketDataError(payload["Note"])

    if payload.get("Information"):
        raise MarketDataError(payload["Information"])

    if not isinstance(payload, dict):
        raise MarketDataError("Unexpected market data response")

    return payload


def _api_key():
    env_key = str(os.environ.get("ALPHA_VANTAGE_API_KEY") or "").strip()
    if env_key:
        return env_key

    config_path = Path(os.environ.get("MARKET_DATA_CONFIG_PATH") or DEFAULT_CONFIG_PATH)
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MarketDataError(
            f"Missing market data config: {config_path}. Set ALPHA_VANTAGE_API_KEY or create config file."
        ) from exc
    except json.JSONDecodeError as exc:
        raise MarketDataError(f"Invalid JSON in market data config: {config_path}") from exc

    file_key = str(payload.get("alpha_vantage_api_key") or "").strip()
    if file_key:
        return file_key

    raise MarketDataError(
        "Alpha Vantage API key is not configured. Set ALPHA_VANTAGE_API_KEY or add alpha_vantage_api_key to config JSON."
    )


def get_quote(symbol):
    normalized = _canonical_symbol(symbol)
    if not normalized:
        raise MarketDataError("symbol is required")

    candidates = _candidate_symbols(symbol)

    price = None
    resolved_symbol = normalized

    for candidate in candidates:
        payload = _request(
            {
                "function": "GLOBAL_QUOTE",
                "symbol": candidate,
            }
        )

        row = payload.get("Global Quote") or {}
        price_raw = row.get("05. price")
        if price_raw in (None, ""):
            payload = _request(
                {
                    "function": "TIME_SERIES_DAILY",
                    "symbol": candidate,
                    "outputsize": "compact",
                }
            )
            series = payload.get("Time Series (Daily)") or {}
            if series:
                latest_date = sorted(series.keys(), reverse=True)[0]
                latest_row = series.get(latest_date) or {}
                price_raw = latest_row.get("4. close")

        try:
            parsed_price = float(str(price_raw))
        except (TypeError, ValueError):
            continue

        if parsed_price <= 0:
            continue

        price = parsed_price
        resolved_symbol = normalized
        break

    if price is None:
        raise MarketDataError(f"No quote returned for {normalized}")

    return {
        "symbol": resolved_symbol,
        "price": price,
    }
