"""Actual stock BERT safetensors + train/predict subprocess smoke.

The model is RANDOM initialized: this is physical loader provenance evidence,
not pretrained mmBERT/Granite competence, real future-task quality or NDU.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import torch

from multimodal_alignment_contract import canonical, load_pinned_document, sha
from multimodal_candidate_gate import PLAN, RESULT, validate_plan
from multimodal_pinned_candidate import host_identity, text_input_digest
from multimodal_real_encoder import PROFILE_SCHEMA
from multimodal_head import StateGatedCellHead


@unittest.skipUnless(importlib.util.find_spec("transformers"), "requires pinned HF hosted runtime")
class PhysicalPinnedCandidateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from transformers import BertConfig, BertModel, BertTokenizerFast
        cls.BertConfig = BertConfig
        cls.BertModel = BertModel
        cls.BertTokenizerFast = BertTokenizerFast
        torch.set_num_threads(1)

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.model_root = self.root / "model"
        self.model_root.mkdir()
        with torch.random.fork_rng():
            torch.manual_seed(101)
            config = self.BertConfig(
                vocab_size=18, hidden_size=16, intermediate_size=32,
                num_hidden_layers=1, num_attention_heads=4, max_position_embeddings=32,
                hidden_dropout_prob=0., attention_probs_dropout_prob=0.)
            model = self.BertModel(config).eval().requires_grad_(False)
        model.save_pretrained(self.model_root, safe_serialization=True)
        (self.model_root / "vocab.txt").write_text(
            "[PAD]\n[UNK]\n[CLS]\n[SEP]\n[MASK]\nsmall\ntest\n"
            "real\nencoder\ntext\nexample\nzero\none\ntwo\nthree\nfour\n"
            "train\nfuture\n", encoding="utf-8")
        token = self.BertTokenizerFast(vocab_file=str(self.model_root / "vocab.txt"),
                                       do_lower_case=True)
        self.assertEqual(len(token), config.vocab_size)
        token.save_pretrained(self.model_root)
        inventory = {p.relative_to(self.model_root).as_posix():sha(p.read_bytes())
                     for p in self.model_root.rglob("*") if p.is_file()}
        self.profile={"schema":PROFILE_SCHEMA,"candidate":"tiny_random",
                      "snapshot":{"revision":"a"*40,"kind":"encoder","files":inventory},
                      "expected_width":16,"maximum_tokens":32,"batch_size":4,
                      "pooling":"attention-mask-mean","normalization":"none"}
        self.profile_sha=sha(canonical(self.profile))
        self.profile_path=self.root / "profile.json"
        self.profile_path.write_bytes(canonical(self.profile))
        self.train_rows=[]
        self.future_rows=[]
        self.truth=[]
        for i in range(16):
            state=[float(i%2)]*64
            text=f"small test train {i}"
            self.train_rows.append({"case_id":f"t{i:02d}","group_id":f"train_g{i//2}",
                                    "scope":"tiny_stem","observed_at":i+1,"split":"train",
                                    "text":text,"state":state,"label":i%2})
            future_text=f"small test future {i}"
            future_state=[float((i+1)%2)]*64
            fingerprint=text_input_digest("tiny_stem",future_text,future_state)
            self.future_rows.append({"case_id":f"f{i:02d}","group_id":f"future_g{i//2}",
                                     "scope":"tiny_stem","observed_at":201+i,"split":"future",
                                     "text":future_text,"state":future_state,
                                     "input_sha256":fingerprint})
            self.truth.append({"case_id":f"f{i:02d}","group_id":f"future_g{i//2}",
                               "scope":"tiny_stem","observed_at":201+i,
                               "input_sha256":fingerprint,"label":i%2})
        features=[{k:r[k] for k in ("case_id","group_id","scope","observed_at","input_sha256")}
                  for r in self.future_rows]
        host=host_identity()
        self.plan={"schema":PLAN,"scope":"tiny_stem",
                   "train_sha256":sha(b"".join(canonical(x) for x in self.train_rows)),
                   "future_source_sha256":sha(b"".join(canonical(x) for x in features)),
                   "future_targets_sha256":sha(b"".join(canonical(x) for x in self.truth)),
                   "train_group_sha256s":sorted({sha(x["group_id"].encode()) for x in self.train_rows}),
                   "train_cutoff":100,"future_start":200,"future_end":300,
                   "classes":2,"train_steps":4,
                   "head_parameters":StateGatedCellHead(16,64,8,2).parameter_count(),
                   "seed":7,"hardware_sha256":host["hardware_sha256"],
                   "environment_sha256":host["environment_sha256"],
                   "candidates":[
                       {"name":"no_change","profile_sha256":sha(b"baseline-p"),
                        "snapshot_sha256":sha(b"baseline-w")},
                       {"name":"tiny_random","profile_sha256":self.profile_sha,
                        "snapshot_sha256":sha(canonical(self.profile["snapshot"]))}]}
        validate_plan(self.plan)
        self.plan_path=self.root / "plan.json"
        self.plan_path.write_bytes(canonical(self.plan))
        self.plan_sha=sha(canonical(self.plan))
        self.train_path=self.root / "train.jsonl"
        self.train_path.write_bytes(b"".join(canonical(x) for x in self.train_rows))
        self.future_path=self.root / "future_inputs.jsonl"
        self.future_path.write_bytes(b"".join(canonical(x) for x in self.future_rows))

    def command(self, operation, extra):
        script=Path(__file__).with_name("multimodal_pinned_candidate.py")
        base=[sys.executable,str(script),operation,"--plan",str(self.plan_path),
              "--plan-sha256",self.plan_sha,"--profile",str(self.profile_path),
              "--profile-sha256",self.profile_sha,"--candidate","tiny_random",
              "--model-snapshot",str(self.model_root)]
        env=os.environ.copy()
        env.update({"HF_HUB_OFFLINE":"1","TRANSFORMERS_OFFLINE":"1",
                    "HF_HUB_DISABLE_IMPLICIT_TOKEN":"1","TOKENIZERS_PARALLELISM":"false"})
        return subprocess.run(base+extra,env=env,capture_output=True,text=True,timeout=180)

    def trained(self):
        directory=self.root / "trained"
        p=self.command("train",["--train",str(self.train_path),
                                "--train-sha256",self.plan["train_sha256"],
                                "--output-dir",str(directory)])
        self.assertEqual(p.returncode,0,p.stderr)
        receipt_path=directory / "train_receipt.json"
        receipt_sha=sha(receipt_path.read_bytes())
        receipt=load_pinned_document(receipt_path,receipt_sha)
        return directory,receipt,receipt_sha

    def test_added_token_beyond_verified_embedding_is_rejected(self):
        from transformers import AutoTokenizer
        from execution import InputError, LocalEncoder
        tokenizer = AutoTokenizer.from_pretrained(
            self.model_root, local_files_only=True, trust_remote_code=False)
        self.assertEqual(len(tokenizer), 18)
        self.assertEqual(tokenizer.add_tokens(["brand_new_token"]), 1)
        self.assertEqual(len(tokenizer), 19)
        tokenizer.save_pretrained(self.model_root)
        files = {p.relative_to(self.model_root).as_posix(): sha(p.read_bytes())
                 for p in self.model_root.rglob("*") if p.is_file()}
        manifest = {"revision": "a" * 40, "kind": "encoder", "files": files}
        with self.assertRaisesRegex(InputError, "tokenizer vocabulary exceeds"):
            LocalEncoder(self.model_root, manifest, maximum_tokens=32)

    def test_physical_load_train_persist_reload_source_only_predict(self):
        trained, receipt, receipt_sha=self.trained()
        self.assertEqual(receipt["model_forwards"],4)
        self.assertEqual(receipt["head_parameters"],self.plan["head_parameters"])
        self.assertTrue(receipt["checkpoint_locally_verified"])
        self.assertFalse(receipt["actual_pretrained_model_proven"])
        self.assertFalse(receipt["publisher_authenticated"])
        self.assertFalse(receipt["production_accepted"])
        output=self.root / "predicted"
        p=self.command("predict",["--train-receipt",str(trained/"train_receipt.json"),
                                  "--train-receipt-sha256",receipt_sha,
                                  "--head",str(trained/"head.safetensors"),
                                  "--future-inputs",str(self.future_path),
                                  "--future-inputs-sha256",sha(self.future_path.read_bytes()),
                                  "--output-dir",str(output)])
        self.assertEqual(p.returncode,0,p.stderr)
        result_path=output/"candidate_result.json"
        result=load_pinned_document(result_path,sha(result_path.read_bytes()))
        self.assertEqual(result["schema"],RESULT)
        self.assertEqual(result["execution"]["physical_forwards"],8)
        self.assertEqual(len(result["predictions"]),16)
        self.assertTrue(all(len(r["probabilities"])==2 for r in result["predictions"]))
        self.assertTrue(all("label" not in r and "text" not in r for r in result["predictions"]))
        self.assertFalse(result["execution"]["publisher_authenticated"])
        self.assertTrue((output/"predict_evidence.json").exists())

    def test_tamper_between_train_predict_fails_with_no_candidate_result(self):
        trained,_,receipt_sha=self.trained()
        model_file=next(self.model_root/x for x in self.profile["snapshot"]["files"]
                        if x.endswith(".safetensors"))
        data=bytearray(model_file.read_bytes());data[-1]^=1;model_file.write_bytes(data)
        output=self.root/"predicted"
        p=self.command("predict",["--train-receipt",str(trained/"train_receipt.json"),
                                  "--train-receipt-sha256",receipt_sha,
                                  "--head",str(trained/"head.safetensors"),
                                  "--future-inputs",str(self.future_path),
                                  "--future-inputs-sha256",sha(self.future_path.read_bytes()),
                                  "--output-dir",str(output)])
        self.assertNotEqual(p.returncode,0)
        self.assertFalse(output.exists())


if __name__=="__main__":
    unittest.main()
