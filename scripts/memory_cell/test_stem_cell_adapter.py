"""Runtime contract tests for the encoder LoRA boundary.

These tests deliberately use a tiny local torch module and a narrow PEFT/storage
shim. They exercise DifferentiatedEncoder without a pretrained checkpoint. The
separate transformer tests retain actual BERT/PEFT tensor integration coverage.
"""

from dataclasses import dataclass, replace
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest

import torch
from torch import nn


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _load_adapter():
    """Load the adapter against local test doubles, never a pretrained model."""
    selector_encoder = types.ModuleType("selector_encoder")

    class FrozenPairEncoder:
        def __init__(self, directory):
            raise AssertionError("the contract fixture must not load a checkpoint")

        def encode(self, query, family, pool, *, revoked):
            return "encoded", {"fixture": True}

    selector_encoder.FrozenPairEncoder = FrozenPairEncoder
    native = types.ModuleType("native")
    native.digest = _digest
    pretrained = types.ModuleType("pretrained")

    def frozen_digest(model):
        payload = json.dumps(model.base.detach().cpu().tolist(), separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    pretrained.frozen_digest = frozen_digest
    stem_cell = types.ModuleType("stem_cell")
    stem_cell.sha256 = lambda payload: hashlib.sha256(payload).hexdigest()
    peft = types.ModuleType("peft")

    class LoraConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    def get_peft_model(model, config):
        model.lora_config = config
        return model

    def get_peft_model_state_dict(model):
        return {"adapter": model.adapter.detach().clone()}

    def set_peft_model_state_dict(model, state):
        with torch.no_grad():
            model.adapter.copy_(state["adapter"])

    peft.LoraConfig = LoraConfig
    peft.get_peft_model = get_peft_model
    peft.get_peft_model_state_dict = get_peft_model_state_dict
    peft.set_peft_model_state_dict = set_peft_model_state_dict
    modules = {
        "selector_encoder": selector_encoder,
        "native": native,
        "pretrained": pretrained,
        "stem_cell": stem_cell,
        "peft": peft,
    }
    saved = {name: sys.modules.get(name) for name in modules}
    sys.modules.update(modules)
    path = Path(__file__).with_name("stem_cell_adapter.py")
    spec = importlib.util.spec_from_file_location("stem_cell_adapter_fixture", path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
    return module


class TinyModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.base = nn.Parameter(torch.tensor([1.0]), requires_grad=False)
        self.adapter = nn.Parameter(torch.tensor([0.0]))

    def forward(self, input_ids, attention_mask):
        scale = input_ids.float().sum(dim=-1, keepdim=True)
        return types.SimpleNamespace(logits=scale * self.adapter + self.base * 0)


class TinyTokenizer:
    def encode(self, question, text=None, add_special_tokens=True):
        return list(range(max(1, len(question) + (len(text) if text else 0))))

    def __call__(self, questions, texts, *, padding, truncation, return_tensors):
        del padding, truncation, return_tensors
        values = torch.tensor([[1, 0], [2, 0]], dtype=torch.long)
        return {"input_ids": values, "attention_mask": torch.ones_like(values)}


@dataclass
class Features:
    question_id: str = "q1"
    family: str = "family"
    encoder_identity: str = "parent"
    pool_digest: str = "pool"
    roots: frozenset[str] = frozenset({"root-a"})
    candidate_ids: tuple[str, ...] = ("positive", "negative")

    def validate(self, dimension):
        if dimension != 2:
            raise AssertionError("unexpected fixture dimension")


class Query:
    identity = "q1"
    observed_at = "2026-01-01"
    content = "question"


@dataclass(frozen=True)
class FixtureWindow:
    text: str
    observed_at: str = "2026-01-01"

    def identity(self):
        return self.text


class Pool:
    windows = (FixtureWindow("positive"), FixtureWindow("negative"))
    inspected = ({"root": "root-a"},)

    def seal(self):
        return "pool"

    def revalidate(self, query, revoked):
        if query.identity != "q1" or "root-a" in revoked:
            raise ValueError("withdrawn source")


@dataclass
class Row:
    features: Features
    positive_indices: tuple[int, ...] = (0,)


@dataclass
class Cut:
    question_ids: frozenset[str] = frozenset({"q1"})
    families: frozenset[str] = frozenset({"family"})
    allowed_roots: frozenset[str] = frozenset({"root-a"})
    forbidden_roots: frozenset[str] = frozenset()
    admission_digest: str = "admission"


def make_encoder(module):
    encoder = module.DifferentiatedEncoder.__new__(module.DifferentiatedEncoder)
    encoder.parent_identity = "parent"
    encoder.identity = "parent"
    encoder.dimension = 2
    encoder.tokenizer = TinyTokenizer()
    encoder.model = TinyModel()
    encoder.base_digest = module.frozen_digest(encoder.model)
    encoder.roots = set()
    encoder.frozen = False
    encoder.adapter_digest = None
    encoder.receipt = None
    encoder.quarantined = False
    return encoder


class DifferentiatedEncoderContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_adapter()

    def test_fit_updates_only_adapter_then_freezes(self):
        encoder = make_encoder(self.module)
        receipt = encoder.fit(
            (Row(Features()),),
            {"q1": Query()},
            {"q1": Pool()},
            Cut(),
            revoked=set(),
            steps=2,
        )
        self.assertTrue(encoder.frozen)
        self.assertFalse(any(p.requires_grad for p in encoder.model.parameters()))
        self.assertGreater(receipt["adapter_delta_squared_norm"], 0)
        self.assertEqual(encoder.base_digest, self.module.frozen_digest(encoder.model))
        encoder.verify_frozen()

    def test_export_restore_round_trip_preserves_identity(self):
        import tempfile

        source = make_encoder(self.module)
        source.fit(
            (Row(Features()),),
            {"q1": Query()},
            {"q1": Pool()},
            Cut(),
            revoked=set(),
            steps=2,
        )
        with tempfile.TemporaryDirectory() as directory:
            expected = source.export(Path(directory) / "source")
            restored = make_encoder(self.module)
            restored.restore_into(
                Path(directory) / "source",
                expected_metadata=expected,
                allowed_roots={"root-a"},
                revoked=set(),
            )
            self.assertEqual(restored.identity, source.identity)
            self.assertEqual(restored.tensor_bytes(), source.tensor_bytes())
            restored.verify_frozen()

    def test_restore_rejects_tamper_and_revocation(self):
        import tempfile

        source = make_encoder(self.module)
        source.fit(
            (Row(Features()),),
            {"q1": Query()},
            {"q1": Pool()},
            Cut(),
            revoked=set(),
            steps=2,
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "source"
            metadata = source.export(destination)
            (destination / "adapter.safetensors").write_bytes(b"tampered")
            with self.assertRaises(ValueError):
                make_encoder(self.module).restore_into(
                    destination,
                    expected_metadata=metadata,
                    allowed_roots={"root-a"},
                    revoked=set(),
                )
            with self.assertRaises(ValueError):
                make_encoder(self.module).restore_into(
                    destination,
                    expected_metadata=metadata,
                    allowed_roots={"root-a"},
                    revoked={"root-a"},
                )

    def test_frozen_encoder_withdraws_before_use(self):
        encoder = make_encoder(self.module)
        encoder.fit(
            (Row(Features()),),
            {"q1": Query()},
            {"q1": Pool()},
            Cut(),
            revoked=set(),
            steps=2,
        )
        with self.assertRaises(ValueError):
            encoder.encode(Query(), "family", Pool(), revoked={"root-a"})

    def test_candidate_inventory_drift_rejects_before_training(self):
        encoder = make_encoder(self.module)
        before = encoder.tensor_bytes()
        changed = replace(Features(), candidate_ids=("negative", "positive"))
        with self.assertRaises(ValueError):
            encoder.fit(
                (Row(changed),),
                {"q1": Query()},
                {"q1": Pool()},
                Cut(),
                revoked=set(),
                steps=2,
            )
        self.assertEqual(encoder.tensor_bytes(), before)


if __name__ == "__main__":
    unittest.main()
