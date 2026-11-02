"""Endpoint selection and verification: dedicated traffic can never be mislabelled (offline tests)."""
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "harness"))

import metrics  # noqa: E402
import tofa_relay  # noqa: E402
from endpoints import get_endpoint  # noqa: E402


class EndpointRegistryTest(unittest.TestCase):
    def test_public_and_dedicated_differ_in_model(self):
        pub, ded = get_endpoint("public"), get_endpoint("dedicated")
        self.assertEqual(pub["model"], "openai/gpt-oss-120b")
        self.assertTrue(ded["model"].startswith("dedicated/"))
        self.assertNotEqual(pub["model"], ded["model"])

    def test_unknown_endpoint_rejected(self):
        with self.assertRaises(SystemExit):
            get_endpoint("bogus")


class RelayGuardTest(unittest.TestCase):
    def test_mismatched_model_is_refused_locally_and_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "r.jsonl"
            # upstream is an unroutable address: the guard must answer before any network access
            relay = tofa_relay.serve(0, str(log), "http://127.0.0.1:9", "dedicated/x", "dedicated")
            threading.Thread(target=relay.serve_forever, daemon=True).start()
            body = json.dumps({"model": "openai/gpt-oss-120b", "messages": []}).encode()
            req = urllib.request.Request(f"http://127.0.0.1:{relay.server_address[1]}/v1/chat/completions", data=body,
                                         headers={"Content-Type": "application/json"}, method="POST")
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req, timeout=10)
            self.assertEqual(ctx.exception.code, 400)
            relay.shutdown()
            rec = json.loads(log.read_text().splitlines()[0])
            self.assertTrue(rec["guard_rejected"])
            self.assertEqual(rec["endpoint"], "dedicated")


class VerifyEndpointTest(unittest.TestCase):
    def rec(self, model, response_model):
        return {"method": "POST", "path": "/v1/chat/completions", "model": model, "response_model": response_model,
                "upstream": "https://api.tokenfactory.nebius.com", "status": 200}

    def test_verified_when_all_match(self):
        v = metrics.verify_endpoint([self.rec("dedicated/x", "dedicated/x")] * 3, "dedicated/x")
        self.assertTrue(v["verified"])

    def test_public_response_never_counts_as_dedicated(self):
        v = metrics.verify_endpoint([self.rec("dedicated/x", "dedicated/x"), self.rec("dedicated/x", "openai/gpt-oss-120b")], "dedicated/x")
        self.assertFalse(v["verified"])
        v = metrics.verify_endpoint([self.rec("openai/gpt-oss-120b", "openai/gpt-oss-120b")], "dedicated/x")
        self.assertFalse(v["verified"])

    def test_http_errors_and_recovery(self):
        w = [{"path": "/v1/chat/completions", "t_recv": 0, "status": 200},
             {"path": "/v1/chat/completions", "t_recv": 1, "status": 503, "error": "x"},
             {"path": "/v1/chat/completions", "t_recv": 3.5, "status": 200}]
        h = metrics.http_errors(w)
        self.assertEqual((h["errors"], h["statuses"], h["recovery_s"]), (1, [503], [2.5]))


class OverlayTest(unittest.TestCase):
    def test_overlay_substitutions_hit_the_committed_patch(self):
        text = (ROOT / "dsh" / "tofa.patch.yml").read_text()
        for needle in ("- id: openai/gpt-oss-120b", "model: openai/gpt-oss-120b",
                       "baseURL: https://api.tokenfactory.nebius.com/v1", "reasoningEffort: medium"):
            self.assertEqual(text.count(needle), 1, needle)


if __name__ == "__main__":
    unittest.main()
