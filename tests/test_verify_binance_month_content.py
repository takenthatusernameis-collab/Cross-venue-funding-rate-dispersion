import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import verify_binance_month_content as verify

FUNDING_CSV = (
    "calc_time,funding_interval_hours,last_funding_rate\n"
    "1790812800000,8,0.00010000\n"
    "1790841600000,8,-0.00020000\n"
)
KLINES_CSV = (
    "open_time,open,high,low,close,volume,close_time,quote_volume,"
    "count,taker_buy_volume,taker_buy_quote_volume,ignore\n"
    "1790812800000,100.0,101.0,99.0,100.5,10.0,1790816399999,1000.0,5,4.0,400.0,0\n"
)


def _zip_bytes(csv_text, member="data.csv"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr(member, csv_text)
    return buf.getvalue()


class _Resp:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=None):
        return self.body if size is None else self.body[:size]


class FakeOpener:
    def __init__(self, mapping):
        self.mapping = mapping

    def __call__(self, req, timeout=None):
        url = getattr(req, "full_url", req)
        if url not in self.mapping:
            raise KeyError("unexpected URL: %s" % url)
        return _Resp(self.mapping[url])


def _mapping(symbol="BTCUSDT", field="fundingRate", month="2026-10", csv_text=FUNDING_CSV, digest=None):
    url = verify.object_url(symbol, field, month)
    import hashlib
    zipb = _zip_bytes(csv_text)
    sha = digest or hashlib.sha256(zipb).hexdigest()
    name = url.rsplit("/", 1)[-1]
    return url, zipb, {url: zipb, url + ".CHECKSUM": ("%s  %s\n" % (sha, name)).encode()}


class ParseChecksumTests(unittest.TestCase):
    def test_parses_digest_and_filename(self):
        digest, name = verify.parse_checksum_text(
            "9c09b0bc6d8a57da06c34ec41add7dc9917dcb45dd83f7393ab0b3c2a2c34e5e  BTCUSDT-fundingRate-2026-10.zip\n"
        )
        self.assertEqual(digest, "9c09b0bc6d8a57da06c34ec41add7dc9917dcb45dd83f7393ab0b3c2a2c34e5e")
        self.assertEqual(name, "BTCUSDT-fundingRate-2026-10.zip")

    def test_rejects_non_sha256_digest(self):
        with self.assertRaises(ValueError):
            verify.parse_checksum_text("deadbeef  file.zip\n")

    def test_rejects_missing_filename(self):
        with self.assertRaises(ValueError):
            verify.parse_checksum_text("a" * 64 + "\n")

    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            verify.parse_checksum_text("\n\n")


class ObjectUrlTests(unittest.TestCase):
    def test_funding_url_pattern(self):
        self.assertEqual(
            verify.object_url("BTCUSDT", "fundingRate", "2026-10"),
            "https://data.binance.vision/data/futures/um/monthly/fundingRate/"
            "BTCUSDT/BTCUSDT-fundingRate-2026-10.zip",
        )

    def test_klines_url_pattern(self):
        self.assertEqual(
            verify.object_url("ETHUSDT", "klines", "2026-10"),
            "https://data.binance.vision/data/futures/um/monthly/klines/"
            "ETHUSDT/1h/ETHUSDT-1h-2026-10.zip",
        )


