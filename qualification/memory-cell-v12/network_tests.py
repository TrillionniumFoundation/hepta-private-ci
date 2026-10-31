"""Behavioral regression checks; these fixtures are not efficacy evidence."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from learned import MLP, features
from categorical import train_categorical
from network import Cell, Network, active_mask, fit_cell, lower_gain
from network_experiment import (load_network, refresh, save_network, structure,
                                targets_matrix, verify_refresh)


class NetworkTests(unittest.TestCase):
    def test_categorical_multisource_learning_and_exact_optimizer_restore(self):
        x = np.eye(7, dtype=np.float32)
        y = np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0],
                      [0, 0, 0, 1], [1, 1, 0, 0], [0, 0, 1, 1],
                      [0, 0, 0, 0]], dtype=np.float32)
        model = train_categorical(x, y, hidden=12, steps=240, seed=313)
        self.assertEqual(model.receipt["ignored_empty_target_rows"], 1)
        for i in range(6):
            targets = set(np.flatnonzero(y[i]))
            predicted = set(np.argsort(-model.predict(x[i:i + 1])[0])[:len(targets)])
            self.assertEqual(targets, predicted)
        self.assertTrue(all(value > 0 for value in model.receipt["parameter_change_norm"].values()))
        restored = MLP.from_export(model.export(include_optimizer=True))
        left = train_categorical(x, y, hidden=12, steps=10, seed=17, initial=model)
        right = train_categorical(x, y, hidden=12, steps=10, seed=17, initial=restored)
        for name in left.arrays:
            np.testing.assert_array_equal(left.arrays[name], right.arrays[name])
        cell = Cell("categorical", "semantic", restored, list(range(4)), ["source"])
        np.testing.assert_allclose(cell.scores(x, 4).sum(axis=1), np.ones(len(x)), atol=1e-6)

    def test_shared_document_sections_and_future_versions(self):
        records = [dict(id="a1", source_id="filehash", path="guide", heading="A", version=1),
                   dict(id="b1", source_id="filehash", path="guide", heading="B", version=1),
                   dict(id="a2", source_id="changed", path="guide", heading="A", version=2,
                        available_phase=1, withdrawn_phase=2)]
        np.testing.assert_array_equal(active_mask(records, 0), [True, True, False])
        np.testing.assert_array_equal(active_mask(records, 1), [False, True, True])
        np.testing.assert_array_equal(active_mask(records, 2), [False, True, False])

    def test_actual_sparse_router_skips_unselected_models(self):
        x = features(["owner lease authority", "query memory evidence", "owner lease", "memory query"], dimension=16)
        y = np.array([[1, 0], [0, 1], [1, 0], [0, 1]], dtype=np.float32)
        cells = [fit_cell(str(i), "specialist", x, y, [i], ["source"], hidden=8, steps=80, seed=i + 1)
                 for i in range(2)]
        network = Network(cells, 2, top_k=1)
        network.fit_router(x, y)
        self.assertGreater(network.router_receipt["parameter_change_l2"], 0)
        for cell in cells:
            cell.calls = 0
        scores, selected = network.scores(x, np.ones(2, dtype=bool))
        self.assertEqual(sum(cell.calls for cell in cells), len(x))
        self.assertEqual([len(row) for row in selected], [1] * len(x))
        self.assertTrue(np.isfinite(scores).all())
        self.assertGreater(len(set(row[0] for row in selected)), 1)

    def test_sleep_wake_restores_optimizer_and_rejects_corruption(self):
        x = features(["owner", "memory"], dimension=8)
        cell = fit_cell("one", "semantic", x, np.eye(2), [0, 1], ["source"], hidden=4, steps=20, seed=9)
        original = cell.model.export(include_optimizer=True)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sleep.json"
            cell.sleep(path)
            self.assertIsNone(cell.model)
            with self.assertRaises(RuntimeError):
                cell.scores(x, 2)
            cell.wake()
            self.assertEqual(cell.model.export(include_optimizer=True), original)
            cell.sleep(path)
            value = json.loads(path.read_text())
            value["parameter_sha256"] = "0" * 64
            path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):
                cell.wake()

    def test_router_skips_sleeping_cells_and_accounts_actual_historical_reads(self):
        x = np.eye(4, dtype=np.float32)
        y = np.array([[1, 0], [0, 1], [1, 0], [0, 1]], dtype=np.float32)
        cells = [fit_cell(str(i), "specialist", x, y, [i], ["source"],
                          hidden=4, steps=10, seed=i + 21) for i in range(2)]
        network = Network(cells, 2, top_k=1)
        with tempfile.TemporaryDirectory() as temp:
            cells[0].sleep(Path(temp) / "first.json")
            network.fit_router(x, y)
            self.assertEqual([cell.calls for cell in cells], [0, len(x)])
            self.assertEqual(network.router_receipt["evaluated_cells"], ["1"])
            self.assertEqual(network.router_receipt["sleeping_cells"], ["0"])
            self.assertEqual(network.resource()["router_historical_cell_reads"], len(x))
            np.testing.assert_array_equal(network.router[:, 0], np.zeros(x.shape[1] + 1))
            _, routes = network.scores(x, np.ones(2, dtype=bool))
            self.assertEqual(routes, [["1"] for _ in x])
            cells[1].sleep(Path(temp) / "second.json")
            network.fit_router(x, y)
            self.assertEqual(network.router_receipt["historical_cell_reads"], 0)
            scores, routes = network.scores(x, np.ones(2, dtype=bool))
            np.testing.assert_array_equal(scores, np.zeros((len(x), 2)))
            self.assertEqual(routes, [[] for _ in x])

    def test_refresh_keeps_unassigned_parameters_and_optimizer_without_fake_training(self):
        x, y = np.eye(4, dtype=np.float32), np.eye(4, dtype=np.float32)
        cells = [fit_cell(name, "specialist", x, y, range(4), ["source"],
                          hidden=4, steps=10, seed=i + 40)
                 for i, name in enumerate(("assigned", "unassigned"))]
        # A stable tied router chooses the first expert for every historical row.
        previous = Network(cells, 4, top_k=1, router=np.zeros((5, 2), dtype=np.float32))
        untouched = cells[1].export()
        result = refresh(previous, x, y, np.ones(4, bool), ["new-source"], 71,
                         dict(hidden=4, steps=10))
        verify_refresh(previous, result)
        self.assertEqual(result.cells[1].export(), untouched)
        self.assertEqual([row["action"] for row in result.refresh_receipt], ["continued", "unassigned"])
        self.assertEqual(Network.restore(result.export()).refresh_receipt, result.refresh_receipt)

    def test_selected_split_sleep_and_wake_survive_next_phase_and_portable_restore(self):
        # Admission is injected only to cover successful selection branches.
        # Model training, optimizer restoration, disk IO, routing, and subsequent
        # maintenance all execute; this is not evidence of a utility improvement.
        texts = ["owner authority lease", "memory source proof", "owner renewal state", "memory source snapshot"]
        x, y = features(texts, dimension=8), np.eye(4, dtype=np.float32)
        rows = [dict(id=str(i), text=text) for i, text in enumerate(texts)]
        mask = np.ones(4, bool)
        protocol = json.loads(Path(__file__).with_name("NETWORK_PROTOCOL.json").read_text())
        protocol.update(hidden=4, steps=20, dimension=8)
        for action in ("split", "sleep", "wake"):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                first, second = root / "phase-1", root / "phase-2"
                first.mkdir()
                second.mkdir()
                parent = Network([fit_cell("parent", "universal", x, y, range(4), ["source"],
                                           hidden=4, steps=20, seed=51)], 4)
                comparison = 0

                def forced_gate(*args, **kwargs):
                    nonlocal comparison
                    candidate = ("split", "merge", "sleep", "wake")[comparison // 4]
                    comparison += 1
                    accepted = candidate == action
                    return dict(mean=1. if accepted else -1., lower=1. if accepted else -1.,
                                admitted=accepted)

                with patch("network_experiment.lower_gain", side_effect=forced_gate):
                    selected, _, _, _ = structure(parent, x, y, mask, ["new-source"],
                        rows, x, [[i] for i in range(4)], first, 53, protocol)
                self.assertEqual(json.loads((first / "DECISIONS.json").read_text())["selected"], action)
                self.assertEqual([cell.model is None for cell in selected.cells],
                                 [action == "sleep", False])
                continued = refresh(selected, x, y, mask, ["later-source"], 57, protocol)
                verify_refresh(selected, continued)
                save_network(second / "selected.json.gz", continued)
                recovered = load_network(second / "selected.json.gz")
                verify_refresh(selected, recovered)
                np.testing.assert_array_equal(continued.scores(x, mask)[0], recovered.scores(x, mask)[0])
                if action == "sleep":
                    source_checkpoint = Path(selected.cells[0].sleeping["path"])
                    copied_checkpoint = Path(recovered.cells[0].sleeping["path"])
                    self.assertNotEqual(source_checkpoint.resolve(), copied_checkpoint.resolve())
                    self.assertTrue(copied_checkpoint.is_file())
                    source_checkpoint.unlink()
                    recovered.cells[0].wake()
                    recovered.fit_router(x, y)
                    self.assertTrue(np.isfinite(recovered.scores(x, mask)[0]).all())

    def test_real_structural_cycle_preserves_parent_and_writes_all_decisions(self):
        texts = ["owner authority lease", "memory source proof", "owner renewal state", "memory source snapshot"]
        x = features(texts, dimension=8)
        y = np.eye(4, dtype=np.float32)
        cell = fit_cell("parent", "universal", x, y, range(4), ["root-a", "root-b"],
                        hidden=4, steps=40, seed=13)
        parent = Network([cell], 4)
        before = copy.deepcopy(parent.export())
        rows = [dict(id=str(i), text=text) for i, text in enumerate(texts)]
        protocol = json.loads(Path(__file__).with_name("NETWORK_PROTOCOL.json").read_text())
        protocol.update(hidden=4, steps=40, dimension=8)
        with tempfile.TemporaryDirectory() as temp:
            restored, decisions, controls, candidates = structure(parent, x, y, np.ones(4, bool),
                ["new-source"], rows, x, [[i] for i in range(4)], Path(temp), 17, protocol)
            self.assertEqual(parent.export(), before)
            self.assertEqual({d["action"] for d in decisions}, {"split", "merge", "sleep", "wake"})
            self.assertEqual(candidates["sleep"].cells[0].model, None)
            self.assertIsNotNone(candidates["wake"].cells[0].model)
            for child in candidates["split"].cells:
                self.assertTrue({"root-a", "root-b"}.issubset(child.dependencies))
                self.assertGreater(child.receipts[-1]["initial_optimizer_step"], 0)
            replay = load_network(Path(temp) / "selected.json.gz")
            np.testing.assert_array_equal(restored.scores(x, np.ones(4, bool))[0],
                                          replay.scores(x, np.ones(4, bool))[0])
            self.assertTrue(all(d["all_exploration_penalty"] >= 0 for d in decisions))

    def test_equal_outcomes_do_not_justify_extra_cost(self):
        result = lower_gain([1, 0, 1, 1], [1, 0, 1, 1], .2, .1)
        self.assertFalse(result["admitted"])
        self.assertLess(result["lower"], 0)


if __name__ == "__main__":
    unittest.main()
