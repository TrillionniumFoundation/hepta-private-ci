"""Source-disjoint batch-size timing, delay and independent audit of CPU Conv2d."""
from __future__ import annotations

from pathlib import Path
import json
import shutil
import tempfile
import unittest

import torch

from experiments.shared_stem_cell import execution as e
from experiments.shared_stem_cell import public_video as public
from experiments.shared_stem_cell import test_public_video as video_fixture
from experiments.shared_stem_cell import video_cpu_tune as tune
from experiments.shared_stem_cell import audit_video_cpu_tune as audit


class SourceDisjointCpuTuneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.fixture=video_fixture.PublicVideoTests()
        cls.fixture.setUp()
        cls.root=cls.fixture.root/"source-disjoint"
        cls.root.mkdir()
        f=cls.fixture
        data,cohort=public.stage(cls.root,_read=f.read,_decode=f.decode,
            inventory=f.inventory,revision=f.revision,readme_blob=f.readme_blob)
        e.write_once(cls.root/"manifest.json",{
            "schema":"hepta.shared-stem-media.v1", "classes":2,"steps":80,"seed":20261014,
            "temporal":False,"video_profile":"paired_temporal_order_v1",
            "dataset":data,"cohort":cohort,
            "models":{"clip":{"path":"vision/model","revision":"b"*40,"files":{}}}})
        cls.output=cls.fixture.root/"tune"
        cls.result=tune.run(cls.root,cls.output,
            workloads=(("forward_only",8,2),("paired",16,8)),
            calibration_rounds=2,evaluation_rounds=2,warmups=0)

    @classmethod
    def tearDownClass(cls): cls.fixture.tearDown()

    def audited(self):return audit.audit(self.root,self.output)

    def alter(self,fn):
        scratch=Path(tempfile.mkdtemp(dir=self.fixture.root))
        self.addCleanup(lambda: shutil.rmtree(scratch,ignore_errors=True))
        files=("protocol.json","training.json","calibration.json","selection.json",
               "holdout-predictions.json","evaluation.json","warmup-records.json","report.json")
        doc={name:json.loads((self.output/name).read_bytes()) for name in files}
        fn(doc)
        for name in files:
            scratch.joinpath(name).write_bytes(e.canonical(doc[name]))
        # Attacker may rehash every changed layer, to test structural independent auditor.
        report=doc["report.json"]
        report["protocol_sha256"]=e.sha((scratch/"protocol.json").read_bytes())
        report["calibration_sha256"]=e.sha((scratch/"calibration.json").read_bytes())
        report["selection_sha256"]=e.sha((scratch/"selection.json").read_bytes())
        report["holdout_prediction_sha256"]=e.sha((scratch/"holdout-predictions.json").read_bytes())
        report["evaluation_sha256"]=e.sha((scratch/"evaluation.json").read_bytes())
        report["warmup_sha256"]=e.sha((scratch/"warmup-records.json").read_bytes())
        (scratch/"report.json").write_bytes(e.canonical(report))
        return scratch

    def test_success_replays_without_private_media(self):
        result=self.audited()
        self.assertEqual(len(result["audited_workloads"]),2)
        self.assertFalse(result["production_accepted"])
        self.assertTrue(result["self_reported_timing_not_independently_attested"])
        self.assertFalse(self.result["pretrained_clip_executed"])

    def test_selection_presealed_and_dataset_sources_never_cross(self):
        s=e.decode((self.output/"selection.json").read_bytes())
        sets=[set(x) for x in s["source_groups"].values()]
        self.assertEqual({key:len(val) for key,val in s["source_groups"].items()},
                         {"train":6,"calibration":2,"holdout":2})
        self.assertEqual(len(set.union(*sets)),10)
        self.assertFalse(s["holdout_labels_used"])
        v=e.decode((self.output/"holdout-predictions.json").read_bytes())
        self.assertEqual(v["selection_sha256"],e.sha((self.output/"selection.json").read_bytes()))
        for key,selected in s["by_workload"].items():
            self.assertIn(selected["batch_size"],tune.BATCHES)
            self.assertEqual(v["records"][key]["selected_batch_size"],selected["batch_size"])

    def test_real_cpu_conv_was_executed_with_three_batch_sizes(self):
        for key,data in self.result["summary"].items():
            self.assertEqual(set(data["holdout"]),{"1","2","4"})
            cal=e.decode((self.output/"calibration.json").read_bytes())["measurements"][key]
            for b in tune.BATCHES:
                self.assertEqual(len(cal[str(b)]),2)
                self.assertGreater(cal[str(b)][0]["conv_forward_ns"],0)
                self.assertGreater(cal[str(b)][0]["preprocess_ns"],0)
                self.assertGreater(cal[str(b)][0]["physical_forward_calls"],0)
                self.assertEqual(sum(cal[str(b)][0]["conv_batch_sizes"]),cal[str(b)][0]["unique_frames"])

    def test_two_source_disjoint_holdout_samples_have_equal_predictions_across_batch_sizes(self):
        ev=e.decode((self.output/"evaluation.json").read_bytes())["measurements"]
        for key,by_size in ev.items():
            reference=by_size["1"][0]["trace"]["records"]
            for b in (2,4):
                other=by_size[str(b)][0]["trace"]["records"]
                self.assertEqual([r["prediction"] for r in reference],[r["prediction"] for r in other])
                for a,c in zip(reference,other):
                    self.assertLess(max(abs(x-y) for x,y in zip(a["probabilities"],c["probabilities"])),2e-5)

    def test_group_completion_is_causal_and_bounded(self):
        ev=e.decode((self.output/"evaluation.json").read_bytes())["measurements"]
        for key,by_size in ev.items():
            for size in tune.BATCHES:
                trace=by_size[str(size)][0]
                t=trace["all_arrive_at_zero_group_completion_ns"]
                self.assertEqual(len(t),trace["case_count"])
                self.assertEqual(trace["first_group_completion_ns"],min(t))
                self.assertGreaterEqual(trace["stream_wall_ns"],max(t))
                self.assertEqual(trace["group_completion_p99_ns"],max(t))

    def test_margin_rule_takes_smaller_batch_close_to_best(self):
        d={1:[104,104],2:[100,100],4:[98,98]}
        self.assertEqual(tune.choose(d)["batch_size"],2)
        d={1:[103,103],2:[100,100],4:[99,99]}
        self.assertEqual(tune.choose(d)["batch_size"],1)
        d={1:[150,150],2:[130,130],4:[100,100]}
        self.assertEqual(tune.choose(d)["batch_size"],4)

    def test_invalid_complete_calibration_fails_before_selection(self):
        for bad in ({1:[1,2],2:[1,2]}, {1:[1,2],2:[1,2],4:[0,1]},
                    {1:[1],2:[1,2],4:[1,2]}):
            with self.assertRaises(e.InputError):tune.choose(bad)

    def test_independent_auditor_catches_changed_timing_even_if_report_rehashed(self):
        def change(doc):
            sample=doc["evaluation.json"]["measurements"]["paired:16:8"]["4"][0]
            sample["wall_ns"]//=2
            # forge candidate's report statistic as if it were recomputed
            doc["report.json"]["summary"]["paired:16:8"]["holdout"]["4"]["wall_median_ns"]//=2
        with self.assertRaises(ValueError):audit.audit(self.root,self.alter(change))

    def test_independent_auditor_catches_forged_physical_calls(self):
        def change(doc):
            sample=doc["evaluation.json"]["measurements"]["paired:16:8"]["4"][0]
            sample["physical_forward_calls"]-=1
            sample["trace"]["physical_work"]["physical_video_calls"]-=1
        with self.assertRaises(ValueError):audit.audit(self.root,self.alter(change))

    def test_independent_auditor_catches_forged_batch_choice(self):
        def change(doc):
            item=doc["selection.json"]["by_workload"]["paired:16:8"]
            item["batch_size"]=1 if item["batch_size"]!=1 else 4
            doc["holdout-predictions.json"]["selection_sha256"]=e.sha(e.canonical(doc["selection.json"]))
            doc["evaluation.json"]["selection_sha256"]=e.sha(e.canonical(doc["selection.json"]))
        with self.assertRaises(ValueError):audit.audit(self.root,self.alter(change))

    def test_missing_or_wrong_source_holdout_rejected(self):
        with self.assertRaises(e.InputError):tune.run(self.root,self.fixture.root/"bad-workload",
            workloads=(("paired",24,2),),calibration_rounds=2,evaluation_rounds=2,warmups=0)

    def test_audit_only_needs_dataset_manifests_and_archived_reports(self):
        scratch=Path(tempfile.mkdtemp(dir=self.fixture.root))
        self.addCleanup(lambda:shutil.rmtree(scratch,ignore_errors=True))
        for filename in ("manifest.json","dataset.jsonl","cohort.json"):
            shutil.copy2(self.root/filename,scratch/filename)
        self.assertFalse((scratch/"frames").exists())
        self.assertEqual(self.audited()["audited_workloads"],
                         audit.audit(scratch,self.output)["audited_workloads"])

    def test_sealed_holdout_prediction_cannot_be_forged_with_new_sha(self):
        def change(doc):
            p=doc["holdout-predictions.json"]["records"]["paired:16:8"]["predictions"][0]
            doc["holdout-predictions.json"]["records"]["paired:16:8"]["predictions"][0]=list(reversed(p))
            doc["evaluation.json"]["prediction_sha256"]=e.sha(e.canonical(doc["holdout-predictions.json"]))
        with self.assertRaises(ValueError):audit.audit(self.root,self.alter(change))

    def test_interleaved_round_order_cannot_be_forged(self):
        def change(doc):
            doc["calibration.json"]["measurements"]["paired:16:8"]["2"][0]["order_position"]=0
            doc["selection.json"]["calibration_sha256"]=e.sha(e.canonical(doc["calibration.json"]))
            doc["evaluation.json"]["selection_sha256"]=e.sha(e.canonical(doc["selection.json"]))
            doc["holdout-predictions.json"]["selection_sha256"]=e.sha(e.canonical(doc["selection.json"]))
        with self.assertRaises(ValueError):audit.audit(self.root,self.alter(change))

    def test_full_cost_ledger_rejects_forged_physical_calls(self):
        def change(doc):
            doc["report.json"]["all_workload_physical_calls_plus_training"]-=1
        with self.assertRaises(ValueError):audit.audit(self.root,self.alter(change))

    def test_independent_auditor_catches_forged_holdout_nll(self):
        def change(doc):
            doc["report.json"]["holdout_scores"]["paired:16:8"]["nll"]+=1
        with self.assertRaises(ValueError):audit.audit(self.root,self.alter(change))

    def test_selection_uses_only_provided_wall_samples_not_labels(self):
        measurements={1:[100,100],2:[60,60],4:[55,55]}
        first=tune.choose(measurements)
        self.assertEqual(first,tune.choose(measurements))
        self.assertFalse(first["uses_accuracy_or_holdout_labels"])


if __name__=="__main__": unittest.main()
