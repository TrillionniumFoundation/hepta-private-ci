"""Check that service contention and unknown HTTP completion cannot erase calls."""

import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("e3_teacher", HERE / "run_teacher.py")
TEACHER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TEACHER)


class OriginalRetentionTest(unittest.TestCase):
    def execute(self, after_busy=False, timeout=False):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("A_RECORDS.json", "PROTOCOL.json"):
                shutil.copyfile(HERE / name, root / name)
            (root / "WEIGHT_IDENTITY.json").write_text(json.dumps({
                "hash_recomputed": True, "sha256": TEACHER.WEIGHT_SHA256,
                "file_identity": {},
            }))
            calls = []

            def request(route, credential, payload=None):
                if route == "/props":
                    return {"model_path": TEACHER.WEIGHT, "model_alias": TEACHER.ALIAS,
                            "chat_template": "fixture-template"}
                if route == "/v1/models":
                    return {"data": [{"id": TEACHER.ALIAS}]}
                calls.append(payload)
                if timeout:
                    raise TimeoutError("fixture unknown HTTP outcome")
                return {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 100, "completion_tokens": 2}}

            slots = [[], [], ValueError("another fixture workload appeared")] if after_busy else None
            with mock.patch.object(TEACHER, "existing_server", return_value=({"pid": 42}, "TEST-ONLY")), \
                    mock.patch.object(TEACHER, "stat_identity", return_value={}), \
                    mock.patch.object(TEACHER, "request", side_effect=request), \
                    mock.patch.object(TEACHER, "idle", side_effect=slots, return_value=[]):
                with self.assertRaises((ValueError, TimeoutError)):
                    TEACHER.main("first", root, root / "run", "0" * 40)
            failed = json.loads((root / "run/first/FAILED.json").read_text())
            original = json.loads((root / "A_RECORDS.json").read_text())[0]
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["messages"], original["task"]["messages"])
            self.assertEqual(failed["requests_sent"], 1)
            self.assertFalse(failed["automatic_retry"])
            self.assertTrue((root / "run/first/REQUEST-0.json").exists())
            return failed, {p.name: json.loads(p.read_text()) for p in
                            (root / "run/first").glob("*RESPONSE*.json")}

    def test_response_survives_postflight_contention(self):
        failed, responses = self.execute(after_busy=True)
        self.assertEqual(failed["responses_received"], 1)
        self.assertEqual(responses["RAW_RESPONSE-0.json"]["raw_response"]["choices"][0]
                         ["message"]["content"], "{}")

    def test_timeout_is_not_retried_or_reported_as_zero_requests(self):
        failed, responses = self.execute(timeout=True)
        self.assertEqual(failed["responses_received"], 0)
        self.assertEqual(responses, {})
        self.assertTrue(failed["unknown_generation_is_not_replayed"])


if __name__ == "__main__":
    unittest.main()
