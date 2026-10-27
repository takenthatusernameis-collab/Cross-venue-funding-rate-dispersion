#!/usr/bin/env python3
"""Offline conformance check for the Binance USD-M archive CSV parser (standard library only).

Validates parse_binance_archive against the schema and sample values documented
in research_state/binance_archive_feasibility_assessment_2026-10-26.json and
research_state/binance_overlap_sample_2026-10-26.json. Also audits
normalize_funding_rate for the Binance 8h interval known-answer (identity),
covering the OKX+Binance exploratory estimand (FVD-EXPLORATORY-003).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from cross_venue_funding_dispersion.signals import normalize_funding_rate
import parse_binance_archive as p


FUNDING_CSV_HEADER = "calc_time,funding_interval_hours,last_funding_rate\n"
KLINES_CSV_HEADER = (
    "open_time,open,high,low,close,volume,close_time,quote_volume,"
    "count,taker_buy_volume,taker_buy_quote_volume,ignore\n"
)

FUNDING_EXAMPLE_ROW = "1704067200000,8,0.00037409"
KLINES_EXAMPLE_ROW = (
    "1717200000000,67577.90,67729.90,67535.40,67690.00,3025.451,"
    "1717203599999,204628990.86440,49741,1569.014,106127949.20210,0"
)


def validate_binance_archive() -> list[str]:
    errors = []
    try:
        rec = p.parse_funding_row(FUNDING_EXAMPLE_ROW.split(","), symbol="BTCUSDT")
        if rec["calc_time_ms"] != 1704067200000:
            errors.append("funding calc_time_ms wrong")
        if rec["timestamp_utc"] != "2024-01-01T00:00:00Z":
            errors.append("funding timestamp_utc wrong: %r" % rec["timestamp_utc"])
        if rec["funding_interval_hours"] != 8.0:
            errors.append("funding interval wrong")
        if rec["rate"] != 0.00037409:
            errors.append("funding rate wrong")
        if rec["symbol"] != "BTCUSDT":
            errors.append("funding symbol wrong")

        krec = p.parse_klines_row(KLINES_EXAMPLE_ROW.split(","), symbol="BTCUSDT")
        if krec["open_time_ms"] != 1717200000000:
            errors.append("klines open_time_ms wrong")
        if krec["timestamp_utc"] != "2024-06-01T00:00:00Z":
            errors.append("klines timestamp_utc wrong: %r" % krec["timestamp_utc"])
        if krec["close_time_utc"] != "2024-06-01T00:59:59.999000Z":
            errors.append("klines close_time_utc wrong: %r" % krec["close_time_utc"])
        if krec["open"] != 67577.90:
            errors.append("klines open wrong")
        if krec["high"] != 67729.90:
            errors.append("klines high wrong")
        if krec["low"] != 67535.40:
            errors.append("klines low wrong")
        if krec["close"] != 67690.00:
            errors.append("klines close wrong")
        if krec["volume"] != 3025.451:
            errors.append("klines volume wrong")
        if krec["quote_volume"] != "204628990.86440":
            errors.append("klines quote_volume wrong")
        if krec["count"] != "49741":
            errors.append("klines count wrong")

        funding_text = FUNDING_CSV_HEADER + FUNDING_EXAMPLE_ROW + "\n"
        recs = p.parse_funding_csv(funding_text, symbol="BTCUSDT")
        if len(recs) != 1:
            errors.append("funding csv count wrong")
        if recs[0]["timestamp_utc"] != "2024-01-01T00:00:00Z":
            errors.append("funding csv timestamp wrong")

        klines_text = KLINES_CSV_HEADER + KLINES_EXAMPLE_ROW + "\n"
        krecs = p.parse_klines_csv(klines_text, symbol="BTCUSDT")
        if len(krecs) != 1:
            errors.append("klines csv count wrong")

        multi_funding = FUNDING_CSV_HEADER + FUNDING_EXAMPLE_ROW + "\n" + "1704096000000,8,0.000037409\n"
        multi_recs = p.parse_funding_csv(multi_funding, symbol="BTCUSDT")
        if len(multi_recs) != 2:
            errors.append("multi funding count wrong")
        if multi_recs[1]["timestamp_utc"] != "2024-01-01T08:00:00Z":
            errors.append("multi funding second timestamp wrong: %r" % multi_recs[1]["timestamp_utc"])

        binance_rate = 0.00037409
        if normalize_funding_rate(binance_rate, 8.0) != binance_rate:
            errors.append("Binance 8h normalization should be identity (OKX|Binance both 8h)")

        hl_equiv_rate = normalize_funding_rate(binance_rate, 1.0)
        if abs(hl_equiv_rate - binance_rate * 8.0) > 1e-18:
            errors.append("HL 1h->8h normalization wrong relative to Binance rate")
        if normalize_funding_rate(binance_rate / 8.0, 1.0) != binance_rate:
            errors.append("Binance 8h rate not equal to HL 1h rate / 8")
    except Exception as exc:
        errors.append("parser known-answer raised: %s" % exc)

    for bad_csv in ["bad_header,extra\n1,8,0.1\n", "calc_time,funding_interval_hours,last_funding_rate\n"]:
        try:
            p.parse_funding_csv(bad_csv)
            errors.append("bad funding csv accepted: %r" % bad_csv)
        except ValueError:
            pass
        except Exception as exc:
            errors.append("bad funding csv raised wrong type: %s" % exc)

    try:
        p.parse_funding_csv(FUNDING_CSV_HEADER + "notanumber,8,0.1\n")
        errors.append("non-numeric calc_time accepted")
    except ValueError:
        pass
    except Exception as exc:
        errors.append("non-numeric calc_time raised wrong type: %s" % exc)

    try:
        p.parse_funding_csv(FUNDING_CSV_HEADER + "1704067200000,4,0.1\n")
        errors.append("non-8h funding interval accepted")
    except ValueError:
        pass
    except Exception as exc:
        errors.append("non-8h interval raised wrong type: %s" % exc)

    try:
        p.parse_funding_row(["1704067200000"])
        errors.append("short funding row accepted")
    except ValueError:
        pass
    except Exception as exc:
        errors.append("short funding row raised wrong type: %s" % exc)

    for bad_args in [(0.001, 0), (float("nan"), 8), (float("inf"), 8), (0.001, -1), (1e308, 1.0)]:
        try:
            normalize_funding_rate(*bad_args)
            errors.append("invalid normalize_funding_rate input accepted")
        except ValueError:
            pass
        except Exception as exc:
            errors.append("invalid normalize_funding_rate raised wrong type: %s" % exc)

    return errors


def main() -> int:
    errors = validate_binance_archive()
    if errors:
        for e in errors:
            print("FAIL:", e)
        sys.exit(1)
    print("BINANCE_ARCHIVE_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
