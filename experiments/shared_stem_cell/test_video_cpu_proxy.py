"""Real frozen CPU convolution diagnostics; not a pretrained CLIP test."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

import torch

from experiments.shared_stem_cell import audit_video_cpu_proxy as audit
from experiments.shared_stem_cell import execution as e
from experiments.shared_stem_cell import public_video as public
from experiments.shared_stem_cell import video_cpu_proxy as cpu
from experiments.shared_stem_cell import test_public_video as video_test


class CpuProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.fixture=video_test.PublicVideoTests()
        cls.fixture.setUp()
        cls.root=cls.fixture.root / "source"
        cls.root.mkdir()
        f=cls.fixture
        dataset,cohort=public.stage(cls.root,_read=f.read,_decode=f.decode,
            inventory=f.inventory,revision=f.revision,readme_blob=f.readme_blob)
        e.write_once(cls.root/"manifest.json",{
            "schema":"hepta.shared-stem-media.v1", "classes":2, "steps":80,"seed":17,
            "temporal":False,"video_profile":"paired_temporal_order_v1",
            "dataset":dataset,"cohort":cohort,
            "models":{"clip":{"path":"vision/model","revision":"b"*40,"files":{}}}})
        cls.output=cls.fixture.root/"bench"
        cls.result=cpu.measure(cls.root,cls.output,sizes=(8,),rounds=2,warmups=1)

    @classmethod
    def tearDownClass(cls):
        cls.fixture.tearDown()

    def audited(self):
        return audit.audit(self.root,self.output)

    def alter(self, fn):
        scratch=Path(tempfile.mkdtemp(dir=self.fixture.root))
        self.addCleanup(lambda: shutil.rmtree(scratch,ignore_errors=True))
        for name in ("protocol.json","plan.json","trace.json","report.json"):
            shutil.copy2(self.output/name,scratch/name)
        report=json.loads((scratch/"report.json").read_text())
        trace=json.loads((scratch/"trace.json").read_text())
        plan=json.loads((scratch/"plan.json").read_text())
        protocol=json.loads((scratch/"protocol.json").read_text())
        fn(report,trace,plan,protocol)
        (scratch/"trace.json").write_bytes(e.canonical(trace))
        report["trace_sha256"]=e.sha((scratch/"trace.json").read_bytes())
        (scratch/"report.json").write_bytes(e.canonical(report))
        (scratch/"plan.json").write_bytes(e.canonical(plan))
        (scratch/"protocol.json").write_bytes(e.canonical(protocol))
        return scratch

    def test_real_pillow_conv_gru_dispatch_with_independent_audit(self):
        result=self.audited()
        self.assertEqual(len(result["audited_workloads"]),4)
        self.assertFalse(result["real_CLIP_or_model_accuracy_qualified"])
        self.assertTrue(self.result["experiment_has_real_rgb_conv2d"])
        self.assertFalse(self.result["pretrained_vision_model"])
        self.assertFalse(self.result["net_full_study_savings_established"])

    def test_microbatch_outputs_fixed_depth_match_all_rows(self):
        trace=json.loads((self.output/"trace.json").read_text())["records"]
        for profile in cpu.PROFILES:
            for depth in cpu.DEPTHS:
                a=trace[f"{profile}:8:{depth}:1"]["records"]
                b=trace[f"{profile}:8:{depth}:4"]["records"]
                self.assertEqual([r["prediction"] for r in a],[r["prediction"] for r in b])
                self.assertLessEqual(max(abs(x-y) for u,v in zip(a,b) for x,y in
                                         zip(u["probabilities"],v["probabilities"])),2e-5)

    def test_source_order_reuse_reduces_physical_calls_not_per_cell_quality(self):
        a=self.result["measurements"]["paired:8:8"]
        self.assertEqual(a["batch_1"][0]["physical_calls"],16)
        self.assertEqual(a["batch_4"][0]["physical_calls"],4)
        self.assertEqual(a["batch_1"][0]["unique_frames"],32)
        self.assertEqual(a["batch_4"][0]["unique_frames"],32)
        for v in a["batch_1"]+a["batch_4"]:
            self.assertGreater(v["preprocess_ns"],0)
            self.assertGreater(v["conv_forward_ns"],0)
            self.assertGreater(v["read_source_bytes"],0)
            self.assertEqual(v["wall_ns"],v["stream_wall_ns"]+v["research_wrapper_overhead_ns"])

    def test_frozen_conv_accepts_only_real_finite_bounded_tensor(self):
        model=cpu.FrozenPixelConv()
        self.assertFalse(any(p.requires_grad for p in model.parameters()))
        with torch.no_grad():
            self.assertEqual(model(torch.rand(2,3,cpu.RESIZE,cpu.RESIZE)).shape,(2,cpu.WIDTH))
        with self.assertRaises(e.InputError):model(torch.full((1,3,cpu.RESIZE,cpu.RESIZE),float('nan')))
        with self.assertRaises(e.InputError):model(torch.zeros(17,3,cpu.RESIZE,cpu.RESIZE))

    def test_fails_if_image_bytes_do_not_match_declared_identity(self):
        base=cpu.PixelTower(cpu.FrozenPixelConv())
        ref={"path":"frames/does-not-exist.png","sha256":"0"*64,"timestamp_us":0}
        with self.assertRaises(Exception): base.encode("video",[ref],self.root)
        self.assertEqual(base.calls["clip"],0)

    def test_auditor_refuses_counter_forgeries_even_with_recomputed_trace_digest(self):
        def change(report,trace,plan,protocol):
            report["measurements"]["paired:8:8"]["batch_4"][0]["physical_calls"]=1
            trace["records"]["paired:8:8:4"]["physical_work"]["physical_video_calls"]=1
        scratch=self.alter(change)
        with self.assertRaises(ValueError):audit.audit(self.root,scratch)

    def test_auditor_refuses_forged_per_event_physical_call(self):
        def change(report,trace,plan,protocol):
            trace["records"]["forward_only:8:2:4"]["events"][0]["physical_video_calls"]=0
        with self.assertRaises(ValueError):audit.audit(self.root,self.alter(change))

    def test_auditor_refuses_false_wall_quantiles(self):
        def change(report,trace,plan,protocol):
            report["measurements"]["paired:8:2"]["serial_wall"]["median_ns"]//=2
        with self.assertRaises(ValueError):audit.audit(self.root,self.alter(change))

    def test_auditor_refuses_posthoc_protocol_changes(self):
        def change(report,trace,plan,protocol):
            protocol["rounds"]=3
            plan["protocol_sha256"]=e.sha(e.canonical(protocol))
            report["protocol_sha256"]=plan["protocol_sha256"]
        with self.assertRaises(ValueError):audit.audit(self.root,self.alter(change))

    def test_auditor_checks_source_binding_without_source_images(self):
        # Dataset/cohort manifests are sufficient: no unlicensed image export.
        isolated=Path(tempfile.mkdtemp(dir=self.fixture.root))
        self.addCleanup(lambda: shutil.rmtree(isolated,ignore_errors=True))
        for name in ("manifest.json","dataset.jsonl","cohort.json"):
            shutil.copy2(self.root/name,isolated/name)
        self.assertEqual(self.audited()["source_sha256"],audit.audit(isolated,self.output)["source_sha256"])
        self.assertFalse((isolated/"frames").exists())

    def test_bad_grid_and_unfrozen_model_rejected(self):
        with self.assertRaises(e.InputError):cpu.measure(self.root,self.fixture.root/"bad-grid",sizes=(1,),rounds=1)
        tower=cpu.FrozenPixelConv().train()
        with self.assertRaises(e.InputError):cpu.PixelTower(tower)


if __name__=="__main__": unittest.main()
