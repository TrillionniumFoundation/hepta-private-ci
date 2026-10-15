"""Independent artifact verifier negative controls: synthetic envelope only."""
import copy
import io
import json
import unittest
import zipfile
from e2_original_vision_receipt_audit import audit_archive, AuditError, canonical, digest, MODEL, REVISION, WEIGHTS_SHA


def material():
    weights={"model.safetensors":WEIGHTS_SHA,"config.json":digest(b"config"),
             "preprocessor_config.json":digest(b"processor")}
    identity=digest(canonical([MODEL, REVISION, weights, "cls-first-token", "l2"]))
    rows=[]
    for i in range(2):
        row={"case_id":f"source-{i}","group_id":f"g-{i}","scope":"research",
             "observed_at":i,"split":"train","condition":"vision_required",
             "image_sha256":digest(f"img{i}".encode()),"question":"which object?"}
        row["source_sha256"]=digest(canonical(["hepta.e2.image-case.v1",row["case_id"],row["group_id"],row["scope"],row["observed_at"],row["condition"],row["image_sha256"],row["question"]]))
        row["source"]={"modality":"image","input_sha256":row["image_sha256"],"encoder_sha256":identity,"values":[1.0]+[0.0]*383}
        rows.append(row)
    return rows,weights


def zipped(rows=None,weights=None, receipt_change=None, raw_features=None, members=None):
    if rows is None or weights is None:
        rows, weights = material()
    data = raw_features if raw_features is not None else b"".join(canonical(x) for x in rows)
    receipt = {"schema":"hepta.e2.dinov2-source-features.v1", "phase":"train", "encoder_repo":MODEL,
               "encoder_revision":REVISION, "source_sha256":digest(b"inputs"),
               "output_sha256":digest(data),"snapshot_file_sha256s":weights,
               "image_count":2,"actual_model_forwards":2, "feature_width":384, "wall_ns":1,
               "checkpoint_locally_byte_verified":True,"publisher_authenticated":False,
               "labels_seen":False,"production_accepted":False,"authority":"DENY_ALL"}
    if receipt_change:
        receipt_change(receipt)
    out=io.BytesIO()
    with zipfile.ZipFile(out,"w",compression=zipfile.ZIP_DEFLATED) as z:
        if members is None:
            z.writestr("features.jsonl",data)
            z.writestr("receipt.json",canonical(receipt))
        else:
            for name,contents in members:
                z.writestr(name,contents)
    return out.getvalue()


class AuditTests(unittest.TestCase):
    def check_bad(self,blob):
        with self.assertRaises((AuditError,ValueError)):
            audit_archive(blob,digest(blob))

    def test_good_synthetic_archive(self):
        blob=zipped()
        got=audit_archive(blob,digest(blob))
        self.assertEqual(got["cases"],2)
        self.assertTrue(got["independent_archive_consistency"])
        self.assertFalse(got["physical_execution_independently_attested"])
        self.assertFalse(got["production_accepted"])

    def test_archive_pin(self):
        with self.assertRaises(AuditError): audit_archive(zipped(),digest(b"wrong"))

    def test_unexpected_entry(self):
        self.check_bad(zipped(members=[("features.jsonl",b"test"),("../receipt.json",b"test")]))

    def test_duplicate_member(self):
        self.check_bad(zipped(members=[("features.jsonl",b"test"),("features.jsonl",b"test")]))

    def test_false_publisher_authority(self):
        self.check_bad(zipped(receipt_change=lambda r:r.update(publisher_authenticated=True)))

    def test_false_production_authority(self):
        self.check_bad(zipped(receipt_change=lambda r:r.update(production_accepted=True)))

    def test_missing_forward(self):
        self.check_bad(zipped(receipt_change=lambda r:r.update(actual_model_forwards=0)))

    def test_weight_revision(self):
        self.check_bad(zipped(receipt_change=lambda r:r.update(encoder_revision="0"*40)))

    def test_changed_saved_weights(self):
        self.check_bad(zipped(receipt_change=lambda r:r["snapshot_file_sha256s"].update({"model.safetensors":digest(b"other")})))

    def test_source_case_mutation(self):
        rows, w=material();rows[0]["question"]="tampered?"
        self.check_bad(zipped(rows,w))

    def test_duplicate_case(self):
        rows,w=material();rows[1]=copy.deepcopy(rows[0])
        self.check_bad(zipped(rows,w))

    def test_bad_encoder_identity(self):
        rows,w=material();rows[0]["source"]["encoder_sha256"]=digest(b"different")
        self.check_bad(zipped(rows,w))

    def test_future_target_leak(self):
        rows,w=material();rows[0]["label"]="cat"
        self.check_bad(zipped(rows,w))

    def test_nonfinite_vector(self):
        rows,w=material();rows[0]["source"]["values"][0]=float('nan')
        malformed=json.dumps(rows[0],allow_nan=True).encode()+b"\n"+canonical(rows[1])
        self.check_bad(zipped(rows,w,raw_features=malformed))

    def test_bad_dimension(self):
        rows,w=material();rows[0]["source"]["values"]=[1.0]*383
        self.check_bad(zipped(rows,w))

    def test_bad_l2(self):
        rows,w=material();rows[0]["source"]["values"]=[2.0]+[0.0]*383
        self.check_bad(zipped(rows,w))

    def test_bad_scope(self):
        rows,w=material();rows[0]["scope"]="different"
        self.check_bad(zipped(rows,w))

    def test_bad_phase(self):
        self.check_bad(zipped(receipt_change=lambda r:r.update(phase="invalid")))

    def test_wrong_raw_digest(self):
        blob=zipped()
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            f=z.read("features.jsonl")+b"\n";r=z.read("receipt.json")
        self.check_bad(zipped(members=[("features.jsonl",f),("receipt.json",r)]))

if __name__=="__main__":unittest.main()
