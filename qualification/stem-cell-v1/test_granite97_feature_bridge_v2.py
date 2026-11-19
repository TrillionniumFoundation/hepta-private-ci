"""Contract-only, no model or independent physically authenticated issuer."""
import copy
import json
import os
import tempfile
from pathlib import Path
import unittest
from granite97_feature_bridge_v2 import (
    ADAPTER, ENCODER_DOMAIN, EXPORT_SCHEMA, MATERIAL, MODEL, REVISION,
    REVIEW_SCHEMA, BridgeError, bridge, complete_input_sha, read_regular, sha,
)

def fixtures():
    source = b"A constructed public text stimulus."
    ids, mask = [101, 102], [1,1]
    vals = [0, 1] * (len(ids) * 384 // 2)
    pack = b"".join(i.to_bytes(8,"big",signed=True) for i in vals)
    export = dict(
        schema=EXPORT_SCHEMA, model_id=MODEL, revision=REVISION,
        material_digest=MATERIAL, encoder_digest=sha(ENCODER_DOMAIN + bytes.fromhex(MATERIAL)),
        tokenizer_digest=sha(b"tok"),normalizer_digest=sha(b"norm"),
        quantization_digest=sha(b"q"),preprocessing_digest=sha(b"p"),
        adapter_digest=ADAPTER,source_sha256=sha(source),
        input_digest=complete_input_sha(source, ids, mask),
        principal_id="research:p1",purpose_id="research:features",
        generation=9, authority_epoch=1,input_ids=ids,attention_mask=mask,
        values_q24=vals,width=384,expires_at_ms=2000000,
        encoder_forwards=1, encoder_cpu_ns=999, encoder_wall_ns=1000,
    )
    encoded=(json.dumps(export,sort_keys=True,separators=(",", ":"))+"\n").encode()
    review=dict(schema=REVIEW_SCHEMA,export_sha256=sha(encoded),
        source_sha256=sha(source),input_digest=export["input_digest"],
        material_sha256=MATERIAL,encoder_digest=export["encoder_digest"],
        feature_q24_sha256=sha(pack),reviewer_encoder_forwards=1,
        reviewer_encoder_cpu_ns=1234,reviewer_encoder_wall_ns=1250,
        exact_tensors=74,model_replayed=True,authority="DENY_ALL",
        producer_claimed_forwards=1,producer_claimed_cpu_ns=999,
        producer_claimed_wall_ns=1000,
        selected_model=False,production_authorized=False)
    return source,export,review

def encode(x):
    return (json.dumps(x,sort_keys=True,separators=(",", ":"))+"\n").encode()

class BridgeTests(unittest.TestCase):
    def test_nominal(self):
        s,e,r=fixtures()
        obj=bridge(s,encode(e),encode(r),now_ms=1000000)
        self.assertEqual(len(obj.q24_blob),2*384*8)
        self.assertEqual(obj.replay["authority"],"DENY_ALL")
        self.assertFalse(obj.replay["production_authorized"])
        self.assertEqual(obj.replay["bridge_observed_forward_count"],0)
        self.assertEqual(obj.envelope.slot_count,2)

    def test_original_mutations(self):
        s,e,r=fixtures()
        with self.assertRaises(BridgeError):bridge(s+b"x",encode(e),encode(r),now_ms=1000000)
        with self.assertRaises(BridgeError):bridge(s,encode(e),encode(r),now_ms=2000000)

    def test_missing_review_denied(self):
        s,e,r=fixtures()
        with self.assertRaises(BridgeError):bridge(s,encode(e),b"{}",now_ms=1000000)
        for key,val in (("model_replayed",False),("production_authorized",True),
                        ("reviewer_encoder_forwards",0),("feature_q24_sha256",sha(b"bad"))):
            with self.subTest(key=key):
                rr=dict(r,**{key:val})
                with self.assertRaises(BridgeError):bridge(s,encode(e),encode(rr),now_ms=1000000)

    def test_export_mutations(self):
        s,e,r=fixtures()
        cases=[("input_ids",[102,101]),("attention_mask",[0,1]),
               ("material_digest",sha(b"fake")),("adapter_digest",sha(b"identity")),
               ("principal_id",""),("width",383),("values_q24",[0]*767),
               ("encoder_forwards",True),("generation",True),
               ("model_id","other"),("expiry",None)]
        for key,val in cases:
            with self.subTest(key=key):
                ee=copy.deepcopy(e)
                if key=="expiry":ee["expires_at_ms"]=1
                else: ee[key]=val
                with self.assertRaises(BridgeError):bridge(s,encode(ee),encode(r),now_ms=1000000)

    def test_duplicate_json(self):
        s,e,r=fixtures()
        with self.assertRaises(BridgeError):
            bridge(s,b'{"schema":"A","schema":"B"}',encode(r),now_ms=1000000)
        with self.assertRaises(BridgeError):
            bridge(s,encode(e),b'{"authority":"DENY_ALL","authority":"DENY_ALL"}',now_ms=1000000)

    def test_scope_changes_require_matching_real_review(self):
        s,e,r=fixtures()
        for key,val in (("principal_id","research:p2"),("epoch",3),("purpose_id","research:other")):
            ee=copy.deepcopy(e)
            if key=="epoch":ee["authority_epoch"]=val
            else: ee[key]=val
            with self.assertRaises(BridgeError):bridge(s,encode(ee),encode(r),now_ms=1000000)

    def test_path_safety(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); f=root/"source";f.write_bytes(b"abc")
            self.assertEqual(read_regular(f,3),b"abc")
            bad=root/"link";bad.symlink_to(f)
            with self.assertRaises(BridgeError):read_regular(bad,100)
            other=root/"hard";os.link(f,other)
            with self.assertRaises(BridgeError):read_regular(f,100)
            with self.assertRaises(BridgeError):read_regular(root,100)

if __name__ == "__main__":unittest.main()
