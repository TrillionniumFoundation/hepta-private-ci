"""Wire-boundary regressions; stdlib only, no training or decoder calls."""

import copy
import hashlib
import json
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_backend import ENCODER, HEAD, features, sha
from native_tick_contract import validate_tick_binding
import native_worker


def fixture():
    values = features("What is the repair for case-one?")
    vector = b"".join(struct.pack(">q", v) for v in values)
    feature = hashlib.sha256(
        b"hepta.neuron.input-features.q24.v1" + struct.pack(">Q", len(values)) + vector
    ).hexdigest()
    tick_id, subject = b"native:wire:fixture", b"subject:wire:fixture"
    objective, ndu = sha(b"controlled objective"), sha(b"controlled NDU")
    tick_bytes = (
        b"hepta.neuron.tick-input.v1" + struct.pack(">I", len(tick_id)) + tick_id
    )
    tick_bytes += (
        struct.pack(">I", len(subject)) + subject + struct.pack(">QQ", 1, 1234)
    )
    tick_bytes += (
        bytes(32) + bytes.fromhex(feature + objective + ndu) + b"\0\0" + vector
    )
    tick, source, query = sha(tick_bytes), sha(b"source fixture"), sha(b"query fixture")
    binding = {
        "schema": "hepta.memory-cell.native-tick-binding.v1",
        "tick_id": tick_id.decode(),
        "subject_id": subject.decode(),
        "logical_sequence": 1,
        "monotonic_time_micros": 1234,
        "checkpoint_digest": "0" * 64,
        "input_feature_digest": feature,
        "objective_digest": objective,
        "ndu_snapshot_digest": ndu,
        "body_generation": None,
        "modulator_digest": None,
        "tick_digest": tick,
        "query_digest": query,
        "source_binding_digest": source,
        "joint_digest": sha(
            b"hepta.memory-cell.source-query-tick.v1"
            + bytes.fromhex(source + query + tick)
        ),
    }
    return {
        "schema": "hepta.memory-cell.native-request.v2",
        "repo": str(Path(__file__).resolve().parents[2]),
        "model": "/unused/model",
        "checkpoint": "/unused/checkpoint",
        "scope": "wire-fixture",
        "source_root": source,
        "rank": 8,
        "seed": 1,
        "pins": {},
        "question": "What is the repair for case-one?",
        "query_digest": query,
        "source_binding_digest": source,
        "neuron_request": {
            "request_id": tick_id.decode(),
            "config_id": "config:fixture",
            "generation": 1,
            "model_id": "model:fixture",
            "encoder_digest": sha(ENCODER),
            "head_digest": sha(HEAD),
            "weights_digest": sha(b"controlled weights"),
            "input_digest": tick,
            "feature_vector_q24": values,
            "expected_output_width": 4,
        },
        "tick_binding": binding,
    }


class BoundaryTests(unittest.TestCase):
    def test_v1_and_v2_reach_pinned_inspection_only_with_their_own_binding(self):
        request = fixture()
        self.assertEqual(
            validate_tick_binding(request), request["neuron_request"]["input_digest"]
        )
        for version in (1, 2):
            supplied = copy.deepcopy(request)
            if version == 1:
                supplied["schema"] = "hepta.memory-cell.native-request.v1"
                supplied.pop("tick_binding")
                supplied["neuron_request"]["input_digest"] = supplied[
                    "source_binding_digest"
                ]
            with patch.object(
                native_worker,
                "inspect",
                side_effect=RuntimeError("inspection boundary"),
            ) as inspect:
                with self.assertRaisesRegex(RuntimeError, "inspection boundary"):
                    native_worker.run(json.dumps(supplied).encode())
                inspect.assert_called_once()
            supplied["neuron_request"]["input_digest"] = sha(b"substitution")
            with patch.object(native_worker, "inspect") as inspect:
                with self.assertRaises(ValueError):
                    native_worker.run(json.dumps(supplied).encode())
                inspect.assert_not_called()

    def test_each_live_context_dimension_is_bound(self):
        for field, value in {
            "tick_id": "other:tick",
            "subject_id": "other:subject",
            "logical_sequence": 2,
            "monotonic_time_micros": 1235,
            "checkpoint_digest": sha(b"other checkpoint"),
            "input_feature_digest": sha(b"other features"),
            "objective_digest": sha(b"other objective"),
            "ndu_snapshot_digest": sha(b"other NDU"),
            "body_generation": 0,
            "modulator_digest": sha(b"other modulator"),
        }.items():
            with self.subTest(field=field):
                request = fixture()
                request["tick_binding"][field] = value
                with self.assertRaises(ValueError):
                    validate_tick_binding(request)

    def test_source_query_and_feature_substitution_is_rejected(self):
        for field in ("source_binding_digest", "query_digest"):
            request = fixture()
            request[field] = sha(b"other authority binding")
            with self.assertRaises(ValueError):
                validate_tick_binding(request)
        request = fixture()
        request["neuron_request"]["feature_vector_q24"][0] += 1
        with self.assertRaises(ValueError):
            validate_tick_binding(request)

    def test_noncanonical_numeric_and_schema_shapes_are_rejected(self):
        for field, value in {
            "logical_sequence": True,
            "monotonic_time_micros": 1.0,
            "body_generation": -1,
            "query_digest": "A" * 64,
            "subject_id": "bad subject",
            "unexpected_field": "injection",
        }.items():
            with self.subTest(field=field):
                request = fixture()
                request["tick_binding"][field] = value
                with self.assertRaises(ValueError):
                    validate_tick_binding(request)


if __name__ == "__main__":
    unittest.main(verbosity=2)
