"""Source-only Hugging Face fixture tests, no network and no pretrained loads."""
from __future__ import annotations

import copy
import unittest
from types import SimpleNamespace as S

import gate
import preflight


def good_meta(name):
    names = set(preflight.WANTED[name])
    if name.startswith("laya"):
        names.add("tokenizer/tokenizer_config.json")
    elif name == "ettin400":
        names.add("tokenizer_config.json")
    else:
        names.add("spm.model")
    entries = []
    for path in sorted(names):
        tensor = preflight.is_weight(path)
        entries.append(S(rfilename=path, size=1_500_000_000 if tensor else 100,
                         lfs={"sha256": "a"*64} if tensor else None,
                         blob_id=None if tensor else "b"*40))
    return S(sha=gate.MODELS[name][1], siblings=entries)


class PreflightTests(unittest.TestCase):
    def test_full_four_metadata_only(self):
        revmap = {v[0]: k for k, v in gate.MODELS.items()}
        def resolver(*, repo_id, revision, files_metadata):
            k = revmap[repo_id]
            self.assertEqual(revision, gate.MODELS[k][1])
            self.assertIs(files_metadata, True)
            return good_meta(k)
        result = preflight.run(resolver)
        self.assertEqual(len(result["models"]), 4)
        self.assertEqual(result["disposition"], "HOLD_NO_GO")
        self.assertIs(result["all_original_weights_downloaded"], False)
        self.assertTrue(result["models"][2]["requires_safe_weights_only_conversion"])
    def test_hub_root_gitattributes_is_not_a_model_input(self):
        # All four real pinned Hub trees include a root .gitattributes.
        for name in gate.MODELS:
            with self.subTest(name=name):
                meta=good_meta(name)
                meta.siblings.append(S(rfilename=".gitattributes", size=500,
                                       blob_id="c"*40, lfs=None))
                result=preflight.inspect_model(name, meta)
                self.assertEqual(result["other_repo_files_excluded"], 1)
                self.assertNotIn(".gitattributes", [v["filename"]
                    for v in result["selected_source_inventory"]])

    def test_duplicate_git_transport_file_denied(self):
        meta=good_meta("ettin400")
        meta.siblings += [S(rfilename=".gitattributes", size=100, blob_id="c"*40, lfs=None),
                          S(rfilename=".gitattributes", size=100, blob_id="c"*40, lfs=None)]
        with self.assertRaisesRegex(gate.Denied,"duplicate Git bookkeeping"):
            preflight.inspect_model("ettin400", meta)

    def test_unknown_hidden_path_and_hidden_nested_member_denied(self):
        for path in (".env", "tokenizer/.hidden.json", ".gitattributes/evil.bin"):
            with self.subTest(path=path):
                meta=good_meta("ettin400")
                meta.siblings.append(S(rfilename=path, size=100, blob_id="c"*40, lfs=None))
                with self.assertRaises(gate.Denied):
                    preflight.inspect_model("ettin400", meta)

    def test_wrong_sha(self):
        x = good_meta("ettin400"); x.sha = "0"*40
        with self.assertRaises(gate.Denied): preflight.inspect_model("ettin400", x)
    def test_missing_weight(self):
        x = good_meta("ettin400"); x.siblings = [v for v in x.siblings if v.rfilename != "pytorch_model.bin"]
        with self.assertRaises(gate.Denied): preflight.inspect_model("ettin400", x)
    def test_missing_lfs(self):
        x = good_meta("ettin400")
        next(v for v in x.siblings if v.rfilename == "pytorch_model.bin").lfs = None
        with self.assertRaises(gate.Denied): preflight.inspect_model("ettin400", x)
    def test_unsafe_parent_path(self):
        x = good_meta("ettin400"); x.siblings.append(S(rfilename="../weights.bin", size=500, lfs={"sha256":"a"*64}))
        with self.assertRaises(gate.Denied): preflight.inspect_model("ettin400", x)
    def test_duplicate_file(self):
        x = good_meta("ettin400"); x.siblings.append(copy.copy(x.siblings[0]))
        with self.assertRaises(gate.Denied): preflight.inspect_model("ettin400", x)
    def test_missing_tokenizer(self):
        x = good_meta("ettin400"); x.siblings = [v for v in x.siblings if "tokenizer" not in v.rfilename]
        with self.assertRaises(gate.Denied): preflight.inspect_model("ettin400", x)
    def test_missing_head_bundle(self):
        x = good_meta("openjev434"); x.siblings = [v for v in x.siblings if v.rfilename != "head.safetensors"]
        with self.assertRaises(gate.Denied): preflight.inspect_model("openjev434", x)
    def test_unbounded_weight(self):
        x = good_meta("ettin400"); next(v for v in x.siblings if v.rfilename == "pytorch_model.bin").size = preflight.MAX_WEIGHT_BYTES + 1
        with self.assertRaises(gate.Denied): preflight.inspect_model("ettin400", x)
    def test_wrong_model(self):
        with self.assertRaises(gate.Denied): preflight.inspect_model("evil", good_meta("ettin400"))
    def test_malformed_lfs(self):
        x = good_meta("ettin400"); next(v for v in x.siblings if v.rfilename == "pytorch_model.bin").lfs = {"sha256":"NO"}
        with self.assertRaises(gate.Denied): preflight.inspect_model("ettin400", x)
    def test_no_remote_code_path(self):
        r = preflight.inspect_model("laya421", good_meta("laya421"))
        self.assertIs(r["remote_code_execution_allowed"], False)
        self.assertIs(r["loaded_model_tensors_verified"], False)
    def test_laya_family_siblings_excluded_from_download(self):
        x = good_meta("laya421")
        x.siblings.append(S(rfilename="typed-decisions/model.safetensors",size=100000,lfs={"sha256":"c"*64}))
        x.siblings.append(S(rfilename="multilingual/model.safetensors",size=100000,lfs={"sha256":"c"*64}))
        r = preflight.inspect_model("laya421", x)
        self.assertEqual(r["other_repo_files_excluded"], 2)
        self.assertFalse(any("typed-decisions" in v["filename"] for v in r["selected_source_inventory"]))
    def test_missing_non_lfs_source_sha(self):
        x = good_meta("ettin400")
        next(v for v in x.siblings if v.rfilename == "config.json").blob_id = None
        with self.assertRaises(gate.Denied): preflight.inspect_model("ettin400", x)
    def test_double_counted_family_not_paid(self):
        x = good_meta("laya421")
        x.siblings.extend([S(rfilename=f"multilingual/extra{i}.safetensors",size=3*1024**3,lfs={"sha256":"f"*64}) for i in range(2)])
        r = preflight.inspect_model("laya421", x)
        self.assertLess(r["selected_total_bytes"], preflight.MAX_TOTAL_BYTES)
    def test_path_filter_refuses_remote_python_execution(self):
        for model in gate.MODELS:
            self.assertFalse(preflight.chosen(model, "trust_remote_code.py"))
            self.assertFalse(preflight.chosen(model, "../model.safetensors"))
        self.assertFalse(preflight.chosen("openjev434", "typed_decisions/loader.py"))
    def test_small_file_lfs_supported(self):
        x = good_meta("ettin400")
        obj = next(v for v in x.siblings if v.rfilename == "tokenizer.json")
        obj.lfs, obj.blob_id = {"sha256": "d"*64}, None
        r = preflight.inspect_model("ettin400", x)
        self.assertEqual(next(v for v in r["selected_source_inventory"] if v["filename"] == "tokenizer.json")["source_identity_type"], "lfs_sha256")

if __name__ == "__main__": unittest.main()
