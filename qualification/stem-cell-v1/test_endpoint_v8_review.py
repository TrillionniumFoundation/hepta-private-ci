"""Pure stdlib V8 fixture and mutation tests; no neural work is executed."""
import copy
from hashlib import sha256
import math
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

from endpoint_v8_checkpoint_review import (ARMS, BRIDGE_SHAPES, ENDPOINT_EXTRA, LOCAL_EXTRA,
    audit_extra_matching, audit_initial_tensors, audit_initialization, audit_learning_change,
    checkpoint_tensors, parameter_shapes, tensor_summary)
from endpoint_v8_review import audit_deleted_panel, audit_fit, audit_start_predictions, audit_support_transform
from binding_review import _digest, _id, audit_scores
from test_retention_v7_review import cases, training_fixture


def tensor_material(arm):
    result = {}
    for name, shape in parameter_shapes(arm).items():
        zero = name in ("endpoint_branch.output.weight", "head.endpoint_local.output.weight")
        result[name] = (tuple(shape), struct.pack("<f", 0. if zero else .125) * math.prod(shape))
    return result


def write_checkpoint(path, tensors):
    """Produce a bounded protocol-2 CPU FP32 archive without importing Torch."""
    string = lambda value: b"X" + struct.pack("<I", len(value.encode())) + value.encode()
    integer = lambda value: b"J" + struct.pack("<i", value)
    sequence = lambda values: b"(" + b"".join(integer(v) for v in values) + b"t"
    ordered = b"ccollections\nOrderedDict\n)R"
    raw, payloads = b"\x80\x02" + ordered + b"(", {}
    for index, (name, (shape, data)) in enumerate(sorted(tensors.items())):
        count, strides = 1, []
        for size in reversed(shape):
            strides.append(count)
            count *= size
        key = str(index)
        storage = (b"(" + string("storage") + b"ctorch\nFloatStorage\n" + string(key)
                   + string("cpu") + integer(count) + b"tQ")
        raw += (string(name) + b"ctorch._utils\n_rebuild_tensor_v2\n(" + storage + integer(0)
                + sequence(shape) + sequence(reversed(strides)) + b"\x89" + ordered + b"tR")
        payloads[key] = data
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("fixture/data.pkl", raw + b"u.")
        archive.writestr("fixture/byteorder", b"little")
        for key, value in payloads.items():
            archive.writestr("fixture/data/" + key, value)


def fit_fixture(arm="endpoint"):
    fixture = list(training_fixture("diverse"))
    receipt, initial = fixture[0], fixture[-1]
    count = 42562 if arm == "bridge" else 46722
    receipt.update(model_arm=arm, recipe="diverse", parameter_count=count, parameter_bytes=count * 4)
    initial["parameter_count"] = count
    return fixture


def identity_fixture(arm):
    endpoints = arm in ("endpoint", "broken")
    return dict(schema="hepta.endpoint-reader.v8", arm=arm, input_dim=384, hidden_dim=32,
        max_hops=8, max_facts=256, max_tokens=1024, parameter_count=42562 + (4160 if arm != "bridge" else 0),
        common_parameter_count=42562, added_parameter_count=0 if arm == "bridge" else 4160,
        old_fact_bridge_retained=True, public_feature_arguments=6, state_transition="TokenReader-v4",
        residual_location="parallel_endpoint_prepare" if endpoints else "local_head_hidden" if arm == "local" else "none",
        endpoint_input="LayerNorm_h(project(LayerNorm_input(raw_fact_tokens)))" if endpoints else None,
        shared_entity_match_projection=endpoints, self_key_index_edges=False,
        broken_self_payload_possible=arm == "broken", fact_axis_unit="caller_supplied_fact_or_token_chunk",
        slot_semantics="learned_latent_endpoints_not_certified_entity_parser", broken_payload_only=arm == "broken",
        public_value_order="raw_valid_token_SHA256_then_input_index",
        hash_tie_limit="index_tie_break_no_unconditional_equivariance_claim",
        zero_or_one_valid_fact_message="zero_for_endpoint_and_broken",
        pure_binding_causal_identification=False, same_parameter_count_is_same_compute=False)


