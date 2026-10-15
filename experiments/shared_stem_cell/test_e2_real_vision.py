"""E2 vision ingress tests: real bytes and synthetic vectors, no real checkpoint."""
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from e2_real_vision_features import (parse_source, canonical, sha, Rejected, _load_image,
                                     checked_file, validate_vector)
from e2_real_vision_bridge_ingress import produce

D = sha(b"actual-image-bytes")


def row(i, phase="train", condition="vision_required", group=None):
    r = dict(case_id=f"c{i}", group_id=group or f"g{i}", scope="research-scope", observed_at=i+1,
             split=phase, condition=condition, image_path=f"im{i}.png", image_sha256=D,
             question="What class of object is pictured?")
    r["source_sha256"] = sha(canonical(["hepta.e2.image-case.v1", r["case_id"],
                        r["group_id"], r["scope"], r["observed_at"], r["condition"],
                        r["image_sha256"], r["question"]]))
    return r


def doc(rows):
    return b"".join(canonical(r) for r in rows)


def feature_rows(rows):
    return [{k:v for k,v in r.items() if k!="image_path"} |
            {"source":{"modality":"image", "input_sha256":r["image_sha256"],
                       "encoder_sha256":sha(b"checkpoint-identity"), "values":[0.001] * 384}}
            for r in rows]


def receipt(rows, phase):
    return {"schema":"hepta.e2.dinov2-source-features.v1", "phase":phase,
            "checkpoint_locally_byte_verified":True, "labels_seen":False,
            "production_accepted":False, "authority":"DENY_ALL",
            "image_count":len(rows), "actual_model_forwards":len(rows),
            "output_sha256":sha(doc(feature_rows(rows)))}


def anchors(rows):
    return doc([{k:r[k] for k in ("case_id","group_id","scope","observed_at","source_sha256")}
                | {"target_text":"a research training caption"} for r in rows])


class E2RealVisionTests(unittest.TestCase):
    def test_train_only_source_and_independent_text_join(self):
        rows=[row(0),row(1)]
        raw=doc(rows)
        self.assertEqual(len(parse_source(raw,sha(raw),"train")),2)
        joined=produce(doc(feature_rows(rows)),receipt(rows,"train"),phase="train",anchors=anchors(rows))
        self.assertEqual(len(joined),2)
        self.assertEqual(joined[0]["source"]["modality"],"image")
        self.assertIn("target_text",joined[0]);self.assertNotIn("label",str(joined))

    def test_future_is_source_only(self):
        rows=[row(3,"future")]
        self.assertEqual(len(parse_source(doc(rows),sha(doc(rows)),"future")),1)
        future=produce(doc(feature_rows(rows)),receipt(rows,"future"),phase="future")
        self.assertNotIn("target_text",future[0])
        self.assertEqual(future[0]["split"],"future")

    def test_future_anchor_leak_rejected(self):
        rows=[row(3,"future")]
        with self.assertRaises(Rejected):
            produce(doc(feature_rows(rows)),receipt(rows,"future"),phase="future",anchors=anchors(rows))

    def test_source_label_leak_rejected(self):
        rows=[row(0),row(1)];rows[0]["label"]="cat"
        with self.assertRaises(Rejected):parse_source(doc(rows),sha(doc(rows)),"train")

    def test_source_group_change_rejected(self):
        rows=[row(0),row(1)];rows[0]["group_id"]="changed"
        with self.assertRaises(Rejected):parse_source(doc(rows),sha(doc(rows)),"train")

    def test_question_change_rejected(self):
        rows=[row(0),row(1)];rows[0]["question"]="is it a cat?"
        with self.assertRaises(Rejected):parse_source(doc(rows),sha(doc(rows)),"train")

    def test_duplicate_source_case_rejected(self):
        rows=[row(0),row(0)]
        with self.assertRaises(Rejected):parse_source(doc(rows),sha(doc(rows)),"train")

    def test_prevent_visual_removed_fake_forward(self):
        rows=[row(0,"future",condition="visual_evidence_removed")]
        with self.assertRaises(Rejected):parse_source(doc(rows),sha(doc(rows)),"future")

    def test_anchor_mismatch_rejected(self):
        rows=[row(0),row(1)]; anchor=[json.loads(x) for x in anchors(rows).splitlines()]
        anchor[0]["group_id"]="tampered"
        with self.assertRaises(Rejected):
            produce(doc(feature_rows(rows)),receipt(rows,"train"),phase="train",anchors=doc(anchor))

    def test_missing_anchor_rejected(self):
        rows=[row(0),row(1)]
        with self.assertRaises(Rejected):
            produce(doc(feature_rows(rows)),receipt(rows,"train"),phase="train",anchors=anchors(rows[:1]))

    def test_receipt_tampering_rejected(self):
        rows=[row(0,"future")];r=receipt(rows,"future");r["actual_model_forwards"]=0
        with self.assertRaises(Rejected):produce(doc(feature_rows(rows)),r,phase="future")

    def test_untrusted_forged_authority_rejected(self):
        rows=[row(0,"future")];r=receipt(rows,"future");r["production_accepted"]=True
        with self.assertRaises(Rejected):produce(doc(feature_rows(rows)),r,phase="future")

    def test_invalid_f32_rejected(self):
        rows=[row(0,"future")];f=feature_rows(rows)
        broken=doc(f).replace(b"0.001",b"NaN",1)
        rec=receipt(rows,"future"); rec["output_sha256"]=sha(broken)
        with self.assertRaises(Rejected):produce(broken,rec,phase="future")
        with self.assertRaises(Rejected):validate_vector([0]*383)

    def test_actual_image_bytes_pinned_and_loaded(self):
        with tempfile.TemporaryDirectory() as d:
            fp=Path(d)/"tiny.png"
            img=Image.new("RGB",(16,16),(10,20,30)); img.save(fp)
            got=_load_image(fp,sha(fp.read_bytes()))
            self.assertEqual(got.size,(16,16))
            with self.assertRaises(Rejected):_load_image(fp,sha(b"other"))

    def test_filename_escape_rejected(self):
        rows=[row(0,"future")];rows[0]["image_path"]="../escape.png"
        with self.assertRaises(Rejected):parse_source(doc(rows),sha(doc(rows)),"future")

    def test_partition_mismatch_rejected(self):
        rows=[row(0,"future")]
        with self.assertRaises(Rejected):parse_source(doc(rows),sha(doc(rows)),"train")

    def test_source_sha_corrupted_rejected(self):
        rows=[row(0,"future")]
        with self.assertRaises(Rejected):parse_source(doc(rows),sha(b"bad"),"future")

if __name__=="__main__":unittest.main()
