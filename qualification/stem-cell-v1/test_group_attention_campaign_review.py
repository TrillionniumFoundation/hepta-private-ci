"""Synthetic file-record forgery checks for stdlib independent campaign review."""
import copy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

from group_attention_campaign_review import ARMS, COHORTS, DIRECT, SYSTEM2, REQUIRED_SOURCES, MODES, MODELS, _digest, _summarize, review
from group_campaign_review import COMPOSITION_PROMPT, _parse
from group_checkpoint_audit import verify_checkpoint_file


def _case(family, query, facts, prefix):
    source = hashlib.sha256(json.dumps([family, query, sorted(facts)],
                                        separators=(",", ":")).encode()).hexdigest()
    if family == "dependency":
        prompt = f"Start at {query[1]} and follow every link. What is the endpoint class? Answer one of A B C D E F G H."
        lines = [f"{a} links to {b}." if kind == "link" else f"{a} has class {b}."
                 for kind, a, b in facts]
    elif family == "constraint":
        prompt = "Which class satisfies every allowed-class constraint? Answer one of A B C D E F G H."
        lines = [f"Constraint {i} allows {' '.join(values)}." for _, i, values in facts]
    else:
        prompt = f"What is the class of the last event for {query[1]} by time? Answer one of A B C D E F G H."
        lines = [f"At time {time}, {entity} has class {label}."
                 for entity, time, label in facts]
    return dict(case_id=prefix + "/" + source[:20], source_group=source,
                family=family, text="\n".join([prompt, *lines]))


def fake_system2_trace(row, critic_sha):
    """Synthetic correctly sequenced receipts, never authentic execution."""
    mode = row["execution_mode"]
    steps = row["steps"]
    kinds = []
    trailing_value = row["execution_status"].startswith("ndu_stop:")
    for step in range(steps):
        kinds.extend(("propose", "verify"))
        if step < steps - 1 or trailing_value:
            kinds.append("value")
    proposed = [chr(65 + row["prediction"])] * steps
    feedback = "missing_evidence" if not row["evidence_supported"] else "supported"
    trace = []
    step_index = 0
    for idx, kind in enumerate(kinds, start=1):
        if kind == "propose":
            output_digest = _digest(proposed[step_index])
        elif kind == "verify":
            accepted = feedback == "supported" and (
                mode == "ndu" or step_index == steps-1)
            output_digest = _digest([accepted, feedback])
            step_index += 1
        else:
            output_digest = _digest({"synthetic": idx})
        trace.append(dict(kind=kind, call=idx, elapsed_ns=1,
                          status="completed", output_digest=output_digest))
    workspaces = [
        dict(step=idx, feature_sha256=row["feature_sha256"],
             model_sha256=row["model_sha256"],
             state_sha256=hashlib.sha256(f"{row['case_id']}/state/{idx}".encode()).hexdigest())
        for idx in range(1, steps + 1)
    ]
    statuses = (["missing_evidence"] * steps if not row["evidence_supported"]
                else ["supported"] * steps)
    decisions = ([dict(continue_computation=False,
                       reason=row["execution_status"].removeprefix("ndu_stop:"),
                       estimate_id=item["output_digest"])
                  for item in trace if item["kind"] == "value"] if mode == "ndu" else [])
    return dict(schema="hepta.group.system2-full-trace.v2",
                authority="DENY_ALL", cohort=row["cohort"], arm=row["arm"],
                case_id=row["case_id"], mode=mode, status=row["execution_status"],
                feature_sha256=row["feature_sha256"],
                model_sha256=row["model_sha256"],
                critic_sha256=critic_sha,
                final_candidate=chr(65 + row["prediction"]), calls=len(trace),
                trace=trace, workspace_bindings=workspaces,
                verifier_statuses=statuses, proposed_candidates=proposed,
                ndu_decisions=decisions,
                independent_success_established=False, production_authorized=False)


def fixture_checkpoint(path, scalar):
    """Valid tiny safetensors archive built without Torch or its serializer."""
    header = json.dumps({
        "weight": {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]}
    }, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(len(header).to_bytes(8, "little") + header +
                     struct.pack("<f", float(scalar)))
    return verify_checkpoint_file(path)


