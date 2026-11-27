"""Byte-level V6 architecture audit fixtures; no neural imports or execution."""

from hashlib import sha256
import json
from pathlib import Path
import struct
import tempfile
import unittest

from bridge_review import (BASE_SHAPES, EXTRA_NAMES, _parameter_sha, audit_architecture,
                           audit_arm_admission, audit_common_initializations, audit_initialization,
                           audit_stop_schedule, review_run)
from binding_protocol import binding_manifest, build_binding_protocol
from dataclasses import asdict


def identity(arm):
    return dict(schema="hepta-bridge-reader-v1", arm=arm, input_dim=384, hidden_dim=32,
        max_hops=8, max_facts=256, max_tokens=1024, parameter_count=38466 + (4096 if arm != "base" else 0),
        base_parameter_count=38466, added_parameter_count=4096 if arm != "base" else 0,
        state_transition="TokenReader-v4", cross_fact_attention=arm == "bridge",
        residual_location={"base": "none", "bridge": "cross_fact_prepare", "wide": "local_head_hidden"}[arm])


def fixture(root, arm, *, changed_common=False, nonfinite=False, nonzero_output=False, seed=41):
    folder = Path(root) / arm
    folder.mkdir(parents=True, exist_ok=True)
    shapes = dict(BASE_SHAPES, **{name: [32, 32] for name in EXTRA_NAMES[arm]})
    tensors, definitions, chunks, offset = {}, [], [], 0
    for name, shape in sorted(shapes.items()):
        count = 1
        for size in shape:
            count *= size
        number = .125
        if name == "project.weight" and changed_common:
            number = .25
        if name == "project.weight" and nonfinite:
            number = float("nan")
        if arm != "base" and name == EXTRA_NAMES[arm][-1]:
            number = .1 if nonzero_output else 0.
        payload = struct.pack("<f", number) * count
        tensors[name] = (shape, payload)
        definitions.append(dict(name=name, shape=shape, dtype="torch.float32", offset=offset,
            nbytes=len(payload), sha256=sha256(payload).hexdigest(), role="common" if name in BASE_SHAPES else "extra"))
        chunks.append(payload)
        offset += len(payload)
    binary = b"".join(chunks)
    (folder / "initialization.bin").write_bytes(binary)
    record = dict(schema="hepta.bridge.initialization.v1", arm=arm, seed=seed, file="initialization.bin",
        file_sha256=sha256(binary).hexdigest(), parameter_count=38466 + (4096 if arm != "base" else 0),
        common_parameter_count=38466, extra_parameter_count=4096 if arm != "base" else 0,
        training_parameter_sha256=_parameter_sha(tensors), execution_parameter_sha256=_parameter_sha(tensors, typed=True),
        tensors=definitions, architecture=identity(arm))
    path = folder / "initialization.json"
    path.write_text(json.dumps(record))
    return path


