import unittest
import sys
import math
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
import parse_binance_archive as p
from cross_venue_funding_dispersion.signals import normalize_funding_rate

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


class MsToIsoTests(unittest.TestCase):
    def test_ms_to_iso_epoch(self):
        self.assertEqual(p.ms_to_iso(0), "1970-01-01T00:00:00Z")

    def test_ms_to_iso_btc_funding_jan2024(self):
        self.assertEqual(p.ms_to_iso(1704067200000), "2024-01-01T00:00:00Z")

    def test_ms_to_iso_klines_close_with_millis(self):
        self.assertEqual(p.ms_to_iso(1717203599999), "2024-06-01T00:59:59.999000Z")

    def test_ms_to_iso_negative_raises(self):
        with self.assertRaises((ValueError, OSError)):
            p.ms_to_iso(-1)


class ParseFundingRowTests(unittest.TestCase):
    def test_known_answer_from_feasibility_assessment(self):
        rec = p.parse_funding_row(FUNDING_EXAMPLE_ROW.split(","), symbol="BTCUSDT")
        self.assertEqual(rec["calc_time_ms"], 1704067200000)
        self.assertEqual(rec["timestamp_utc"], "2024-01-01T00:00:00Z")
        self.assertEqual(rec["funding_interval_hours"], 8.0)
        self.assertAlmostEqual(rec["rate"], 0.00037409)
        self.assertEqual(rec["symbol"], "BTCUSDT")

    def test_eight_hour_spacing_jan2024(self):
        row0 = "1704067200000,8,0.00037409"
        row1 = "1704096000000,8,0.00037409"
        rec0 = p.parse_funding_row(row0.split(","))
        rec1 = p.parse_funding_row(row1.split(","))
        self.assertEqual(rec0["timestamp_utc"], "2024-01-01T00:00:00Z")
        self.assertEqual(rec1["timestamp_utc"], "2024-01-01T08:00:00Z")

    def test_negative_rate_preserved(self):
        rec = p.parse_funding_row(["1704067200000", "8", "-0.00002045"], symbol="ETHUSDT")
        self.assertAlmostEqual(rec["rate"], -0.00002045)

    def test_too_few_fields_raises(self):
        with self.assertRaises(ValueError):
            p.parse_funding_row(["1704067200000"])

    def test_non_numeric_calc_time_raises(self):
        with self.assertRaises(ValueError):
            p.parse_funding_row(["notanumber", "8", "0.1"])

    def test_non_numeric_rate_raises(self):
        with self.assertRaises(ValueError):
            p.parse_funding_row(["1704067200000", "8", "notarate"])

    def test_nan_rate_raises(self):
        with self.assertRaises(ValueError):
            p.parse_funding_row(["1704067200000", "8", "nan"])

    def test_zero_interval_raises(self):
        with self.assertRaises(ValueError):
            p.parse_funding_row(["1704067200000", "0", "0.1"])

    def test_negative_interval_raises(self):
        with self.assertRaises(ValueError):
            p.parse_funding_row(["1704067200000", "-1", "0.1"])


class ParseFundingCsvTests(unittest.TestCase):
    def test_known_answer_single_row(self):
        text = FUNDING_CSV_HEADER + FUNDING_EXAMPLE_ROW + "\n"
        recs = p.parse_funding_csv(text, symbol="BTCUSDT")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["timestamp_utc"], "2024-01-01T00:00:00Z")
        self.assertEqual(recs[0]["funding_interval_hours"], 8.0)

    def test_multi_row_eight_hour_spacing(self):
        text = (
            FUNDING_CSV_HEADER
            + "1704067200000,8,0.00037409\n"
            + "1704096000000,8,-0.00001\n"
            + "1704124800000,8,0.00002\n"
        )
        recs = p.parse_funding_csv(text)
        self.assertEqual(len(recs), 3)
        self.assertEqual(recs[0]["timestamp_utc"], "2024-01-01T00:00:00Z")
        self.assertEqual(recs[1]["timestamp_utc"], "2024-01-01T08:00:00Z")
        self.assertEqual(recs[2]["timestamp_utc"], "2024-01-01T16:00:00Z")

    def test_wrong_header_raises(self):
        with self.assertRaises(ValueError):
            p.parse_funding_csv("bad_header,extra\n1,8,0.1\n")

    def test_empty_csv_raises(self):
        with self.assertRaises(ValueError):
            p.parse_funding_csv("")

    def test_missing_header_raises(self):
        with self.assertRaises(ValueError):
            p.parse_funding_csv("1704067200000,8,0.1\n")

    def test_non_8h_interval_rejected(self):
        text = FUNDING_CSV_HEADER + "1704067200000,4,0.1\n"
        with self.assertRaises(ValueError):
            p.parse_funding_csv(text)

    def test_empty_lines_skipped(self):
        text = FUNDING_CSV_HEADER + "\n" + FUNDING_EXAMPLE_ROW + "\n\n"
        recs = p.parse_funding_csv(text)
        self.assertEqual(len(recs), 1)

    def test_jan2024_month_93_rows(self):
        text = FUNDING_CSV_HEADER
        for day in range(1, 32):
            for hour_offset in [0, 8, 16]:
                ms = 1704067200000 + (day - 1) * 86400000 + hour_offset * 3600000
                text += "%d,8,0.0001\n" % ms
        recs = p.parse_funding_csv(text)
        self.assertEqual(len(recs), 93)
        self.assertEqual(recs[0]["timestamp_utc"], "2024-01-01T00:00:00Z")
        self.assertEqual(recs[-1]["timestamp_utc"], "2024-01-31T16:00:00Z")


