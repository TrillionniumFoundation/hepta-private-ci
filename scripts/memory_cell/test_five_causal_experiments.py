"""Hermetic protocol tests. All tasks, pins, executors and reviews are fixtures.

No output of this module is natural-language, model or independent-human evidence.
"""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import five_causal_experiments as f
from full_cell_matrix import evaluate_reader_gate
from test_full_cell_matrix import gate_fixture, fingerprint


def bundle_fixture(families=2):
    tasks = []
    for split in ("train", "validation", "confirmation", "retention"):
        for i in range(families if split == "confirmation" else (2 if split == "retention" else 1)):
            tid = f"{split}:{i}"
            family = "old-family" if split in ("train", "retention") else f"{split}-family-{i}"
            tasks.append(dict(id=tid, split=split, family=family, source_roots=[f"source:{tid}"],
                              exposure_groups=[f"template:{tid}"], content_sha256=f.digest(tid)))
    b = dict(schema="hepta.five-causal.bundle.v1", protocol_sha256=f.digest(f.PROTOCOL),
             data_kind="natural_unseen", cohort=tasks, trials=[], files={}, executors={})
    for e, arms in f.ARMS.items():
        for task in tasks:
            if task["split"] not in ("confirmation", "retention"):
                continue
            for a in arms:
                b["trials"].append(dict(trial_id=f"{e}:{a}:{task['id']}", experiment=e, arm=a,
                    task_id=task["id"], request=dict(question="FIXTURE question", options=[], evidence=[]),
                    bindings={k:f.digest(k) for k in f.BINDINGS}, implementation_sha256=f.digest(e if e == "reader" else e+a),
                    checkpoint_sha256=f.digest("fixture-checkpoint"), timeout_seconds=2.0))
    b["control_annotations"] = {}
    b["split_parameter_counts"] = {a: 8192 for a in ("joint_unsplit", "offline_split", "fixed_split")}
    b["budget_caps"] = {e:dict(wall_seconds=2.0,active_flops=1000,energy_joules=100,model_calls=10) for e in f.ARMS}
    evaluation_tasks = [t for t in tasks if t["split"] in ("confirmation", "retention")]
    for i,t in enumerate(evaluation_tasks):
        tid=t["id"]
        peers=[x for x in evaluation_tasks if x["split"]==t["split"] and x["id"]!=tid]
        donor=peers[0]["id"]
        b["control_annotations"][tid] = dict(critical_evidence_ids=["critical"], missing_modality="video", wrong_pair_donor=donor)
        base=[dict(id="text",modality="text",text="fixture text",asset_sha256=None,position=0),
              dict(id="video1",modality="video",text="",asset_sha256=f.digest(tid+"v1"),position=1),
              dict(id="video2",modality="video",text="",asset_sha256=f.digest(tid+"v2"),position=2)]
        for row in b["trials"]:
            if row["task_id"] != tid: continue
            if row["experiment"] == "reader" and row["arm"] == "human_sufficient":
                row["request"]["evidence"]=[dict(id="critical",modality="text",text="fixture premise",asset_sha256=None,position=0)]
            if row["experiment"] != "multimodal": continue
            evidence=copy.deepcopy(base)
            if row["arm"] in ("text_only","missing_modality"): evidence=evidence[:1]
            if row["arm"] == "time_shuffle": evidence[1]["position"],evidence[2]["position"]=2,1
            if row["arm"] == "wrong_pair":
                evidence[1]["asset_sha256"]=f.digest(donor+"v1")
                evidence[2]["asset_sha256"]=f.digest(donor+"v2")
            row["request"]["evidence"]=evidence
    return b


def review_fixture(b, scope="preregistration", **extra):
    r = dict(schema="hepta.five-causal.review.v1", scope=scope, owner="fixture-owner", experimenter="fixture-author",
             revoked=False, valid_from="2020-01-01T00:00:00Z", valid_until="2099-01-01T00:00:00Z",
             bundle_sha256=f.digest(b), grouping_review="independent_source_and_task_family_reviewed",
             prior_exposure_review="not_used_in_development", exposure_audit_sha256=f.digest("fixture-audit"),
             checkpoints_frozen_at="2019-12-01T00:00:00Z", cohort_released_at="2019-12-02T00:00:00Z")
    r.update(extra)
    return r


