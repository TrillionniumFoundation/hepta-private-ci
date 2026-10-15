"""Actual original source/manifest tests for V7.4 portability, no fabricated Encoder."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile
import sys
from unittest.mock import patch

import bridge_portable_v74 as p

ROOT = Path(os.getenv("HEPTA_V74_ARCHIVES", "/mnt/data/hepta_research_material"))
PATHS = {
    "v4":ROOT / "hepta_token_evidence_ndu_v4_20261015.zip",
    "v5":ROOT / "hepta_binding_learning_v5_20261015.zip",
    "v6":ROOT / "hepta_bridge_learning_v6_20261015.zip",
}


class SourceIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not all(f.is_file() for f in PATHS.values()):
            raise RuntimeError("Required original archive files absent; never skip as success")
        cls.material = p.originals(**PATHS)

    def test_real_archives_byte_exact_and_sealed(self):
        for key in ("v4","v5","v6"):
            self.assertEqual(self.material["archive"][key]["sha256"],p.ZIPS[key])
        self.assertEqual(self.material["archive"]["v6"]["member_count"],212)
        self.assertEqual(self.material["archive"]["v4"]["member_count"],313)
        self.assertEqual(self.material["archive"]["v5"]["member_count"],61)

    def test_experiment_provenance_chain(self):
        a=self.material["archive"]
        self.assertEqual(a["v4_design_sha256"],"cdefd9c8576af2fd45dcbfb61bb6f3041a7dbe1a6e87433a705817476ae10d21")
        self.assertEqual(a["v5_design_sha256"],"f443f6b2c211c248254945ea99fe24ffb8baf4b0709a92f5f2d998f723fec8df")
        self.assertEqual(a["v6_design_sha256"],"5880398dd5cc15c59cf592477ef93968c16f513fdde9a98ef6d11af64dcc63e5")

    def test_all_real_train_and_tune_case_counts(self):
        self.assertEqual(len(self.material["source"]["reader_train"]),128)
        self.assertEqual(len(self.material["natural"]["train"]),3909)
        self.assertEqual(len(self.material["natural"]["tune"]),827)
        self.assertEqual(len(self.material["source"]["internal_tune"]),64)
        self.assertTrue(all(x["source_split"]=="train" for x in self.material["natural"]["train"]))

    def test_original_three_pretrained_model_identity(self):
        for seed in p.SEEDS:
            self.assertEqual(len(self.material["warmup"][seed]["execution_parameter_sha256"]),64)
            self.assertEqual(len(self.material["warmup"][seed]["model_file_sha256"]),64)
            self.assertEqual(self.material["plans"][seed]["updates"],500)
            self.assertEqual(len(self.material["plans"][seed]["binding_batches"]),500)

    def test_original_model_material_is_not_hallucinated(self):
        self.assertEqual(self.material["model"]["model_id"],p.MODEL_ID)
        self.assertEqual(self.material["model"]["revision"],p.REVISION)
        self.assertEqual(self.material["model"]["files"]["model.safetensors"],194889568)
        self.assertEqual(self.material["model"]["sha256"]["model.safetensors"],"f3ea88b230492811046145513710e76b4cc8c2ad49e8708da0e7247e548903be")

    def test_original_source_order_enforced(self):
        plan=self.material["plans"][41]
        self.assertEqual(plan["natural_case_ids"],[p.source_id(x) for x in self.material["natural"]["train"]])
        self.assertEqual(plan["binding_case_ids"],[p.source_id(x) for x in self.material["source"]["reader_train"]])
        self.assertEqual(plan["plan_sha256"],p.sha(p.canonical({k:v for k,v in plan.items() if k!="plan_sha256"})))

    def test_missing_model_is_blocked_not_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            r=p.material_preflight(d,self.material["model"])
            self.assertFalse(r["ready"])
            self.assertIn("model.safetensors",r["missing"])
            self.assertIn("material.json",r["missing"])
            self.assertFalse(r["issuer_signature_verified"])

    def test_forged_model_short_material_denied(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/"config.json").write_text("attacker")
            with self.assertRaisesRegex(ValueError,"pinned actual Granite file differs"):
                p.material_preflight(d,self.material["model"])

    def test_symlink_to_checkpoint_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/"actual").write_text("attacker")
            (Path(d)/"model.safetensors").symlink_to("actual")
            r=p.material_preflight(d,self.material["model"])
            self.assertFalse(r["ready"])
            self.assertIn("model.safetensors",r["missing"])

    def test_given_but_incomplete_cache_blocks_exact_mode(self):
        with tempfile.TemporaryDirectory() as d:
            z=p.cache_preflight(d,self.material["v5_cache_sha256"])
            self.assertFalse(z["exact"])
            self.assertEqual(set(z["missing"]),{"metadata.json","tokens.pt"})

    def test_changed_cache_metadata_denied(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/"metadata.json").write_text("{}")
            with self.assertRaisesRegex(ValueError,"TokenBank differs"):
                p.cache_preflight(d,self.material["v5_cache_sha256"])

    def test_canonical_source_id_separates_candidates(self):
        row=self.material["source"]["reader_train"][0]
        alter=copy.deepcopy(row)
        alter["answer_id"]="CHANGED"
        self.assertNotEqual(p.source_id(row),p.source_id(alter))

    def test_duplicate_ids_refused(self):
        cases=copy.deepcopy(self.material["source"]["reader_train"])
        cases[1]=copy.deepcopy(cases[0])
        with self.assertRaisesRegex(ValueError,"duplicate"):
            p._unpack_rows(cases,128,"binding")

    def test_unregistered_annotation_field_refused(self):
        cases=copy.deepcopy(self.material["source"]["reader_train"])
        cases[0]["private_oracle_label"]="attack"
        with self.assertRaisesRegex(ValueError,"unregistered case fields"):
            p._unpack_rows(cases,128,"binding")

    def test_duplicate_json_key_denied(self):
        with self.assertRaisesRegex(ValueError,"duplicate JSON"):
            json.loads('{"x":1,"x":2}',object_pairs_hook=p._no_dups)

    def test_archived_absolute_paths_not_used_as_output_path(self):
        self.assertTrue(self.material["design"]["historical_baselines"]["41"]["folder"].startswith("/workspace/"))
        self.assertNotIn("/workspace/",p.canonical(p.preflight(**PATHS,snapshot=Path('/does-not-exist'))).decode())

    def test_refuse_one_byte_archive_mutation(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"bad.zip"
            blob=PATHS["v6"].read_bytes()
            path.write_bytes(blob[:-1]+bytes([blob[-1]^1]))
            with self.assertRaisesRegex(ValueError,"immutable full original archive SHA changed"):
                p._checked_archive(path,p.V6_SHA)

    def test_train_command_refuses_absent_model_without_output(self):
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/"must-not-exist"
            args=["bridge_portable_v74.py","train","--v4",str(PATHS["v4"]),
                  "--v5",str(PATHS["v5"]),"--v6",str(PATHS["v6"]),
                  "--snapshot",str(Path(d)/"NO_REAL_ENCODER"),"--output",str(target)]
            with patch.object(sys,"argv",args), self.assertRaisesRegex(ValueError,"real pretrained material absent"):
                p.main()
            self.assertFalse(target.exists())

    def test_archive_semantics_not_automatic_model_selection(self):
        with tempfile.TemporaryDirectory() as d:
            r=p.preflight(**PATHS,snapshot=d)
            self.assertEqual(r["status"],"BLOCKED_MODEL_MATERIAL")
            self.assertEqual(r["experiment_identity"],"new_source_locked_reencoding")
            self.assertFalse(r["production_authorized"])
            self.assertFalse(r["cell_split_authorized"])
            self.assertFalse(r["new_v74_training_performed"])


if __name__=="__main__":
    unittest.main()
