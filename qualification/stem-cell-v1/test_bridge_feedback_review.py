"""Pure stdlib fixtures and mutation tests; no neural experiment is executed."""
import copy
from hashlib import sha256
import json
import math
from pathlib import Path
import random
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

from binding_review import _digest, _group_batches, _id, audit_scores
from bridge_feedback_review import (audit_freeze, audit_manifest, audit_revision_fit, audit_verifier,
    checkpoint_digests, expected_models, file_sha)
from bridge_review import BASE_SHAPES, EXTRA_NAMES
from bridge_revision_review import feedback_hash, permutation, transitions


def hashed(value):
    return sha256(str(value).encode()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True))


def cases(groups=4, seed=41):
    result = []
    for group in range(groups):
        for world in (0, 1):
            owners = (f"Ada{group}", f"Ben{group}") if not world else (f"Ben{group}", f"Ada{group}")
            facts = [f"The coin{seed}_{group} belongs to {owners[0]}.",
                     f"The bead{seed}_{group} belongs to {owners[1]}.",
                     f"Ada{group} stores all their possessions in the blue box.",
                     f"Ben{group} stores all their possessions in the green box."]
            for answer in (0, 1):
                result.append(dict(source_split="train", paragraph_id=f"binding-v4/train/{seed}/{group}/world-{world}",
                    question_id="0", answer_id=str(answer), facts=facts,
                    question=f"Where is the coin{seed}_{group} stored?", candidate=f"The {('blue', 'green')[answer]} box.",
                    label=int(answer == world), source_hash=sha256("\n".join(facts).encode()).hexdigest(),
                    sentence_ids=[1, 2, 3, 4], evidence_sentence_indices=[1, 3 + world],
                    segmentation="synthetic-ownership-storage-v1"))
    return result


def checkpoint(path, shapes):
    """Handwritten protocol-2 Torch ZIP fixture, without importing Torch."""
    string = lambda value: b"X" + struct.pack("<I", len(value.encode())) + value.encode()
    integer = lambda value: b"J" + struct.pack("<i", value)
    sequence = lambda values: b"(" + b"".join(integer(v) for v in values) + b"t"
    ordered = b"ccollections\nOrderedDict\n)R"
    raw, payloads = b"\x80\x02" + ordered + b"(", {}
    for index, (name, shape) in enumerate(sorted(shapes.items())):
        count, strides = 1, []
        for size in reversed(shape):
            strides.append(count)
            count *= size
        key = str(index)
        storage = (b"(" + string("storage") + b"ctorch\nFloatStorage\n" + string(key)
                   + string("cpu") + integer(count) + b"tQ")
        raw += (string(name) + b"ctorch._utils\n_rebuild_tensor_v2\n(" + storage + integer(0)
                + sequence(shape) + sequence(reversed(strides)) + b"\x89" + ordered + b"tR")
        payloads[key] = struct.pack("<f", (index + 1) / 100) * count
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("fixture/data.pkl", raw + b"u.")
        archive.writestr("fixture/byteorder", b"little")
        for key, value in payloads.items():
            archive.writestr("fixture/data/" + key, value)
    return checkpoint_digests(path, shapes)


def provenance():
    return dict(file_path="fixture/verifier.pt", file_sha256=hashed("file"), model_sha256=hashed("verifier"),
        training_source_groups=[hashed(f"verifier-{i}") for i in range(8)], synthetic_trained=False,
        original_training_reused_not_recharged=True)


def cost(mode, size):
    names = (["reader_prepare", "reader_step"] if mode == "cheap_fixed1" else
             ["verifier_prepare", "verifier_step"] if mode == "cheap_verifier" else
             ["reader_prepare", "reader_step", "verifier_prepare", "verifier_step", "reader_step", "verifier_step", "reader_step"])
    return dict(cpu_ns=20, wall_ns=40, callbacks=[dict(component=n, cpu_ns=1, wall_ns=2) for n in names],
        calls={name: names.count(name) for name in ("reader_prepare", "reader_step", "verifier_prepare", "verifier_step")},
        physical_batch_size=size, formula_flops=None, callback_costs_are_nested=True, shared_encoder_included=False,
        per_case_attribution="singleton_only", external_shuffle_feedback_required=False)


