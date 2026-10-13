"""Actual saved-tensor counterexamples; synthetic inputs, never model efficacy."""
from copy import deepcopy
import hashlib
import json
import unittest

import torch

from development_study_data import canonical, phase
from development_study_replay import replay
import public_structural_checks as public_checks


class SelectionReplayChecks(unittest.TestCase):
    setUp = public_checks.ReplayChecks.setUp
    modify_record = public_checks.ReplayChecks.modify_record

    @classmethod
    def setUpClass(cls):
        cls.threads = torch.get_num_threads()
        torch.set_num_threads(1)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.threads)

    def rehash_selection(self, transform):
        sha = self.modify_record("selection.json", transform)
        self.modify_record("run.json", lambda r: r["sealed"].update(selection_sha256=sha))

    def test_valid_selection_counts_and_ties_reproduce(self):
        result = replay(self.output, self.dataset)["selection_replay"]
        original = json.loads((self.output / "selection.json").read_text())
        self.assertEqual(result["selected_arm"], original["selected_arm"])
        self.assertEqual(result["comparisons"], original["comparisons"])
        self.assertEqual(result["calibration_rows"], 8)
        self.assertFalse(result["physical_costs_attested"])

    def test_rehashed_changed_winner_is_rejected(self):
        def mutate(r):
            r["selected_arm"] = next(n for n in r["checkpoints"] if n != r["selected_arm"])
        self.rehash_selection(mutate)
        with self.assertRaisesRegex(ValueError, "selection does not reproduce"):
            replay(self.output, self.dataset)

    def test_rehashed_free_split_is_rejected(self):
        self.rehash_selection(lambda r: r["costs"]["adaptation"]["split"].update(stored_scalars=0))
        with self.assertRaisesRegex(ValueError, "cost differs"):
            replay(self.output, self.dataset)

    def test_rehashed_extra_training_steps_are_rejected(self):
        self.rehash_selection(lambda r: r["costs"]["adaptation"]["split"].update(steps=16))
        with self.assertRaisesRegex(ValueError, "cost differs"):
            replay(self.output, self.dataset)

    def test_rehashed_group_support_is_rejected(self):
        self.rehash_selection(lambda r: r["comparisons"]["frozen"].update(group_count=100000))
        with self.assertRaisesRegex(ValueError, "selection does not reproduce"):
            replay(self.output, self.dataset)

    def test_rehashed_lower_bound_is_rejected(self):
        self.rehash_selection(lambda r: r["comparisons"]["wider"].update(net_lower_bound=1.0))
        with self.assertRaisesRegex(ValueError, "selection does not reproduce"):
            replay(self.output, self.dataset)

    def test_rehashed_parameter_digest_is_rejected(self):
        self.rehash_selection(lambda r: r["costs"]["adaptation"]["continued"].update(parameter_digest="0"*64))
        with self.assertRaisesRegex(ValueError, "fitted parameter digest"):
            replay(self.output, self.dataset)

    def test_rehashed_generation_is_rejected(self):
        self.rehash_selection(lambda r: r["checkpoints"]["split"].update(generation=99))
        with self.assertRaisesRegex(ValueError, "generation mismatch"):
            replay(self.output, self.dataset)

    def test_rehashed_cell_alias_is_rejected(self):
        self.rehash_selection(lambda r: r["checkpoints"]["split"].update(cell_ids=["parent", "parent"]))
        with self.assertRaisesRegex(ValueError, "Cell/generation"):
            replay(self.output, self.dataset)

    def test_rehashed_training_source_identity_is_rejected(self):
        self.rehash_selection(lambda r: r.update(training_input_digest="0"*64))
        with self.assertRaisesRegex(ValueError, "training-input digest"):
            replay(self.output, self.dataset)

    def test_boolean_is_not_a_parameter_count(self):
        self.rehash_selection(lambda r: r["costs"]["adaptation"]["frozen"].update(steps=False))
        with self.assertRaisesRegex(ValueError, "cost differs"):
            replay(self.output, self.dataset)

    def test_supported_positive_split_is_not_rejected_by_default(self):
        from dataclasses import replace
        from development_tensors import BasisCellHeads, parameter_digest
        from development_study_fit import RoutedBank, select_candidate
        from development_selection_replay import verify_selection
        from development_study_data import digest
        from development_study_replay import tensor_forward
        config = replace(self.config, rank=1)
        models = {}
        for name in ("frozen", "continued", "wider", "more_data", "split"):
            rank, cells = (2 if name == "wider" else 1), (("parent", "child") if name == "split" else ("parent",))
            bank = BasisCellHeads(2, 2, rank, cells, generation=config.generation + int(name != "frozen"))
            with torch.no_grad():
                bank.base.weight.zero_(); bank.base.bias.zero_(); bank.basis.zero_(); bank.gate_axes.zero_()
                bank.basis[0, 0, 1] = 1
                if name == "split":
                    bank.coefficients[:, 0] = torch.tensor([-10., 10.])
            models[name] = RoutedBank(bank, torch.tensor([[-1., 0.], [1., 0.]]) if name == "split" else None)
        inputs = [{"sample_id": f"{p}-{i}", "source_group": f"{p}-{i}", "phase": p,
                   "input_fingerprint": "1"*64} for p, n in (("base", 2), ("adapt", 2), ("extra", 2), ("calibration", 64)) for i in range(n)]
        x = torch.tensor([[-1. if i % 2 else 1., 0.] for i in range(len(inputs))])
        y = torch.ones(64, dtype=torch.long)
        states, costs, inventory = {}, {}, {}
        for name, model in models.items():
            states[name] = model.state_dict()
            steps = 0 if name == "frozen" else config.adaptation_steps
            rows = 4 if name == "more_data" else 2
            costs[name] = {"stored_scalars": sum(v.numel() for v in states[name].values()),
                          "trainable_parameters": (len(model.bank.cell_ids) * (2*model.bank.rank+1)) if steps else 0,
                          "steps": steps, "sample_presentations": steps*rows, "training_rows": rows,
                          "parameter_digest": parameter_digest(model)}
            inventory[name] = {"cell_ids": model.bank.cell_ids, "generation": model.bank.generation}
        groups = [r["source_group"] for r in inputs if r["phase"] == "calibration"]
        selection = select_candidate({n: m(x[6:]) for n, m in models.items()}, y, groups, costs, config)
        selection.update(costs={"adaptation": costs}, checkpoints=inventory, training_input_digest=digest(inputs))
        result = verify_selection(selection, states, x, inputs, y, config, tensor_forward)
        self.assertEqual(result["selected_arm"], "split")
        self.assertTrue(all(r["net_lower_bound"] > 0 for r in result["comparisons"].values()))

    def test_independent_formula_rejects_finite_parameters_that_overflow(self):
        from safetensors.torch import load
        from development_study_replay import tensor_forward
        state = load((self.output / "frozen.safetensors").read_bytes())
        state["bank.base.weight"].fill_(3e38)
        with self.assertRaisesRegex(ValueError, "nonfinite independently"):
            tensor_forward(state, torch.full((1, 4), 3e38), 1, 2)

    def test_evaluation_labels_do_not_change_calibration_choice(self):
        before = replay(self.output, self.dataset)["selection_replay"]
        rows = deepcopy(self.rows)
        for r in rows:
            if phase(r) in {"held_out", "future_1", "future_2", "ood"}:
                r["label"] = 1 - r["label"]
        self.dataset.write_bytes(b"".join(canonical(r) for r in rows))
        self.modify_record("run.json", lambda r: r.update(dataset_sha256=hashlib.sha256(self.dataset.read_bytes()).hexdigest()))
        self.assertEqual(before, replay(self.output, self.dataset)["selection_replay"])


if __name__ == "__main__":
    unittest.main()
