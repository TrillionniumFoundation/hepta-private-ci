"""Source-only controls; no authentic checkpoint is decoded."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from qualification.hcsn_currentstate_n256_authentic_tailcheck537_hexfix.test_tail537 import (
    _index256_fixture,
)
from qualification.hcsn_currentstate_n256_authentic_tailcheck537_hexfix.tail537 import (
    advance_to_index537,
)

from .admission import REQUEST, admit_runtime
from .continuation import (
    SOURCE_INDEX,
    TARGET_INDEX,
    advance_to_index1159,
    encode_raw_index1159,
    final_tail_check,
)


class Tail1159IntentTests(unittest.TestCase):
    def test_frozen_work_denominator(self):
        request = json.loads(REQUEST.read_text())
        self.assertEqual(TARGET_INDEX - SOURCE_INDEX, 622)
        self.assertEqual(request["budget"]["recurrence_row_actions"], 6220)
        self.assertEqual(request["budget"]["tail_checks"], 10)
        self.assertEqual(request["budget"]["rounding_calls_cap"], 5180)
        self.assertEqual(request["budget"]["provider_calls"], 0)
        self.assertEqual(request["checkpoint_caps"]["aggregate_compact_bytes"], 134217728)
        self.assertFalse(request["actual_execution_authorized"])

    def test_missing_allocation_refuses_before_input_read(self):
        digest = __import__("hashlib").sha256(REQUEST.read_bytes()).hexdigest()
        environment = {
            "HCSN_REQUEST_SHA256": digest,
            "UNIQUE_EXECUTION_KEY": json.loads(REQUEST.read_text())["execution_key"],
            "HCSN_ATTEMPT_ID": "001",
        }
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(SystemExit, "not authorized"):
                admit_runtime()

    def test_false_authorization_refuses_even_with_filled_runtime_fields(self):
        request = json.loads(REQUEST.read_text())
        request["runtime_admission"] = {
            "allocation_sha256": "a" * 64,
            "calendar_sha256": "b" * 64,
            "concurrency": 1,
            "host_observation_sha256": "c" * 64,
            "runtime_sha256": "d" * 64,
        }
        with tempfile.TemporaryDirectory() as directory:
            request_path = Path(directory) / "REQUEST.json"
            request_path.write_text(json.dumps(request, sort_keys=True))
            digest = __import__("hashlib").sha256(request_path.read_bytes()).hexdigest()
            environment = {
                "HCSN_REQUEST_SHA256": digest,
                "UNIQUE_EXECUTION_KEY": request["execution_key"],
                "HCSN_ATTEMPT_ID": "001",
            }
            with patch("qualification.hcsn_currentstate_n256_tail1159_intent.admission.REQUEST", request_path):
                with patch.dict(os.environ, environment, clear=True):
                    with self.assertRaisesRegex(SystemExit, "not authorized"):
                        admit_runtime()

    def test_package_contains_no_runtime_outputs(self):
        names = {path.name for path in Path(__file__).resolve().parent.iterdir()}
        self.assertFalse({"RUN_OUTPUT", "FINAL_OUTPUT", "COLLECTED_LANES"} & names)

    def test_small_exact_continuation_and_tail(self):
        state256, parent = _index256_fixture()
        state537 = advance_to_index537(state256, parent)
        state1159 = advance_to_index1159(state537, parent)
        tail = final_tail_check(state1159, parent)
        self.assertEqual(state1159.included_index, TARGET_INDEX)
        self.assertEqual(tail["coordinate_count"], 2)
        self.assertTrue(tail["all_coordinates_unique"])
        self.assertEqual(encode_raw_index1159(state1159), encode_raw_index1159(state1159))

    def test_wrong_boundary_refuses(self):
        state256, parent = _index256_fixture()
        with self.assertRaisesRegex(ValueError, "not index537"):
            advance_to_index1159(state256, parent)
        with self.assertRaisesRegex(ValueError, "not index1159"):
            final_tail_check(state256, parent)


if __name__ == "__main__":
    unittest.main()