class BridgeReviewTests(unittest.TestCase):
    def test_decodes_actual_fp32_payloads_and_reconstructs_both_named_digests(self):
        with tempfile.TemporaryDirectory() as directory:
            for arm, extra in (("base", 0), ("bridge", 4096), ("wide", 4096)):
                path = fixture(directory, arm)
                report = audit_initialization(path)
                self.assertEqual((report["parameter_count"], report["extra_parameter_count"]), (38466 + extra, extra))
                self.assertTrue(report["initial_tensor_values_independently_decoded"])
                self.assertNotEqual(report["training_parameter_sha256"], report["execution_parameter_sha256"])
                self.assertTrue(audit_architecture(identity(arm), report)["passed"])

    def test_same_seed_common_bytes_are_compared_to_historical_actual_base(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = {arm: fixture(directory, arm) for arm in ("base", "bridge", "wide")}
            previous = dict(initial_model_sha256=audit_initialization(paths["base"])["training_parameter_sha256"])
            report = audit_common_initializations(paths, previous)
            self.assertTrue(report["historical_base_initialization_authenticated"])
            self.assertTrue(report["extra_matrices_initial_bytes_also_equal"])
            paths["bridge"] = fixture(directory, "bridge", changed_common=True)
            with self.assertRaisesRegex(ValueError, "common initial tensor bytes"):
                audit_common_initializations(paths, previous)
            paths["bridge"] = fixture(directory, "bridge")
            with self.assertRaisesRegex(ValueError, "historical"):
                audit_common_initializations(paths, dict(initial_model_sha256="0" * 64))

    def test_hashes_shapes_coverage_and_counts_reject_independent_mutations(self):
        mutations = ((lambda r: r.update(file_sha256="0" * 64), "binary byte hash"),
            (lambda r: r["tensors"][0].update(sha256="0" * 64), "payload hash"),
            (lambda r: r["tensors"][0].update(offset=4), "contiguous"),
            (lambda r: r["tensors"][0].update(role="extra"), "role binding"),
            (lambda r: r.update(parameter_count=999), "parameter count"),
            (lambda r: r.update(training_parameter_sha256="0" * 64), "parameter digest"),
            (lambda r: r["tensors"][0].update(shape=[1, 1024]), "name/shape"))
        with tempfile.TemporaryDirectory() as directory:
            for mutate, message in mutations:
                path = fixture(directory, "base")
                record = json.loads(path.read_text())
                mutate(record)
                path.write_text(json.dumps(record))
                with self.assertRaisesRegex(ValueError, message):
                    audit_initialization(path)

    def test_finite_initial_values_and_zero_residual_output_are_required(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "nonfinite"):
                audit_initialization(fixture(directory, "bridge", nonfinite=True))
            with self.assertRaisesRegex(ValueError, "output initialization"):
                audit_initialization(fixture(directory, "wide", nonzero_output=True))

    def test_local_control_cannot_be_mislabeled_as_cross_fact_architecture(self):
        with tempfile.TemporaryDirectory() as directory:
            report = audit_initialization(fixture(directory, "wide"))
            mislabeled = dict(identity("wide"), cross_fact_attention=True)
            with self.assertRaisesRegex(ValueError, "metadata disagrees"):
                audit_architecture(mislabeled, report)

    def test_earliest_full_raw_training_gate_controls_actual_update_budget(self):
        cases = build_binding_protocol()["reader_train"]
        good = [.99 if case.label else .01 for case in cases]
        receipt = dict(requested_steps=8000, batch_size=16, depth=3, learning_rate=.001, pair_weight=.5,
            optimizer="Adam_foreach_false", stop_rule=dict(diagnostic_interval=250),
            completed_steps=250, status="train_gate_passed", diagnostics=[
                dict(optimizer_step=0, binding=dict(probabilities=[.5] * 128)),
                dict(optimizer_step=250, binding=dict(probabilities=good))])
        result = audit_stop_schedule(receipt, cases)
        self.assertEqual((result["optimizer_updates"], result["training_exposures"]), (250, 4000))
        changed = dict(receipt, completed_steps=500, diagnostics=[*receipt["diagnostics"],
            dict(optimizer_step=500, binding=dict(probabilities=good))])
        with self.assertRaisesRegex(ValueError, "earliest"):
            audit_stop_schedule(changed, cases)
        changed = dict(receipt, diagnostics=[receipt["diagnostics"][-1]])
        with self.assertRaisesRegex(ValueError, "diagnostic missing"):
            audit_stop_schedule(changed, cases)

    def test_all_three_seeds_are_required_and_wide_cannot_replace_bridge(self):
        runs = {arm: [dict(seed=seed, independently_qualified=arm == "wide") for seed in (41, 47, 53)]
                for arm in ("base", "bridge", "wide")}
        report = audit_arm_admission(runs)
        self.assertTrue(report["admitted"]["wide"])
        self.assertFalse(report["bridge_continuation_authorized"])
        self.assertFalse(report["wide_substitution_authorized"])
        runs["bridge"].pop()
        with self.assertRaisesRegex(ValueError, "three seeds"):
            audit_arm_admission(runs)

    def test_complete_preparation_cli_contract_audits_sources_and_nine_initializations(self):
        with tempfile.TemporaryDirectory() as directory:
            root, previous = Path(directory) / "current", Path(directory) / "previous"
            root.mkdir()
            previous.mkdir()
            (root / "runtime.py").write_text("x = 1\n")
            runtime = {"runtime.py": sha256((root / "runtime.py").read_bytes()).hexdigest()}
            (previous / "design.json").write_text(json.dumps(dict(runtime_source_sha256=runtime)))
            initial, baselines = {}, {}
            for seed in (41, 47, 53):
                for arm in ("base", "bridge", "wide"):
                    path = fixture(root / f"seed-{seed}", arm, seed=seed)
                    for name in ("initialization.json", "initialization.bin"):
                        path = path.parent / name
                        initial[str(path.relative_to(root))] = sha256(path.read_bytes()).hexdigest()
                old = previous / f"seed-{seed}"
                old.mkdir()
                digest = audit_initialization(root / f"seed-{seed}" / "base" / "initialization.json")["training_parameter_sha256"]
                names = ("warmup.pt", "warmup-model.json", "warmup-training.json", "warmup-binding-train.json",
                         "warmup-natural-internal.json", "warmup-gate.json")
                for name in names:
                    (old / name).write_text(json.dumps(dict(initial_model_sha256=digest)))
                baselines[str(seed)] = dict(folder=str(old), reused_historical_training=True, newly_performed_training=False,
                    files_sha256={name: sha256((old / name).read_bytes()).hexdigest() for name in names}, initial_training_parameter_sha256=digest)
            parts = build_binding_protocol()
            membership = binding_manifest(parts, dataset_files_sha256={"train": "a" * 64},
                source_files_sha256={"v4": "b" * 64}, code_files_sha256=runtime)
            design = dict(runtime_source_sha256=runtime, membership=membership,
                primary_variant="bridge", control_variant="wide", gate=dict(control_cannot_replace_failed_primary=True),
                same_parameter_count_is_same_compute=False, same_budget_limit_is_same_actual_cost=False,
                training=dict(max_updates=8000, batch_size=16, depth=3, learning_rate=.001, pair_weight=.5,
                    diagnostic_interval=250, wall_time_budget_ns=1_800_000_000_000,
                    loss="last_hop_CE_plus_world_pair_margin", stopping="earliest_full_train_gate"),
                initialization_files_sha256=initial, historical_baselines=baselines,
                previous_v5_design_sha256=sha256((previous / "design.json").read_bytes()).hexdigest())
            (root / "design.json").write_text(json.dumps(design))
            (root / "all-cases.json").write_text(json.dumps({role: [asdict(c) for c in cases] for role, cases in parts.items()}))
            report = review_run(root, root)
            self.assertTrue(report["passed"])
            self.assertFalse(report["warmup_phase_complete"])
            self.assertEqual(len(report["initializations"]), 3)
            self.assertEqual(sum(len(item["arms"]) for item in report["initializations"]), 9)


if __name__ == "__main__":
    unittest.main()