def execution(rows, model_sha, verifier, mode="real", seed=41):
    size, events, observed = len(rows), [], []
    donors = permutation([_id(r) for r in rows], seed) if mode == "shuffle" else None
    rounds = 0 if mode == "cheap_verifier" else 1 if mode == "cheap_fixed1" else 3
    for hop in range(rounds):
        for index, row in enumerate(rows):
            positive = .25 if not hop else (.8 if row["label"] else .2) if mode in ("real", "reset") else .35
            feedback = (None if not hop else [0., 0., 0., 0.] if mode in ("zero", "late_fusion", "verifier_only")
                        else observed[hop - 1][donors[index] if donors is not None else index])
            events.append(dict(step=hop + 1, batch_row=index, case_id=_id(row), source_sha256=row["source_hash"],
                prediction=int(positive > .5), probabilities=[1 - positive, positive],
                state_sha256=hashed((model_sha, hop, index)), feedback=feedback,
                feedback_sha256=None if feedback is None else feedback_hash(feedback),
                feedback_donor_batch_row=donors[index] if hop and donors is not None else None,
                feedback_donor_case_id=_id(rows[donors[index]]) if hop and donors is not None else None,
                reader_model_sha256=model_sha, verifier_model_sha256=verifier["model_sha256"]))
        if hop < 2 and rounds == 3:
            observed.append([[.4, .6, float(events[hop * size + i]["prediction"] == 1), 1.] for i in range(size)])
    probabilities = ([v["probabilities"] for v in events[-size:]] if events else [[.4, .6] for _ in rows])
    if mode == "verifier_only":
        probabilities = [v[:2] for v in observed[-1]]
    elif mode == "late_fusion":
        fp32 = lambda value: struct.unpack("<f", struct.pack("<f", value))[0]
        probabilities = [[fp32(fp32(a + b) * .5) for a, b in zip(p, v[:2])] for p, v in zip(probabilities, observed[-1])]
    return dict(schema="hepta.revision-execution.v1", mode=mode,
        prediction_rule="raw_probability_strictly_greater_than_0.5", probabilities=probabilities,
        predictions=[int(v[1] > .5) for v in probabilities], initial_proposals=events[:size], events=events,
        verifier_observations=observed, reader_model_sha256=model_sha, verifier_model_sha256=verifier["model_sha256"],
        verifier_artifact_sha256=verifier["file_sha256"], verifier_provenance_sha256=_digest(verifier),
        input_feature_sha256s=[hashed(([_id(r) for r in rows], i)) for i in range(6)],
        external_feedback_sha256=None, shuffle_indices=donors, shuffle_uses_current_observations=donors is not None,
        late_fusion_rule="0.5_reader_probability_plus_0.5_last_verifier_probability",
        verifier_synthetic_trained=False, verifier_acceptance_is_semantic_truth=False, cost=cost(mode, size), labels_read=False)