def write_journal(b, path, *, experiment="sharing", failed=None, omit=None, incomplete=None):
    previous = "0"*64; judgments = {}
    with path.open("xb") as out:
        for r in b["trials"]:
            if r["experiment"] != experiment or r["trial_id"] == omit:
                continue
            tid = r["trial_id"]
            packet = {"request":r["request"], "checkpoint_sha256":r["checkpoint_sha256"],
                      "bindings":r["bindings"], "timeout_seconds":r["timeout_seconds"]}
            req = f.digest(packet)
            previous = f.journal_append(out, dict(event="started", trial_id=tid, request_sha256=req), previous)
            if tid == incomplete:
                continue
            result = dict(request_sha256=req, answer="FIXTURE output",
                          resources=dict(active_flops=10, energy_joules=None, peak_memory_bytes=20, model_calls=1))
            status = "failed" if tid == failed else "succeeded"
            previous = f.journal_append(out, dict(event="finished", trial_id=tid, request_sha256=req,
                status=status, result=None if tid == failed else result, wall_seconds_including_process_start=.01), previous)
            if status == "succeeded":
                score = 1.0 if r["arm"] == "shared_trained_head" else 0.0
                judgments[tid] = dict(score=score, grounded_and_cited=False, exact_refusal=False, unsupported_claim=False)
    review = review_fixture(b, "outcome_adjudication", experiment=experiment, execution_kind="real_model",
                            raw_sha256=f.file_sha(path), judgments_sha256=f.digest(judgments))
    return judgments, review


class ReaderGateVersionTests(unittest.TestCase):
    def resigned(self, schema, ordinary=18, refusal=19):
        gate, trust = gate_fixture()
        gate["schema"] = schema
        gate["conditions"]["ordinary_retrieval"]["grounded_and_cited"] = ordinary
        gate["conditions"]["no_evidence"]["exact_refusal"] = refusal
        trust["reviewed_gate_content_sha256"] = fingerprint({k:gate[k] for k in ("schema","cohort","model_binding","conditions","capabilities")})
        gate["independent_review"]["trust_manifest_sha256"] = fingerprint(trust)
        return gate, trust

    def test_v2_semantics_preserved_when_retrieval_is_equal(self):
        gate, trust = self.resigned("hepta.reader-gate.v2")
        self.assertFalse(evaluate_reader_gate(gate, trust, trusted_review_sha256=fingerprint(trust)).passed)

    def test_v3_accepts_adequate_reader_with_equal_retrieval(self):
        gate, trust = self.resigned("hepta.reader-gate.v3")
        self.assertTrue(evaluate_reader_gate(gate, trust, trusted_review_sha256=fingerprint(trust)).passed)

    def test_v3_still_requires_negative_control(self):
        gate, trust = self.resigned("hepta.reader-gate.v3", refusal=17)
        self.assertFalse(evaluate_reader_gate(gate, trust, trusted_review_sha256=fingerprint(trust)).passed)

    def test_v3_still_requires_external_trust_pin(self):
        gate, trust = self.resigned("hepta.reader-gate.v3")
        self.assertFalse(evaluate_reader_gate(gate, trust).passed)

    def test_changing_version_invalidates_review(self):
        gate, trust = gate_fixture(); gate["schema"] = "hepta.reader-gate.v3"
        self.assertFalse(evaluate_reader_gate(gate, trust, trusted_review_sha256=fingerprint(trust)).passed)

    def test_unhashable_cohort_fails_closed(self):
        gate, trust = gate_fixture(); gate["cohort"][0] = []
        self.assertFalse(evaluate_reader_gate(gate, trust, trusted_review_sha256=fingerprint(trust)).passed)


