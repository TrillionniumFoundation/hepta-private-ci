"""Independent candidate matrix contract regression; fixture scores are not efficacy."""
from __future__ import annotations

from copy import deepcopy
import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

from multimodal_alignment_contract import canonical, sha
from multimodal_bridge import ContractError
from multimodal_candidate_gate import PLAN, RESULT, READOUT, evaluate, validate_plan


def pin(name):
    return sha(name.encode())


def fixture():
    plan = {
        "schema": PLAN, "scope": "scope_A", "train_sha256": pin("train"),
        "future_source_sha256": "", "future_targets_sha256": "",
        "train_group_sha256s": sorted([pin("group_train_0"), pin("group_train_1")]),
        "train_cutoff": 100, "future_start": 101, "future_end": 200,
        "classes": 2, "train_steps": 192, "head_parameters": 9744,
        "seed": 39, "hardware_sha256": pin("one-machine"),
        "environment_sha256": pin("pinned-env"),
        "candidates": sorted([
            {"name": n, "profile_sha256": pin("profile:"+n),
             "snapshot_sha256": pin("snapshot:"+n)}
            for n in ("no_change", "mmbert_small", "granite_97m")], key=lambda x:x["name"]),
    }
    future = [{"case_id": f"f{i:02d}", "group_id": f"heldout_g{i//2}",
               "scope": "scope_A", "observed_at": 101+i,
               "input_sha256": pin(f"future_source:{i}"), "label": i % 2}
              for i in range(24)]
    sources = [{k:r[k] for k in ("case_id","group_id","scope","observed_at","input_sha256")}
               for r in future]
    plan["future_source_sha256"] = sha(b"".join(canonical(x) for x in sources))
    plan["future_targets_sha256"] = sha(b"".join(canonical(x) for x in future))
    plan_digest = sha(canonical(plan))
    outcomes = []
    for c in plan["candidates"]:
        name = c["name"]
        rows = []
        for i, source in enumerate(sources):
            # Baseline wrong on 8; Granite rescues 6; mmBERT rescues 4
            good = i >= 8 if name == "no_change" else (i >= 2 if name == "granite_97m" else i >= 4)
            label = future[i]["label"] if good else 1 - future[i]["label"]
            rows.append({**source, "probabilities": [0.95 if j == label else 0.05 for j in range(2)]})
        doc = {"schema": RESULT, "candidate": name, "plan_sha256": plan_digest,
               "profile_sha256": c["profile_sha256"], "snapshot_sha256": c["snapshot_sha256"],
               "train_sha256": plan["train_sha256"], "future_source_sha256": plan["future_source_sha256"],
               "hardware_sha256": plan["hardware_sha256"], "environment_sha256": plan["environment_sha256"],
               "train_steps": 0 if name=="no_change" else 192,
               "head_parameters": 0 if name=="no_change" else 9744,
               "seed": 39, "execution": {"physical_forwards": 2,
                   "checkpoint_locally_verified": True, "publisher_authenticated": False,
                   "resident_bytes": 1024, "wall_ns": 10_000_000, "cpu_ns": 8_000_000,
                   "energy_joules": None},
               "predictions": rows}
        outcomes.append((doc, sha(canonical(doc))))
    return plan, future, outcomes, plan_digest


def pinned(updated):
    return updated, sha(canonical(updated))


