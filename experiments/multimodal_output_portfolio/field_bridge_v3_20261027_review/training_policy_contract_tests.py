"""Synthetic tests of whole-trajectory fitting and actual terminal bank control flow."""

from copy import deepcopy
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import numpy as np

from ..field_bridge_v3_20261027 import training_bank as B
from ..field_bridge_v3_20261027.training_common import Costs, MODES, configuration, file_hash, object_hash
from ..field_bridge_v3_20261027.training_policy import fit_bank, predict


class TrainingPolicyContracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hepta-v3-policy-contract-")
        self.root = Path(self.temporary.name)
        self.protocol = json.loads((Path(__file__).parent.parent / "field_bridge_v3_20261027/PROTOCOL.json").read_text())
        self.p = configuration(self.protocol)

    def tearDown(self):
        self.temporary.cleanup()

    def write_bank(self, path, raw, values):
        rows = [{"trajectory": i // 6, "step": (i % 6) * 48, "state": raw[i].tolist(),
                 "action_values": values[i].tolist()} for i in range(24)]
        path.write_text(json.dumps({"seed": 17, "records": rows, "reference_sha256": "synthetic",
                                   "training_configuration_sha256": object_hash(self.p)}))

    def test_group_cv_excludes_entire_heldout_trajectory_from_normalization_and_fit(self):
        rng = np.random.default_rng(9071)
        raw, values = rng.normal(size=(24, 30)), rng.normal(size=(24, 4))
        source = self.root / "bank.json"
        self.write_bank(source, raw, values)
        first = self.root / "fit-one"; first.mkdir()
        result = fit_bank(source, first, self.protocol)
        raw[:6] += 1000.; values[:6] -= 1000.
        self.write_bank(source, raw, values)
        second = self.root / "fit-two"; second.mkdir()
        changed = fit_bank(source, second, self.protocol)
        for mode in MODES:
            for index in range(3):
                a = result["all_candidates"][mode]["candidates"][index]["folds"][0]
                b = changed["all_candidates"][mode]["candidates"][index]["folds"][0]
                self.assertEqual(a["head"], b["head"])
                self.assertEqual(a["training_trajectories"], [1, 2, 3])
                self.assertEqual(a["head"]["fit_rows"], 18)
            self.assertEqual(result["controllers"][mode]["dimension"], {"field": 12, "generic": 12, "richer": 30, "h7": 7}[mode])

    def test_equal_cv_scores_use_first_registered_alpha_and_prediction_tie_is_first_action(self):
        source = self.root / "bank.json"
        self.write_bank(source, np.random.default_rng(9).normal(size=(24, 30)), np.zeros((24, 4)))
        out = self.root / "fit"; out.mkdir()
        result = fit_bank(source, out, self.protocol)
        for mode in MODES:
            self.assertEqual(result["all_candidates"][mode]["selected_index"], 0)
            self.assertEqual(int(np.argmax(predict(result["controllers"][mode], np.zeros(30)))), 0)
        self.assertEqual(result["resources"]["linear_system_solves"], 60)

    def test_terminal_bank_uses_reference_tail_but_advances_only_chosen_prefix(self):
        costs = Costs()
        baseline = {"values": {"reward": np.array([0.])}, "output_sha256": ["synthetic"],
                    "source_ids": [("synthetic:a", "synthetic:b")], "means": {"reward": 0.}}
        context = SimpleNamespace(protocol=self.protocol, costs=costs, seed=17, group="fit", original=None,
            observers={"reward": None}, probe=[], action=0, baseline_guard=baseline,
            corpus=SimpleNamespace(splits={"fit_gradient": None}))
        reference = self.root / "REFERENCE.json"
        reference.write_text(json.dumps({"seed": 17, "selected_action_index": 2,
                                         "training_configuration_sha256": object_hash(self.p)}))
        out = self.root / "bank"; out.mkdir()

        def identity(model, optimizer):
            return {"parameters": float(model["value"]), "optimizer": float(optimizer["momentum"])}

        def advance(model, optimizer, start, action, schedule_id):
            multiplier = self.p["multipliers"][action]
            for step in range(start, start + 48):
                if multiplier:
                    optimizer["momentum"] = .9 * optimizer["momentum"] + 1 + step / 1000 + schedule_id / 10000
                    model["value"] += multiplier * optimizer["momentum"]

        def block(ctx, model, optimizer, start, action, schedule_id):
            before = identity(model, optimizer)
            advance(model, optimizer, start, action, schedule_id)
            costs.add("scheduled_gradient_microsteps", 48)
            return {"before": before, "candidate": identity(model, optimizer), "after": identity(model, optimizer),
                    "accepted": True, "guard_output_sha256": [str(model["value"])], "guard_values": [model["value"]]}

        def score(model, *args, **kwargs):
            return {**baseline, "means": {"reward": model["value"]}, "values": {"reward": np.array([model["value"]])}}

        def hard_save(path, value):
            Path(path).write_text(json.dumps(value["means"]))
            return {"file_sha256": file_hash(path), "means": value["means"], "rows": 1}

        def checkpoint(path, model, optimizer, protocol, metadata):
            value = {"model": deepcopy(model), "optimizer": deepcopy(optimizer), "metadata": metadata}
            Path(path).write_text(json.dumps(value))
            return value

        def measure(ctx, model, optimizer, step, schedule_id, retain=False):
            return [model["value"], optimizer["momentum"], step / 288] + [0.] * 27, score(model), {"synthetic": True}

        with patch.multiple(B, make_model=lambda *args: {"value": 0.}, new_optimizer=lambda *args: {"momentum": 0.},
            clone_state=lambda m, o, *args: (deepcopy(m), deepcopy(o)), guarded_block=block, state_identity=identity,
            hard_panel=score, save_hard=hard_save, save_checkpoint=checkpoint, measure_state=measure):
            result = B.build_bank(context, reference, out)
        bank = json.loads((out / "BANK.json").read_text())
        self.assertEqual(len(bank["records"]), 24)
        self.assertEqual(result["resources"]["scheduled_gradient_microsteps"], 17280)
        for row in bank["records"]:
            for action in range(4):
                model, optimizer = deepcopy(row["state_checkpoint"]["model"]), deepcopy(row["state_checkpoint"]["optimizer"])
                for step in range(row["step"], 288, 48):
                    advance(model, optimizer, step, action if step == row["step"] else 2, row["schedule_id"])
                self.assertEqual(model["value"], row["action_values"][action])
            chosen = self.p["exploration_paths"][row["trajectory"]][row["step"] // 48]
            self.assertEqual(row["selected_after"], row["branches"][chosen]["first_block_after"])
        with gzip.open(out / "decisions-and-outcomes.jsonl.gz", "rt") as stream:
            journal = [json.loads(line) for line in stream]
        by_hash = {object_hash(row): row for row in journal}
        for row in journal:
            if row["kind"] == "block_outcome":
                self.assertLess(by_hash[row["decision_sha256"]]["record_index"], row["record_index"])
            if row["kind"] == "terminal_branch_outcome":
                self.assertLess(by_hash[row["branch_set_commit"]]["record_index"], row["record_index"])


if __name__ == "__main__":
    unittest.main()
