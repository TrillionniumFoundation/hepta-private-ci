import copy
import unittest

import numpy as np

from contracts import ContractError, RunSession, RunSpec, UnsupportedModality, digest, validate_tensor


def specification():
    return {"objective_id": "objective:1", "run_id": "run:1", "artifact_sha256": "a" * 64,
            "modalities": ["text", "image"], "budget": {"compute_units": 10, "output_bytes": 8}, "deadline_ns": 100}


class ContractTests(unittest.TestCase):
    def test_all_modality_interface_rejects_unimplemented_profiles(self):
        for mode in ("audio", "video", "unknown"):
            value = specification()
            value["modalities"] = [mode]
            with self.assertRaises(UnsupportedModality):
                RunSpec.parse(value, now_ns=1)
            with self.assertRaises(UnsupportedModality):
                validate_tensor(mode, np.zeros(1))

    def test_invalid_request_boundaries(self):
        for field, invalid in (("objective_id", ""), ("artifact_sha256", "latest"), ("deadline_ns", 1),
                               ("modalities", ["text", "text"]), ("unknown", True)):
            value = specification()
            value[field] = invalid
            with self.assertRaises(ContractError):
                RunSpec.parse(value, now_ns=1)

    def test_tensor_validation_and_copy(self):
        original = np.zeros((16, 16, 3))
        validated = validate_tensor("image", original)
        original[:] = 1
        self.assertEqual(validated.sum(), 0)
        for mode, value in (("image", np.zeros((65, 2, 3))), ("text", [float("nan")]), ("text", [float("inf")]),
                            ("text", np.zeros(4097)), ("image", np.zeros((16, 16)))):
            with self.assertRaises(ContractError):
                validate_tensor(mode, value)

    def test_compute_includes_controller_and_rejection_is_atomic(self):
        session = RunSession(RunSpec.parse(specification(), now_ns=1))
        session.charge("controller", 3, now_ns=2)
        session.charge("generator", 7, now_ns=3)
        expected = session.checkpoint()
        with self.assertRaises(AttributeError):
            session.spec = RunSpec.parse(specification(), now_ns=1)
        with self.assertRaises(ContractError):
            session.charge("generator", 1, now_ns=4)
        self.assertEqual(session.checkpoint(), expected)
        self.assertEqual(session.spent, {"controller": 3, "generator": 7, "output_bytes": 0})

    def test_delivery_is_append_only_and_bounded(self):
        session = RunSession(RunSpec.parse(specification(), now_ns=1))
        session.publish("text", b"hello", expected_prefix_sha256=digest(b""), now_ns=2)
        for chunk, predecessor in ((b"x", digest(b"")), (b"world", digest(b"hello"))):
            with self.assertRaises(ContractError):
                session.publish("text", chunk, expected_prefix_sha256=predecessor, now_ns=3)
        self.assertEqual(session.prefix("text"), b"hello")

    def test_cancel_and_reload_preserve_identity_and_terminal_state(self):
        session = RunSession(RunSpec.parse(specification(), now_ns=1))
        session.charge("controller", 2, now_ns=2)
        session.publish("text", b"ok", expected_prefix_sha256=digest(b""), now_ns=3)
        session.cancel()
        checkpoint = session.checkpoint()
        restored = RunSession.restore(checkpoint, expected_artifact_sha256="a" * 64, now_ns=4)
        self.assertEqual(restored.checkpoint(), checkpoint)
        with self.assertRaises(ContractError):
            restored.charge("generator", 1, now_ns=5)
        for artifact, now in (("b" * 64, 4), ("a" * 64, 100)):
            with self.assertRaises(ContractError):
                RunSession.restore(checkpoint, expected_artifact_sha256=artifact, now_ns=now)
        corrupted = copy.deepcopy(checkpoint)
        corrupted["payload"]["spent"]["controller"] = 0
        with self.assertRaises(ContractError):
            RunSession.restore(corrupted, expected_artifact_sha256="a" * 64, now_ns=4)


if __name__ == "__main__":
    unittest.main()