def paired_fit():
    natural, binding, updates, verifier = cases(seed=47), cases(), 2, provenance()
    plan = dict(schema="hepta.binding.continuation-plan.v1", seed=41, updates=updates, batch_size=16,
        logical_update_order=["natural", "binding"])
    rng = random.Random("hepta-binding-natural-v5/41")
    plan["natural_batches"] = [rng.sample(range(len(natural)), 16) for _ in range(updates)]
    plan["binding_batches"] = _group_batches(binding, updates, 16, 41)
    for prefix, rows in (("natural", natural), ("binding", binding)):
        plan[prefix + "_case_ids"] = [_id(r) for r in rows]
        plan[prefix + "_targets"] = [r["label"] for r in rows]
        plan[prefix + "_source_groups"] = [r["source_hash"] for r in rows]
    plan["plan_sha256"] = _digest(plan)
    sources = sorted({r["source_hash"] for r in natural + binding})
    core = dict(seed=41, execution_parameter_sha256=hashed("core"), parameter_count=42562, training_source_groups=sources)
    receipt = dict(schema="hepta.revision-paired-fit.v1", status="completed", forced_candidates=False,
        final_evaluation_authorized=False, feedback_schema="verifier_p0_p1_agreement_evidence_present.v1",
        learning_rate=.001, pair_weight=.5, depth_supervision="last_hop_CE_plus_binding_pair",
        plan_sha256=plan["plan_sha256"], initial_core_sha256=core["execution_parameter_sha256"],
        initial_verifier_sha256=verifier["model_sha256"], initial_models_equal=True,
        reader_training_source_groups=sources, verifier_provenance=verifier, verifier_provenance_sha256=_digest(verifier),
        natural_sequence_sha256=_digest(plan["natural_batches"]), binding_sequence_sha256=_digest(plan["binding_batches"]),
        requested_logical_updates=updates, completed_logical_updates=updates, batch_size=16, updates=[], models={},
        feedback_training_verified=True, original_core_unchanged=True, verifier_unchanged=True,
        identical_source_and_call_schedules=True, cpu_ns=1000, wall_ns=2000, formula_flops=None, nested_costs_additive=False)
    current = {arm: core["execution_parameter_sha256"] for arm in ("real", "zero")}
    for logical in range(updates):
        for stream, source in (("natural", natural), ("binding", binding)):
            indices = plan[stream + "_batches"][logical]
            rows = [source[i] for i in indices]
            item = dict(logical_step=logical + 1, stream=stream, indices=indices,
                        sample_sha256=_digest([_id(r) for r in rows]), arms={})
            for arm in ("real", "zero"):
                trace = execution(rows, current[arm], verifier, arm)
                initial, final = [e["prediction"] for e in trace["initial_proposals"]], trace["predictions"]
                columns = [v * 1e-5 for v in (1, 2, 3, 4)] if arm == "real" else [0.] * 4
                norm, updated = math.sqrt(sum(v * v for v in columns)), hashed((arm, logical, stream))
                item["arms"][arm] = dict(mode=arm, case_ids=[_id(r) for r in rows], targets=[r["label"] for r in rows],
                    initial_reader_sha256=current[arm], verifier_sha256=verifier["model_sha256"],
                    events=trace["events"], verifier_observations=trace["verifier_observations"],
                    initial_predictions=initial, final_predictions=final, transitions=transitions(initial, final, rows, training=True),
                    forward_cost=trace["cost"], cpu_ns=50, wall_ns=100,
                    feedback_gradient_l2_by_column=columns, feedback_column_gradient_l2=norm,
                    feedback_column_gradients_nonzero=norm > 0, parameter_gradient_l2=.1,
                    hop_state_gradient_l2=[.1] * 3, pair_weight=.5 if stream == "binding" else 0.,
                    binary_cross_entropy=1., pair_loss=.4 if stream == "binding" else 0.,
                    loss=1.2 if stream == "binding" else 1., updated_reader_sha256=updated,
                    input_feature_sha256s=trace["input_feature_sha256s"])
                current[arm] = updated
            receipt["updates"].append(item)
    for arm in ("real", "zero"):
        total = {}
        for item in receipt["updates"]:
            for key, value in item["arms"][arm]["transitions"].items():
                total[key] = total.get(key, 0) + value
        receipt["models"][arm] = dict(completed_updates=4, natural_updates=2, binding_updates=2,
            natural_exposures=32, binding_exposures=32, feedback_nonzero_gradient_updates=4 if arm == "real" else 0,
            feedback_nonzero_updates_by_column=[4 if arm == "real" else 0] * 4, transitions=total,
            actual_calls=dict(reader_prepare=4, reader_step=12, verifier_prepare=4, verifier_step=8),
            model_sha256=current[arm], execution_parameter_sha256=current[arm], training_parameter_sha256=hashed((arm, "legacy")),
            frozen=True, parameter_count=42562, parameter_bytes=42562 * 4)
    return receipt, plan, natural, binding, core