def fixture(directory):
    train = _case("dependency", ("follow", "n0"),
                  [("link", "n0", "n9"), ("label", "n9", "A")], "train")
    valid_a = _case("dependency", ("follow", "n0"),
                    [("link", "n0", "n5"), ("label", "n5", "F")], "validation")
    valid_b = _case("dependency", ("follow", "n0"),
                    [("link", "n0", "n6"), ("label", "n6", "G")], "validation")
    first = _case("dependency", ("follow", "n0"),
                  [("link", "n0", "n2"), ("label", "n2", "B")], "test")
    second = _case("constraint", ("intersection",), [("allow", "0", ("C",))], "test")
    long = _case("temporal", ("latest", "sensor0"), [("sensor0", 10, "D")], "test")
    pair = [[c["case_id"], c["source_group"]] for c in (first, second)]
    composed_source = hashlib.sha256(json.dumps(
        ["composition", ("sum_mod", 8), pair], separators=(",", ":")).encode()).hexdigest()
    composition = dict(case_id="composition/" + composed_source[:20],
        source_group=composed_source, family="composition",
        text=COMPOSITION_PROMPT + "\n[LEFT]\n" + first["text"]
        + "\n[RIGHT]\n" + second["text"])
    deleted = [dict(c, text=c["text"].splitlines()[0]) for c in (first, second)]
    cases = dict(train=[train], validation=[valid_a, valid_b], test=[first, second], long=[long],
                 deleted=deleted, composition=[composition])
    source_dir = Path(__file__).parent
    source_hashes = {
        name: hashlib.sha256((source_dir / name).read_bytes()).hexdigest()
        for name in REQUIRED_SOURCES
    }
    protocol = dict(schema="hepta.group.paired-step-campaign.v1",
        source_sha256=source_hashes,
        frozen_candidate_arms=list(ARMS), evaluation_cohorts=list(COHORTS),
        train_source_groups=[train["source_group"]], public_cases=cases,
        steps=3, seed=17,
        training_profile="sgd_v1",
        optimizer_policy={"core_optimizer_kind": "sgd", "core_learning_rate": 0.05},
        optimizer_comparison_scope="registered_training_regime_not_isolated_optimizer_effect",
        critic_fit_splits=["validation_fit", "validation_calibration"],
        live_system2_modes=["fixed", "ndu"])
    assignments = [dict(case_id=train["case_id"], source_group=train["source_group"],
                        family="dependency",
                        operations=["follow_edge", "read_terminal_label"],
                        evidence_indices=[0, 1], slots=[0, 1])]
    teacher = dict(schema="hepta.group.train-attention-binding.v2",
        source_groups_sha256=_digest([train["source_group"]]),
        authority="DENY_ALL", train_only=True, supervised_steps=2,
        total_teacher_steps=2, truncated_teacher_steps=0,
        coalesced_teacher_steps=0, supervised_slots=2,
        terminal_evidence_supervised_cases=1,
        slot_assignment_sha256=_digest(assignments),
        slot_assignments=assignments,
        tokenizer_calls=1, teacher_tensor_sha256="a" * 64)
    forward_ids = ["f" * 64]
    teacher.update(token_id_binding_complete=True,
                   token_id_forward_witness_sha256=_digest(forward_ids),
                   token_id_retokenized_sha256=_digest(forward_ids))
    encoder = dict(actual_forward_calls=8,
                   token_id_witness_schema="hepta.group.encoder-token-ids.v1",
                   train_forward_token_id_witnesses=forward_ids)
    critic = dict(cpu_ns=200, wall_ns=250, separate_fits_charged=True,
                  source_group_independence_claimed=False, receipts={})
    for model_owner in ("core", "attention"):
        critic["receipts"][model_owner] = dict(
            metadata=dict(source_groups={
                "fit": [valid_a["source_group"]],
                "calibration": [valid_b["source_group"]]},
                future_support_guaranteed=False,
                confidence_bound_established=False),
            parameters_sha256=hashlib.sha256(model_owner.encode()).hexdigest(),
            fit_rows=3, calibration_rows=3)
    material = {}
    for i, name in enumerate(("core_initial", *DIRECT), start=1):
        filename = f"group-{name}.safetensors"
        observed = fixture_checkpoint(directory / filename, i)
        material[name] = dict(
            file=filename, authority="DENY_ALL",
            model_sha256=observed["model_sha256"],
            checkpoint_sha256=observed["checkpoint_sha256"],
            bytes=observed["bytes"], tensor_count=len(observed["tensors"]))
    material_cost = dict(
        cpu_ns=40, wall_ns=50,
        total_artifact_bytes=sum(x["bytes"] for x in material.values()),
        independent_execution_attested=False, files=material)
    training = {}
    initial_core = material["core_initial"]["model_sha256"]
    for arm in DIRECT:
        training[arm] = dict(status="completed", completed_steps=3, seed=17,
            cpu_ns=100, wall_ns=100, parameter_count=112,
            initial_model_sha256=(initial_core if arm in ("core", "attention")
                                  else hashlib.sha256(("initial:" + arm).encode()).hexdigest()),
            trained_model_sha256=material[arm]["model_sha256"],
            sample_and_depth_sha256="b" * 64,
            optimizer_kind="sgd", optimizer_learning_rate=0.05,
            optimizer="SGD_without_momentum", optimizer_bytes=0,
            attention_supervision_enabled=arm == "attention",
            attention_target_sha256="a" * 64 if arm == "attention" else None)
    rows, summaries, full_traces = [], {}, []
    for cohort in COHORTS:
        for arm in ARMS:
            group_rows = []
            for case in cases[cohort]:
                correct, _, _ = _parse(case, missing=cohort == "deleted")
                mode = MODES[arm]
                depth = 1 if arm in ("static", "wide") else 4
                if mode == "ndu":
                    depth = 1
                row = dict(cohort=cohort, arm=arm, case_id=case["case_id"],
                    source_group=case["source_group"],
                    feature_sha256=hashlib.sha256(
                        (cohort + case["text"]).encode()).hexdigest(),
                    model_sha256=material[MODELS[arm]]["model_sha256"],
                    prediction=0 if correct is None else correct,
                    evidence_supported=correct is not None,
                    success=correct is not None, unsupported_attempt=correct is None,
                    valid_execution=True, steps=depth,
                    verifier_calls=0 if mode == "direct" else depth,
                    search_formula_work=None if mode == "direct" else 100,
                    execution_mode=mode,
                    execution_status=("direct_forward" if mode == "direct"
                        else "verifier_accepted_not_independent_eval" if correct is not None
                        else "depth_exhausted" if mode == "fixed"
                        else "ndu_stop:no_supported_net_gain"),
                    wall_ns=20, cpu_ns=10)
                row["full_trace_sha256"] = None
                if arm in SYSTEM2:
                    artifact = fake_system2_trace(
                        row, critic["receipts"][MODELS[arm]]["parameters_sha256"])
                    full_traces.append(artifact)
                    row["full_trace_sha256"] = _digest(artifact)
                rows.append(row)
                group_rows.append(row)
            status_counts = {}
            for row in group_rows:
                status = row["execution_status"]
                status_counts[status] = status_counts.get(status, 0) + 1
            summaries[f"{cohort}.{arm}"] = dict(n=len(group_rows),
                failed_episodes=0,
                correct=sum(r["success"] for r in group_rows),
                unsupported_attempts=sum(r["unsupported_attempt"] for r in group_rows),
                steps=sum(r["steps"] for r in group_rows),
                verifier_calls=sum(r["verifier_calls"] for r in group_rows),
                execution_statuses=status_counts,
                cpu_ns=sum(r["cpu_ns"] for r in group_rows),
                wall_ns=sum(r["wall_ns"] for r in group_rows),
                p50_ns=20, p95_ns=20)
    report = dict(schema="hepta.group.paired-step-observation.v1",
        full_system2_trace_count=len(full_traces),
        full_system2_trace_manifest_sha256=_digest(full_traces),
        protocol_sha256=_digest(protocol), authority="DENY_ALL",
        production_authorized=False, natural_future_win_established=False,
        equal_actual_training_work=False, teacher=teacher, critic_cost=critic,
        real_system2_callbacks_executed=True,
        heldout_target_stripped_before_system2_callbacks=True,
        same_model_critic_frozen_on_validation_only=True,
        initial_core_sha256=initial_core,
        checkpoint_materialization=material_cost,
        encoder_cost=encoder, training=training, summaries=summaries)
    for name, data in (("protocol", protocol), ("teacher", teacher),
                       ("encoder", encoder), ("observations", rows), ("report", report),
                       ("system2-traces", full_traces)):
        (directory / (name + ".json")).write_text(json.dumps(data))
    return {name: copy.deepcopy(value) for name, value in
            (("protocol", protocol), ("teacher", teacher), ("encoder", encoder),
             ("observations", rows), ("report", report), ("system2-traces", full_traces))}


