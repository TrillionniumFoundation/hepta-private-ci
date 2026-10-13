"""Native transport/optimization tests; all weights and data here are fixtures.

Real pretrained acceptance is a separate explicit archived-weight execution.
"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import torch
from torch import nn
from safetensors.torch import save_file

import five_causal_experiments as c
import five_causal_native as n
from experiments.shared_stem_cell.execution import Head, parameters


class ToyEncoder:
    """Deliberately a patched test constructor, never a runtime fallback."""
    simulated = False  # Exercises constructor checks, NOT a real model claim.
    loads = 0

    def __init__(self, root, manifest, maximum_tokens):
        type(self).loads += 1
        self.root, self.manifest = root, manifest
        self.loaded = nn.Linear(4, 4, bias=False).eval()
        with torch.no_grad():
            self.loaded.weight.copy_(torch.eye(4))
        self.loaded.requires_grad_(False)
        self.model = self.loaded
        self.forward_calls = 0

    def encode(self, texts):
        self.forward_calls += 1
        with torch.no_grad():
            return self.model(torch.tensor([[float(len(t)%5), 1., 0., 1.] for t in texts]))

    def close(self):
        return None


def request(text="fixture request"):
    return {"question": text, "options": ["no", "yes"], "evidence": []}


def put(root, manifest):
    digest = c.digest(manifest)
    (root/"bundles").mkdir(exist_ok=True)
    (root/"bundles"/(digest+".json")).write_bytes(c.canonical(manifest))
    return digest


def fixture(root, *, cell="one", sharing="shared"):
    model = Head(4, 2, "gated", 4).eval()
    path = root / (cell+".safetensors")
    save_file(model.state_dict(), str(path))
    snapshot = {"files": {"tokenizer.json": "a"*64, "model.safetensors": "b"*64},
                "kind": "encoder", "revision": "a"*40}
    bindings = {k: c.digest(k) for k in c.BINDINGS}
    bindings["encoder"] = c.digest(snapshot)
    bindings["tokenizer"] = n.tokenizer_binding(snapshot)
    bindings["preprocessor"] = c.digest("five-native.public-json.mean-pool.v1")
    manifest = {"schema": n.SCHEMA, "kind": "head", "sharing": sharing,
                "scope": "fixture", "purpose": "unit-test", "generation": "one", "cell": cell,
                "model_path": "model", "snapshot": snapshot, "maximum_tokens": 64,
                "bindings": bindings, "head": {"path": path.name, "sha256": c.file_sha(path),
                    "kind": "gated", "width": 4, "classes": 2, "rank": 4}}
    packet = {"request": request(), "checkpoint_sha256": put(root, manifest),
              "bindings": bindings, "timeout_seconds": 2}
    return manifest, packet


class NativeSessionTests(unittest.TestCase):
    def setUp(self):
        ToyEncoder.loads = 0

    def test_real_constructor_absence_is_error_not_toy_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); _, packet = fixture(root)
            with self.assertRaises((ValueError, OSError, ImportError)):
                n.NativeSession(root).answer(packet)

    def test_two_shared_cells_load_one_model_and_two_heads(self):
        with tempfile.TemporaryDirectory() as d, patch.object(n, "LocalEncoder", ToyEncoder):
            root = Path(d); _, a = fixture(root, cell="a"); _, b = fixture(root, cell="b")
            session = n.NativeSession(root)
            for packet in (a,b):
                result = session.answer(packet, arm="shared")
                c.validate_result(result,c.digest(packet))
                self.assertEqual(result["resources"]["model_calls"],1)
                self.assertIsNone(result["resources"]["active_flops"])
            summary = session.close()
            self.assertEqual(ToyEncoder.loads,1)
            self.assertEqual(summary["resident_heads"],2)

    def test_replicated_cells_really_have_two_loaded_models(self):
        with tempfile.TemporaryDirectory() as d, patch.object(n, "LocalEncoder", ToyEncoder):
            root=Path(d);_,a=fixture(root,cell="a",sharing="replicated");_,b=fixture(root,cell="b",sharing="replicated")
            session=n.NativeSession(root)
            session.answer(a);session.answer(b)
            self.assertEqual(session.close()["resident_model_objects"],2)

    def test_comparison_arms_do_not_share_warm_cache(self):
        with tempfile.TemporaryDirectory() as d, patch.object(n,"LocalEncoder",ToyEncoder):
            root=Path(d);_,p=fixture(root)
            session=n.NativeSession(root,cache_bytes=1024)
            for arm in ("frozen","trained"):
                self.assertEqual(session.answer(p,arm=arm)["resources"]["model_calls"],1)
            self.assertEqual(ToyEncoder.loads,2)

    def test_exact_features_can_be_reused_with_bounded_storage(self):
        with tempfile.TemporaryDirectory() as d, patch.object(n,"LocalEncoder",ToyEncoder):
            root=Path(d);_,p=fixture(root)
            session=n.NativeSession(root,cache_bytes=16)
            first=session.answer(p);second=session.answer(p)
            self.assertEqual(first["answer"],second["answer"])
            self.assertEqual(second["resources"]["model_calls"],0)
            self.assertEqual(session.close()["cache_tensor_bytes"],16)

    def test_question_changes_require_new_forward(self):
        with tempfile.TemporaryDirectory() as d, patch.object(n,"LocalEncoder",ToyEncoder):
            root=Path(d);_,p=fixture(root)
            session=n.NativeSession(root,cache_bytes=16);session.answer(p)
            q=deepcopy(p);q["request"]["question"]="different"
            self.assertEqual(session.answer(q)["resources"]["model_calls"],1)

    def test_wrong_checkpoint_digest_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);_,p=fixture(root);p["checkpoint_sha256"]="f"*64
            with self.assertRaises(c.Invalid): n.NativeSession(root).answer(p)

    def test_packet_binding_drift_rejected_before_model_load(self):
        with tempfile.TemporaryDirectory() as d, patch.object(n,"LocalEncoder",ToyEncoder):
            root=Path(d);_,p=fixture(root);p=deepcopy(p);p["bindings"]["prompt"]="f"*64
            with self.assertRaises(c.Invalid):n.NativeSession(root).answer(p)
            self.assertEqual(ToyEncoder.loads,0)

    def test_media_does_not_silently_become_text(self):
        with tempfile.TemporaryDirectory() as d, patch.object(n,"LocalEncoder",ToyEncoder):
            root=Path(d);_,p=fixture(root)
            p["request"]["evidence"]=[{"id":"video","modality":"video","text":"","asset_sha256":"c"*64,"position":0}]
            with self.assertRaises(c.Invalid):n.NativeSession(root).answer(p)
            self.assertEqual(ToyEncoder.loads,0)

    def test_gold_and_arm_fields_cannot_reach_native_model(self):
        with tempfile.TemporaryDirectory() as d, patch.object(n,"LocalEncoder",ToyEncoder):
            root=Path(d);_,p=fixture(root);p["gold_answer"]="yes"
            with self.assertRaises(c.Invalid):n.NativeSession(root).answer(p)
            self.assertEqual(ToyEncoder.loads,0)

    def test_modified_head_file_rejected(self):
        with tempfile.TemporaryDirectory() as d, patch.object(n,"LocalEncoder",ToyEncoder):
            root=Path(d);m,p=fixture(root)
            (root/m["head"]["path"]).write_bytes(b"tampered")
            with self.assertRaises(c.Invalid):n.NativeSession(root).answer(p)

    def test_cached_head_does_not_bypass_modified_bytes(self):
        with tempfile.TemporaryDirectory() as d, patch.object(n,"LocalEncoder",ToyEncoder):
            root=Path(d);m,p=fixture(root);session=n.NativeSession(root)
            session.answer(p)
            (root/m["head"]["path"]).write_bytes(b"tampered after load")
            with self.assertRaises(c.Invalid):session.answer(p)

    def test_active_base_cannot_be_mutated_by_head_inference(self):
        with tempfile.TemporaryDirectory() as d, patch.object(n,"LocalEncoder",ToyEncoder):
            root=Path(d);_,p=fixture(root);session=n.NativeSession(root)
            session.answer(p);base=next(iter(session.models.values())).loaded
            before=parameters(base);session.answer(p)
            self.assertEqual(before,parameters(base))
            self.assertTrue(all(not p.requires_grad for p in base.parameters()))

    def test_model_capacity_rejected_before_second_load(self):
        with tempfile.TemporaryDirectory() as d, patch.object(n,"LocalEncoder",ToyEncoder):
            root=Path(d);_,a=fixture(root,cell="a",sharing="replicated");_,b=fixture(root,cell="b",sharing="replicated")
            session=n.NativeSession(root,max_models=1);session.answer(a)
            with self.assertRaises(c.Invalid):session.answer(b)
            self.assertEqual(ToyEncoder.loads,1)

    def test_option_width_must_match_head(self):
        with tempfile.TemporaryDirectory() as d, patch.object(n,"LocalEncoder",ToyEncoder):
            root=Path(d);_,p=fixture(root);p["request"]["options"].append("maybe")
            with self.assertRaises(c.Invalid):n.NativeSession(root).answer(p)

    def test_native_stage_requires_actual_running_source_sha(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);_,p=fixture(root)
            row={**p,"implementation_sha256":"a"*64,"arm":"shared_trained_head"}
            with self.assertRaises(c.Invalid):n.native_profiles(n.NativeSession(root),[row],"sharing")

    def test_replicated_arm_cannot_use_shared_model_owner(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);_,p=fixture(root)
            row={**p,"implementation_sha256":c.file_sha(Path(n.__file__)),"arm":"replicated_full"}
            with self.assertRaises(c.Invalid):n.native_profiles(n.NativeSession(root),[row],"sharing")


class NativeTrainingTests(unittest.TestCase):
    def setUp(self):
        ToyEncoder.loads=0

    def plan(self):
        return {"schema":"hepta.five-native.training.v1","data_kind":"historical_development",
                "steps":4,"seed":13,"head_kind":"gated","model_path":"model","snapshot":{},"maximum_tokens":64,
                "rows":[{"id":"row"+str(i),"cell":"one","scope":"fixture","split":"train",
                          "request":request("fixture "+str(i)),"label":i%2} for i in range(8)]}

    def test_real_torch_optimizer_changes_head_and_preserves_base(self):
        with tempfile.TemporaryDirectory() as d,patch.object(n,"LocalEncoder",ToyEncoder):
            root=Path(d);report=n.train_heads(self.plan(),root,root/"trained")
            self.assertTrue(report["base_unchanged"])
            self.assertEqual(report["encoder_forward_calls"],1)
            models=report["cells"][0]["models"]
            self.assertNotEqual(models["trained"]["sha256"],models["frozen"]["sha256"])
            self.assertIsNone(report["future_task_gain"])
            self.assertFalse(report["production_accepted"])

    def test_future_rows_rejected_before_optimization(self):
        p=self.plan();p["rows"][0]["split"]="confirmation"
        with tempfile.TemporaryDirectory() as d,patch.object(n,"LocalEncoder",ToyEncoder):
            with self.assertRaises(c.Invalid):n.train_heads(p,Path(d),Path(d)/"out")
            self.assertEqual(ToyEncoder.loads,0)

    def test_cross_scope_pooling_rejected(self):
        p=self.plan();p["rows"][0]["scope"]="another"
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(c.Invalid):n.train_heads(p,Path(d),Path(d)/"out")

    def test_duplicate_training_rows_rejected(self):
        p=self.plan();p["rows"].append(p["rows"][0])
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(c.Invalid):n.train_heads(p,Path(d),Path(d)/"out")

    def test_class_meanings_must_not_change_by_row(self):
        p=self.plan();p["rows"][0]["request"]["options"].reverse()
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(c.Invalid):n.train_heads(p,Path(d),Path(d)/"out")

    def test_missing_training_model_fails_without_mock_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises((ValueError,ImportError,OSError)):
                n.train_heads(self.plan(),Path(d),Path(d)/"out")

    def test_training_cannot_overwrite_existing_result(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            with self.assertRaises(FileExistsError):n.train_heads(self.plan(),root,root)


class ExactChatTokenTests(unittest.TestCase):
    def backend(self, capacity=16):
        class Tokenizer:
            eos_token_id=9
            def __call__(self,*args,**kwargs):
                raise AssertionError("chat tokenized twice")
            def apply_chat_template(self,messages,*,tokenize,add_generation_prompt):
                assert tokenize is True and add_generation_prompt is True
                assert len(messages)==2
                return [1,2,3]
            def decode(self,tokens,**kwargs):
                return "fixture answer"
        class Model:
            config=SimpleNamespace(max_position_embeddings=capacity,is_encoder_decoder=False)
            calls=0
            def generate(self,**kwargs):
                self.calls+=1
                assert kwargs["input_ids"].tolist()==[[1,2,3]]
                assert kwargs["do_sample"] is False and kwargs["num_beams"]==1
                return torch.cat([kwargs["input_ids"],torch.tensor([[8,9]])],dim=1)
        return SimpleNamespace(tokenizer=Tokenizer(),loaded=Model())

    def test_chat_template_ids_are_used_without_retokenization(self):
        backend=self.backend()
        answer,receipt=n.generate_exact(backend,"public",8,2)
        self.assertEqual(answer,"fixture answer")
        self.assertEqual(receipt["input_tokens"],3)
        self.assertEqual(receipt["generated_tokens"],2)
        self.assertEqual(backend.loaded.calls,1)

    def test_full_position_budget_checked_before_generation(self):
        backend=self.backend(capacity=4)
        with self.assertRaises(c.Invalid):n.generate_exact(backend,"public",8,2)
        self.assertEqual(backend.loaded.calls,0)

    def test_no_silent_prompt_truncation(self):
        backend=self.backend()
        with self.assertRaises(c.Invalid):n.generate_exact(backend,"public",2,2)
        self.assertEqual(backend.loaded.calls,0)

    def test_changed_causal_prefix_rejected(self):
        backend=self.backend()
        backend.loaded.generate=lambda **kwargs:torch.tensor([[4,5,6,9]])
        with self.assertRaises(c.Invalid):n.generate_exact(backend,"public",8,2)

    def test_decoder_output_overrun_rejected(self):
        backend=self.backend()
        with self.assertRaises(c.Invalid):n.generate_exact(backend,"public",8,1)


if __name__ == "__main__":
    unittest.main()