class VerifyObjectTests(unittest.TestCase):
    def test_verified_funding_object_records_rows_and_interval(self):
        url, _zipb, mapping = _mapping()
        rec = verify.verify_object("BTCUSDT", "fundingRate", "2026-10", opener=FakeOpener(mapping))
        self.assertTrue(rec["checksum_match"])
        self.assertIsNone(rec["error"])
        self.assertEqual(rec["rows"], 2)
        self.assertEqual(rec["funding_interval_hours"], [8.0])
        self.assertEqual(rec["first_utc"], "2026-10-01T00:00:00Z")
        self.assertIsNotNone(rec["actual_sha256"])

    def test_verified_klines_object_records_rows(self):
        url, _zipb, mapping = _mapping(field="klines", csv_text=KLINES_CSV)
        rec = verify.verify_object("BTCUSDT", "klines", "2026-10", opener=FakeOpener(mapping))
        self.assertTrue(rec["checksum_match"])
        self.assertIsNone(rec["error"])
        self.assertEqual(rec["rows"], 1)
        self.assertIsNone(rec["funding_interval_hours"])

    def test_checksum_mismatch_fails_closed(self):
        url, _zipb, mapping = _mapping(digest="0" * 64)
        rec = verify.verify_object("BTCUSDT", "fundingRate", "2026-10", opener=FakeOpener(mapping))
        self.assertFalse(rec["checksum_match"])
        self.assertIn("checksum mismatch", rec["error"])
        self.assertIsNone(rec["rows"])

    def test_non_8h_interval_fails_closed(self):
        csv_text = FUNDING_CSV.replace(",8,", ",4,")
        url, _zipb, mapping = _mapping(csv_text=csv_text)
        rec = verify.verify_object("BTCUSDT", "fundingRate", "2026-10", opener=FakeOpener(mapping))
        self.assertIsNotNone(rec["error"])
        self.assertIsNone(rec["rows"])
        self.assertFalse(verify.summarize([rec])["content_proven"])

    def test_multiple_csv_members_fail_closed(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("a.csv", FUNDING_CSV)
            archive.writestr("b.csv", FUNDING_CSV)
        import hashlib
        zipb = buf.getvalue()
        url = verify.object_url("BTCUSDT", "fundingRate", "2026-10")
        mapping = {
            url: zipb,
            url + ".CHECKSUM": ("%s  x.zip\n" % hashlib.sha256(zipb).hexdigest()).encode(),
        }
        rec = verify.verify_object("BTCUSDT", "fundingRate", "2026-10", opener=FakeOpener(mapping))
        self.assertIsNotNone(rec["error"])
        self.assertIsNone(rec["rows"])

    def test_missing_object_records_error_without_raising(self):
        rec = verify.verify_object("BTCUSDT", "fundingRate", "2026-10", opener=FakeOpener({}))
        self.assertFalse(rec["checksum_match"])
        self.assertIsNotNone(rec["error"])
        self.assertIsNone(rec["rows"])


class SummarizeTests(unittest.TestCase):
    def _verified(self, symbol="BTCUSDT", field="fundingRate"):
        _url, _zipb, mapping = _mapping(
            symbol=symbol, field=field,
            csv_text=FUNDING_CSV if field == "fundingRate" else KLINES_CSV,
        )
        return verify.verify_object(symbol, field, "2026-10", opener=FakeOpener(mapping))

    def test_content_proven_true_only_when_all_objects_verify(self):
        records = [self._verified("BTCUSDT", "fundingRate"), self._verified("BTCUSDT", "klines")]
        summary = verify.summarize(records)
        self.assertTrue(summary["content_proven"])
        self.assertEqual(summary["objects_failed"], 0)
        self.assertEqual(summary["funding_interval_hours_observed"], [8.0])

    def test_content_proven_false_when_one_object_fails(self):
        good = self._verified("BTCUSDT", "fundingRate")
        bad = verify.verify_object("ETHUSDT", "fundingRate", "2026-10", opener=FakeOpener({}))
        summary = verify.summarize([good, bad])
        self.assertFalse(summary["content_proven"])
        self.assertEqual(summary["objects_failed"], 1)

    def test_build_artifact_preserves_fail_closed_gate_flags(self):
        artifact = verify.build_artifact(
            "2026-10", ["BTCUSDT"], ["fundingRate"],
            [self._verified("BTCUSDT", "fundingRate")],
            accessed_at_utc="2026-11-17T00:00:00Z",
        )
        self.assertEqual(artifact["status"], "EXPLORATORY_ONLY")
        self.assertEqual(artifact["original_confirmatory_gate"], "BLOCKED_DATA_GATE")
        self.assertFalse(artifact["backtest_completed"])
        self.assertFalse(artifact["performance_metrics_computed"])
        self.assertTrue(artifact["coverage_summary"]["content_proven"])


class MainTests(unittest.TestCase):
    def test_main_writes_artifact_and_returns_zero_when_proven(self):
        url, _zipb, mapping = _mapping()
        opener = FakeOpener(mapping)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.json"
            original = verify.urlopen
            verify.urlopen = opener
            try:
                code = verify.main(["--month", "2026-10", "--symbols", "BTCUSDT",
                                    "--fields", "fundingRate", "--output", str(out)])
            finally:
                verify.urlopen = original
            self.assertEqual(code, 0)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(data["coverage_summary"]["content_proven"])

    def test_main_returns_one_when_not_proven(self):
        original = verify.urlopen
        verify.urlopen = FakeOpener({})
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.json"
            try:
                code = verify.main(["--month", "2026-10", "--symbols", "BTCUSDT",
                                    "--fields", "fundingRate", "--output", str(out)])
            finally:
                verify.urlopen = original
            self.assertEqual(code, 1)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertFalse(data["coverage_summary"]["content_proven"])


class ParserCliImportTests(unittest.TestCase):
    def test_parse_binance_archive_main_has_path_in_scope(self):
        import parse_binance_archive as p
        self.assertTrue(callable(p.main))
        self.assertTrue(hasattr(p, "Path"))


def _funding_csv(timestamps_ms, interval=8, rate="0.00010000"):
    lines = ["calc_time,funding_interval_hours,last_funding_rate"]
    lines.extend("%d,%s,%s" % (ms, interval, rate) for ms in timestamps_ms)
    return "\n".join(lines) + "\n"


def _monthly_funding_ms(year, month, days, start_hour=0):
    import calendar
    from datetime import datetime, timedelta, timezone
    base = datetime(year, month, 1, tzinfo=timezone.utc)
    end = base + timedelta(days=days - 1, hours=start_hour)
    stamps = []
    cursor = base
    while cursor <= end:
        stamps.append(int(cursor.timestamp() * 1000))
        cursor += timedelta(hours=8)
    return stamps


class FundingContinuityTests(unittest.TestCase):
    """Multi-month continuity must fail closed on real gaps, not on source jitter."""

    def _record(self, month, stamps, symbol="BTCUSDT"):
        url, zipb, mapping = _mapping(
            symbol=symbol, field="fundingRate", month=month, csv_text=_funding_csv(stamps)
        )
        return verify.verify_object(symbol, "fundingRate", month, opener=FakeOpener(mapping))

    def test_consecutive_months_are_contiguous(self):
        aug = _monthly_funding_ms(2026, 8, 2)          # 2026-08-01 00:00 .. 2026-08-01 16:00
        sep = [aug[-1] + 8 * 3600 * 1000, aug[-1] + 16 * 3600 * 1000]
        out = verify.funding_continuity([self._record("2026-08", aug), self._record("2026-09", sep)])
        self.assertTrue(out["all_symbols_contiguous"])
        info = out["by_symbol"]["BTCUSDT"]
        self.assertEqual(info["gaps"], [])
        self.assertEqual(info["rows"], 6)
        self.assertEqual(info["duplicate_timestamps"], 0)

    def test_missing_settlement_across_month_seam_is_a_gap(self):
        aug = _monthly_funding_ms(2026, 8, 2)
        sep = [aug[-1] + 24 * 3600 * 1000]              # skips the next 8h settlement
        out = verify.funding_continuity([self._record("2026-08", aug), self._record("2026-09", sep)])
        self.assertFalse(out["all_symbols_contiguous"])
        self.assertEqual(len(out["by_symbol"]["BTCUSDT"]["gaps"]), 1)
        self.assertAlmostEqual(out["by_symbol"]["BTCUSDT"]["gaps"][0]["hours"], 24.0)

    def test_sub_second_source_jitter_is_not_a_gap(self):
        aug = _monthly_funding_ms(2026, 8, 2)
        jittered = [aug[0] + 1, aug[1] + 4, aug[2] + 2]
        out = verify.funding_continuity([self._record("2026-08", jittered)])
        self.assertTrue(out["all_symbols_contiguous"])

    def test_failed_month_fails_continuity_closed(self):
        good = self._record("2026-08", _monthly_funding_ms(2026, 8, 2))
        bad = verify.verify_object("BTCUSDT", "fundingRate", "2026-09", opener=FakeOpener({}))
        out = verify.funding_continuity([good, bad])
        self.assertFalse(out["all_symbols_contiguous"])
        self.assertFalse(out["by_symbol"]["BTCUSDT"]["contiguous"])

    def test_build_multi_month_artifact_keeps_gate_flags_and_per_month_summary(self):
        aug = _monthly_funding_ms(2026, 8, 2)
        records = [
            self._record("2026-08", aug),
            self._record("2026-09", [aug[-1] + 8 * 3600 * 1000]),
        ]
        artifact = verify.build_multi_month_artifact(
            ["2026-08", "2026-09"], ["BTCUSDT"], ["fundingRate"], records,
            accessed_at_utc="2026-11-17T00:00:00Z",
        )
        self.assertEqual(artifact["artifact_type"], "binance_multi_month_content_verification")
        self.assertEqual(artifact["months"], ["2026-08", "2026-09"])
        self.assertEqual(sorted(artifact["per_month_summary"]), ["2026-08", "2026-09"])
        self.assertTrue(artifact["funding_continuity"]["all_symbols_contiguous"])
        self.assertEqual(artifact["status"], "EXPLORATORY_ONLY")
        self.assertEqual(artifact["original_confirmatory_gate"], "BLOCKED_DATA_GATE")
        self.assertFalse(artifact["backtest_completed"])
        self.assertFalse(artifact["performance_metrics_computed"])

    def test_main_months_flag_fails_closed_on_gap(self):
        aug = _monthly_funding_ms(2026, 8, 2)
        sep = [aug[-1] + 32 * 3600 * 1000]
        mapping = {}
        for month, stamps in (("2026-08", aug), ("2026-09", sep)):
            _url, _zipb, month_map = _mapping(month=month, csv_text=_funding_csv(stamps))
            mapping.update(month_map)
        original = verify.urlopen
        verify.urlopen = FakeOpener(mapping)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.json"
            try:
                code = verify.main(["--months", "2026-08", "2026-09", "--symbols", "BTCUSDT",
                                    "--fields", "fundingRate", "--output", str(out)])
            finally:
                verify.urlopen = original
            self.assertEqual(code, 1)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(data["coverage_summary"]["content_proven"])
            self.assertFalse(data["funding_continuity"]["all_symbols_contiguous"])

    def test_main_requires_month_or_months(self):
        with self.assertRaises(SystemExit):
            verify.main(["--symbols", "BTCUSDT", "--output", "/tmp/unused.json"])


class CommittedBinanceOverlapContentTests(unittest.TestCase):
    """Source-independent audit of the committed multi-month overlap artifact."""

    STATE = ROOT / "research_state"
    NAME = "binance_overlap_content_2026-08_to_2026-10_2026-11-17.json"

    def _artifact(self):
        path = self.STATE / self.NAME
        self.assertTrue(path.is_file(), "multi-month overlap content artifact missing")
        return json.loads(path.read_text(encoding="utf-8"))

    def _manifest(self):
        return json.loads(
            (self.STATE / "exploratory_run_manifest_2026-10-27.json").read_text(encoding="utf-8")
        )

    def test_all_overlap_months_fully_checksum_verified(self):
        artifact = self._artifact()
        summary = artifact["coverage_summary"]
        self.assertEqual(artifact["months"], ["2026-08", "2026-09", "2026-10"])
        self.assertTrue(summary["content_proven"])
        self.assertEqual(summary["objects_requested"], 24)
        self.assertEqual(summary["objects_checksum_verified"], 24)
        self.assertEqual(summary["objects_failed"], 0)
        self.assertEqual(summary["funding_interval_hours_observed"], [8.0])
        for obj in artifact["objects"]:
            self.assertTrue(obj["checksum_match"], obj)
            self.assertIsNone(obj["error"], obj)
            self.assertEqual(obj["expected_sha256"], obj["actual_sha256"])

    def test_funding_series_is_contiguous_with_no_seam_gaps(self):
        artifact = self._artifact()
        continuity = artifact["funding_continuity"]
        self.assertTrue(continuity["all_symbols_contiguous"])
        symbols = {"BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT"}
        self.assertEqual(set(continuity["by_symbol"]), symbols)
        for symbol, info in continuity["by_symbol"].items():
            self.assertEqual(info["gaps"], [], symbol)
            self.assertEqual(info["duplicate_timestamps"], 0, symbol)
            self.assertEqual(info["rows"], 276, symbol)

    def test_union_spans_the_manifest_intersection(self):
        artifact = self._artifact()
        manifest = self._manifest()
        common = manifest["coverage_summary"]
        continuity = artifact["funding_continuity"]["by_symbol"]
        for info in continuity.values():
            self.assertLessEqual(info["first_utc"], common["common_funding_start_utc"])
            self.assertEqual(info["last_utc"], common["common_funding_end_utc"])
        self.assertTrue(common["binance_overlap_content_proven"])
        self.assertEqual(common["binance_overlap_continuity_gaps"], 0)

    def test_overlap_artifact_listed_with_matching_hash(self):
        import hashlib
        path = self.STATE / self.NAME
        manifest = self._manifest()
        recorded = {
            a["path"]: a["sha256"] for a in manifest["output_artifacts"]
            if a.get("path", "").endswith(self.NAME)
        }
        self.assertTrue(recorded, "multi-month artifact must be listed in output_artifacts")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(recorded["research_state/" + self.NAME], actual)

    def test_overlap_artifact_claims_no_performance(self):
        artifact = self._artifact()
        self.assertFalse(artifact["backtest_completed"])
        self.assertFalse(artifact["performance_metrics_computed"])
        self.assertEqual(artifact["original_confirmatory_gate"], "BLOCKED_DATA_GATE")


class CommittedBinanceContentEvidenceTests(unittest.TestCase):
    """Source-independent audit of the committed 2026-10 content artifact.

    Reads committed research_state JSON only; no network. Guards that the
    manifest's intersection end still matches the last verified Binance funding
    settlement, so a later archive-availability claim cannot drift away from
    the parsed content evidence.
    """

    STATE = ROOT / "research_state"

    def _newest_content_artifact(self):
        files = sorted(self.STATE.glob("binance_month_content_*.json"))
        self.assertTrue(files, "no commit-level Binance content artifact present")
        return json.loads(files[-1].read_text(encoding="utf-8"))

    def test_content_artifact_is_fully_checksum_verified(self):
        artifact = self._newest_content_artifact()
        summary = artifact["coverage_summary"]
        self.assertTrue(summary["content_proven"])
        self.assertEqual(summary["objects_failed"], 0)
        self.assertEqual(summary["funding_interval_hours_observed"], [8.0])
        for obj in artifact["objects"]:
            self.assertTrue(obj["checksum_match"], obj)
            self.assertIsNone(obj["error"], obj)
            self.assertEqual(obj["expected_sha256"], obj["actual_sha256"])

    def test_funding_last_settlement_matches_manifest_intersection_end(self):
        artifact = self._newest_content_artifact()
        funding_last = {
            o["last_utc"] for o in artifact["objects"] if o["field"] == "fundingRate"
        }
        self.assertEqual(len(funding_last), 1, funding_last)
        manifest = json.loads(
            (self.STATE / "exploratory_run_manifest_2026-10-27.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            funding_last.pop(), manifest["coverage_summary"]["common_funding_end_utc"]
        )
        self.assertTrue(manifest["coverage_summary"]["binance_content_proven"])

    def test_content_artifact_listed_with_matching_hash(self):
        import hashlib
        files = sorted(self.STATE.glob("binance_month_content_*.json"))
        artifact_path = files[-1]
        manifest = json.loads(
            (self.STATE / "exploratory_run_manifest_2026-10-27.json").read_text(encoding="utf-8")
        )
        recorded = {
            a["path"]: a["sha256"] for a in manifest["output_artifacts"]
            if a.get("path", "").endswith(artifact_path.name)
        }
        self.assertTrue(recorded, "content artifact must be listed in output_artifacts")
        actual = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        self.assertEqual(recorded["research_state/" + artifact_path.name], actual)

    def test_no_performance_claim_in_content_artifact(self):
        artifact = self._newest_content_artifact()
        self.assertFalse(artifact["backtest_completed"])
        self.assertFalse(artifact["performance_metrics_computed"])
        self.assertEqual(artifact["original_confirmatory_gate"], "BLOCKED_DATA_GATE")


if __name__ == "__main__":
    unittest.main()
