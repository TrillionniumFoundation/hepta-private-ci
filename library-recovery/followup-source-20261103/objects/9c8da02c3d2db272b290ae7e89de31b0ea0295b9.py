"""Offline negative tests for matched real-model CPU diagnostic self-consistency."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import hepta_neuron_cpu_benchmark_verify as verifier
from hepta_neuron_cpu_benchmark import SCHEMA,EXPECTED_PARAMETERS
from hepta_neuron_model_trials import MODEL_IDS, InvalidTrial


def make_receipt(arm):
    samples = [float(i)/1000 + 1 for i in range(100)]
    mem = {"rss_bytes": 1200, "peak_rss_bytes": 1200}
    p = {"schema":SCHEMA,"arm":arm,"model_id":MODEL_IDS[arm],
         "source_revision":"a"*40,"source_catalog_sha256":"b"*64,
         "weights_sha256":"c"*64,"installed_sdk_python_sha256":"d"*64,
         "physical_artifact_tree_sha256":"e"*64,"device":"cpu","cpu_threads":2,
         "parameters":EXPECTED_PARAMETERS[arm],"effective_context":512,
         "effective_head_budget":192,"warmup_count":5,"sample_count":100,
         "input_tokens":39,"timing_samples_ms":samples,
         "mean_ms":round(sum(samples)/len(samples),6),"p50_ms":1.049,"p95_ms":1.094,
         "p99_ms":1.098,"load_ms":100.0,
         "serial_invocations_per_second":round(1000/(sum(samples)/len(samples)),5),
         "rss_before_model_load":mem,"rss_after_model_load":mem,
         "rss_after_forwards":mem,
         "measurement_scope":"serial single CPU process, synthetic repeated identical prompt"}
    for field in verifier.FALSE_ONLY:p[field]=False
    return p


class ThreeArmVerifierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.receipts = self.root / "receipts"
        self.receipts.mkdir()
        self.catalog = self.root / "catalog.json"
        self.catalog.write_text('{}')
        self.data={arm:make_receipt(arm) for arm in verifier.ARMS}
        self.pins={"revision":"a"*40,"variants":{arm:{"weights_sha256":"c"*64} for arm in verifier.ARMS}}
        for arm in verifier.ARMS:self.save(arm)
        self.patcher1=patch.object(verifier,"verify_catalog",return_value=self.pins)
        self.patcher2=patch.object(verifier,"sha_file",return_value="b"*64)
        self.patcher1.start();self.patcher2.start()
        self.addCleanup(self.patcher1.stop);self.addCleanup(self.patcher2.stop)
        self.addCleanup(self.temp.cleanup)

    def save(self,arm):
        (self.receipts/f"{arm}-cpu-diagnostic.json").write_text(json.dumps(self.data[arm]))

    def test_three_arm_self_consistency_cannot_promote(self):
        o=verifier.verify_bundle(self.receipts,self.catalog,"d"*64)
        self.assertEqual(len(o["arms"]),3)
        self.assertFalse(o["production_p99_sla_established"])
        self.assertFalse(o["ndu_selection_authorized"])

    def test_tampered_p99_rejected(self):
        self.data["typed"]["p99_ms"]=0.01
        self.save("typed")
        with self.assertRaisesRegex(InvalidTrial,"p99"):
            verifier.verify_bundle(self.receipts,self.catalog,"d"*64)

    def test_missing_variant_rejected(self):
        (self.receipts/"multilingual-cpu-diagnostic.json").unlink()
        with self.assertRaisesRegex(InvalidTrial,"unexpected/aliased"):
            verifier.verify_bundle(self.receipts,self.catalog,"d"*64)

    def test_false_production_claim_rejected(self):
        self.data["laya"]["promotion_authorized"]=True
        self.save("laya")
        with self.assertRaisesRegex(InvalidTrial,"must deny"):
            verifier.verify_bundle(self.receipts,self.catalog,"d"*64)

    def test_mismatched_weight_rejected(self):
        self.data["multilingual"]["weights_sha256"]="f"*64
        self.save("multilingual")
        with self.assertRaisesRegex(InvalidTrial,"identity mismatch"):
            verifier.verify_bundle(self.receipts,self.catalog,"d"*64)

    def test_symlink_and_rss_regression_rejected(self):
        self.data["laya"]["rss_after_forwards"]={"rss_bytes":1200,"peak_rss_bytes":500}
        self.save("laya")
        with self.assertRaisesRegex(InvalidTrial,"RSS"):
            verifier.verify_bundle(self.receipts,self.catalog,"d"*64)

if __name__=="__main__": unittest.main()
