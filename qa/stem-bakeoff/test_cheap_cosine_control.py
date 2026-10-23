"""Fail-closed regression suite for the P42 post-hoc cheap-cosine comparator.

All fixtures are synthetic and are NEVER scientific outcome evidence.
"""
import copy
from io import BytesIO
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np

import cheap_cosine_control as control

def fixture_row(image, caption, split, block):
    row={"image_id":image,"source_caption_image_id":caption,
         "caption_id":caption+100000,"label":int(image==caption),
         "split":split,"pair_block_id":control.sha(f"{split}:{block}".encode()),
         "image_sha256":control.sha(f"img:{image}".encode()),
         "text_sha256":control.sha(f"caption:{caption}".encode())}
    row["row_id"]=control.sha(control.canon(row))
    return row

def fixtures():
    result={}
    for i,split in enumerate(control.SPLITS):
        a,b=2*i+1,2*i+2
        result[split]=[fixture_row(a,a,split,0),fixture_row(a,b,split,0),
                       fixture_row(b,b,split,0),fixture_row(b,a,split,0)]
    return result

class CheapCosineControlTests(unittest.TestCase):
    def test_complete_source_isolation(self):
        self.assertEqual(control.inspect_rows(fixtures())["test"]["rows"],4)

    def test_cross_split_original_image_rejected(self):
        f=fixtures()
        f["test"]=[fixture_row(1,1,"test",0),fixture_row(1,2,"test",0),
                   fixture_row(2,2,"test",0),fixture_row(2,1,"test",0)]
        with self.assertRaises(ValueError):control.inspect_rows(f)

    def test_wrong_label_or_hash_rejected(self):
        f=fixtures();f["test"][0]["label"]=0
        with self.assertRaises(ValueError):control.inspect_rows(f)
        f=fixtures();f["test"][0]["row_id"]="0"*64
        with self.assertRaises(ValueError):control.inspect_rows(f)

    def test_duplicate_or_incomplete_block_rejected(self):
        f=fixtures();f["test"][0]=copy.deepcopy(f["test"][1])
        with self.assertRaises(ValueError):control.inspect_rows(f)
        f=fixtures();f["train"].pop()
        with self.assertRaises(ValueError):control.inspect_rows(f)

    def test_original_caption_image_cosine(self):
        x=np.array([[1,0],[0,1]],dtype=np.float32)
        self.assertEqual(control.cosine(fixtures()["test"],[7,8],x,x).tolist(),[1,0,1,0])
        with self.assertRaises(ValueError):
            control.cosine(fixtures()["test"],[7,8],x,np.zeros_like(x))

    def test_train_only_learner_and_calibration(self):
        x=np.tile([.9,.1,.8,.2],40)
        y=np.tile([1,0,1,0],40)
        trained=control.fit_train_only(x,y)
        self.assertGreater(trained.weight,0)
        self.assertLess(control.nll(trained.logits(x),y),.2)
        self.assertAlmostEqual(trained.center,.5)
        temp=min(control.TEMPS,key=lambda t:control.nll(trained.logits(x)/t,y))
        self.assertIn(temp,control.TEMPS)
        self.assertEqual(control.evaluate(trained.logits(x),
                          [{"label":int(v)} for v in y],temp)["accuracy"],1.)

    def test_unbalanced_or_nonfinite_train_rejected(self):
        with self.assertRaises(ValueError):control.fit_train_only([.1,.2,.3,.4],[0,0,0,0])
        with self.assertRaises(ValueError):control.fit_train_only([.1,float("nan"),.3,.4],[0,1,0,1])

    def test_paired_bootstrap_is_posthoc(self):
        rows=fixtures()["train"]+fixtures()["test"]
        d=control.paired_delta(rows,[True]*8,[True,False,True,False]*2)
        self.assertAlmostEqual(d["learned_minus_cheap_accuracy"],.5)
        self.assertFalse(d["new_independent_trial"])

    def test_invalid_archive_manifest_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"archive.json").write_text('{"fake":true}')
            with self.assertRaises(ValueError):control.load_frozen(root,root/"archive.json")

    def test_source_bytes_cannot_change_after_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"blob"
            p.write_bytes(b"tampered")
            with self.assertRaises(ValueError):
                control.source_file(p,{"bytes":8,"sha256":"0"*64})

    def test_full_synthetic_archive_replay(self):
        """Exercises all source-binding, learning, pairing and receipt paths."""
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"original"
            ids=list(range(1,385))
            image_splits={"train":ids[:128],"dev":ids[128:192],
                          "calibration":ids[192:256],"test":ids[256:]}
            rows={}
            for split,src in image_splits.items():
                rows[split]=[]
                for b,n in enumerate(range(0,len(src),2)):
                    a,c=src[n:n+2]
                    rows[split].extend([fixture_row(a,a,split,b),fixture_row(a,c,split,b),
                                        fixture_row(c,c,split,b),fixture_row(c,a,split,b)])
            text=np.eye(384,768,dtype=np.float32)
            image=text.copy()
            stream=BytesIO()
            np.savez(stream,text=text,image=image)
            members={}
            def save(name,raw):
                path=root/name
                path.parent.mkdir(exist_ok=True,parents=True)
                path.write_bytes(raw)
                members[name]={"bytes":len(raw),"sha256":control.sha(raw)}
            save("cohorts/manifest.json",control.canon({
                "schema":"hepta.real-coco-pair-cohorts.v1","authority":"DENY_ALL"}))
            for split in control.SPLITS:
                save(f"cohorts/{split}.jsonl",
                     b"\n".join(control.canon(row) for row in rows[split])+b"\n")
            save("bank/features.npz",stream.getvalue())
            h=hashlib.sha256()
            for name,array in (("text",text),("image",image)):
                h.update(control.canon([name,str(array.dtype),list(array.shape)]))
                h.update(array.tobytes())
            save("bank/manifest.json",control.canon({
                "schema":"hepta.multimodal-feature-bank.v1","authority":"DENY_ALL",
                "plan":{"dataset_manifest_sha256":members["cohorts/manifest.json"]["sha256"]},
                "features_sha256":members["bank/features.npz"]["sha256"],
                "feature_tensor_sha256":h.hexdigest(),"image_ids":ids}))
            save("results/report.json",control.canon({
                "authority":"DENY_ALL","production_activation_allowed":False}))
            original=[{"source_id":r["row_id"],"pair_block_id":r["pair_block_id"],
                       "label":r["label"],"arm":"text_image","intervention":"paired",
                       "prediction":r["label"]} for r in rows["test"]]
            save("results/text_image-gated-test/rows.json",control.canon(original))
            archive=Path(td)/"manifest.json"
            archive.write_bytes(control.canon({
                "schema":"hepta.multimodal-evidence-archive.v1",
                "authority":"DENY_ALL","production_activation_allowed":False,
                "members":members}))
            a,b,c=control.ARCHIVE_SHA,control.DATA_SHA,control.BANK_SHA
            try:
                control.ARCHIVE_SHA=control.sha(archive.read_bytes())
                control.DATA_SHA=members["cohorts/manifest.json"]["sha256"]
                control.BANK_SHA=members["bank/manifest.json"]["sha256"]
                result=control.run(restored=root,archive_manifest=archive,output=Path(td)/"comparison")
                self.assertEqual(result["split_metrics"]["test"]["accuracy"],1.)
                self.assertEqual(result["original_trained_head_correct"],256)
                self.assertEqual(len(json.loads((Path(td)/"comparison/test-rows.json").read_text())),256)
                self.assertFalse(result["production_activation_allowed"])
            finally:
                control.ARCHIVE_SHA,control.DATA_SHA,control.BANK_SHA=a,b,c

if __name__=="__main__":
    unittest.main()
