import hashlib
import json
import sys
import unittest
from pathlib import Path
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import kilo_free_model_fallback as selector


class FakeResponse:
    status = 200

    def __init__(self, body, status=200):
        self.body = body
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=None):
        return self.body if size is None else self.body[:size]


def model(model_id, prompt="0", completion="0"):
    return {"id": model_id, "pricing": {"prompt": prompt, "completion": completion}}


class KiloFreeModelFallbackTests(unittest.TestCase):
    def test_catalog_selection_requires_explicit_zero_input_and_output_prices(self):
        payload = {"data": [
            model("poolside/laguna-s-2.1:free"),
            model("dots-studio/dots-3-note-preview:free", 0, "0.0"),
            model("paid/provider-model", "0.0001", "0.0002"),
            {"id": "provider/missing-pricing"},
            model("kilo-auto/free"),
            model("provider/bool-price", False, 0),
        ]}
        result = selector.extract_free_model_ids(payload)
        self.assertEqual(result, [
            "poolside/laguna-s-2.1:free",
            "dots-studio/dots-3-note-preview:free",
        ])

    def test_catalog_selection_diversifies_providers_before_second_variant(self):
        payload = {"data": [
            model("nvidia/model-a:free"),
            model("nvidia/model-b:free"),
            model("dots-studio/model-c:free"),
            model("poolside/model-d:free"),
        ]}
        result = selector.extract_free_model_ids(payload, max_models=4)
        self.assertEqual(result[:3], [
            "nvidia/model-a:free",
            "dots-studio/model-c:free",
            "poolside/model-d:free",
        ])
        self.assertEqual(len(result), 4)

    def test_healthcheck_contains_no_repository_content(self):
        payload = selector.healthcheck_payload("provider/model:free")
        self.assertEqual(payload["model"], "provider/model:free")
        self.assertEqual(payload["messages"], [{"role": "user", "content": "Reply with exactly OK."}])
        self.assertLess(payload["max_tokens"], 10)
        self.assertFalse(payload["stream"])

    def test_successful_selection_uses_no_authorization_header_and_hashes_responses(self):
        catalog_body = json.dumps({"data": [
            model("poolside/laguna-s-2.1:free"),
            model("nvidia/nemotron-3.5-super-vl:free"),
            model("paid/model", "0.01", "0.02"),
        ]}).encode()
        chat_body = json.dumps({"choices": [{"message": {"content": "OK"}}]}).encode()
        captured = []

        def fake_open(request, timeout):
            captured.append({
                "url": request.full_url,
                "method": request.get_method(),
                "headers": {k.lower(): v for k, v in request.header_items()},
                "body": request.data,
                "timeout": timeout,
            })
            if request.full_url == selector.MODELS_URL:
                return FakeResponse(catalog_body)
            payload = json.loads(request.data.decode("utf-8"))
            self.assertNotIn("paid/model", payload["model"])
            return FakeResponse(chat_body)

        report = selector.run_selection(opener=fake_open)
        self.assertEqual(report["status"], "FREE_MODEL_ROUTES_AVAILABLE")
        self.assertEqual(report["usable_models"], [
            "poolside/laguna-s-2.1:free",
            "nvidia/nemotron-3.5-super-vl:free",
        ])
        self.assertEqual(len(captured), 3)
        for request in captured:
            self.assertNotIn("authorization", request["headers"])
            self.assertNotIn("api_key", request["headers"])
        self.assertEqual(report["catalog"]["response_sha256"], hashlib.sha256(catalog_body).hexdigest())
        self.assertTrue(all(item["response_sha256"] == hashlib.sha256(chat_body).hexdigest()
                            for item in report["attempts"]))
        self.assertFalse(report["repository_content_sent"])
        self.assertFalse(report["credentials_used"])
        self.assertEqual(report["paid_models_considered"], 0)

    def test_gateway_failure_fails_closed_without_marking_a_model_usable(self):
        def no_network(request, timeout):
            raise URLError("network unavailable")

        report = selector.run_selection(opener=no_network)
        self.assertEqual(report["status"], "FREE_MODEL_CATALOG_UNAVAILABLE")
        self.assertEqual(report["usable_models"], [])
        self.assertFalse(report["credentials_used"])
        self.assertFalse(report["repository_content_sent"])

    def test_model_access_error_does_not_store_untrusted_response_body(self):
        from urllib.error import HTTPError
        catalog_body = json.dumps({"data": [model("poolside/laguna-s-2.1:free")]}).encode()

        def fake_open(request, timeout):
            if request.full_url == selector.MODELS_URL:
                return FakeResponse(catalog_body)
            raise HTTPError(request.full_url, 429, "rate limited", {}, None)

        report = selector.run_selection(opener=fake_open)
        self.assertEqual(report["status"], "NO_ZERO_COST_MODEL_RESPONDED")
        self.assertFalse(report["usable_models"][0:1])
        attempt = report["attempts"][0]
        self.assertEqual(attempt["http_status"], 429)
        self.assertEqual(attempt["error"], "HTTPError:429")
        self.assertNotIn("rate limited", json.dumps(report))

    def test_missing_or_paid_catalog_models_never_trigger_model_requests(self):
        calls = []
        def fake_open(request, timeout):
            calls.append(request.full_url)
            return FakeResponse(json.dumps({"data": [
                model("paid/model", "0.0001", "0.0001"),
                {"id": "unknown/model"},
            ]}).encode())

        report = selector.run_selection(opener=fake_open)
        self.assertEqual(report["status"], "NO_ZERO_COST_MODELS_IN_CATALOG")
        self.assertEqual(report["usable_models"], [])
        self.assertEqual(calls, [selector.MODELS_URL])


if __name__ == "__main__":
    unittest.main()
