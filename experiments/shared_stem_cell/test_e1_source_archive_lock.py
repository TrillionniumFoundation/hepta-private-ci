"""Synthetic source-bundle attacks; no new pretrained training or data-origin proof."""
import copy
import io
import json
import unittest
from zipfile import ZipFile, ZIP_DEFLATED

import e1_source_archive_lock as e

H = "a"*64
SPLITS = (("train",64,64),("calibration",16,16),("test",32,32))

def fixture():
    cases=[]
    for split,n0,n1 in SPLITS:
        for label,quota in ((0,n0),(1,n1)):
            for i in range(quota):
                text=f"test fixture only {split} class{label} index{i}"
                joint={"state":text,"question":e.QUESTION,"options":list(e.OPTIONS)}
                source=e.digest(text.encode())
                cases.append({"case_id":source[:24],"split":split,"label":label,
                              "label_name":e.OPTIONS[label],"source_digest":source,
                              "group_id":source,"joint_input":joint,
                              "joint_input_digest":e.digest(e.canonical(joint))})
    panel={"schema":"hepta.stem.agnews-binary-capability-panel.v1",
           "dataset":"szhuggingface/ag_news","dataset_commit_prefix":"98c5322",
           "dataset_file_sha256":dict(e.DATASET_BYTES),"label_mapping":{"world":0,"sports":1},"case_count":224,
           "cross_sectional_not_future":True,"production_promotion":"DENY_ALL",
           "cases":cases}
    panel_sha=e.digest(e.canonical(panel))
    src={"schema":"hepta.stem.agnews-input-receipt.v1","panel_digest":panel_sha,
         "source_sha256":dict(e.DATASET_BYTES),"production_promotion":"DENY_ALL",
         "future_longitudinal_evidence":False}
    comparison={"panel_digest":panel_sha,"production_promotion":"DENY_ALL",
                "three_future_windows_present":False}
    laya={"schema":"hepta.stem.agnews-physical-arm.v1",
          "arm_id":"laya421_frozen","panel_digest":panel_sha,
          "production_promotion":"DENY_ALL",
          "rows":[{k:c[k] for k in ("case_id","source_digest","joint_input_digest","split")}
                  for c in cases if c["split"] in ("calibration","test")]}
    files={"stem-agnews-source.json":src,"stem-agnews-comparison.json":comparison,
           "stem-laya-physical-arm.json":laya}
    return panel,files

def archive(files):
    buf=io.BytesIO()
    with ZipFile(buf,"w",compression=ZIP_DEFLATED) as z:
        for name,obj in files.items():
            z.writestr(name,e.canonical(obj))
    return buf.getvalue()

