"""Physical batched Cell dispatch, same Reader, true isolated serial controls."""
from pathlib import Path
import tempfile
import unittest
from dataclasses import replace

import torch

from experiments.shared_stem_cell import execution as e, media_execution as media
from experiments.shared_stem_cell import video_anytime as anytime
from experiments.shared_stem_cell import video_temporal as temporal
from experiments.shared_stem_cell import video_value as value
from experiments.shared_stem_cell import video_batch as batch
from experiments.shared_stem_cell.test_video_temporal import FakeBase


def examples(sources=4):
    items=[]
    for source in range(sources):
        forward=[{"path": f"{source}-{i}.png", "sha256":f"{source*8+i:02x}"+"0"*62,
                  "timestamp_us":i*40000} for i in range(8)]
        for direction, order in (("f",forward),("r",list(reversed(forward)))):
            frames=[dict(x,timestamp_us=i*40000) for i,x in enumerate(order)]
            items.append(media.MediaCase(case_id=f"{source}-{direction}",scope="research-video",
                         group=f"source-{source}",split="holdout",observed_at=280000,
                         inputs={"video":frames}))
    return items


def critic(offset=0.0):
    return {"schema":"hepta.video-value-critic.v1","coefficients":{
        str(d):[float(offset),0.,0.,0.,0.] for d in (2,4,6)}}


class VideoMicrobatchTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.model=anytime.AnytimeCell(3).eval().requires_grad_(False)
        self.cases=examples()
        self.root=Path(".")

    def serial(self,policy,arm):
        tower=temporal.FrameCacheTowers(FakeBase())
        records=[]
        for c in self.cases:
            records.append({"case_id":c.case_id, **value.stream_one(self.model,
                c.inputs["video"], self.root,tower,policy,critic())})
        return records,{"unique_frames":len(tower.cache),"physical_video_calls":tower.physical_video_calls,
                        "cache_hits":tower.frame_cache_hits,"requested_frame_rows":sum(r["depth"] for r in records)}

    def test_fixed_two_same_predictions_less_physical_dispatches(self):
        p={"kind":"fixed","depth":2}
        serial,cost=self.serial(p,"fixed_2")
        tower=FakeBase()
        result=batch.stream_cases(self.model,self.cases,self.root,tower,p,critic(),batch_size=4)
        rows=result["records"]
        self.assertEqual([r["depth"] for r in rows],[2]*8)
        self.assertEqual([r["prediction"] for r in rows],[r["prediction"] for r in serial])
        self.assertEqual(result["physical_work"]["unique_frames"],cost["unique_frames"])
        self.assertLess(result["physical_work"]["physical_video_calls"],cost["physical_video_calls"])
        self.assertEqual(result["physical_work"]["physical_video_calls"],2)
        self.assertEqual(tower.calls["clip"],2)
        self.assertEqual(sum(x["requested_frames"] for x in result["events"]),16)

    def test_fixed_eight_same_probas_and_all_cache_calls_charged_once(self):
        policy={"kind":"fixed","depth":8}
        serial,cost=self.serial(policy,"fixed_8")
        tower=FakeBase();result=batch.stream_cases(self.model,self.cases,self.root,tower,policy,critic())
        for a,b in zip(result["records"],serial):
            self.assertEqual(a["depth"],b["depth"])
            self.assertEqual(a["prediction"],b["prediction"])
            self.assertTrue(torch.allclose(torch.tensor(a["probabilities"]),
                      torch.tensor(b["probabilities"]),atol=2e-5,rtol=2e-5))
        self.assertEqual(result["physical_work"]["unique_frames"],cost["unique_frames"])
        self.assertEqual(sum(x["physical_video_calls"] for x in result["events"]),tower.calls["clip"])
        self.assertTrue(all(x["requested_frames"]<=8 for x in result["events"]))
        self.assertEqual(result["physical_work"]["requested_frame_rows"],64)
        self.assertEqual(len(result["events"]),8)

    def test_singleton_batch_semantics_match_scalar_even_with_cache_price(self):
        p={"kind":"cache_value","price":0.05}
        serial,cost=self.serial(p,"cache_value")
        r=batch.stream_cases(self.model,self.cases,self.root,FakeBase(),p,critic(),batch_size=1)
        self.assertEqual([x["depth"] for x in r["records"]],[x["depth"] for x in serial])
        self.assertEqual([x["prediction"] for x in r["records"]],[x["prediction"] for x in serial])
        self.assertEqual(r["physical_work"]["unique_frames"],cost["unique_frames"])
        self.assertEqual(r["physical_work"]["physical_video_calls"],cost["physical_video_calls"])

    def test_cache_value_batch_trace_separates_microbatch_cost_from_rows(self):
        p={"kind":"cache_value","price":0.05}
        r=batch.stream_cases(self.model,self.cases,self.root,FakeBase(),p,critic(),batch_size=4)
        self.assertEqual(len(r["records"]),8)
        self.assertLessEqual(r["physical_work"]["physical_video_calls"],32)
        self.assertEqual(sum(x["physical_video_calls"] for x in r["events"]),
                         r["physical_work"]["physical_video_calls"])
        self.assertEqual(r["physical_work"]["microbatches"],2)
        self.assertTrue(all(x["charged_once_to_batch"] for x in r["events"]))
        self.assertTrue(all("shared_batch_event_id" in x for row in r["records"] for x in row["exits_seen"]))

    def test_mixed_policy_frozen_reader_no_weights_changed(self):
        ident=e.parameters(self.model)
        for policy in ({"kind":"confidence","threshold":0.75},
                       {"kind":"value","price":0.05},
                       {"kind":"fixed","depth":6}):
            r=batch.stream_cases(self.model,self.cases,self.root,FakeBase(),policy,critic())
            self.assertEqual(len(r["records"]),len(self.cases))
            self.assertTrue(all(x["depth"] in anytime.DEPTHS for x in r["records"]))
        self.assertEqual(e.parameters(self.model),ident)

    def test_bad_identity_scope_and_future_order_reject_before_tower(self):
        p={"kind":"fixed","depth":2}
        for items in (
            [self.cases[0],self.cases[0]],
            [self.cases[0],replace(self.cases[1],scope="foreign")],
            [replace(self.cases[0],inputs={"video":self.cases[0].inputs["video"][:-1]})],
            [replace(self.cases[0],inputs={"video":[*self.cases[0].inputs["video"][:2],
                                  dict(self.cases[0].inputs["video"][2],timestamp_us=0),
                                  *self.cases[0].inputs["video"][3:]]})],
        ):
            base=FakeBase()
            with self.assertRaises(e.InputError):
                batch.stream_cases(self.model,items,self.root,base,p,critic())
            self.assertEqual(base.calls["clip"],0)

    def test_bad_policy_reject_before_model_or_encoder(self):
        for p in ({"kind":"fixed","depth":3},{"kind":"confidence","threshold":.765},
                  {"kind":"cache_value","price":0.023},{"kind":"unexpected"}):
            base=FakeBase()
            with self.assertRaises(e.InputError):
                batch.stream_cases(self.model,self.cases,self.root,base,p,critic())
            self.assertEqual(base.calls["clip"],0)
        base=FakeBase()
        with self.assertRaises(e.InputError):
            batch.stream_cases(self.model,self.cases,self.root,base,{"kind":"fixed","depth":2},critic(),batch_size=9)
        self.assertEqual(base.calls["clip"],0)

    def test_stale_timestamps_rejected_not_filled_with_fake_values(self):
        class BadBase(FakeBase):
            def encode(self,*args,**kwargs):
                v,t=super().encode(*args,**kwargs)
                return v,t+1
        b=BadBase()
        with self.assertRaises(e.InputError):
            batch.stream_cases(self.model,self.cases,self.root,b,{"kind":"fixed","depth":2},critic())
        self.assertEqual(b.calls["clip"],1)

    def test_shadow_bundle_preserves_serial_receipts_and_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            policies={"fixed_2":{"kind":"fixed","depth":2},
                      "fixed_8":{"kind":"fixed","depth":8},
                      "cache_value":{"kind":"cache_value","price":.05}}
            originals,costs={},{}
            for arm,policy in policies.items():
                originals[arm],costs[arm]=self.serial(policy,arm)
            report=batch.run_shadow(self.model,self.cases,self.root,FakeBase(),
                 policies,critic(),originals,costs,Path(tmp)/"batch",
                 selection_sha256="a"*64,serial_predictions_sha256="b"*64)
            self.assertTrue(report["shadow_charged_separately"])
            self.assertEqual(report["comparison"]["fixed_2"]["same_prediction"],len(self.cases))
            self.assertEqual(report["comparison"]["fixed_8"]["same_depth"],len(self.cases))
            self.assertTrue((Path(tmp)/"batch/predictions.json").exists())