class ParseKlinesRowTests(unittest.TestCase):
    def test_known_answer_from_feasibility_assessment(self):
        rec = p.parse_klines_row(KLINES_EXAMPLE_ROW.split(","), symbol="BTCUSDT")
        self.assertEqual(rec["open_time_ms"], 1717200000000)
        self.assertEqual(rec["timestamp_utc"], "2024-06-01T00:00:00Z")
        self.assertAlmostEqual(rec["open"], 67577.90)
        self.assertAlmostEqual(rec["high"], 67729.90)
        self.assertAlmostEqual(rec["low"], 67535.40)
        self.assertAlmostEqual(rec["close"], 67690.00)
        self.assertAlmostEqual(rec["volume"], 3025.451)
        self.assertEqual(rec["close_time_ms"], 1717203599999)
        self.assertEqual(rec["close_time_utc"], "2024-06-01T00:59:59.999000Z")
        self.assertEqual(rec["quote_volume"], "204628990.86440")
        self.assertEqual(rec["count"], "49741")
        self.assertEqual(rec["symbol"], "BTCUSDT")

    def test_close_before_open_raises(self):
        row = "1717203599999,67577.90,67729.90,67535.40,67690.00,3025.451,1717200000000,x,y,z,a,b,c"
        with self.assertRaises(ValueError):
            p.parse_klines_row(row.split(","), symbol="BTCUSDT")

    def test_too_few_fields_raises(self):
        with self.assertRaises(ValueError):
            p.parse_klines_row(["1717200000000"])

    def test_nan_close_raises(self):
        row = "1717200000000,67577.90,67729.90,67535.40,nan,3025.451,1717203599999,x,y,z,a,b,c"
        with self.assertRaises(ValueError):
            p.parse_klines_row(row.split(","), symbol="BTCUSDT")

    def test_negative_price_raises(self):
        row = "1717200000000,-1,67729.90,67535.40,67690.00,3025.451,1717203599999,x,y,z,a,b,c"
        with self.assertRaises(ValueError):
            p.parse_klines_row(row.split(","), symbol="BTCUSDT")


class ParseKlinesCsvTests(unittest.TestCase):
    def test_known_answer_single_row(self):
        text = KLINES_CSV_HEADER + KLINES_EXAMPLE_ROW + "\n"
        recs = p.parse_klines_csv(text, symbol="BTCUSDT")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["open_time_ms"], 1717200000000)

    def test_wrong_header_raises(self):
        with self.assertRaises(ValueError):
            p.parse_klines_csv("bad,header\n1,2\n")

    def test_empty_csv_raises(self):
        with self.assertRaises(ValueError):
            p.parse_klines_csv("")

    def test_duplicate_timestamps_raises(self):
        text = KLINES_CSV_HEADER + KLINES_EXAMPLE_ROW + "\n" + KLINES_EXAMPLE_ROW + "\n"
        with self.assertRaises(ValueError):
            p.parse_klines_csv(text)

    def test_unsorted_timestamps_raises(self):
        row2 = "1717200000000,1,2,3,4,5,1717203599999,6,7,8,9,10,11"
        row1 = "1717286400000,1,2,3,4,5,1717290399999,6,7,8,9,10,11"
        text = KLINES_CSV_HEADER + row1 + "\n" + row2 + "\n"
        with self.assertRaises(ValueError):
            p.parse_klines_csv(text)