class FiveProtocolTests(unittest.TestCase):
    def test_five_experiments_22_arms_and_15_contrasts(self):
        p = f.plan()
        self.assertEqual(len(p["experiments"]), 5)
        self.assertEqual(p["total_arms"], 22)
        self.assertEqual(sum(map(len, f.CONTRASTS.values())), 15)
        self.assertFalse(p["model_efficacy_established"])

    def test_valid_bundle_and_old_family_retention(self):
        b = bundle_fixture()
        self.assertEqual(len(f.validate_bundle(b)), 6)

    def mutation_rejected(self, change):
        b = bundle_fixture(); change(b)
        with self.assertRaises(f.Invalid): f.validate_bundle(b)

    def test_missing_arm(self): self.mutation_rejected(lambda b:b["trials"].pop())
    def test_duplicate_trial(self): self.mutation_rejected(lambda b:b["trials"].append(copy.deepcopy(b["trials"][0])))
    def test_synthetic_cohort(self): self.mutation_rejected(lambda b:b.update(data_kind="synthetic"))
    def test_protocol_edit(self): self.mutation_rejected(lambda b:b.update(protocol_sha256="a"*64))
    def test_gold_leak(self): self.mutation_rejected(lambda b:b["trials"][0]["request"].update(gold_answer="secret"))
    def test_verifier_drift(self): self.mutation_rejected(lambda b:b["trials"][1]["bindings"].update(verifier="a"*64))
    def test_checkpoint_changes_during_holdout(self): self.mutation_rejected(lambda b:b["trials"][4].update(checkpoint_sha256="a"*64))

    def test_source_leakage(self):
        self.mutation_rejected(lambda b:b["cohort"][2].update(source_roots=b["cohort"][0]["source_roots"]))
    def test_content_leakage(self):
        self.mutation_rejected(lambda b:b["cohort"][2].update(content_sha256=b["cohort"][0]["content_sha256"]))
    def test_template_leakage(self):
        self.mutation_rejected(lambda b:b["cohort"][2].update(exposure_groups=b["cohort"][0]["exposure_groups"]))
    def test_task_family_leakage(self):
        self.mutation_rejected(lambda b:b["cohort"][2].update(family=b["cohort"][0]["family"]))
    def test_same_template_cannot_inflate_family_count(self):
        self.mutation_rejected(lambda b:b["cohort"][3].update(exposure_groups=b["cohort"][2]["exposure_groups"]))

    def test_evidence_annotations_not_public(self):
        b = bundle_fixture()
        b["trials"][0]["request"]["evidence"] = [dict(id="e1", modality="text", text="fixture",
                      asset_sha256=None, position=0, is_key_premise=True)]
        with self.assertRaises(f.Invalid): f.validate_bundle(b)

    def test_renaming_identical_media_is_not_a_shuffle(self):
        def change(b):
            base=next(r for r in b["trials"] if r["experiment"]=="multimodal" and r["arm"]=="joint_unsplit")
            row=next(r for r in b["trials"] if r["experiment"]=="multimodal" and r["arm"]=="time_shuffle")
            row["request"]=copy.deepcopy(base["request"])
        self.mutation_rejected(change)

    def test_false_wrong_pair_label_rejected(self):
        def change(b):
            base=next(r for r in b["trials"] if r["experiment"]=="multimodal" and r["arm"]=="joint_unsplit")
            row=next(r for r in b["trials"] if r["experiment"]=="multimodal" and r["arm"]=="wrong_pair")
            row["request"]=copy.deepcopy(base["request"])
        self.mutation_rejected(change)

    def test_false_premise_removal_rejected(self):
        def change(b):
            base=next(r for r in b["trials"] if r["experiment"]=="reader" and r["arm"]=="human_sufficient")
            row=next(r for r in b["trials"] if r["experiment"]=="reader" and r["arm"]=="critical_premise_removed")
            row["request"]=copy.deepcopy(base["request"])
        self.mutation_rejected(change)

    def test_split_parameter_budget_must_match(self):
        self.mutation_rejected(lambda b:b["split_parameter_counts"].update(offline_split=16384))

    def test_unequal_deadline_not_compute_matched(self):
        self.mutation_rejected(lambda b:b["trials"][0].update(timeout_seconds=3.0))

    def test_no_ndu_flag_inferred_from_suffix(self):
        self.mutation_rejected(lambda b:b["trials"][0].update(experiment="x_no_ndu",arm="x_no_ndu"))

    def test_reader_stage_can_be_frozen_before_multimodal_stage(self):
        b=bundle_fixture()
        b["trials"]=[r for r in b["trials"] if r["experiment"]=="reader"]
        del b["split_parameter_counts"]
        self.assertEqual(len(f.validate_bundle(b)),6)

    def test_reviewed_disposition_without_gate_bytes_does_not_admit_ndu(self):
        b=bundle_fixture(); r=review_fixture(b)
        reader=review_fixture(b,"reader_admission",disposition="qualified_for_registered_capabilities",
                              experiments=["ndu"],reader_raw_sha256="a"*64,judgments_sha256="b"*64,gate_receipt_sha256="c"*64)
        with tempfile.TemporaryDirectory() as d, patch.object(f,"check_materials",return_value=None):
            with self.assertRaises(f.Invalid):
                f.execute(b,r,f.digest(r),Path(d),Path(d)/"out","ndu",reader,f.digest(reader))

    def test_reader_cannot_change_model_between_evidence_arms(self):
        self.mutation_rejected(lambda b:b["trials"][0].update(implementation_sha256="a"*64))

    def test_wrong_pair_donor_stays_in_same_partition(self):
        def change(b):
            b["control_annotations"]["confirmation:0"]["wrong_pair_donor"]="retention:0"
        self.mutation_rejected(change)

    def test_no_self_attestation(self):
        b = bundle_fixture(); r = review_fixture(b)
        with self.assertRaises(f.Invalid): f.validate_freeze(b,r,None)
        f.validate_freeze(b,r,f.digest(r))

    def test_same_reviewer_and_author(self):
        b=bundle_fixture(); r=review_fixture(b, owner="fixture-author")
        with self.assertRaises(f.Invalid): f.validate_freeze(b,r,f.digest(r))

    def test_revoked(self):
        b=bundle_fixture(); r=review_fixture(b, revoked=True)
        with self.assertRaises(f.Invalid): f.validate_freeze(b,r,f.digest(r))

    def test_no_post_release_training(self):
        b=bundle_fixture(); r=review_fixture(b, checkpoints_frozen_at="2021-01-01T00:00:00Z")
        with self.assertRaises(f.Invalid): f.validate_freeze(b,r,f.digest(r))

    def test_forged_bundle_breaks_trust(self):
        b=bundle_fixture(); r=review_fixture(b); b["trials"][0]["request"]["question"]="changed"
        with self.assertRaises(f.Invalid): f.validate_freeze(b,r,f.digest(r))

    def test_no_model_material_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(f.Invalid): f.check_materials(bundle_fixture(),Path(d))

    def test_source_symlink_and_traversal_denied(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/"a").write_bytes(b"a"); (root/"link").symlink_to(root/"a")
            for name in ("link", "../a", "/a"):
                with self.assertRaises(f.Invalid): f.source_file(root,name,f.file_sha(root/"a"))

    def test_duplicate_and_nan_json_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"bad.json"
            for raw in ('{"a":1,"a":2}', '{"a":NaN}'):
                p.write_text(raw)
                with self.assertRaises(f.Invalid): f.load(p)

    def test_existing_output_never_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"x.json"; f.write_new(p,{"x":1})
            with self.assertRaises(FileExistsError): f.write_new(p,{"x":2})