class CandidateGateTests(unittest.TestCase):
    def setUp(self):
        self.plan, self.truth, self.results, self.pin = fixture()

    def test_full_matched_matrix_and_explicit_no_promotion(self):
        report = evaluate(self.plan, self.truth, self.results, self.pin)
        self.assertEqual(report["schema"], READOUT)
        self.assertEqual(set(report["candidate_results"]),
                         {"no_change","granite_97m","mmbert_small"})
        self.assertEqual(report["candidate_results"]["no_change"]["cases"],24)
        self.assertEqual(report["candidate_results"]["granite_97m"]["recovered_errors_vs_no_change"],6)
        self.assertEqual(report["candidate_results"]["mmbert_small"]["recovered_errors_vs_no_change"],4)
        self.assertIsNone(report["winner"])
        self.assertFalse(report["independent_ndu_verified"])
        self.assertFalse(report["resource_receipts_independently_attested"])
        self.assertFalse(report["production_accepted"])
        self.assertGreater(report["candidate_results"]["granite_97m"]["accuracy"],
                           report["candidate_results"]["no_change"]["accuracy"])

    def test_wrong_plan_sha_rejected(self):
        with self.assertRaises(ContractError):
            evaluate(self.plan, self.truth, self.results, pin("not-plan"))

    def test_plan_requires_baseline_complete_sorted_roster(self):
        for bad in (lambda p:p["candidates"].pop(),
                    lambda p:p["candidates"].reverse(),
                    lambda p:p["candidates"][2].update(name="granite_97m"),
                    lambda p:p.update(head_parameters=0),
                    lambda p:p.update(future_start=100),
                    lambda p:p.update(seed=True),
                    lambda p:p.update(train_group_sha256s=[pin("fake")])):
            plan = deepcopy(self.plan);bad(plan)
            with self.subTest(plan=plan),self.assertRaises(ContractError):
                validate_plan(plan)

    def test_future_window_witness_and_group_nonoverlap(self):
        for bad in (lambda a:a[0].update(scope="other"),
                    lambda a:a[0].update(group_id="group_train_0"),
                    lambda a:a[0].update(observed_at=100),
                    lambda a:a[0].update(label=2),
                    lambda a:a[0].update(case_id="f01"),
                    lambda a:a.reverse(),
                    lambda a:a.pop()):
            truth = deepcopy(self.truth); bad(truth)
            with self.subTest(error=bad),self.assertRaises(ContractError):
                evaluate(self.plan,truth,self.results,self.pin)

    def test_fail_closed_on_one_candidate_missing_or_duplicate(self):
        for subset in (self.results[:-1], self.results[:1]+self.results[:1]+self.results[2:]):
            with self.assertRaises(ContractError):
                evaluate(self.plan,self.truth,subset,self.pin)

    def test_no_heldout_labels_or_unseen_fields_in_prediction(self):
        for field,value in (("label",0),("target",0),("target_text","secret")):
            files=deepcopy(self.results)
            files[0][0]["predictions"][0][field] = value
            files[0] = pinned(files[0][0])
            with self.subTest(field=field),self.assertRaises(ContractError):
                evaluate(self.plan,self.truth,files,self.pin)

    def test_same_exact_future_cohort_for_all_models(self):
        for field,value in (("case_id","not-the-same"),("observed_at",199),
                            ("input_sha256",pin("unseen-input")),("group_id","other_group")):
            files=deepcopy(self.results)
            files[1][0]["predictions"][0][field]=value
            files[1]=pinned(files[1][0])
            with self.subTest(field=field),self.assertRaises(ContractError):
                evaluate(self.plan,self.truth,files,self.pin)

    def test_unfair_training_and_environment_drift(self):
        for field,value in (("head_parameters",4096),("train_steps",191),
                            ("seed",17),("environment_sha256",pin("other-env")),
                            ("hardware_sha256",pin("other-device")),
                            ("snapshot_sha256",pin("other-model")),
                            ("profile_sha256",pin("other-profile")),
                            ("plan_sha256",pin("other-plan")),
                            ("train_sha256",pin("other-train"))):
            files=deepcopy(self.results)
            files[1][0][field]=value
            files[1]=pinned(files[1][0])
            with self.subTest(field=field),self.assertRaises(ContractError):
                evaluate(self.plan,self.truth,files,self.pin)

    def test_invalid_forward_or_resource_receipt(self):
        for field,value in (("physical_forwards",0),("checkpoint_locally_verified",False),
                            ("resident_bytes",0),("wall_ns",0),
                            ("cpu_ns",0),("energy_joules",float("nan")),
                            ("publisher_authenticated","true")):
            files=deepcopy(self.results)
            files[0][0]["execution"][field]=value
            if field != "energy_joules":
                files[0]=pinned(files[0][0])
            else:
                # Canonical JSON forbids NaN even before receipt verification.
                with self.assertRaises(ValueError):
                    pinned(files[0][0])
                continue
            with self.subTest(field=field),self.assertRaises(ContractError):
                evaluate(self.plan,self.truth,files,self.pin)

    def test_bad_probabilities_rejected(self):
        for values in ([0.4,0.4], [1.1,-0.1], [1.0], [True,0.0],
                       [0.5,0.5,0.0], [float("inf"),0.0]):
            files=deepcopy(self.results)
            files[0][0]["predictions"][0]["probabilities"]=values
            if all(type(x) is not float or math_isfinite(x) for x in values):
                files[0]=pinned(files[0][0])
                with self.subTest(values=values),self.assertRaises(ContractError):
                    evaluate(self.plan,self.truth,files,self.pin)

    def test_tampered_candidate_digest_rejected(self):
        files=deepcopy(self.results)
        files[0][0]["predictions"][0]["probabilities"]=[0.5,0.5]
        with self.assertRaises(ContractError):
            evaluate(self.plan,self.truth,files,self.pin)

    def test_cli_proves_pin_and_file_partition(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            def write(name,raw):
                p=root/name;p.write_bytes(raw);return p,sha(raw)
            plan_path, plan_sha=write("plan.json", canonical(self.plan))
            ground_path, ground_sha=write("ground.jsonl",b"".join(canonical(x) for x in self.truth))
            paths=[write(f"{i}.json",canonical(doc)) for i,(doc,_) in enumerate(self.results)]
            arguments=[sys.executable,str(Path(__file__).parent/"multimodal_candidate_gate.py"),
                       "--plan",str(plan_path),"--plan-sha256",plan_sha,
                       "--future-targets",str(ground_path),"--future-targets-sha256",ground_sha]
            for path,digest in paths:
                arguments.extend(["--candidate",str(path),"--candidate-sha256",digest])
            dest=root/"decision.json";arguments.extend(["--output",str(dest)])
            child=subprocess.run(arguments,capture_output=True,text=True,check=False)
            self.assertEqual(child.returncode,0,child.stderr)
            readout=json.loads(dest.read_text())
            self.assertIsNone(readout["winner"])
            with self.assertRaises(FileExistsError):
                # No silent overwrite of an existing independent decision.
                from multimodal_alignment_contract import write_new
                write_new(dest,readout)
            self.assertEqual(sha(dest.read_bytes()),sha(canonical(readout)))


def math_isfinite(x):
    return x == x and x not in (float("inf"),-float("inf"))


if __name__ == "__main__":
    unittest.main()
