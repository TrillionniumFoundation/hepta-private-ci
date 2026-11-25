"""Engineering admission tests only; no frozen PFT experiment is rerun."""

import copy
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from distributed import Receiver, array_hash, hashed, seal
from transport import worker


def header(size=2):
    return {"size": size, "parent_id": hashed("parent"),
            "coordinate_id": hashed("coordinates"), "objective_id": hashed("objective")}


def contribution(binding, x, y, client="a", data="data-a"):
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    return seal({**binding, "client_id": client, "count": len(x),
                 "data_sha256": hashed(data), "gram": (x.T @ x).tolist(),
                 "moment": (x.T @ y).tolist()})


class AdmissionTests(unittest.TestCase):
    def test_pooled_effective_direction_solution_matches_augmented_least_squares(self):
        # Fixed 3D parent, two effective coordinates, deliberately unequal shards.
        basis = np.array([[0., 1.], [1., 0.], [0., 0.]])
        parent = np.array([.2, -.1, .5])
        x = np.array([[1., 0., 2.], [4., .2, 1.], [3., -.1, -2.], [0., 2., 1.]])
        y = np.array([1., 2., -1., 3.])
        design, residual = x @ basis, y - x @ parent
        binding = {**header(), "parent_id": array_hash(parent), "coordinate_id": array_hash(basis)}
        messages = [contribution(binding, design[:3], residual[:3]),
                    contribution(binding, design[3:], residual[3:], "b", "data-b")]
        receivers = [Receiver(binding), Receiver(binding)]
        for receiver, order in zip(receivers, ((0, 1, 0), (1, 0, 1)), strict=True):
            self.assertEqual([receiver.accept(messages[i]) for i in order], ["accepted", "accepted", "duplicate"])
        for actual, expected in zip(receivers[0].sums(), receivers[1].sums(), strict=True):
            np.testing.assert_array_equal(actual, expected)
        gram, moment = receivers[0].sums()
        ridge = .2  # Add the shared prior once after pooling.
        action = np.linalg.solve(gram + ridge * np.eye(2), moment)
        reference = np.linalg.lstsq(np.vstack((design, np.sqrt(ridge) * np.eye(2))),
                                   np.r_[residual, np.zeros(2)], rcond=None)[0]
        np.testing.assert_allclose(parent + basis @ action, parent + basis @ reference, rtol=1e-12, atol=1e-12)
        self.assertEqual(receivers[0].freeze("cutoff"), receivers[1].freeze("cutoff"))

    def test_caller_cannot_mutate_registered_identity_or_contribution(self):
        binding = header()
        message = contribution(binding, np.eye(2), [1., 2.])
        receiver = Receiver(binding)
        binding["parent_id"] = hashed("changed")
        receiver.header["coordinate_id"] = hashed("changed")
        self.assertEqual(receiver.accept(message), "accepted")
        message["gram"][0][0] = 900.
        receiver.messages[next(iter(receiver.messages))]["moment"][0] = 1000.
        gram, moment = receiver.sums()
        np.testing.assert_array_equal(gram, np.eye(2))
        np.testing.assert_array_equal(moment, [1., 2.])

    def test_declared_data_replay_under_another_client_is_rejected(self):
        receiver = Receiver(header())
        message = contribution(header(), np.eye(2), [1., 2.])
        self.assertEqual(receiver.accept(message), "accepted")
        replay = seal({**message, "client_id": "another-client"})
        self.assertNotEqual(replay["contribution_id"], message["contribution_id"])
        self.assertEqual(receiver.accept(replay), "rejected_duplicate_data")
        self.assertEqual(len(receiver.messages), 1)

    def test_boolean_counts_and_dimensions_are_not_integers(self):
        message = contribution(header(1), [[1.]], [1.])
        for key, status in (("count", "rejected_count"), ("size", "rejected_shape")):
            with self.subTest(key=key):
                self.assertEqual(Receiver(header(1)).accept(seal({**message, key: True})), status)
        for invalid in (None, {}, {**header(), "size": True}, {**header(), "parent_id": "not-a-digest"}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                Receiver(invalid)
        self.assertEqual(Receiver(header()).accept(None), "rejected_malformed")

    def test_incompatible_identity_integrity_and_same_id_conflict(self):
        message = contribution(header(), np.eye(2), [1., 2.])
        receiver = Receiver(header())
        self.assertEqual(receiver.accept(message), "accepted")
        for key, status in (("parent_id", "rejected_stale_parent"),
                            ("coordinate_id", "rejected_wrong_coordinates"),
                            ("objective_id", "rejected_wrong_objective")):
            self.assertEqual(receiver.accept(seal({**message, key: hashed("different")})), status)
        tampered = copy.deepcopy(message)
        tampered["moment"][0] += 1.
        self.assertEqual(receiver.accept(tampered), "rejected_integrity")
        self.assertEqual(receiver.accept(seal(tampered)), "rejected_conflicting_contribution")

    def test_obviously_impossible_statistics_are_rejected(self):
        base = contribution(header(), np.eye(2), [1., 2.])
        cases = [({"gram": [[1., 0.], [0., -1.]]}, "rejected_non_psd_gram"),
                 ({"gram": [[0., 0.], [0., 0.]]}, "rejected_inconsistent_moment"),
                 ({"gram": [[1., 1.], [1., 1.]], "moment": [1., -1.]}, "rejected_inconsistent_moment"),
                 ({"count": 1}, "rejected_impossible_sample_rank"),
                 ({"gram": [[1., .1], [0., 1.]]}, "rejected_non_psd_gram")]
        for changed, status in cases:
            with self.subTest(changed=changed):
                receiver = Receiver(header())
                self.assertEqual(receiver.accept(seal({**base, **changed})), status)
                self.assertEqual(receiver.messages, {})

    def test_small_positive_directions_and_tiny_gram_are_preserved(self):
        # A small nonzero eigenvalue cannot be discarded merely by rcond.
        for scale in (1e-10, 1e-150):
            with self.subTest(scale=scale):
                x = np.diag([1., scale])
                message = contribution(header(), x, [0., 1.])
                receiver = Receiver(header())
                self.assertEqual(receiver.accept(message), "accepted")
                np.testing.assert_array_equal(receiver.sums()[1], [0., scale])
        receiver = Receiver(header())
        message = contribution(header(), np.eye(2) * 1e-150, [1e100, -1e100])
        self.assertEqual(receiver.accept(message), "accepted")
        # Rounding-level negative Gram eigenvalues are inconclusive, not a
        # reason to claim malicious data or discard a genuine contribution.
        rounded = seal({**contribution(header(), np.eye(2), [1., 0.]),
                        "gram": [[1., 0.], [0., -1e-16]]})
        self.assertEqual(Receiver(header()).accept(rounded), "accepted")

    def test_finite_individual_packets_cannot_overflow_the_aggregate(self):
        base = contribution(header(), np.eye(2), [0., 0.])
        for changed in ({"gram": [[1e308, 0.], [0., 1e308]]}, {"moment": [1e308, 0.]}):
            with self.subTest(changed=changed):
                receiver = Receiver(header())
                first = seal({**base, **changed})
                second = seal({**first, "client_id": "b", "data_sha256": hashed("b")})
                self.assertEqual(receiver.accept(first), "accepted")
                before = receiver.sums()
                self.assertEqual(receiver.accept(second), "rejected_aggregate_overflow")
                for actual, expected in zip(receiver.sums(), before, strict=True):
                    np.testing.assert_array_equal(actual, expected)
                self.assertEqual(len(receiver.messages), 1)

    def test_late_data_requires_a_distinct_fork_and_snapshot(self):
        receiver = Receiver(header())
        first = contribution(header(), np.eye(2), [1., 2.])
        late = contribution(header(), [[2., 1.]], [4.], "b", "late-data")
        receiver.accept(first)
        frozen = receiver.freeze("before-independent-task")
        self.assertEqual(receiver.accept(first), "duplicate")
        self.assertEqual(receiver.accept(late), "rejected_frozen_candidate")
        with self.assertRaises(ValueError):
            receiver.freeze("rewrite-cutoff")
        next_receiver = receiver.fork()
        self.assertEqual(next_receiver.accept(late), "accepted")
        successor = next_receiver.freeze("next-task-cutoff")
        self.assertEqual(successor["parent_snapshot_id"], frozen["snapshot_id"])
        self.assertNotEqual(successor["snapshot_id"], frozen["snapshot_id"])
        self.assertEqual(receiver.freeze("before-independent-task"), frozen)

    def test_cold_restore_retains_freeze_and_external_bindings(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ledger.json"
            receiver = Receiver(header())
            receiver.accept(contribution(header(), np.eye(2), [1., 2.]))
            frozen = receiver.freeze("candidate-cutoff")
            receiver.checkpoint(path)
            restored = Receiver.restore(path, expected_header=header(), expected_snapshot_id=frozen["snapshot_id"])
            self.assertEqual(restored.freeze("candidate-cutoff"), frozen)
            self.assertEqual(restored.accept(contribution(header(), [[1., 2.]], [3.], "b", "late")), "rejected_frozen_candidate")
            for binding in ({"expected_header": {**header(), "parent_id": hashed("other")}},
                            {"expected_snapshot_id": hashed("other")}):
                with self.subTest(binding=binding), self.assertRaises(ValueError):
                    Receiver.restore(path, **binding)
            changed = json.loads(path.read_text())
            changed["body"]["snapshot"]["statistics_sha256"] = hashed("changed")
            changed["body_sha256"] = hashed(changed["body"])
            path.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):
                Receiver.restore(path)

    def test_legacy_unfrozen_checkpoint_is_readable_and_can_be_pinned(self):
        message = contribution(header(), np.eye(2), [1., 2.])
        body = {"header": header(), "messages": [message]}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "legacy.json"
            path.write_text(json.dumps({"body": body, "body_sha256": hashed(body)}))
            restored = Receiver.restore(path, expected_header=header())
            self.assertEqual(restored.accept(message), "duplicate")
            with self.assertRaises(ValueError):
                Receiver.restore(path, expected_snapshot_id=hashed("not-frozen"))

    def test_existing_worker_cli_persists_a_closed_candidate(self):
        # One bounded peer exercises the actual worker publication path without
        # repeating the four-peer research campaign or claiming P2P evidence.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                address = list(reservation.getsockname())
            binding = {**header(), "parent_id": array_hash(np.zeros(2)),
                       "objective_id": hashed({"ridge": .2, "loss": "sum squared residual", "version": 1})}
            message = contribution(binding, np.eye(2), [1., 2.])
            config = {"node": 0, "directory": str(root), "header": binding,
                      "message": message, "crash_once": False, "addresses": [address],
                      "startup_delay_seconds": 0, "round_id": "engineering-cutoff",
                      "ridge": .2, "parent": [0., 0.]}
            config_path = root / "config.json"
            config_path.write_text(json.dumps(config))
            result = subprocess.run([sys.executable, str(Path(__file__).with_name("transport.py")),
                                     "--worker", str(config_path)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            publication = json.loads((root / "result.json").read_text())
            restored = Receiver.restore(root / "ledger.json", expected_header=binding,
                                        expected_snapshot_id=publication["statistics_snapshot_id"])
            self.assertEqual(restored.freeze("engineering-cutoff")["snapshot_id"], publication["statistics_snapshot_id"])
            self.assertEqual(restored.accept(contribution(binding, [[2., 0.]], [3.], "b", "late")), "rejected_frozen_candidate")
            np.testing.assert_allclose(publication["candidate"], np.array([1., 2.]) / 1.2)

    def test_worker_refuses_a_different_actual_objective_before_side_effects(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            binding = {**header(), "objective_id": hashed({"ridge": .2, "loss": "sum squared residual", "version": 1})}
            with patch("transport.Peer") as peer, patch("transport.run_case") as old_campaign:
                for changed in (.3, True, -1., 0., None, float("nan"), float("inf")):
                    with self.subTest(ridge=changed), self.assertRaises(ValueError):
                        path.write_text(json.dumps({"header": binding, "ridge": changed}))
                        worker(path, False)
                peer.assert_not_called()
                old_campaign.assert_not_called()
            self.assertEqual(list(Path(temp).iterdir()), [path])

    def test_worker_binds_the_actual_parent_before_side_effects(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            binding = {**header(), "parent_id": array_hash(np.zeros(2)),
                       "objective_id": hashed({"ridge": .2, "loss": "sum squared residual", "version": 1})}
            with patch("transport.Peer") as peer:
                for parent in ([1., 0.], [0.], [0., float("inf")]):
                    with self.subTest(parent=parent), self.assertRaises(ValueError):
                        path.write_text(json.dumps({"header": binding, "ridge": .2, "parent": parent}))
                        worker(path, False)
                peer.assert_not_called()
            self.assertEqual(list(Path(temp).iterdir()), [path])


if __name__ == "__main__":
    unittest.main()
