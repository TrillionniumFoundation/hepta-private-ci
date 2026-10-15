"""Original-source paired Linux wait4 hardware-accounting regressions (DENY_ALL)."""
from __future__ import annotations

import copy
import math
import os
from pathlib import Path
import tempfile
import unittest

from qualification.cell_meta_execution_af import physical_router_audit as audit
from qualification.cell_meta_execution_af import physical_router_trial as trial
from qualification.cell_meta_execution_af import physical_router_top1 as top1
from qualification.cell_meta_execution_af import physical_router_hard_train as hardtrain
from qualification.cell_meta_execution_af import physical_router_frozen_baseline as frozenprod
from qualification.cell_meta_execution_af import physical_router_fivearm_review as five
from qualification.cell_meta_execution_af import physical_router_os_meter as meter
from qualification.cell_meta_execution_af import physical_router_paired_screen as paired


class OsIsolatedMeterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.root=Path(cls.temp.name)
        shared=trial.synthetic_panel(seed=41,rule="conditional",rows=64)
        cls.bundles={}
        for seed in paired.SEEDS:
            panel=copy.deepcopy(shared)
            panel["source"]["seed"]=seed
            soft=trial.run(panel,steps=2)
            post=top1.create_report(panel,soft)
            hard=hardtrain.produce(panel,soft,post)
            frozen=frozenprod.produce(panel,soft,post,hard)
            report=five.descriptive(panel,soft,post,hard,frozen)
            bundle={"panel":panel,"soft":soft,"posthoc":post,"hard":hard,
                    "frozen":frozen,"five":report}
            cls.bundles[seed]=bundle
            names={"panel":"trial-panel","soft":"trial-report",
                   "posthoc":"top1-report","hard":"hard-train-report",
                   "frozen":"frozen-report","five":"fivearm-report"}
            for key,name in names.items():
                (cls.root/f"{seed}-{name}.json").write_bytes(audit.canonical(bundle[key])+b"\n")
        cls.paired=paired.screen(cls.bundles)
        cls.measured=meter._launch(cls.root,41,"fixed_router",timeout=40)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_real_fresh_process_wait4_cpu_rss_and_exact_fp32(self):
        x=self.measured
        self.assertEqual(x["child_exit_status"],0)
        self.assertTrue(x["physical_os_process_executed"])
        self.assertTrue(x["complete_result_recomputed_and_equal"])
        self.assertGreater(x["os_wait4_total_cpu_seconds"],0)
        self.assertGreater(x["os_wait4_peak_rss_bytes"],0)
        self.assertGreater(x["parent_monotonic_elapsed_seconds"],0)
        self.assertAlmostEqual(x["os_wait4_total_cpu_seconds"],
            x["os_wait4_user_cpu_seconds"]+x["os_wait4_system_cpu_seconds"],places=5)

    def test_parent_binds_exact_source_bundle_and_saved_tensor(self):
        x=self.measured
        self.assertEqual(x["source_bundle_sha256"],audit.digest(self.bundles[41]))
        original=self.bundles[41]["hard"]["results"][1]
        self.assertEqual(x["full_result_sha256"],
                         audit.digest(meter.strip_time(original,"fixed_router")))

    def test_actual_frozen_cpu_without_second_stage_training(self):
        child=meter._launch(self.root,41,meter.NAMED[0],timeout=40)
        self.assertTrue(child["complete_result_recomputed_and_equal"])
        self.assertEqual(child["full_result_sha256"],audit.digest(
            meter.strip_time(self.bundles[41]["frozen"],meter.NAMED[0])))
        self.assertEqual(self.bundles[41]["frozen"]["meters"]
                         ["additional_stage2_optimizer_updates"],0)

    def test_actual_learned_stochastic_route_replays_from_registered_seed(self):
        child=meter._launch(self.root,41,"learned_router",timeout=40)
        self.assertEqual(child["full_result_sha256"],audit.digest(
            meter.strip_time(self.bundles[41]["hard"]["results"][2],"learned_router")))
        self.assertTrue(self.bundles[41]["hard"]["results"][2]["meters"]["sampled_routes"])

    def test_flags_never_grant_production_or_matched_compute(self):
        for field in ("full_lifecycle_cost_matched","external_host_signatures_verified",
                      "actual_future_outcomes_verified","independent_ndu_selection_authorized"):
            self.assertIs(self.measured[field],False)
        self.assertEqual(self.measured["authority_posture"],"DENY_ALL")
        self.assertEqual(self.measured["production_admission"],"BLOCKED")
        self.assertIsNone(self.measured["cpu_energy_joules"])
        self.assertIsNone(self.measured["gpu_peak_bytes"])

    def test_unsupported_seed_and_arm_fail_before_dispatch(self):
        for kw in ({"seed":99,"arm":"fixed_router"},
                   {"seed":41,"arm":"arbitrary-effect"}):
            with self.subTest(kw=kw), self.assertRaises(meter.ResourceDenied):
                meter._launch(self.root,kw["seed"],kw["arm"])

    def test_invalid_timeout_fails_closed(self):
        for v in (0,-1,math.inf,float("nan"),meter.TIMEOUT_SECONDS+1):
            with self.subTest(timeout=v), self.assertRaises(meter.ResourceDenied):
                meter._launch(self.root,41,"no_change",timeout=v)

    def test_rehashed_but_changed_original_logits_fail(self):
        b=copy.deepcopy(self.bundles[41])
        b["hard"]["results"][1]["predictions"]["future_1"][0]["probability"]=.987
        b["hard"]["results"][1]["prediction_sha256"] = audit.digest(
            b["hard"]["results"][1]["predictions"])
        with self.assertRaises(Exception):
            meter._worker(b,"fixed_router")

    def test_child_fake_authority_fields_rejected(self):
        x={"arm":"fixed_router","operation":"actual_fresh_sparse_top1_training",
           "original_bundle_sha256":"a"*64,"replayed_immutable_result_sha256":"b"*64,
           "original_result_sha256":"b"*64,
           "result_identity_and_full_fp32_replay_match":True,"authority_posture":"DENY_ALL",
           "production_admission":"BLOCKED","future_window_prospective":False,
           "full_lifecycle_cost_matched":False,"new_pretrained_encoder_forward":False,
           "external_host_signatures_verified":False}
        meter.accept_child(x,"fixed_router")
        for key,value in (("external_host_signatures_verified",True),
                          ("full_lifecycle_cost_matched",True),
                          ("new_pretrained_encoder_forward",True),
                          ("result_identity_and_full_fp32_replay_match",False),
                          ("authority_posture","ALLOW"),
                          ("original_result_sha256","0"*64),
                          ("replayed_immutable_result_sha256","a"*64),
                          ("operation","other")):
            changed=copy.deepcopy(x);changed[key]=value
            with self.subTest(key=key),self.assertRaises(meter.ResourceDenied):
                meter.accept_child(changed,"fixed_router")

    def test_child_duplicate_field_or_forged_hash_denied(self):
        x={"arm":"fixed_router","operation":"actual_fresh_sparse_top1_training",
           "original_bundle_sha256":"a"*64,"replayed_immutable_result_sha256":"b"*64,
           "original_result_sha256":"b"*64,
           "result_identity_and_full_fp32_replay_match":True,"authority_posture":"DENY_ALL",
           "production_admission":"BLOCKED","future_window_prospective":False,
           "full_lifecycle_cost_matched":False,"new_pretrained_encoder_forward":False,
           "external_host_signatures_verified":False}
        for changed in [dict(x, extra=1), dict(x, original_bundle_sha256="g"*64),
                        dict(x, original_result_sha256="c"*64)]:
            with self.assertRaises(meter.ResourceDenied):
                meter.accept_child(changed,"fixed_router")

    def test_duplicate_receipt_key_and_nonfinite_denied(self):
        with self.assertRaises(meter.ResourceDenied):
            __import__("json").loads('{"arm":"fixed_router","arm":"learned_router"}',
                object_pairs_hook=meter._reject_duplicate_json)
        with self.assertRaises(meter.ResourceDenied):
            __import__("json").loads('{"value":NaN}',
                parse_constant=lambda _: (_ for _ in ()).throw(meter.ResourceDenied("nonfinite")))

    def test_report_validation_requires_all_original_three_seed_bundles(self):
        missing=self.root/"53-hard-train-report.json"
        missing.rename(self.root/"53-hard-train-report.json.off")
        try:
            with self.assertRaises((meter.ResourceDenied, OSError)):
                meter.measure(self.root,seeds=(41,))
        finally:
            (self.root/"53-hard-train-report.json.off").rename(missing)

    def test_unregistered_subset_and_duplicate_seed_denied(self):
        for seeds in ((41,41), (42,), (), (41,99)):
            with self.subTest(seeds=seeds),self.assertRaises(meter.ResourceDenied):
                meter.measure(self.root,seeds=seeds)

    def fake_source_bound_shards(self, folder):
        # STRUCTURAL fixtures; these are NOT actual OS observations.
        cached = getattr(self.__class__, "cached_fake_shards", None)
        if cached is not None:
            for seed,raw in cached.items():
                (folder/f"{seed}-os-meter.json").write_bytes(raw)
            return
        from qualification.cell_meta_execution_af import physical_router_cost_frontier as cost
        source=paired.screen(self.bundles)
        cost_report=cost.evaluate(self.bundles,source)
        psha=audit.digest(source);csha=audit.digest(cost_report)
        for seed in paired.SEEDS:
            measurements=[]
            for arm in meter.NAMED:
                b=self.bundles[seed]
                item=(b["frozen"] if arm==meter.NAMED[0]
                      else b["hard"]["results"][meter.NAMED.index(arm)-1])
                measurements.append({
                    "seed":seed,"arm":arm,"child_exit_status":0,
                    "full_result_sha256":audit.digest(meter.strip_time(item,arm)),
                    "source_bundle_sha256":audit.digest(b),
                    "os_wait4_user_cpu_seconds":2.0,
                    "os_wait4_system_cpu_seconds":0.2,
                    "os_wait4_total_cpu_seconds":2.2,
                    "os_wait4_peak_rss_bytes":123456789,
                    "parent_monotonic_elapsed_seconds":2.5,
                    "physical_os_process_executed":True,
                    "complete_result_recomputed_and_equal":True,
                    "measurement_scope":"fresh_python_process_full_import_audit_and_arm_operation",
                    "cpu_energy_joules":None,"gpu_peak_bytes":None,
                    "full_lifecycle_cost_matched":False,
                    "external_host_signatures_verified":False,
                    "actual_future_outcomes_verified":False,
                    "independent_ndu_selection_authorized":False,
                    "production_admission":"BLOCKED","authority_posture":"DENY_ALL"})
            fake={"schema":meter.SCHEMA,"source_paired_report_sha256":psha,
                "source_cost_report_sha256":csha,
                "host_kernel":"Linux","host_machine":"x86_64",
                "paired_seed_count":1,"paired_original_source_count":384,
                "measurements":measurements,"processes_are_separate_and_serial":True,
                "process_cpu_rss_not_full_lifecycle_comparable":True,
                "cpu_measurements_have_model_import_and_replay_cost":True,
                "real_pretrained_encoder_executed_in_this_trial":False,
                "external_host_attestation":False,"statistical_winner_certified":False,
                "actual_future_outcomes_verified":False,"ndu_selection_authorized":False,
                "production_admission":"BLOCKED","authority_posture":"DENY_ALL"}
            (folder/f"{seed}-os-meter.json").write_bytes(audit.canonical(fake)+b"\n")
        self.__class__.cached_fake_shards={
            seed:(folder/f"{seed}-os-meter.json").read_bytes() for seed in paired.SEEDS}

    def test_three_seed_join_is_descriptive_not_attested(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d);self.fake_source_bound_shards(path)
            merged=meter.join_shards(self.root,path)
            self.assertEqual(merged["exact_15_isolated_processes"],15)
            self.assertEqual(merged["original_source_row_count_not_tripled"],384)
            self.assertFalse(merged["resource_or_model_winner_certified"])
            self.assertFalse(merged["original_host_or_model_signatures_authenticated"])
            self.assertFalse(merged["independent_future_ndu_outcomes_observed"])
            self.assertEqual(merged["authority_posture"],"DENY_ALL")

    def test_cross_architecture_shard_denied_even_with_valid_source_hashes(self):
        # Every model tensor, source identity and measured process digest stays
        # unchanged. Previously a mismatched hardware architecture could be
        # silently pooled into one descriptive median.
        with tempfile.TemporaryDirectory() as d:
            path=Path(d);self.fake_source_bound_shards(path)
            item=audit.load(path/"47-os-meter.json")
            self.assertEqual(item["host_machine"],"x86_64")
            item["host_machine"]="aarch64"
            (path/"47-os-meter.json").write_bytes(audit.canonical(item)+b"\n")
            with self.assertRaisesRegex(meter.ResourceDenied,
                                        "mixed host architectures"):
                meter.join_shards(self.root,path)

    def test_missing_one_physical_shard_denied(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d);self.fake_source_bound_shards(path)
            (path/"47-os-meter.json").unlink()
            with self.assertRaises((meter.ResourceDenied,OSError,audit.AuditError)):
                meter.join_shards(self.root,path)

    def test_forged_full_lifecycle_and_nonsensical_cpu_denied(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d);self.fake_source_bound_shards(path)
            report=audit.load(path/"41-os-meter.json")
            report["measurements"][0]["full_lifecycle_cost_matched"]=True
            (path/"41-os-meter.json").write_bytes(audit.canonical(report)+b"\n")
            with self.assertRaises(meter.ResourceDenied):
                meter.join_shards(self.root,path)
            report["measurements"][0]["full_lifecycle_cost_matched"]=False
            report["measurements"][0]["os_wait4_total_cpu_seconds"]=0.0
            (path/"41-os-meter.json").write_bytes(audit.canonical(report)+b"\n")
            with self.assertRaises(meter.ResourceDenied):
                meter.join_shards(self.root,path)

    def test_changed_result_hash_and_arm_selection_denied(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d);self.fake_source_bound_shards(path)
            report=audit.load(path/"53-os-meter.json")
            report["measurements"][3]["full_result_sha256"]="a"*64
            (path/"53-os-meter.json").write_bytes(audit.canonical(report)+b"\n")
            with self.assertRaises(meter.ResourceDenied):
                meter.join_shards(self.root,path)
            report["measurements"][3]["full_result_sha256"] = audit.digest(
                meter.strip_time(self.bundles[53]["hard"]["results"][2],"learned_router"))
            report["measurements"][3]["arm"]="fixed_router"
            (path/"53-os-meter.json").write_bytes(audit.canonical(report)+b"\n")
            with self.assertRaises(meter.ResourceDenied):
                meter.join_shards(self.root,path)

    def test_report_limitations_are_explicit_after_one_seed_five_arms(self):
        result=meter.measure(self.root,seeds=(41,))
        self.assertEqual(len(result["measurements"]),5)
        self.assertEqual(result["paired_seed_count"],1)
        self.assertEqual(result["paired_original_source_count"],384)
        self.assertTrue(result["process_cpu_rss_not_full_lifecycle_comparable"])
        self.assertFalse(result["real_pretrained_encoder_executed_in_this_trial"])
        self.assertFalse(result["statistical_winner_certified"])
        self.assertEqual(result["authority_posture"],"DENY_ALL")

if __name__=="__main__":
    unittest.main()