class BridgeFeedbackAuditTests(unittest.TestCase):
    def test_selected_bridge_manifest_binds_decoded_weights_and_shared_arm_wrapper(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            shapes = dict(BASE_SHAPES, **{name: [32, 32] for name in EXTRA_NAMES["bridge"]})
            decoded = checkpoint(root / "revision-real.pt", shapes)
            identity = dict(schema="hepta-bridge-reader-v1", arm="bridge", input_dim=384, hidden_dim=32,
                max_hops=8, max_facts=256, max_tokens=1024, parameter_count=42562, base_parameter_count=38466,
                added_parameter_count=4096, state_transition="TokenReader-v4", cross_fact_attention=True,
                residual_location="cross_fact_prepare")
            model = {k: decoded[k] for k in ("parameter_count", "training_parameter_sha256", "execution_parameter_sha256")}
            write(root / "revision-pair-training.json", dict(models=dict(real=model), reader_training_source_groups=[hashed("reader")]))
            wrapper = dict(model_receipt=model, shared_training_receipt="revision-pair-training.json",
                           shared_receipt_sha256=file_sha(root / "revision-pair-training.json"))
            write(root / "revision-real-training.json", wrapper)
            manifest = dict(file="revision-real.pt", file_sha256=file_sha(root / "revision-real.pt"),
                architecture=identity, frozen_ns=10, **model, training_source_groups=[hashed("reader")],
                training_receipt_file="revision-real-training.json", training_receipt_sha256=file_sha(root / "revision-real-training.json"))
            path = root / "revision-real-model.json"
            write(path, manifest)
            self.assertEqual(audit_manifest(path, expected_arm="bridge")["parameter_count"], 42562)
            with self.assertRaisesRegex(ValueError, "architecture arm"):
                audit_manifest(path, expected_arm="wide")
            wrapper["shared_receipt_sha256"] = "0" * 64
            write(root / "revision-real-training.json", wrapper)
            manifest["training_receipt_sha256"] = file_sha(root / "revision-real-training.json")
            write(path, manifest)
            with self.assertRaisesRegex(ValueError, "shared revision"):
                audit_manifest(path)

    def test_exact_21_model_freeze_and_no_invented_fresh_start_time(self):
        with tempfile.TemporaryDirectory() as folder:
            root, rows = Path(folder), cases(groups=32)
            for name in expected_models():
                seed = int(Path(name).parts[0].split("-")[1])
                write(root / name, dict(frozen_ns=10, seed=seed, execution_parameter_sha256=hashed(name)))
            write(root / "warmup-completion.json", dict(primary_all_passed=True))
            write(root / "continuation-completion.json", dict(contrastive_all_passed=True))
            for seed in (41, 47, 53):
                branch = root / f"seed-{seed}" / "bridge"
                write(branch / "retention-gates.json", dict(contrastive=dict(passed=True)))
                probabilities = [.99 if row["label"] else .01 for row in rows]
                for name in ("warmup", "contrastive"):
                    ids = [_id(r) for r in rows]
                    panel = dict(probabilities=probabilities, metrics=audit_scores(rows, probabilities),
                        case_ids=ids, depth=3, labels_entered_model=False,
                        model_execution_parameter_sha256=hashed(f"seed-{seed}/bridge/{name}-model.json"),
                        batches=[dict(batch_id=str(i), case_ids=ids[i:i + 16], steps=3,
                            proposal_steps=len(ids[i:i + 16]) * 3, cpu_ns=1, wall_ns=2) for i in range(0, len(ids), 16)])
                    write(branch / (name + "-binding-train.json"), panel)
            gates = {"warmup-completion.json", "continuation-completion.json"} | {
                f"seed-{s}/bridge/retention-gates.json" for s in (41, 47, 53)}
            frozen = dict(frozen_ns=20, manifests={name: file_sha(root / name) for name in expected_models()},
                          gate_evidence_sha256={name: file_sha(root / name) for name in gates})
            write(root / "all-models-frozen.json", frozen)
            with mock.patch("bridge_feedback_review.audit_manifest", side_effect=lambda path, **_: json.loads(Path(path).read_text())):
                models, report = audit_freeze(root, dict(reader_train=rows))
                self.assertEqual(len(models), 21)
                self.assertFalse(report["fresh_started"])
                self.assertIsNone(report["boundary"]["fresh_started_ns"])
                frozen["manifests"]["unexpected-model.json"] = frozen["manifests"].pop(next(iter(frozen["manifests"])))
                write(root / "all-models-frozen.json", frozen)
                with self.assertRaisesRegex(ValueError, "21-model"):
                    audit_freeze(root, dict(reader_train=rows))

    def test_import_and_checkpoint_decoder_are_pure_stdlib_and_distinguish_digests(self):
        subprocess.run([sys.executable, "-c", "import sys; import bridge_feedback_review; assert 'torch' not in sys.modules"], check=True, cwd=Path(__file__).resolve().parent)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "reader.pt"
            result = checkpoint(path, {"weight": [2, 3], "bias": [2]})
            self.assertEqual(result["parameter_count"], 8)
            self.assertNotEqual(result["training_parameter_sha256"], result["execution_parameter_sha256"])
            with self.assertRaisesRegex(ValueError, "registered complete"):
                checkpoint_digests(path, {"weight": [2, 3]})
            with zipfile.ZipFile(path, "a") as archive:
                archive.writestr("fixture/data/unused", b"1234")
            with self.assertRaisesRegex(ValueError, "unreferenced"):
                checkpoint_digests(path, {"weight": [2, 3], "bias": [2]})

    def test_unregistered_pickle_code_is_rejected_without_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "reader.pt"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("fixture/data.pkl", b"\x80\x02cos\nsystem\nX\x04\x00\x00\x00true\x85R.")
                archive.writestr("fixture/byteorder", b"little")
            with self.assertRaisesRegex(ValueError, "unregistered pickle"):
                checkpoint_digests(path, {"weight": [1]})

    def test_shared_matched_fit_replays_on_policy_feedback_gradients_and_outer_cost_once(self):
        receipt, plan, natural, binding, core = paired_fit()
        report = audit_revision_fit(receipt, plan, natural, binding, core, expected_updates=2)
        self.assertTrue(report["passed"])
        self.assertTrue(report["all_four_real_columns_received_nonzero_gradient"])
        self.assertEqual(report["outer_cost_once"], dict(cpu_ns=1000, wall_ns=2000))
        self.assertEqual(report["nested_update_costs_not_added"], dict(cpu_ns=400, wall_ns=800))

    def test_fit_rejects_eight_independent_provenance_gradient_and_cost_mutations(self):
        original, plan, natural, binding, core = paired_fit()
        mutations = [lambda r: r.update(forced_candidates=True),
            lambda r: r.update(initial_core_sha256=hashed("wrong")),
            lambda r: r["updates"][0].update(indices=list(reversed(r["updates"][0]["indices"]))),
            lambda r: r["updates"][0]["arms"]["zero"]["feedback_gradient_l2_by_column"].__setitem__(0, .1),
            lambda r: r["updates"][0]["arms"]["real"]["events"][16].update(feedback=[0.] * 4),
            lambda r: r["updates"][0]["arms"]["real"].update(updated_reader_sha256=hashed("broken chain")),
            lambda r: r["updates"][0]["arms"]["zero"]["forward_cost"]["callbacks"].pop(),
            lambda r: r.update(cpu_ns=399)]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                receipt = copy.deepcopy(original)
                mutation(receipt)
                with self.assertRaises(ValueError):
                    audit_revision_fit(receipt, plan, natural, binding, core, expected_updates=2)

    def test_original_verifier_freeze_weight_source_and_both_digest_encodings(self):
        with tempfile.TemporaryDirectory() as folder:
            native = Path(folder)
            seed = native / "seed-41"
            seed.mkdir()
            decoded = checkpoint(seed / "verifier.pt", BASE_SHAPES)
            sources = [hashed(f"verifier-{i}") for i in range(8)]
            artifact = dict(file="verifier.pt", file_sha256=file_sha(seed / "verifier.pt"),
                model_sha256=decoded["training_parameter_sha256"], training_source_groups=sources)
            write(seed / "artifacts.json", dict(verifier=artifact))
            write(seed / "verifier-training.json", dict(actual_intervention_exposures=0,
                model_sha256=decoded["training_parameter_sha256"]))
            write(native / "design.json", dict(verifier=dict(counterfactual_train=False)))
            write(native / "all-artifacts-frozen.json", dict(artifact_manifests_sha256={"41": file_sha(seed / "artifacts.json")}))
            previous = dict(previous_native_freeze_sha256=file_sha(native / "all-artifacts-frozen.json"))
            bound = dict(file_path=str(seed / "verifier.pt"), file_sha256=artifact["file_sha256"],
                model_sha256=decoded["execution_parameter_sha256"], training_source_groups=sources,
                synthetic_trained=False, original_training_reused_not_recharged=True)
            self.assertTrue(audit_verifier(native, previous, 41, {hashed("reader")}, bound)["passed"])
            with self.assertRaisesRegex(ValueError, "digests"):
                audit_verifier(native, previous, 41, set(), {**bound, "model_sha256": decoded["training_parameter_sha256"]})
            with self.assertRaisesRegex(ValueError, "source"):
                audit_verifier(native, previous, 41, {sources[0]}, bound)


if __name__ == "__main__":
    unittest.main()