class NormalizeBinance8hTests(unittest.TestCase):
    SAMPLE_ARTIFACT = "binance_overlap_sample_2026-10-26.json"

    def _sample_path(self):
        return os.path.join(str(ROOT / "research_state"), self.SAMPLE_ARTIFACT)

    def _iter_sample_rates(self):
        path = self._sample_path()
        if not os.path.exists(path):
            self.skipTest("sample artifact not present: %s" % path)
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        samples = data.get("samples", {})
        count = 0
        for key, sample in samples.items():
            for field in ("sample_rate_first", "sample_rate_last"):
                raw = sample.get(field)
                if raw is None:
                    continue
                yield key, field, float(raw)
                count += 1
        if count == 0:
            self.skipTest("no sample_rate entries found in artifact")

    def test_binance_8h_normalization_is_identity(self):
        rate = 0.00037409
        self.assertEqual(normalize_funding_rate(rate, 8.0), rate)

    def test_binance_sample_rates_normalize_identity(self):
        for rate in [0.00005532, 0.00005664, -0.00002045, 0.0001, -0.00001602]:
            self.assertEqual(normalize_funding_rate(rate, 8.0), rate)

    def test_all_checksum_verified_sample_rates_normalize_identity(self):
        for key, field, rate in self._iter_sample_rates():
            with self.subTest(key=key, field=field, rate=rate):
                self.assertEqual(
                    normalize_funding_rate(rate, 8.0),
                    rate,
                    "8h normalization must be identity for verified Binance sample rate",
                )

    def test_binance_8h_rate_equivalent_to_hl_1h_rate_divided_by_8(self):
        binance_rate = 0.00037409
        hl_rate = binance_rate / 8.0
        self.assertAlmostEqual(normalize_funding_rate(hl_rate, 1.0), binance_rate)

    def test_okx_8h_and_binance_8h_directly_comparable(self):
        okx_rate = 0.00037409
        binance_rate = 0.00037409
        okx_norm = normalize_funding_rate(okx_rate, 8.0)
        binance_norm = normalize_funding_rate(binance_rate, 8.0)
        self.assertEqual(okx_norm, binance_norm)

    def test_non_zero_dispersion_when_hl_rate_differs_from_8x_binance(self):
        binance_rate = 0.0001
        hl_rate = 0.0002
        from cross_venue_funding_dispersion.signals import (
            dispersion_from_venue_histories,
        )
        start = "2024-01-01T00:00:00Z"
        end = "2024-01-01T08:00:00Z"
        histories = {
            "Binance": [{"timestamp": start, "rate_8h": normalize_funding_rate(binance_rate, 8.0)}],
            "Hyperliquid": [{"timestamp": start, "rate_8h": normalize_funding_rate(hl_rate, 1.0)}],
        }
        disp, means = dispersion_from_venue_histories(
            histories, start, end, minimum_venues=2, max_staleness_hours=24,
        )
        self.assertIsNotNone(disp)
        self.assertAlmostEqual(means["Binance"], binance_rate)
        self.assertAlmostEqual(means["Hyperliquid"], hl_rate * 8.0)


class FundingCsvToObservationsTests(unittest.TestCase):
    def test_observations_preserve_original_and_normalized(self):
        text = FUNDING_CSV_HEADER + FUNDING_EXAMPLE_ROW + "\n"
        recs = p.parse_funding_csv(text, symbol="BTCUSDT")
        obs = p.funding_csv_to_observations(recs, venue="Binance")
        self.assertEqual(len(obs), 1)
        self.assertEqual(obs[0]["original_rate"], 0.00037409)
        self.assertEqual(obs[0]["interval_hours"], 8.0)
        self.assertEqual(obs[0]["venue"], "Binance")
        self.assertEqual(obs[0]["rate_8h"], 0.00037409)
        self.assertEqual(obs[0]["timestamp"], "2024-01-01T00:00:00Z")

    def test_observations_compatible_with_time_weighted_mean(self):
        text = (
            FUNDING_CSV_HEADER
            + "1704067200000,8,0.0001\n"
            + "1704096000000,8,0.0002\n"
        )
        recs = p.parse_funding_csv(text)
        obs = p.funding_csv_to_observations(recs, venue="Binance")
        from cross_venue_funding_dispersion.signals import time_weighted_mean
        mean = time_weighted_mean(
            obs, "2024-01-01T00:00:00Z", "2024-01-01T16:00:00Z",
            max_staleness_hours=24,
        )
        self.assertIsNotNone(mean)


if __name__ == "__main__":
    unittest.main()