class ArchiveLockTests(unittest.TestCase):
    def accept(self):
        p,f=fixture();blob=archive(f)
        result=e.verify(p,blob,approved_panel_sha=e.digest(e.canonical(p)),
                        approved_archive_sha=e.digest(blob))
        self.assertEqual(result["case_count"],224)
        self.assertEqual(result["historical_laya_pair_count"],96)
        self.assertFalse(result["original_publisher_signature_verified"])
        self.assertFalse(result["production_promotion_permitted"])
    def reject(self,change):
        p,f=fixture();change(p,f);blob=archive(f)
        with self.assertRaises((e.Invalid,KeyError,ValueError,TypeError)):
            e.verify(p,blob,approved_panel_sha=e.digest(e.canonical(p)),
                     approved_archive_sha=e.digest(blob))
    def test_complete_fixture_no_authority(self):self.accept()
    def test_unapproved_actual_selection_even_if_everything_else_matches(self):
        p,f=fixture();raw=archive(f)
        with self.assertRaises(e.Invalid):e.verify(p,raw)
    def test_changed_label(self):self.reject(lambda p,f:p["cases"][0].update(label=1))
    def test_changed_state(self):self.reject(lambda p,f:p["cases"][0]["joint_input"].update(state="changed"))
    def test_changed_group(self):self.reject(lambda p,f:p["cases"][0].update(group_id="changed"))
    def test_changed_case_id(self):self.reject(lambda p,f:p["cases"][0].update(case_id="wrong"))
    def test_wrong_option_order(self):self.reject(lambda p,f:p["cases"][0]["joint_input"].update(options=["sports","world"]))
    def test_missing_case(self):self.reject(lambda p,f:p["cases"].pop())
    def test_duplicate_source(self):self.reject(lambda p,f:p["cases"].__setitem__(1,copy.deepcopy(p["cases"][0])))
    def test_laya_missing(self):self.reject(lambda p,f:f["stem-laya-physical-arm.json"]["rows"].pop())
    def test_laya_swap(self):self.reject(lambda p,f:f["stem-laya-physical-arm.json"]["rows"][0].update(case_id="wrong"))
    def test_laya_duplicate(self):self.reject(lambda p,f:f["stem-laya-physical-arm.json"]["rows"].__setitem__(1,copy.deepcopy(f["stem-laya-physical-arm.json"]["rows"][0])))
    def test_comparison_future_overclaim(self):self.reject(lambda p,f:f["stem-agnews-comparison.json"].update(three_future_windows_present=True))
    def test_archive_source_mismatch(self):self.reject(lambda p,f:f["stem-agnews-source.json"].update(panel_digest=H))
    def test_wrong_publisher_digest(self):self.reject(lambda p,f:f["stem-agnews-source.json"]["source_sha256"].update(train=H))
    def test_wrong_archive_checksum(self):
        p,f=fixture();blob=archive(f)
        with self.assertRaises(e.Invalid):
            e.verify(p,blob,approved_panel_sha=e.digest(e.canonical(p)))
    def test_duplicate_json_source_key(self):
        p,f=fixture()
        self.assertRaises(e.Invalid,e.strict_json,b'{"x":1,"x":2}')
    def test_nonfinite_source_key(self):
        self.assertRaises(e.Invalid,e.strict_json,b'{"x":NaN}')
    def test_duplicate_zip_entry(self):
        p,f=fixture();raw=io.BytesIO()
        with ZipFile(raw,"w") as z:
            for name,obj in f.items():z.writestr(name,e.canonical(obj))
            z.writestr("stem-agnews-source.json",b'{}')
        blob=raw.getvalue()
        with self.assertRaises(e.Invalid):
            e.verify(p,blob,approved_panel_sha=e.digest(e.canonical(p)),
                     approved_archive_sha=e.digest(blob))
    def test_zip_path_traversal(self):
        p,f=fixture();raw=io.BytesIO()
        with ZipFile(raw,"w") as z:
            for name,obj in f.items():z.writestr(name,e.canonical(obj))
            z.writestr("../source.json",b'{}')
        blob=raw.getvalue()
        with self.assertRaises(e.Invalid):
            e.verify(p,blob,approved_panel_sha=e.digest(e.canonical(p)),
                     approved_archive_sha=e.digest(blob))

    def test_training_entry_refuses_changed_public_selection_before_weights(self):
        import tempfile,sys
        from pathlib import Path
        from unittest.mock import patch
        import e1_public_triplet_real_cpu as runner
        p,_=fixture()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);panel=root/"case.json";panel.write_bytes(e.canonical(p))
            argv=["e1_public_triplet_real_cpu","--panel",str(panel),"--model","granite_97m_r2",
                  "--compact-checkout",str(root/"fake-weights"),"--output",str(root/"out.json")]
            with patch.object(sys,"argv",argv),patch.object(runner,"encode_pretrained",side_effect=AssertionError("should not load weights")):
                with self.assertRaisesRegex(runner.Invalid,"source selection differs"):
                    runner.main()
    def test_independent_numeric_entry_refuses_changed_selection(self):
        import tempfile,sys
        from pathlib import Path
        from unittest.mock import patch
        import e1_public_triplet_review as reviewer
        p,_=fixture()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);panel=root/"case.json";panel.write_bytes(e.canonical(p))
            argv=["e1_public_triplet_review","--panel",str(panel),
                  "--granite-97m-r2","g.json","--mmbert-small","m.json",
                  "--embeddinggemma-2-text","e.json","--output",str(root/"out.json")]
            with patch.object(sys,"argv",argv),patch.object(reviewer,"read",side_effect=lambda path:p if Path(path)==panel else {}):
                with self.assertRaisesRegex(reviewer.Invalid,"not the preregistered"):
                    reviewer.main()
    def test_historical_reference_entry_refuses_changed_source(self):
        import tempfile,sys
        from pathlib import Path
        from unittest.mock import patch
        import e1_public_laya_reference as ref
        p,_=fixture()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);panel=root/"case.json";panel.write_bytes(e.canonical(p))
            for n in ("g","m","e"):
                (root/(n+".json")).write_text("{}")
            argv=["e1_public_laya_reference","--panel",str(panel),
                  "--historical-laya-zip",str(root/"fake.zip"),
                  "--granite-97m-r2",str(root/"g.json"),"--mmbert-small",str(root/"m.json"),
                  "--embeddinggemma-2-text",str(root/"e.json"),"--output",str(root/"out.json")]
            with patch.object(sys,"argv",argv):
                with self.assertRaisesRegex(ref.Invalid,"changed source panel"):
                    ref.main()

if __name__=="__main__":
    unittest.main()