def initialization_fixture(folder):
    material, metadata, raw, offset = tensor_material("endpoint"), [], bytearray(), 0
    write_checkpoint(folder / "initialization.pt", material)
    for name, (shape, payload) in sorted(material.items()):
        metadata.append(dict(name=name, shape=list(shape), dtype="torch.float32", offset=offset,
            nbytes=len(payload), sha256=sha256(payload).hexdigest(), role="common" if name in BRIDGE_SHAPES else "extra"))
        raw.extend(payload)
        offset += len(payload)
    (folder / "initialization.bin").write_bytes(raw)
    common, summary = tensor_summary(tensor_material("bridge")), tensor_summary(material)
    return dict(schema="hepta.endpoint.initialization.v8", arm="endpoint", seed=41,
        file="initialization.pt", file_sha256=sha256((folder / "initialization.pt").read_bytes()).hexdigest(),
        raw_file="initialization.bin", raw_file_sha256=sha256(raw).hexdigest(), tensors=metadata,
        architecture=identity_fixture("endpoint"), parameter_count=46722, common_parameter_count=42562,
        extra_parameter_count=4160, training_parameter_sha256=summary["training_parameter_sha256"],
        execution_parameter_sha256=summary["execution_parameter_sha256"],
        common_training_parameter_sha256=common["training_parameter_sha256"],
        common_execution_parameter_sha256=common["execution_parameter_sha256"], training_source_groups=["source"])


def deletion_fixture():
    rows, expected_rows = cases(), []
    for row in rows:
        public = "\n".join(("[QUESTION]", row["question"], "[CANDIDATE]", row["candidate"], "[PASSAGE]", *row["facts"]))
        expected_rows.append(dict(case_id=_id(row), public_source_sha256=sha256(public.encode()).hexdigest(),
            support_sentence_ids=row["evidence_sentence_indices"], deleted_fact_positions=[i - 1 for i in row["evidence_sentence_indices"]]))
    transform = dict(schema="hepta.endpoint.support-delete.v8", cases=expected_rows,
        case_ids=[_id(row) for row in rows], transform_sha256=_digest(expected_rows),
        kind="zero_verified_support_fact_rows_and_masks_keep_positions", exactly_two_support_facts=True,
        labels_unchanged=True, annotations_enter_forward=False, missing_evidence_can_make_task_unanswerable=True,
        diagnostic_only=True)
    tokens = {text: [1, 2, 3] for row in rows for text in row["facts"]}
    before = bytes([1]) * (len(rows) * 4 * 3)
    after = b"".join(bytes(3) if fact in expected_rows[i]["deleted_fact_positions"] else bytes([1]) * 3
                     for i, _ in enumerate(rows) for fact in range(4))
    hashes = [sha256(str(i).encode()).hexdigest() for i in range(6)]
    hashes[3] = sha256(before).hexdigest()
    changed = list(hashes)
    changed[0], changed[3] = sha256(b"changed facts").hexdigest(), sha256(after).hexdigest()
    probabilities = [.75 if r["label"] else .25 for r in rows]
    panel = dict(depth=3, reset=False, deleted_support_only=True, all_evidence_deleted=False,
        used_for_gate_or_selection=False, support_transform_sha256=transform["transform_sha256"],
        labels_entered_model=False, model_execution_parameter_sha256="model", case_ids=transform["case_ids"],
        probabilities=probabilities, metrics=audit_scores(rows, probabilities),
        batches=[dict(batch_id="deleted/0", case_ids=transform["case_ids"], steps=3, proposal_steps=len(rows) * 3, cpu_ns=2, wall_ns=3)],
        transform_observations=[dict(case_ids=transform["case_ids"], labels_and_order_unchanged=True,
            deleted_chunk_positions=[r["deleted_fact_positions"] for r in expected_rows],
            original_feature_sha256=hashes, transformed_feature_sha256=changed,
            feature_shapes=[[16, 4, 3, 384], [16, 2, 384], [16, 2, 384], [16, 4, 3], [16, 2], [16, 2]])])
    return rows, panel, dict(execution_parameter_sha256="model"), transform, tokens


