import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import torch

from qualification.hcsn_adaptive.batched_flow import BatchedFlow, FlowConfig
from qualification.hcsn_adaptive.budget import Budget, CostLedger
from .backend import (BINDINGS, MASK, RULE, SCHEMA, StreamingRidge, canonical, decode_state,
                      encode_state, parse_json, tensor_record, tensor_restore)
from .request import request_digest


def update_request():
    def digest(text):
        return hashlib.sha256(text.encode()).hexdigest()
    names = ["readout.bias", "readout.weight"]
    mask = b"hepta.cell.trainable-mask.v1" + b"".join(len(name).to_bytes(4, "big") + name.encode() for name in names)
    return {"proposal_id": "streaming-ridge-proposal",
            "scope": {"agent_id": "agent", "cell_id": "cell", "run_id": "run1", "principal_digest": digest("principal")},
            "base_bundle_digest": digest("bundle"), "source_frontier": digest("frontier"),
            "dataset_digest": digest("streaming-state-unit-dataset_digest"), "dataset_bytes": 128,
            "credit_profile_digest": digest("credit"), "trainable_mask_digest": hashlib.sha256(mask).hexdigest(),
            "trainable_parameters": names, "from_generation": 1, "candidate_generation": 2,
            "budget": {"maximum_dataset_bytes": 1024, "maximum_steps": 1,
                       "maximum_elapsed_micros": 300_000_000, "maximum_working_bytes": 2_000_000_000}}


def binding():
    result = {name: hashlib.sha256(("streaming-state-unit-" + name).encode()).hexdigest() for name in BINDINGS}
    result["backend_state_schema_digest"] = hashlib.sha256(SCHEMA).hexdigest()
    result["learning_rule_digest"] = hashlib.sha256(RULE).hexdigest()
    result["parameter_mask_digest"] = hashlib.sha256(MASK).hexdigest()
    result["request_digest"] = request_digest(update_request())
    return result


def ledger(directory):
    return CostLedger(Path(directory) / "cost.jsonl", Budget(wall_seconds=300), binding()["request_digest"])


def session(directory):
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(14)
        flow = BatchedFlow(FlowConfig(input_size=2, content_size=2, bins=4, stages=2))
        readout = torch.nn.Linear(len(flow.feature_names), 1, dtype=torch.float64)
    return StreamingRidge(flow, readout, batch=2, ridge=0.01, binding=binding(), ledger=ledger(directory))


def observe(model, index):
    inputs = torch.tensor([[index / 10, -0.2], [0.1, index / 7]], dtype=torch.float64)
    targets = torch.tensor([[index / 4], [-index / 5]], dtype=torch.float64)
    return model.observe(inputs, dt=(index + 1) * 0.025, targets=targets,
                         boundary=torch.tensor([index / 20, -index / 30], dtype=torch.float64))


def candidate_record(candidate):
    return {name: tensor_record(value) for name, value in candidate.named_parameters()}


def cold_worker(root):
    root = Path(root)
    data = (root / "checkpoint.bin").read_bytes()
    acknowledged = json.loads((root / "acknowledged.json").read_text())
    model = StreamingRidge.restore(data, expected_binding=binding(),
                                   expected_digest=acknowledged["digest"], ledger=ledger(root))
    for index in (2, 3):
        observe(model, index)
    candidate = model.propose()
    (root / "continued.bin").write_bytes(model.snapshot())
    (root / "candidate.json").write_bytes(canonical(candidate_record(candidate)))


def export_native_fixture(path):
    with tempfile.TemporaryDirectory() as directory:
        model = session(directory)
        observe(model, 0)
        observe(model, 1)
        candidate = model.propose()
        data = model.snapshot()
        fixture = {"binding": binding(), "state_hex": data.hex(),
                   "state_digest": hashlib.sha256(data).hexdigest(),
                   "parameters_digest": hashlib.sha256(canonical(decode_state(data, binding())["parameters"])).hexdigest(),
                   "time_micros": model.state.time_micros,
                   "candidate_readout": candidate_record(candidate),
                   "update_request": update_request(),
                   "origin": "real BatchedFlow two observations and torch.linalg.solve; unit fixture, no task holdout"}
        fixture["cost_overruns"] = []
        with patch("qualification.hcsn_streaming.backend.copy.deepcopy", side_effect=RuntimeError("fixture copy failure")):
            try:
                model.propose()
            except RuntimeError:
                pass
        failed = model.snapshot()
        fixture["cost_overruns"].append({"kind": "failed", "state_hex": failed.hex(),
            "state_digest": hashlib.sha256(failed).hexdigest()})
        replay_root = Path(directory) / "discarded"
        replay = session(replay_root)
        observe(replay, 0)
        observe(replay, 1)
        checkpoint = replay.snapshot()
        replay.propose()
        replay = StreamingRidge.restore(checkpoint, expected_binding=binding(),
            expected_digest=hashlib.sha256(checkpoint).hexdigest(), ledger=ledger(replay_root))
        replay.propose()
        discarded = replay.snapshot()
        fixture["cost_overruns"].append({"kind": "discarded", "state_hex": discarded.hex(),
            "state_digest": hashlib.sha256(discarded).hexdigest()})
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(canonical(fixture) + b"\n")