class ReadoutTests(unittest.TestCase):
    def test_missing_energy_is_not_zero_or_cost_match(self):
        b=bundle_fixture(8)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"journal"; j,r=write_journal(b,p)
            report=f.analyze(b,p,j,r,f.digest(r))
            self.assertTrue(report["all_trials_adjudicated"])
            self.assertFalse(report["resource_measurements_complete"])
            self.assertFalse(report["compute_matched"])
            self.assertIsNone(report["arms"]["shared_trained_head"]["resources"]["energy_joules"])
            self.assertEqual(report["contrasts"][0]["confirmation"]["families"],8)

    def test_failure_stays_in_denominator_and_disables_positive_claim(self):
        b=bundle_fixture()
        tid=next(x["trial_id"] for x in b["trials"] if x["experiment"]=="sharing" and x["arm"]=="shared_trained_head")
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"journal";j,r=write_journal(b,p,failed=tid)
            report=f.analyze(b,p,j,r,f.digest(r))
            row=report["arms"]["shared_trained_head"]
            self.assertEqual(row["planned"],4); self.assertEqual(row["successful_calls"],3)
            self.assertAlmostEqual(row["failure_inclusive_task_mean"],3/4)
            self.assertFalse(report["all_trials_adjudicated"])

    def test_unattempted_and_interrupted_are_not_dropped(self):
        b=bundle_fixture(); ids=[x["trial_id"] for x in b["trials"] if x["experiment"]=="sharing"]
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"journal";j,r=write_journal(b,p,omit=ids[0],incomplete=ids[1])
            self.assertEqual(f.read_journal(p)[ids[1]]["status"],"unknown_interrupted")
            result=f.analyze(b,p,j,r,f.digest(r))
            self.assertEqual(sum(x["planned"] for x in result["arms"].values()),12)
            self.assertFalse(result["all_trials_adjudicated"])

    def test_raw_tamper_cannot_reuse_review(self):
        b=bundle_fixture()
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"journal";j,r=write_journal(b,p)
            p.write_bytes(p.read_bytes().replace(b"FIXTURE output",b"changed output"))
            with self.assertRaises(f.Invalid): f.analyze(b,p,j,r,f.digest(r))

    def test_judgment_tamper_cannot_reuse_review(self):
        b=bundle_fixture()
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"journal";j,r=write_journal(b,p)
            j[next(iter(j))]["score"] = .9
            with self.assertRaises(f.Invalid): f.analyze(b,p,j,r,f.digest(r))

    def test_wrong_public_input_is_not_same_trial(self):
        b=bundle_fixture()
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"journal";j,r=write_journal(b,p)
            for trial in b["trials"]:
                if trial["experiment"] == "sharing": trial["request"]["question"]="different"
            r["bundle_sha256"]=f.digest(b)
            with self.assertRaises(f.Invalid): f.analyze(b,p,j,r,f.digest(r))

    def test_no_interval_from_repeated_single_template(self):
        self.assertIsNone(f.cluster_interval([1.0]))

    def test_cluster_interval_deterministic(self):
        with patch.dict(f.PROTOCOL, bootstrap_replicates=50):
            self.assertEqual(f.cluster_interval([-.1,.2]*4),f.cluster_interval([-.1,.2]*4))

    def test_blank_journal_cannot_become_a_success(self):
        b=bundle_fixture()
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"journal";p.write_bytes(b"")
            j={};r=review_fixture(b,"outcome_adjudication",experiment="sharing", execution_kind="real_model",
                               raw_sha256=f.file_sha(p),judgments_sha256=f.digest(j))
            result=f.analyze(b,p,j,r,f.digest(r))
            self.assertFalse(result["all_trials_adjudicated"])
            self.assertTrue(all(x["failure_inclusive_task_mean"]==0 for x in result["arms"].values()))