class EndpointV8ReviewTests(unittest.TestCase):
    def test_complete_diverse_fixture_replays_all_four_model_arms(self):
        for arm in ARMS:
            with self.subTest(arm=arm):
                report = audit_fit(*fit_fixture(arm), arm, updates=2)
                self.assertEqual(report["optimizer_updates"], 6)
                self.assertEqual(report["total_exposures"], 96)
                self.assertEqual(report["parameter_count"], 42562 if arm == "bridge" else 46722)
                self.assertEqual(report["teacher_calls"], 0)
                self.assertFalse(report["anchor_used"])

    def test_model_arm_recipe_anchor_and_parameter_count_cannot_be_substituted(self):
        base = fit_fixture()
        mutations = [lambda r: r.update(model_arm="broken"), lambda r: r.update(recipe="anchored"),
            lambda r: r.update(arm="repeat"), lambda r: r.update(parameter_count=42562),
            lambda r: r["updates"][2].update(anchor_weight=1.),
            lambda r: r["updates"][2].update(anchor_mse=.25),
            lambda r: r.update(learning_rate=.0001), lambda r: r.update(teacher_calls_inside_fit=1)]
        for mutation in mutations:
            fixture = copy.deepcopy(base)
            mutation(fixture[0])
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                audit_fit(*fixture, "endpoint", updates=2)

    def test_logits_sampling_exposures_and_actual_cost_are_replayed(self):
        base = fit_fixture()
        mutations = [lambda r: r["updates"][0].update(binary_cross_entropy=.01),
            lambda r: r["updates"][1].update(pair_loss=.01),
            lambda r: r["updates"][0]["indices"].reverse(),
            lambda r: r["updates"][1].update(stream="retention"),
            lambda r: r.update(actual_total_exposures=95), lambda r: r.update(cpu_ns=19),
            lambda r: r["training_source_groups"].pop(), lambda r: r["diagnostics"].pop()]
        for mutation in mutations:
            fixture = copy.deepcopy(base)
            mutation(fixture[0])
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                audit_fit(*fixture, "endpoint", updates=2)

    def test_common_warmup_tensor_bytes_and_zero_output_are_checked(self):
        warmup = tensor_material("bridge")
        for arm in ARMS:
            material = tensor_material(arm)
            report = audit_initial_tensors(material, warmup, arm)
            self.assertEqual(report["old_tensor_count"], 22)
            self.assertTrue(report["old_tensor_bytes_equal"])
            wrong = copy.deepcopy(material)
            name = "project.weight"
            shape, payload = wrong[name]
            wrong[name] = (shape, struct.pack("<f", 1.) + payload[4:])
            with self.subTest(arm=arm), self.assertRaisesRegex(ValueError, "old warmup tensor bytes"):
                audit_initial_tensors(wrong, warmup, arm)
        wrong = tensor_material("endpoint")
        shape, payload = wrong["endpoint_branch.output.weight"]
        wrong["endpoint_branch.output.weight"] = (shape, struct.pack("<f", 1.) + payload[4:])
        with self.assertRaisesRegex(ValueError, "exact zero"):
            audit_initial_tensors(wrong, warmup, "endpoint")

    def test_endpoint_broken_and_local_added_matrix_matching(self):
        arms = {arm: tensor_material(arm) for arm in ARMS}
        self.assertTrue(audit_extra_matching(arms)["passed"])
        for arm, name in (("broken", "endpoint_branch.slot_queries"), ("local", "head.endpoint_local.hidden1.weight")):
            wrong = copy.deepcopy(arms)
            shape, payload = wrong[arm][name]
            wrong[arm][name] = (shape, struct.pack("<f", 2.) + payload[4:])
            with self.subTest(arm=arm), self.assertRaises(ValueError):
                audit_extra_matching(wrong)

    def test_restricted_decoder_retains_every_tensor_byte_and_named_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            for arm in ARMS:
                material = tensor_material(arm)
                path = Path(directory) / f"{arm}.pt"
                write_checkpoint(path, material)
                decoded = checkpoint_tensors(path, parameter_shapes(arm))
                self.assertEqual(decoded, material)
                summary = tensor_summary(decoded)
                self.assertNotEqual(summary["training_parameter_sha256"], summary["execution_parameter_sha256"])
                self.assertEqual(summary["parameter_count"], 42562 if arm == "bridge" else 46722)

    def test_restricted_decoder_rejects_nonfinite_wrong_geometry_and_globals(self):
        with tempfile.TemporaryDirectory() as directory:
            path, shape = Path(directory) / "fixture.pt", {"a": [2, 2]}
            write_checkpoint(path, {"a": ((2, 2), struct.pack("<4f", 0., 1., 2., float("nan")))})
            with self.assertRaisesRegex(ValueError, "nonfinite"):
                checkpoint_tensors(path, shape)
            write_checkpoint(path, {"a": ((2, 2), struct.pack("<4f", 0., 1., 2., 3.))})
            with self.assertRaisesRegex(ValueError, "geometry"):
                checkpoint_tensors(path, {"a": [4]})
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("fixture/data.pkl", b"\x80\x02cos\nsystem\n.")
                archive.writestr("fixture/byteorder", b"little")
            with self.assertRaisesRegex(ValueError, "unregistered pickle global"):
                checkpoint_tensors(path, shape)

    def test_initial_probabilities_require_all_physical_panels_and_exact_equality(self):
        panels = {arm: dict(case_ids=[str(i) for i in range(128)], probabilities=[.5] * 128) for arm in ARMS}
        self.assertEqual(audit_start_predictions(panels)["physical_candidate_observations"], 512)
        wrong = copy.deepcopy(panels)
        wrong["broken"]["probabilities"][0] += 1e-15
        with self.assertRaisesRegex(ValueError, "exactly equal"):
            audit_start_predictions(wrong)
        wrong = copy.deepcopy(panels)
        wrong.pop("local")
        with self.assertRaisesRegex(ValueError, "all four"):
            audit_start_predictions(wrong)

    def test_initial_checkpoint_and_raw_sidecar_are_cross_decoded(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            record = initialization_fixture(folder)
            _, report = audit_initialization(folder, record, tensor_material("bridge"), "endpoint", 41, ["source"])
            self.assertTrue(report["raw_sidecar_and_checkpoint_bytes_equal"])
            for mutation in (lambda r: r["tensors"][0].update(offset=4),
                lambda r: r.update(training_parameter_sha256=r["execution_parameter_sha256"]),
                lambda r: r.update(training_source_groups=["other source"]),
                lambda r: r["architecture"].update(broken_payload_only=True)):
                wrong = copy.deepcopy(record)
                mutation(wrong)
                with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                    audit_initialization(folder, wrong, tensor_material("bridge"), "endpoint", 41, ["source"])
            raw = bytearray((folder / "initialization.bin").read_bytes())
            raw[0] ^= 1
            (folder / "initialization.bin").write_bytes(raw)
            with self.assertRaisesRegex(ValueError, "file SHA"):
                audit_initialization(folder, record, tensor_material("bridge"), "endpoint", 41, ["source"])

    def test_support_deletion_reconstructs_only_two_support_masks(self):
        rows, panel, model, transform, tokens = deletion_fixture()
        self.assertTrue(audit_support_transform(transform, rows)["passed"])
        report = audit_deleted_panel(rows, panel, model, transform, tokens)
        self.assertTrue(report["support_masks_independently_reconstructed"])
        self.assertFalse(report["transformed_fact_values_independently_decoded"])
        mutations = [lambda p: p.update(all_evidence_deleted=True),
            lambda p: p["transform_observations"][0]["transformed_feature_sha256"].__setitem__(3, sha256(b"all zero").hexdigest()),
            lambda p: p["transform_observations"][0]["transformed_feature_sha256"].__setitem__(1, sha256(b"changed question").hexdigest()),
            lambda p: p["transform_observations"][0]["deleted_chunk_positions"][0].pop()]
        for mutation in mutations:
            wrong = copy.deepcopy(panel)
            mutation(wrong)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                audit_deleted_panel(rows, wrong, model, transform, tokens)
        wrong = copy.deepcopy(transform)
        wrong["cases"][0]["deleted_fact_positions"] = [0, 1]
        with self.assertRaisesRegex(ValueError, "grammar/source"):
            audit_support_transform(wrong, rows)

    def test_learning_change_uses_decoded_values_and_does_not_claim_success(self):
        before, after = tensor_material("endpoint"), tensor_material("endpoint")
        for name, value in (("project.weight", .25), ("endpoint_branch.output.weight", .5)):
            shape, payload = after[name]
            after[name] = (shape, struct.pack("<f", value) + payload[4:])
        initial = dict(file_sha256="initial", **tensor_summary(before))
        final = dict(file_sha256="final", **tensor_summary(after))
        items = []
        for name, (shape, payload) in sorted(before.items()):
            left = [x for (x,) in struct.iter_unpack("<f", payload)]
            right = [x for (x,) in struct.iter_unpack("<f", after[name][1])]
            differences = [a - b for a, b in zip(right, left)]
            items.append(dict(name=name, shape=list(shape), role="common" if name in BRIDGE_SHAPES else "extra",
                before_sha256=sha256(payload).hexdigest(), after_sha256=sha256(after[name][1]).hexdigest(),
                l2=math.sqrt(sum(x*x for x in differences)), maximum_absolute_delta=max(map(abs, differences)),
                before_nonzeros=sum(x != 0 for x in left), after_nonzeros=sum(x != 0 for x in right)))
        groups = {role: dict(tensors=sum(t["role"] == role for t in items),
            changed_tensors=sum(t["role"] == role and t["before_sha256"] != t["after_sha256"] for t in items),
            delta_l2=math.sqrt(sum(t["l2"]**2 for t in items if t["role"] == role))) for role in ("common", "extra")}
        record = dict(schema="hepta.endpoint.learning-change.v8", arm="endpoint", initial_weight_sha256="initial",
            final_weight_sha256="final", initial_training_parameter_sha256=initial["training_parameter_sha256"],
            final_training_parameter_sha256=final["training_parameter_sha256"],
            final_execution_parameter_sha256=final["execution_parameter_sha256"],
            scope="training_connection_only_not_causal_success", tensors=items, groups=groups,
            phase_cost=dict(cpu_ns=2, wall_ns=3))
        report = audit_learning_change(record, before, after, "endpoint", initial, final)
        self.assertEqual(report["groups"]["common"]["changed_tensors"], 1)
        self.assertEqual(report["groups"]["extra"]["changed_tensors"], 1)
        wrong = copy.deepcopy(record)
        wrong["tensors"][0]["l2"] += .1
        with self.assertRaisesRegex(ValueError, "delta norm"):
            audit_learning_change(wrong, before, after, "endpoint", initial, final)


if __name__ == "__main__":
    unittest.main()