class BackendTests(unittest.TestCase):
    def test_wire_rejects_ambiguous_shapes_duplicate_keys_and_nonfinite_json(self):
        value = tensor_record(torch.ones(1, 2, dtype=torch.float64))
        for first in (True, 1.0):
            with self.subTest(shape=first), self.assertRaises(ValueError):
                tensor_restore({**value, "shape": [first, 2]}, (1, 2))
        for value in ('{"shape": [], "shape": [1]}', '{"value": NaN}', '{"value": Infinity}'):
            with self.subTest(json=value), self.assertRaises(ValueError):
                parse_json(value)

    def test_noncanonical_geometry_and_missing_bias_cannot_be_admitted(self):
        with tempfile.TemporaryDirectory() as directory:
            original = session(directory)
            flow, readout = original.flow, original.readout
            flow.reset[0] += 0.01
            with self.assertRaises(ValueError):
                StreamingRidge(flow, readout, batch=2, ridge=0.01, binding=binding(), ledger=original.ledger)
            with self.assertRaises(ValueError):
                original.snapshot()
            other = session(Path(directory) / "other")
            no_bias = torch.nn.Linear(readout.in_features, 1, bias=False, dtype=torch.float64)
            with self.assertRaises(ValueError):
                StreamingRidge(other.flow, no_bias, batch=2, ridge=0.01, binding=binding(), ledger=other.ledger)

    def test_candidate_copy_failure_remains_charged_and_settled(self):
        with tempfile.TemporaryDirectory() as directory:
            model = session(directory)
            observe(model, 0)
            with patch("qualification.hcsn_streaming.backend.copy.deepcopy", side_effect=RuntimeError("copy failed")):
                with self.assertRaises(RuntimeError):
                    model.propose()
            self.assertEqual(model.solves, 0)
            self.assertEqual(model.ledger.cost["proposals"], 1)
            self.assertEqual(model.ledger.cost["failures"], 1)
            self.assertIsNone(model.ledger.pending)
            self.assertEqual(decode_state(model.snapshot(), binding())["controller"]["solves"], 0)

    def test_actual_cold_process_restores_next_flow_and_ridge_exactly(self):
        with tempfile.TemporaryDirectory() as directory:
            full_root, cold_root = Path(directory) / "full", Path(directory) / "cold"
            full, paused = session(full_root), session(cold_root)
            for index in (0, 1, 2, 3):
                observe(full, index)
            expected_candidate = candidate_record(full.propose())
            for index in (0, 1):
                observe(paused, index)
            data = paused.snapshot()
            (cold_root / "checkpoint.bin").write_bytes(data)
            (cold_root / "acknowledged.json").write_text(json.dumps({"digest": hashlib.sha256(data).hexdigest()}))
            subprocess.run([sys.executable, "-m", __spec__.name, "--cold", str(cold_root)], check=True)
            expected = decode_state(full.snapshot(), binding())
            actual = decode_state((cold_root / "continued.bin").read_bytes(), binding())
            # Wall time is physically different; all future-relevant numerical state is exact.
            for name in ("parameters", "backend", "controller", "rng", "history"):
                self.assertEqual(actual[name], expected[name])
            self.assertEqual(json.loads((cold_root / "candidate.json").read_text()), expected_candidate)
            self.assertGreater(len(actual["cost_ledger"]["records"]), 0)

    def test_proposal_cannot_change_active_readout(self):
        with tempfile.TemporaryDirectory() as directory:
            model = session(directory)
            before = candidate_record(model.readout)
            observe(model, 0)
            observe(model, 1)
            self.assertNotEqual(candidate_record(model.propose()), before)
            self.assertEqual(candidate_record(model.readout), before)

    def test_resume_keeps_discarded_work_charged_and_rng_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            model = session(directory)
            observe(model, 0)
            data = model.snapshot()
            observe(model, 1)  # Work beyond the retained checkpoint cannot be refunded.
            before = torch.get_rng_state().clone()
            restored = StreamingRidge.restore(data, expected_binding=binding(),
                expected_digest=hashlib.sha256(data).hexdigest(), ledger=ledger(directory))
            self.assertTrue(torch.equal(before, torch.get_rng_state()))
            self.assertEqual(restored.observations, 1)
            self.assertEqual(restored.ledger.cost["encoder_events"], 4)
            self.assertEqual(restored.discarded_observations, 1)
            self.assertEqual(decode_state(restored.snapshot(), binding())["controller"]["discarded_examples"], 2)

    def test_invalid_backend_or_controller_is_rejected_even_with_rebound_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            model = session(directory)
            observe(model, 0)
            original = model.snapshot()
            for mutation in ("mass", "clock", "count", "stats", "indefinite", "rng"):
                sections = decode_state(original, binding())
                if mutation == "mass":
                    sections["backend"]["density"]["bits"][0] = tensor_record(torch.tensor(20.0, dtype=torch.float64))["bits"][0]
                elif mutation == "clock":
                    sections["backend"]["time_micros"] = -1
                elif mutation == "count":
                    sections["controller"]["observations"] = 99
                elif mutation == "stats":
                    sections["history"]["gram"]["bits"][-1] = 0
                elif mutation == "indefinite":
                    width = model.gram.shape[0]
                    gram = torch.eye(width, dtype=torch.float64)
                    gram[0, 1] = gram[1, 0] = 2
                    gram[-1, -1] = model.examples
                    sections["history"]["gram"] = tensor_record(gram)
                else:
                    sections["rng"]["kind"] = "unknown"
                data = encode_state(binding(), {key: canonical(value) for key, value in sections.items()})
                with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                    StreamingRidge.restore(data, expected_binding=binding(),
                        expected_digest=hashlib.sha256(data).hexdigest(), ledger=ledger(directory))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--cold":
        cold_worker(sys.argv[2])
    elif len(sys.argv) == 3 and sys.argv[1] == "--fixture":
        export_native_fixture(sys.argv[2])
    else:
        unittest.main()
