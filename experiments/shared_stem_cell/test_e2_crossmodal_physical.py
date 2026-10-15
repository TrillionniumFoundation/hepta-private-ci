"""Synthetic-only security/mechanism tests, never pretrained model efficacy."""
import copy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from e2_crossmodal_physical import ARMS, CLASSES, _class_predictions, prepare, rows, sha, canon, _verify_split, target_digest, GateError
from e2_crossmodal_independent_score import score, Reject, read_file, source_target_pins

HEX=lambda x: hashlib.sha256(x.encode()).hexdigest()

class E2Tests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)/"panel"
        self.manifest = prepare(self.root)
        self.source = self.root/"source"
        self.withheld = self.root/"withheld"
        self.tr = rows(self.source/"train_images.jsonl")
        self.fu = rows(self.source/"future_images.jsonl")
        self.labels = rows(self.withheld/"future_class_targets.jsonl")
        self.pred = {"schema":"hepta.e2.crossmodal-synthetic-physical.v1.class-predictions",
            "synthetic_data":True, "arms":list(ARMS), "geometry_pred_sha256":HEX("pred-geometry"),
            "class_names":list(CLASSES),"future_labels_seen":False,
            "production_accepted":False,"authority":"DENY_ALL",
            "rows":[{"case_id":r["case_id"],"group_id":r["group_id"],"scope":r["scope"],
                     "observed_at":r["observed_at"],"source_input_sha256":r["image_sha256"],
                     "predicted_labels":{arm: next(l["class_label"] for l in self.labels if l["case_id"]==r["case_id"])
                                         for arm in ARMS}} for r in self.fu]}
        self.receipt={"schema":"hepta.e2.crossmodal-synthetic-physical.v1.producer-receipt",
                      "synthetic_data":True,"future_labels_seen":False,
                      "model_publisher_independently_authenticated":False,
                      "stem_selected":False,"production_accepted":False,
                      "authority":"DENY_ALL","dino_train_forwards":16,
                      "dino_future_forwards":8,"granite_train_forwards":8,
                      "sealed_geometry_predictions_sha256":HEX("pred-geometry")}

    def audit(self,p=None,l=None,f=None,t=None,r=None):
        return score(p if p is not None else self.pred,
                     l if l is not None else self.labels,
                     f if f is not None else self.fu,
                     t if t is not None else self.tr,
                     r if r is not None else self.receipt)

    def test_source_split_and_complete_panel(self):
        tr,fu=_verify_split(self.source,self.manifest)
        self.assertEqual((len(tr),len(fu)),(16,8))
        self.assertEqual(len({r["image_sha256"] for r in tr+fu}),24)
        self.assertEqual(len({r["group_id"] for r in tr+fu}),24)
        self.assertFalse(any("class_label" in r or "target_text" in r for r in fu))
        self.assertEqual(self.manifest["authority"],"DENY_ALL")

    def test_future_target_hashes_not_exposed_to_producer(self):
        self.assertEqual(set(self.manifest["file_sha256s"]), {
            "train_images.jsonl", "future_images.jsonl", "train_anchors.jsonl", "train_class.jsonl"})
        withheld_manifest = json.loads((self.withheld / "target-manifest.json").read_text())
        self.assertEqual(set(withheld_manifest["file_sha256s"]), {
            "future_caption_targets.jsonl", "future_class_targets.jsonl"})
        source_bytes = (self.root / "source-manifest.json").read_bytes()
        self.assertEqual(withheld_manifest["source_manifest_sha256"], sha(source_bytes))
        for digest in withheld_manifest["file_sha256s"].values():
            self.assertNotIn(digest.encode(), source_bytes)
        self.assertEqual(withheld_manifest["authority"], "DENY_ALL")

    def test_evaluator_source_and_target_seal_agreement(self):
        source_bytes = (self.root / "source-manifest.json").read_bytes()
        withheld_manifest = json.loads((self.withheld / "target-manifest.json").read_text())
        source_pins, target_pins = source_target_pins(self.manifest, withheld_manifest, source_bytes)
        self.assertEqual(source_pins["future_images.jsonl"], sha((self.source / "future_images.jsonl").read_bytes()))
        self.assertEqual(target_pins["future_class_targets.jsonl"],
                         target_digest(withheld_manifest, source_bytes, "future_class_targets.jsonl"))
        self.assertEqual(target_pins["future_caption_targets.jsonl"],
                         sha((self.withheld / "future_caption_targets.jsonl").read_bytes()))

    def test_old_source_manifest_with_future_labels_fails_closed(self):
        forged = copy.deepcopy(self.manifest)
        forged["file_sha256s"]["future_class_targets.jsonl"] = HEX("future-target-known")
        with self.assertRaises(GateError):
            _verify_split(self.source, forged)
        target_manifest = json.loads((self.withheld / "target-manifest.json").read_text())
        with self.assertRaises(Reject):
            source_target_pins(forged, target_manifest, canon(forged))

    def test_target_manifest_does_not_accept_wrong_source(self):
        withheld = json.loads((self.withheld / "target-manifest.json").read_text())
        withheld["source_manifest_sha256"] = HEX("wrong-parent")
        source_bytes = (self.root / "source-manifest.json").read_bytes()
        with self.assertRaises(GateError):
            target_digest(withheld, source_bytes, "future_class_targets.jsonl")
        with self.assertRaises(Reject):
            source_target_pins(self.manifest, withheld, source_bytes)

    def test_missing_or_extra_withheld_fields_rejected(self):
        base = json.loads((self.withheld / "target-manifest.json").read_text())
        source_bytes = (self.root / "source-manifest.json").read_bytes()
        for mutation in ("remove", "insert"):
            bad = copy.deepcopy(base)
            if mutation == "remove":
                del bad["file_sha256s"]["future_caption_targets.jsonl"]
            else:
                bad["file_sha256s"]["train_anchors.jsonl"] = HEX("leaked")
            with self.assertRaises(GateError):
                target_digest(bad, source_bytes, "future_class_targets.jsonl")
            with self.assertRaises(Reject):
                source_target_pins(self.manifest, bad, source_bytes)

    def test_withheld_target_bytes_cannot_be_changed_after_seal(self):
        m = json.loads((self.withheld / "target-manifest.json").read_text())
        digest = target_digest(m, (self.root / "source-manifest.json").read_bytes(),
                               "future_class_targets.jsonl")
        path = self.withheld / "future_class_targets.jsonl"
        data = path.read_bytes()
        path.write_bytes(data.replace(b'red-square', b'blue-circle', 1))
        with self.assertRaises(Reject):
            read_file(path, digest, jsonl=True)

    def test_all_five_arm_e2_semantic_claims_absent(self):
        x=self.audit()
        self.assertEqual(x["cases"],8)
        self.assertEqual(len(x["task_arms"]),3)
        self.assertTrue(x["native_multimodal_and_ocr_not_executed"])
        self.assertFalse(x["complete_e2_five_arm_result"])
        self.assertFalse(x["production_accepted"])
        self.assertFalse(x["stem_selected"])

    def test_paired_class_rescue_harm(self):
        p=copy.deepcopy(self.pred)
        p["rows"][0]["predicted_labels"]["unaligned_identity"]="blue-circle"
        p["rows"][1]["predicted_labels"]["fitted"]="blue-circle"
        x=self.audit(p=p)
        y=x["paired_against_unaligned"]
        self.assertEqual(y[0]["rescued"],1)
        self.assertEqual(y[0]["harmed"],1)

    def test_changed_source_bytes_failed(self):
        p=copy.deepcopy(self.pred)
        p["rows"][0]["source_input_sha256"]=HEX("swapped-image")
        with self.assertRaises(Reject):self.audit(p=p)

    def test_label_source_drift(self):
        l=copy.deepcopy(self.labels)
        l[0]["source_sha256"]=HEX("forged-source")
        with self.assertRaises(Reject):self.audit(l=l)

    def test_duplicate_target(self):
        l=copy.deepcopy(self.labels);l[1]=copy.deepcopy(l[0])
        with self.assertRaises(Reject):self.audit(l=l)

    def test_duplicate_prediction(self):
        p=copy.deepcopy(self.pred);p["rows"][1]=copy.deepcopy(p["rows"][0])
        with self.assertRaises(Reject):self.audit(p=p)

    def test_missing_arm(self):
        p=copy.deepcopy(self.pred);del p["rows"][0]["predicted_labels"]["fitted"]
        with self.assertRaises(Reject):self.audit(p=p)

    def test_extra_arm(self):
        p=copy.deepcopy(self.pred);p["rows"][0]["predicted_labels"]["native_multimodal"]="red-square"
        with self.assertRaises(Reject):self.audit(p=p)

    def test_label_in_prediction(self):
        p=copy.deepcopy(self.pred);p["rows"][0]["class_label"]="red-square"
        with self.assertRaises(Reject):self.audit(p=p)

    def test_production_claim_rejected(self):
        r=copy.deepcopy(self.receipt);r["production_accepted"]=True
        with self.assertRaises(Reject):self.audit(r=r)

    def test_fake_forward_claim_rejected(self):
        r=copy.deepcopy(self.receipt);r["dino_train_forwards"]=0
        with self.assertRaises(Reject):self.audit(r=r)

    def test_source_group_overlap_rejected(self):
        f=copy.deepcopy(self.fu);f[0]["group_id"]=self.tr[0]["group_id"]
        with self.assertRaises(Reject):self.audit(f=f)

    def test_false_chronology_rejected(self):
        f=copy.deepcopy(self.fu);f[0]["observed_at"]=1
        with self.assertRaises(Reject):self.audit(f=f)

    def test_image_reuse_rejected(self):
        f=copy.deepcopy(self.fu);f[0]["image_sha256"]=self.tr[0]["image_sha256"]
        with self.assertRaises(Reject):self.audit(f=f)

    def test_noncano_and_duplicate_keys_rejected(self):
        raw=b'{"a":1,"a":2}\n';p=self.source/"duplicate.json"
        p.write_bytes(raw)
        with self.assertRaises(Reject):read_file(p,sha(raw))

    def test_file_byte_pin_rejected(self):
        p=self.source/"train_images.jsonl"
        with self.assertRaises(Reject):read_file(p,HEX("wrong"),jsonl=True)

    def test_class_predictions_only_training_targets(self):
        fake=[]
        map_rows=[]
        for r in self.tr:
            label=next(("-".join([x["class_label"]]) for x in rows(self.source/"train_class.jsonl") if x["case_id"]==r["case_id"]))
            vec=[0.0]*384
            vec[CLASSES.index(label)]=1.0
            fake.append({"case_id":r["case_id"],"target":{"modality":"text","values":vec}})
            map_rows.append({"case_id":r["case_id"],"class_label":label})
        feature={"predictions":[]}
        for r in self.fu:
            feature["predictions"].append({"case_id":r["case_id"],"group_id":r["group_id"],"scope":r["scope"],
                         "observed_at":r["observed_at"],"source_input_sha256":r["image_sha256"],
                         "predictions":{a:[0.25]*384 for a in ARMS}})
        out=_class_predictions(feature,fake,map_rows)
        self.assertFalse(out["future_labels_seen"])
        self.assertEqual(set(out["rows"][0]["predicted_labels"]),set(ARMS))

if __name__=='__main__':unittest.main()