class BatchedArchiveAudit(unittest.TestCase):
    def setUp(self):
        from experiments.shared_stem_cell.test_video_value import ValueEndToEnd
        self.fixture=ValueEndToEnd()
        self.fixture.setUp()
        self.root=self.fixture.root

    def tearDown(self):
        self.fixture.tearDown()

    def test_complete_public_video_fixture_and_independent_audit(self):
        import hashlib
        import json
        from experiments.shared_stem_cell import audit_video_batch
        from experiments.shared_stem_cell.test_public_video import FakeTower
        report=value.run(self.root/"manifest.json",self.root/"value",
                         _tower_factory=FakeTower,microbatch_shadow=True)
        self.assertTrue(report["microbatch_shadow"]["shadow_charged_separately"])
        self.assertEqual(set(report["microbatch_shadow_scores"]), set(batch.SHADOW_ARMS))
        self.assertGreater(report["microbatch_shadow_total_extra_calls"],0)
        checked=audit_video_batch.audit(self.root)
        self.assertEqual(checked["status"],"audited_archived_consistency_only")
        self.assertEqual({r["cases"] for r in checked["microbatch"].values()}, {16})
        self.assertEqual(checked["extra_shadow_calls"],report["microbatch_shadow_total_extra_calls"])
        archived=self.root/"value/batch/predictions.json"
        raw=json.loads(archived.read_bytes())
        raw["arms"]["fixed_2"]["events"][0]["physical_video_calls"] += 1
        poisoned=e.canonical(raw);archived.write_bytes(poisoned)
        # Rehash both payload copies and outer report: independent arithmetic
        # must still detect the forged physical call, not only file mismatch.
        (self.root/"value/batch/fixed_2.json").write_bytes(
            e.canonical(raw["arms"]["fixed_2"]))
        outer=self.root/"value/report.json"
        summary=json.loads(outer.read_bytes())
        summary["microbatch_shadow"]["predictions_sha256"]=hashlib.sha256(poisoned).hexdigest()
        outer.write_bytes(e.canonical(summary))
        with self.assertRaisesRegex(ValueError,"event/count drift"):
            audit_video_batch.audit(self.root)


if __name__=="__main__": unittest.main()
