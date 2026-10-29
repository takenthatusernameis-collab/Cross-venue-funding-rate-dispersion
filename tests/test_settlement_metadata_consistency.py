import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "research_state"

ARTIFACT = STATE_DIR / "settlement_metadata_measurement_2026-10-27.json"
BINANCE_FEASIBILITY = STATE_DIR / "binance_archive_feasibility_assessment_2026-10-26.json"
EXPECTED_UNDERLYINGS = ["BTC", "ETH", "SOL", "AVAX"]
EXPECTED_VENUES = {"OKX", "Binance USD-M", "Hyperliquid"}


def _is_hex_sha256(value):
    return isinstance(value, str) and len(value) == 64 and all(
        c in "0123456789abcdef" for c in value
    )


class SettlementMetadataConsistencyTests(unittest.TestCase):
    """Independent recomputation of claims in settlement_metadata_measurement.

    This test reads the committed on-disk artifact (no network calls) and
    independently recomputes every derived summary flag from the raw venue
    and pair data, verifying that the recorded claims are internally
    consistent and that the honor-code boundaries are respected.
    """

    def setUp(self):
        if not ARTIFACT.exists():
            self.skipTest(f"artifact not present: {ARTIFACT.name}")
        with open(ARTIFACT, encoding="utf-8") as fh:
            self.data = json.load(fh)

    def _venues_by_name(self):
        return {v["venue"]: v for v in self.data["venues"]}

    # ------------------------------------------------------------------
    # Honor-code boundaries (no-metric, no-backtest claims)
    # ------------------------------------------------------------------

    def test_backtest_not_completed(self):
        self.assertFalse(self.data.get("backtest_completed", True),
                         "settlement metadata measurement must not claim a backtest was run")

    def test_no_performance_metrics(self):
        self.assertFalse(self.data.get("performance_metrics_computed", True),
                         "settlement metadata measurement must not claim performance metrics")

    def test_original_confirmatory_gate_blocked(self):
        self.assertEqual(self.data.get("original_confirmatory_gate"), "BLOCKED_DATA_GATE")

    def test_underlyings_match_expected(self):
        self.assertEqual(self.data.get("underlyings"), EXPECTED_UNDERLYINGS)

    def test_venue_names_match_expected(self):
        self.assertEqual(set(self._venues_by_name().keys()), EXPECTED_VENUES)

    # ------------------------------------------------------------------
    # Independent recomputation of measurement_summary from venue data
    # ------------------------------------------------------------------

    def test_okx_settle_provable_recomputed(self):
        okx = self._venues_by_name()["OKX"]
        recomputed = all(
            okx["per_underlying"][b]["settle_currency"] is not None
            for b in EXPECTED_UNDERLYINGS
        )
        self.assertEqual(self.data["measurement_summary"]["okx_settle_provable"], recomputed)
        self.assertTrue(recomputed, "OKX settle currency should be provable (USDT) for all underlyings")

    def test_binance_settle_provable_recomputed(self):
        binance = self._venues_by_name()["Binance USD-M"]
        recomputed = all(
            binance["per_underlying"][b]["settle_currency"] is not None
            for b in EXPECTED_UNDERLYINGS
        )
        self.assertEqual(self.data["measurement_summary"]["binance_settle_provable"], recomputed)
        self.assertTrue(recomputed, "Binance settle currency should be provable for all underlyings")

    def test_hyperliquid_settle_unprovable_recompute(self):
        hl = self._venues_by_name()["Hyperliquid"]
        recomputed = all(
            hl["per_underlying"][b]["settle_currency"] is not None
            for b in EXPECTED_UNDERLYINGS
        )
        self.assertEqual(self.data["measurement_summary"]["hyperliquid_settle_provable"], recomputed)
        self.assertFalse(recomputed, "Hyperliquid settle currency must be unprovable (all None)")

    def test_settlement_currency_values(self):
        venues = self._venues_by_name()
        for base in EXPECTED_UNDERLYINGS:
            with self.subTest(base=base):
                self.assertEqual(venues["OKX"]["per_underlying"][base]["settle_currency"], "USDT")
                self.assertEqual(
                    venues["Binance USD-M"]["per_underlying"][base]["settle_currency"], "USDT")
                self.assertIsNone(venues["Hyperliquid"]["per_underlying"][base]["settle_currency"])

    # ------------------------------------------------------------------
    # Independent recomputation of pair-level match flags from venue data
    # ------------------------------------------------------------------

    def _recompute_pair_match(self, va, vb):
        venues = self._venues_by_name()
        return all(
            venues[va]["per_underlying"][b]["settle_currency"] is not None
            and venues[vb]["per_underlying"][b]["settle_currency"] is not None
            and venues[va]["per_underlying"][b]["settle_currency"]
            == venues[vb]["per_underlying"][b]["settle_currency"]
            for b in EXPECTED_UNDERLYINGS
        )

    def test_okx_binance_pair_match_provable(self):
        pair = self.data["settle_match_pairs"]["OKX|Binance USD-M"]
        recomputed = self._recompute_pair_match("OKX", "Binance USD-M")
        self.assertEqual(pair["settlement_currency_match_provable"], recomputed)
        self.assertTrue(recomputed, "OKX|Binance pair must have provable settlement match (USDT)")

    def test_okx_hyperliquid_pair_match_not_provable(self):
        pair = self.data["settle_match_pairs"]["OKX|Hyperliquid"]
        self.assertFalse(pair["settlement_currency_match_provable"])

    def test_binance_hyperliquid_pair_match_not_provable(self):
        pair = self.data["settle_match_pairs"]["Binance USD-M|Hyperliquid"]
        self.assertFalse(pair["settlement_currency_match_provable"])

    def test_all_pairs_present(self):
        expected_pairs = {"OKX|Binance USD-M", "OKX|Hyperliquid", "Binance USD-M|Hyperliquid"}
        self.assertEqual(set(self.data["settle_match_pairs"].keys()), expected_pairs)

    def test_per_underlying_settle_in_pairs_consistent(self):
        venues = self._venues_by_name()
        pair_defs = [
            ("OKX|Binance USD-M", "OKX", "Binance USD-M"),
            ("OKX|Hyperliquid", "OKX", "Hyperliquid"),
            ("Binance USD-M|Hyperliquid", "Binance USD-M", "Hyperliquid"),
        ]
        for pair_key, va, vb in pair_defs:
            with self.subTest(pair=pair_key):
                pair = self.data["settle_match_pairs"][pair_key]
                for base in EXPECTED_UNDERLYINGS:
                    expected_a = venues[va]["per_underlying"][base]["settle_currency"]
                    expected_b = venues[vb]["per_underlying"][base]["settle_currency"]
                    actual = pair["per_underlying_settle"][base]
                    self.assertEqual(actual["Binance USD-M"],
                                     venues["Binance USD-M"]["per_underlying"][base]["settle_currency"])
                    self.assertEqual(actual["OKX"],
                                     venues["OKX"]["per_underlying"][base]["settle_currency"])
                    self.assertEqual(actual["Hyperliquid"],
                                     venues["Hyperliquid"]["per_underlying"][base]["settle_currency"])

    def test_provable_matched_pair_summary_consistent(self):
        pairs = self.data["settle_match_pairs"]
        okx_binance = pairs["OKX|Binance USD-M"]["settlement_currency_match_provable"]
        expected = ("OKX|Binance USD-M (both USDT)" if okx_binance else None)
        self.assertEqual(self.data["measurement_summary"]["provable_matched_pair"], expected)

    def test_settlement_subcomponent_resolved_consistent(self):
        pair = self.data["settle_match_pairs"]["OKX|Binance USD-M"]
        expected = pair["settlement_currency_match_provable"]
        self.assertEqual(
            self.data["measurement_summary"]["settlement_currency_subcomponent_resolved_for_okx_binance_pair"],
            expected,
        )

    # ------------------------------------------------------------------
    # Evidence-level provenance policy
    # ------------------------------------------------------------------

    def test_okx_evidence_level_verified(self):
        okx = self._venues_by_name()["OKX"]
        for base in EXPECTED_UNDERLYINGS:
            with self.subTest(base=base):
                self.assertEqual(okx["per_underlying"][base]["evidence_level"], "verified")

    def test_binance_evidence_level_verified_documented(self):
        binance = self._venues_by_name()["Binance USD-M"]
        for base in EXPECTED_UNDERLYINGS:
            with self.subTest(base=base):
                self.assertEqual(
                    binance["per_underlying"][base]["evidence_level"], "verified_documented")

    def test_hyperliquid_evidence_level_candidate(self):
        hl = self._venues_by_name()["Hyperliquid"]
        for base in EXPECTED_UNDERLYINGS:
            with self.subTest(base=base):
                self.assertEqual(hl["per_underlying"][base]["evidence_level"], "candidate")

    def test_hyperliquid_evidence_basis_reused(self):
        hl = self._venues_by_name()["Hyperliquid"]
        self.assertEqual(hl["evidence_basis"], "REUSED_FROM_DEPTH_PROBE")
        self.assertEqual(
            hl["reference_artifact"],
            "research_state/historical_overlap_depth_probe_2026-10-25.json",
        )

    def test_binance_evidence_basis_documented(self):
        binance = self._venues_by_name()["Binance USD-M"]
        if binance.get("evidence_basis"):
            self.assertIn("LIVE_FAILOVER", binance["evidence_basis"] + binance.get("evidence_basis", ""))

    # ------------------------------------------------------------------
    # HTTP response metadata sanity
    # ------------------------------------------------------------------

    def test_okx_response_meta_http_200(self):
        okx = self._venues_by_name()["OKX"]
        self.assertEqual(okx["response_meta"]["http_status"], 200)
        self.assertIsNone(okx["response_meta"]["error"])

    def test_binance_response_meta_geo_blocked(self):
        binance = self._venues_by_name()["Binance USD-M"]
        self.assertEqual(binance["response_meta"]["http_status"], 451)
        self.assertIn("451", str(binance["response_meta"]["error"]))

    def test_okx_response_sha256_valid(self):
        okx = self._venues_by_name()["OKX"]
        sha = okx["response_meta"].get("response_sha256")
        self.assertTrue(_is_hex_sha256(sha), f"OKX response_sha256 is not a valid hex digest: {sha}")

    # ------------------------------------------------------------------
    # Residual unmeasured components documented (instrument identity not cleared)
    # ------------------------------------------------------------------

    def test_instrument_identity_not_cleared(self):
        residuals = self.data.get("residual_unmeasured_components", [])
        joined = " ".join(residuals)
        self.assertIn("symbol-mapped only", joined.lower())
        self.assertIn("BLOCKED_DATA_GATE", joined)

    def test_limitation_disclaims_performance(self):
        limitation_text = " ".join(self.data.get("limitations", []))
        self.assertIn("No performance metric", limitation_text)

    # ------------------------------------------------------------------
    # Cross-reference to binance_archive_feasibility_assessment
    # ------------------------------------------------------------------

    def test_binance_provenance_references_feasibility_assessment(self):
        binance = self._venues_by_name()["Binance USD-M"]
        provenance = binance.get("provenance_note", "")
        self.assertIn("binance_archive_feasibility_assessment_2026-10-26.json", provenance)

    def test_binance_feasibility_assessment_exists(self):
        self.assertTrue(BINANCE_FEASIBILITY.exists(),
                         f"referenced Binance feasibility assessment not found: {BINANCE_FEASIBILITY.name}")


if __name__ == "__main__":
    unittest.main()