class ExecutionTransportTests(unittest.TestCase):
    def test_blind_subprocess_records_all_four_conditions(self):
        # check_materials is patched ONLY in this unit test. Its fixture script
        # is not a real Reader and cannot pass a production preflight.
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            script=root/"fixture_executor.py"
            script.write_text('import sys,json,hashlib\np=json.load(sys.stdin)\n'
                'h=hashlib.sha256(json.dumps(p,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(",",":")).encode()).hexdigest()\n'
                'assert set(p)=={"request","checkpoint_sha256","bindings","timeout_seconds"}\n'
                'print(json.dumps({"request_sha256":h,"answer":"FIXTURE","resources":{"active_flops":None,"energy_joules":None,"peak_memory_bytes":None,"model_calls":0}}))\n')
            code=f.file_sha(script); b=bundle_fixture()
            b["executors"]={code:dict(path=script.name,sha256=code,kind="mechanics_fixture")}
            for row in b["trials"]: row["implementation_sha256"]=code
            r=review_fixture(b)
            with patch.object(f,"check_materials",return_value=None):
                receipt=f.execute(b,r,f.digest(r),root,root/"run","reader")
            rows=f.read_journal(root/"run/raw-journal.jsonl")
            self.assertEqual(receipt["planned"],16)
            self.assertTrue(all(x["status"]=="succeeded" for x in rows.values()))
            self.assertFalse(receipt["model_efficacy_established"])

    def test_non_reader_cannot_bypass_reader_review(self):
        b=bundle_fixture();r=review_fixture(b)
        with tempfile.TemporaryDirectory() as d, patch.object(f,"check_materials",return_value=None):
            with self.assertRaises(f.Invalid):f.execute(b,r,f.digest(r),Path(d),Path(d)/"out","ndu")

    def test_cli_preflight_blocks_missing_materials_with_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"blocked.json"
            self.assertEqual(f.main(["preflight","--output",str(p)]),2)
            self.assertEqual(f.load(p)["status"],"blocked")


if __name__ == "__main__":
    unittest.main()
