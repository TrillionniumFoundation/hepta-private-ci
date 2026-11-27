"""Recorded-event fixtures only: no actual V6 feedback or holdout file is read."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from binding_review import _id, audit_scores
from bridge_revision_review import (MODES, ROLES, audit_execution, audit_revision_panel,
    feedback_hash, permutation, review_fresh, transitions)
from test_bridge_feedback_review import cases, execution, hashed, provenance, write


def panel(rows, mode, *, seed=41, model_sha=None, prefix=None):
    model_sha, verifier = model_sha or hashed("reader"), provenance()
    prefix = prefix or f"fresh_combinations/revision-real/{mode}"
    physical, positive, predictions, initial = [], [], [], []
    for start in range(0, len(rows), 16):
        selected = rows[start:start + 16]
        trace = execution(selected, model_sha, verifier, mode, seed)
        positive.extend(p[1] for p in trace["probabilities"])
        predictions.extend(trace["predictions"])
        initial.extend(e["prediction"] for e in trace["initial_proposals"])
        physical.append(dict(batch_id=f"{prefix}/{start // 16}", case_ids=[_id(r) for r in selected],
            feature_preparation=dict(cpu_ns=3, wall_ns=6), shuffle_indices=trace["shuffle_indices"], execution=trace))
    total = dict(cpu_ns=23 * len(physical), wall_ns=46 * len(physical), batch_count=len(physical),
        scope="physical_batch_public_feature_and_control_preparation_plus_execution_once",
        callback_costs_are_nested=True, formula_flops=None, individually_measured_case_latency=False)
    return dict(metrics=audit_scores(rows, positive), probabilities=positive, predictions=predictions,
        initial_predictions=initial, case_ids=[_id(r) for r in rows], physical_batches=physical,
        transitions=transitions(initial, predictions, rows) if initial else None, costs=total, mode=mode,
        labels_entered_model=False, reader_model_sha256=model_sha, verifier_model_sha256=verifier["model_sha256"])


class BridgeRevisionAuditTests(unittest.TestCase):
    def test_each_of_eight_modes_replays_probabilities_feedback_donors_and_physical_costs(self):
        rows, manifest, verifier = cases(groups=8), dict(execution_parameter_sha256=hashed("reader")), provenance()
        for mode in MODES:
            with self.subTest(mode=mode):
                value = panel(rows, mode)
                result = audit_revision_panel(rows, value, manifest, verifier, seed=41,
                    prefix=f"fresh_combinations/revision-real/{mode}")
                self.assertTrue(result["passed"])
                self.assertEqual(result["physical_batches"], 2)
                self.assertEqual(result["costs"], dict(cpu_ns=46, wall_ns=92))
                self.assertEqual(result["transitions"], value["transitions"])

    def test_shuffle_is_reconstructed_from_public_ids_and_rejects_donor_or_feedback_tampering(self):
        rows, verifier = cases(), provenance()
        value = execution(rows, hashed("reader"), verifier, "shuffle")
        expected = permutation([_id(r) for r in rows], 41)
        self.assertEqual(value["shuffle_indices"], expected)
        audit_execution(value, rows, hashed("reader"), verifier, "shuffle", 41)
        for mutation in (
            lambda r: r["events"][16].update(feedback_donor_case_id="wrong-source"),
            lambda r: r["events"][16].update(feedback_donor_batch_row=16),
            lambda r: r["events"][16].update(feedback=[0.] * 4, feedback_sha256=feedback_hash([0.] * 4)),
            lambda r: r.update(shuffle_indices=list(range(16))),
            lambda r: r["cost"]["callbacks"].append(dict(component="verifier_step", cpu_ns=1, wall_ns=2))):
            broken = copy.deepcopy(value)
            mutation(broken)
            with self.assertRaises(ValueError):
                audit_execution(broken, rows, hashed("reader"), verifier, "shuffle", 41)

    def test_output_state_initial_and_cost_mutations_are_rejected(self):
        rows, verifier = cases(), provenance()
        manifest = dict(execution_parameter_sha256=hashed("reader"))
        original = panel(rows, "real")
        mutations = [lambda r: r["physical_batches"][0]["execution"]["events"][0].update(probabilities=[.5, .5], prediction=1),
            lambda r: r["physical_batches"][0]["execution"]["verifier_observations"][0][0].__setitem__(2, 1.),
            lambda r: r["physical_batches"][0]["execution"]["events"][0].update(source_sha256=hashed("wrong")),
            lambda r: r["physical_batches"][0]["execution"]["events"][0].update(state_sha256="opaque"),
            lambda r: r["physical_batches"][0]["execution"].update(reader_model_sha256=hashed("wrong")),
            lambda r: r["physical_batches"][0]["execution"]["cost"]["calls"].update(reader_step=1),
            lambda r: r["physical_batches"][0].update(batch_id="duplicated"),
            lambda r: r["costs"].update(cpu_ns=r["costs"]["cpu_ns"] + 7),
            lambda r: r["transitions"].update(damaged=999),
            lambda r: r.update(labels_entered_model=True)]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                value = copy.deepcopy(original)
                mutation(value)
                with self.assertRaises(ValueError):
                    audit_revision_panel(rows, value, manifest, verifier, seed=41,
                        prefix="fresh_combinations/revision-real/real")

    def test_late_fusion_uses_float32_probability_mean_and_verifier_only_uses_actual_observation(self):
        rows, verifier = cases(), provenance()
        for mode in ("late_fusion", "verifier_only"):
            result = execution(rows, hashed("reader"), verifier, mode)
            audit_execution(result, rows, hashed("reader"), verifier, mode, 41)
            result["probabilities"][0] = [.1, .9]
            result["predictions"][0] = 1
            with self.assertRaisesRegex(ValueError, "output is inconsistent"):
                audit_execution(result, rows, hashed("reader"), verifier, mode, 41)

    def test_complete_96_panel_index_binds_completion_and_counts_physical_cost_once(self):
        with tempfile.TemporaryDirectory() as folder:
            root, parts = Path(folder), {role: cases(groups=32) for role in ROLES}
            models = {(seed, arm): dict(execution_parameter_sha256=hashed((seed, arm)))
                      for seed in (41, 47, 53) for arm in ("real", "zero")}
            verifiers = {seed: provenance() for seed in (41, 47, 53)}
            completion = dict(schema="hepta.bridge.fresh-completion.v6", official_validation_scored=False,
                              repeated_seeds_are_new_examples=False, summaries={str(seed): {} for seed in verifiers})
            for seed, arm in models:
                for role in ROLES:
                    for mode in MODES:
                        prefix = f"{role}/revision-{arm}/{mode}"
                        value = dict(mode=mode, metrics={}, transitions=None, costs={})
                        write(root / f"seed-{seed}" / "fresh" / (prefix + ".json"), value)
                        completion["summaries"][str(seed)][prefix] = {k: value[k] for k in ("metrics", "transitions", "costs")}
            write(root / "completion.json", completion)

            def checked(rows, value, manifest, verifier, **kwargs):
                reference = [[.75, .25] for _ in rows]
                trace = dict(initial_probabilities=reference, probabilities=reference,
                             initial_state_sha256s=[hashed((i, "initial")) for i in range(len(rows))])
                return dict(passed=True, metrics={}, transitions=None, costs=dict(cpu_ns=3, wall_ns=6),
                            traces=[trace], mode=value["mode"], physical_batches=1)

            with mock.patch("bridge_revision_review.audit_revision_panel", side_effect=checked):
                result = review_fresh(root, parts, models, verifiers)
                self.assertEqual(result["panel_count"], 96)
                self.assertEqual(result["physical_costs_once"], dict(cpu_ns=288, wall_ns=576))
                completion["summaries"]["41"]["fresh_combinations/revision-real/real"]["costs"] = dict(cpu_ns=999)
                write(root / "completion.json", completion)
                with self.assertRaisesRegex(ValueError, "summary differs"):
                    review_fresh(root, parts, models, verifiers)


if __name__ == "__main__":
    unittest.main()
