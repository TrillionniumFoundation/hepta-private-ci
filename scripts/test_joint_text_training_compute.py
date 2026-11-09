"""Small synthetic numerical checks, requiring an already installed Torch.

These fixtures do not stand for a real task, signed source, owner admission,
production loading, or qualification. A missing Torch leaves them unexecuted.
"""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import joint_text_training_contract as contract  # noqa: E402
from scripts import joint_text_training_io as worker_io  # noqa: E402
from scripts.test_joint_text_training_contract import synthetic_request  # noqa: E402


class JointTextNumerics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import torch
        from scripts import joint_text_training_compute as compute
        from scripts.joint_generation_v4_io import packet_bytes, read_packet
        from scripts.joint_generation_v4_model import JointGeneratorV4

        cls.torch, cls.compute = torch, compute
        cls.packet_bytes, cls.read_packet = (
            staticmethod(packet_bytes),
            staticmethod(read_packet),
        )
        cls.model_type = JointGeneratorV4

    def fixture(self, inference="actor-greedy-observed-v1", zero=False):
        self.torch.manual_seed(811)
        model = self.model_type(allow_initial_stop=True, suppress_redundant_verify=True)
        if zero:
            with self.torch.no_grad():
                for parameter in model.parameters():
                    parameter.zero_()
        predecessor = model.export_weights(inference_profile=inference)
        request = synthetic_request()
        request.update(
            prefix="A",
            continuation="B",
            steps=2,
            source_content_sha256=contract.sha(b"AB"),
            predecessor_sha256=contract.sha(predecessor),
            predecessor_bytes=len(predecessor),
            maximum_training_milliseconds=300000,
        )
        contract.validate_request(contract.json_bytes(request))
        return request, predecessor

    def test_real_core_gradient_change_and_inactive_groups(self):
        request, predecessor = self.fixture()
        result = self.compute.train_candidate(request, predecessor, lambda: None)
        self.assertNotEqual(result["candidate_bytes"], predecessor)
        groups = {row["group"]: row for row in result["training"]["parameter_groups"]}
        self.assertGreater(groups["core"]["gradient_nonzero_parameters"], 0)
        self.assertGreater(groups["core"]["changed_parameters"], 0)
        self.assertEqual(groups["other_heads"]["gradient_present_parameters"], 0)
        self.assertEqual(groups["other_heads"]["gradient_nonzero_parameters"], 0)
        self.assertEqual(groups["other_heads"]["changed_parameters"], 0)
        self.assertEqual(len(result["training"]["losses_f64_be"]), 3)
        before_meta, _ = self.read_packet(predecessor)
        after_meta, _ = self.read_packet(result["candidate_bytes"])
        self.assertEqual(before_meta, after_meta)
        self.assertEqual(after_meta["allow_initial_stop"], "true")
        self.assertEqual(after_meta["suppress_redundant_verify"], "true")
        self.assertEqual(result["training"]["source_samples"], 1)
        self.assertEqual(result["training"]["source_record_count"], 3)
        self.assertEqual(result["training"]["dataset_observed_rows"], 7)

    def test_actual_text_target_changes_update(self):
        request, predecessor = self.fixture()
        request["steps"] = 1
        first = self.compute.train_candidate(request, predecessor, lambda: None)
        request["continuation"] = "C"
        request["source_content_sha256"] = contract.sha(b"AC")
        second = self.compute.train_candidate(request, predecessor, lambda: None)
        self.assertNotEqual(first["candidate_bytes"], second["candidate_bytes"])

    def test_complete_metadata_and_tensor_profile_rejected(self):
        _, predecessor = self.fixture()
        metadata, tensors = self.read_packet(predecessor)
        for changes in (
            {"unexpected": "must-not-be-normalized"},
            self.compute.NDU_DEFAULTS,
            {"core_state_profile": "reset-each-action-v1"},
        ):
            with (
                self.subTest(changes=changes),
                self.assertRaises(contract.ContractError),
            ):
                self.compute.load_predecessor(
                    self.packet_bytes({**metadata, **changes}, tensors)
                )
        wrong_shape = dict(tensors)
        wrong_shape["token_encoder.weight"] = wrong_shape["token_encoder.weight"][:-1]
        with self.assertRaises(contract.ContractError):
            self.compute.load_predecessor(self.packet_bytes(metadata, wrong_shape))
        _, ndu = self.fixture("ndu-finite-deterministic-v1")
        restored, inference = self.compute.load_predecessor(ndu)
        self.assertEqual(restored.export_weights(inference_profile=inference), ndu)
        metadata, tensors = self.read_packet(ndu)
        metadata["ndu.risk"] = "0.5"
        with self.assertRaises(contract.ContractError):
            self.compute.load_predecessor(self.packet_bytes(metadata, tensors))

    def test_zero_core_gradient_and_expired_budget_do_not_yield_candidate(self):
        request, predecessor = self.fixture(zero=True)
        with self.assertRaisesRegex(contract.ContractError, "no_core_gradient"):
            self.compute.train_candidate(request, predecessor, lambda: None)

        def expired():
            raise contract.ContractError("cooperative_wall_budget")

        with self.assertRaisesRegex(contract.ContractError, "cooperative_wall_budget"):
            self.compute.train_candidate(request, predecessor, expired)

    def test_actual_worker_process_durable_candidate_bindings(self):
        request, predecessor = self.fixture()
        request["steps"] = 1
        request["execution_source_digest"] = worker_io.SourceClosure(ROOT).digest
        raw = contract.json_bytes(request)
        with tempfile.TemporaryDirectory(
            prefix="joint-numerical-synthetic-"
        ) as directory:
            root = Path(directory).resolve()
            request_path, predecessor_path, output = (
                root / "request.json",
                root / "previous.heptapk",
                root / "output",
            )
            request_path.write_bytes(raw)
            predecessor_path.write_bytes(predecessor)
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(ROOT / "scripts/joint_generation_v4_text_worker.py"),
                    "--request",
                    str(request_path),
                    "--predecessor",
                    str(predecessor_path),
                    "--output",
                    str(output),
                ],
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            observation_raw = (output / "observation.json").read_bytes()
            observation = contract.validate_observation(observation_raw, request)
            candidate = (output / "candidate.heptapk").read_bytes()
            completed = json.loads((output / "completed.json").read_bytes())
            self.assertEqual(
                completed["observation_sha256"], contract.sha(observation_raw)
            )
            self.assertEqual(completed["candidate_sha256"], contract.sha(candidate))
            self.assertEqual(
                observation["candidate"]["sha256"], contract.sha(candidate)
            )
            self.assertEqual(observation["request_sha256"], contract.sha(raw))
            self.assertEqual(observation["authority"], "DENY_ALL")
            self.assertIsNone(observation["cost"]["full_history_cost"])
            self.assertEqual(request_path.read_bytes(), raw)
            self.assertEqual(predecessor_path.read_bytes(), predecessor)
            self.assertEqual(
                {path.name for path in output.iterdir()},
                {
                    "started.json",
                    "candidate.heptapk",
                    "observation.json",
                    "completed.json",
                },
            )


if __name__ == "__main__":
    unittest.main()