class PairedReviewTests(unittest.TestCase):
    def test_independent_symbolic_replay_no_promotion(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = review_fixture = fixture(Path(tmp))
            reviewed = review(tmp)
            self.assertTrue(reviewed["complete_group_replay"])
            self.assertFalse(reviewed["future_task_efficacy_proved"])
            self.assertFalse(reviewed["real_host_execution_independently_attested"])
            self.assertEqual(reviewed["descriptive_paired"]["test"]["rescued"], 0)
            self.assertEqual(reviewed["descriptive_paired"]["test"]["harmed"], 0)
            self.assertFalse(reviewed["descriptive_paired"]["long"]["equal_total_compute_demonstrated"])


    def test_real_abort_is_counted_as_negative_in_complete_campaign(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initial = fixture(root)
            rows = copy.deepcopy(initial["observations"])
            traces = copy.deepcopy(initial["system2-traces"])
            report = copy.deepcopy(initial["report"])
            row = next(r for r in rows if r["cohort"] == "test"
                       and r["arm"] == "core_ndu" and r["prediction"] == 1)
            episode = next(t for t in traces if
                           (t["cohort"], t["arm"], t["case_id"]) ==
                           (row["cohort"], row["arm"], row["case_id"]))
            row.update(prediction=2, success=False, valid_execution=False,
                       execution_status="callback_failed", search_formula_work=100)
            episode.update(final_candidate="C", status="callback_failed",
                           proposed_candidates=["C"], verifier_statuses=["unsupported_dependency"],
                           calls=3, ndu_decisions=[],
                           trace=[
                               dict(kind="propose", call=1, status="completed",
                                    elapsed_ns=1, output_digest=_digest("C")),
                               dict(kind="verify", call=2, status="completed",
                                    elapsed_ns=1,
                                    output_digest=_digest([False, "unsupported_dependency"])),
                               dict(kind="value", call=3, status="failed",
                                    elapsed_ns=1, error_type="ValueError")])
            row["full_trace_sha256"] = _digest(episode)
            report["full_system2_trace_manifest_sha256"] = _digest(traces)
            report["summaries"]["test.core_ndu"] = _summarize([
                r for r in rows if r["cohort"] == "test" and r["arm"] == "core_ndu"])
            for name, value in (("observations", rows), ("system2-traces", traces),
                                ("report", report)):
                (root / (name + ".json")).write_text(json.dumps(value))
            result = review(root)
            self.assertTrue(result["passed"])
            self.assertEqual(result["failed_episodes_by_cohort"]["test"], 1)
            self.assertFalse(result["production_promotion_permitted"]
                             if "production_promotion_permitted" in result else False)

    def test_reject_prediction_cost_binding_and_missing_arm(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = fixture(root)
            for mutation in (
                lambda r: r[0].update(success=False),
                lambda r: r[0].update(cpu_ns=0),
                lambda r: r[0].update(feature_sha256="0" * 64),
                lambda r: r.pop(),
                lambda r: r.append(copy.deepcopy(r[0])),
            ):
                rows = copy.deepcopy(files["observations"])
                mutation(rows)
                (root / "observations.json").write_text(json.dumps(rows))
                with self.subTest(mutation=repr(mutation)), self.assertRaises(ValueError):
                    review(root)

    def test_reject_missing_live_heldout_target_redaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            originals = fixture(root)
            changed = copy.deepcopy(originals["report"])
            changed["heldout_target_stripped_before_system2_callbacks"] = False
            (root / "report.json").write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, "System2"):
                review(root)

    def test_reject_fake_training_of_system2_alias_arm(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = fixture(root)
            bad = copy.deepcopy(files["report"])
            bad["training"]["core_ndu"] = copy.deepcopy(bad["training"]["core"])
            (root / "report.json").write_text(json.dumps(bad))
            with self.assertRaisesRegex(ValueError, "training schedule"):
                review(root)

    def test_reject_forged_paired_initial_or_final_weight_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = fixture(root)
            for bad_field in ("initial_model_sha256", "trained_model_sha256"):
                changed = copy.deepcopy(files["report"])
                changed["training"]["attention"][bad_field] = "a" * 64
                (root / "report.json").write_text(json.dumps(changed))
                with self.subTest(field=bad_field), self.assertRaises(ValueError):
                    review(root)

    def test_reject_impossible_verifier_success_and_unpaid_callbacks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = fixture(root)
            for mutate in (
                lambda rows: next(r for r in rows if r["arm"] == "core_fixed" and
                                  r["evidence_supported"]).update(execution_status="depth_exhausted"),
                lambda rows: next(r for r in rows if r["arm"] == "attention_ndu"
                                  and r["evidence_supported"]).update(verifier_calls=0),
                lambda rows: next(r for r in rows if r["arm"] == "core_fixed"
                                  and r["evidence_supported"]).update(search_formula_work=0),
            ):
                rows = copy.deepcopy(files["observations"])
                mutate(rows)
                (root / "observations.json").write_text(json.dumps(rows))
                with self.subTest(mutation=repr(mutate)), self.assertRaises(ValueError):
                    review(root)


    def test_reject_truncated_teacher_or_missing_terminal_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            originals = fixture(root)
            for attr, value in (("truncated_teacher_steps", 1),
                                ("terminal_evidence_supervised_cases", 0),
                                ("supervised_steps", 1),
                                ("supervised_slots", 0)):
                teacher = copy.deepcopy(originals["teacher"])
                report = copy.deepcopy(originals["report"])
                teacher[attr] = value
                report["teacher"] = teacher
                (root / "teacher.json").write_text(json.dumps(teacher))
                (root / "report.json").write_text(json.dumps(report))
                with self.subTest(attr=attr), self.assertRaisesRegex(
                        ValueError, "lossless bounded"):
                    review(root)

    def test_reject_different_forward_ids_with_same_length(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = fixture(root)
            encoder = copy.deepcopy(files["encoder"])
            report = copy.deepcopy(files["report"])
            encoder["train_forward_token_id_witnesses"][0] = "a" * 64
            report["encoder_cost"] = encoder
            (root / "encoder.json").write_text(json.dumps(encoder))
            (root / "report.json").write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, "forward Token ID"):
                review(root)

    def test_reject_teacher_and_unequal_schedule_forgery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = fixture(root)
            changed = copy.deepcopy(files["report"])
            changed["training"]["attention"]["sample_and_depth_sha256"] = "c" * 64
            (root / "report.json").write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, "schedule"):
                review(root)
            (root / "report.json").write_text(json.dumps(files["report"]))
            changed = copy.deepcopy(files["teacher"])
            changed["source_groups_sha256"] = "d" * 64
            (root / "teacher.json").write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, "teacher"):
                review(root)

    def test_reject_missing_or_tampered_physical_checkpoint_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = fixture(root)
            path = root / "group-attention.safetensors"
            original = path.read_bytes()
            modified = bytearray(original)
            modified[-1] ^= 1
            path.write_bytes(modified)
            with self.assertRaisesRegex(ValueError, "stored model bytes"):
                review(root)
            path.write_bytes(original)
            (root / "group-core_initial.safetensors").unlink()
            with self.assertRaises(OSError):
                review(root)

    def test_reject_rehashed_but_causally_wrong_system2_call_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = fixture(root)
            changed = copy.deepcopy(files["system2-traces"])
            target = next(t for t in changed if t["arm"] == "core_fixed")
            target["trace"][0]["kind"] = "verify"
            # Attacker updates both available hash layers; semantic replay must
            # still reject the rewritten callback order.
            changed_rows = copy.deepcopy(files["observations"])
            match = next(r for r in changed_rows if
                         (r["cohort"], r["arm"], r["case_id"]) ==
                         (target["cohort"], target["arm"], target["case_id"]))
            match["full_trace_sha256"] = _digest(target)
            changed_report = copy.deepcopy(files["report"])
            changed_report["full_system2_trace_manifest_sha256"] = _digest(changed)
            (root / "system2-traces.json").write_text(json.dumps(changed))
            (root / "observations.json").write_text(json.dumps(changed_rows))
            (root / "report.json").write_text(json.dumps(changed_report))
            with self.assertRaisesRegex(ValueError, "causal propose"):
                review(root)


    def test_independent_public_verifier_refuses_rehashed_false_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = fixture(root)
            traces = copy.deepcopy(original["system2-traces"])
            rows = copy.deepcopy(original["observations"])
            report = copy.deepcopy(original["report"])
            target = next(t for t in traces if t["cohort"] == "test" and t["arm"] == "core_fixed")
            target["proposed_candidates"][0] = "H"
            target["trace"][0]["output_digest"] = _digest("H")
            row = next(r for r in rows if (r["cohort"], r["arm"], r["case_id"]) ==
                       (target["cohort"], target["arm"], target["case_id"]))
            row["full_trace_sha256"] = _digest(target)
            report["full_system2_trace_manifest_sha256"] = _digest(traces)
            (root / "system2-traces.json").write_text(json.dumps(traces))
            (root / "observations.json").write_text(json.dumps(rows))
            (root / "report.json").write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, "verifier feedback"):
                review(root)

    def test_reject_missing_system2_trajectory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = fixture(root)
            traces = copy.deepcopy(files["system2-traces"])
            traces.pop()
            changed_report = copy.deepcopy(files["report"])
            changed_report["full_system2_trace_count"] = len(traces)
            changed_report["full_system2_trace_manifest_sha256"] = _digest(traces)
            (root / "system2-traces.json").write_text(json.dumps(traces))
            (root / "report.json").write_text(json.dumps(changed_report))
            with self.assertRaises(ValueError):
                review(root)

    def test_reject_forged_exact_source_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = fixture(root)
            changed = copy.deepcopy(files["protocol"])
            changed["source_sha256"]["group_attention_campaign.py"] = "a" * 64
            changed_report = copy.deepcopy(files["report"])
            changed_report["protocol_sha256"] = _digest(changed)
            (root / "protocol.json").write_text(json.dumps(changed))
            (root / "report.json").write_text(json.dumps(changed_report))
            with self.assertRaisesRegex(ValueError, "source SHA"):
                review(root)

    def test_reject_damaged_public_evidence_and_protocol(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = fixture(root)
            changed = copy.deepcopy(files["protocol"])
            changed["public_cases"]["test"][0]["text"] = "injected, no evidence"
            (root / "protocol.json").write_text(json.dumps(changed))
            with self.assertRaises(ValueError):
                review(root)


    def test_reject_duplicate_keys_and_nonfinite_values_before_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture(root)
            protocol = root / "protocol.json"
            raw = protocol.read_text()
            protocol.write_text('{"schema":"injected",' + raw.lstrip()[1:])
            with self.assertRaisesRegex(ValueError, "duplicate JSON"):
                review(root)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture(root)
            teacher = root / "teacher.json"
            raw = teacher.read_text()
            teacher.write_text('{"untrusted":1e999,' + raw.lstrip()[1:])
            with self.assertRaisesRegex(ValueError, "non-finite"):
                review(root)


    def test_reject_mislabeled_optimization_or_invented_optimizer_states(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            originals = fixture(root)
            for mode, mutation in (
                ("claimed_adam", lambda report: report["training"]["core"].update(
                    optimizer_kind="adam", optimizer="Adam_unfused_nonforeach_beta_0.9_0.999",
                    optimizer_bytes=128)),
                ("invented_sgd_moments", lambda report: report["training"]["core"].update(
                    optimizer_bytes=128)),
            ):
                changed = copy.deepcopy(originals["report"])
                mutation(changed)
                (root / "report.json").write_text(json.dumps(changed))
                with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "optimization"):
                    review(root)
            (root / "report.json").write_text(json.dumps(originals["report"]))
            bad_policy = copy.deepcopy(originals["protocol"])
            bad_policy["optimizer_policy"]["core_learning_rate"] = 0.5
            (root / "protocol.json").write_text(json.dumps(bad_policy))
            with self.assertRaisesRegex(ValueError, "optimizer policy"):
                review(root)


if __name__ == "__main__":
    unittest.main()
