"""Composed Reader tests: tiny random model and supervision are FIXTURES.

Actual PEFT optimization, saving, reloading, generation and mutation checks;
no pretrained Reader result, independent review, natural data or efficacy claim.
"""
from copy import deepcopy
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import torch
from safetensors.torch import load_file, save_file

import five_causal_experiments as c
import five_causal_native as n
import five_reader_adapter as a
from five_reader_response_learning import fit_response_adapter
import test_five_reader_response as response_fixtures
from test_five_causal_native import put


class FixtureTokenizer(response_fixtures.Tokenizer):
    eos_token_id = 2
    def decode(self, tokens, **kwargs):
        return "fixture generated ids " + ",".join(map(str, tokens.tolist()))


class FixtureReader:
    simulated = False  # Patched test constructor; NEVER a runtime fallback.
    loads = 0
    def __init__(self, root, snapshot, maximum_tokens):
        type(self).loads += 1
        source = response_fixtures.NativeAdapterTests().backend()
        self.loaded = source.loaded
        self.tokenizer = FixtureTokenizer()
        self.model = self.loaded.base_model
        self.root, self.manifest = root, snapshot
    def close(self):
        pass


def base_manifest():
    snapshot = {"kind": "causal_lm", "revision": "a"*40,
                "files": {"model.safetensors": "a"*64, "tokenizer.json": "b"*64}}
    bindings = {k: c.digest(k) for k in c.BINDINGS}
    bindings.update(n.reader_bindings(snapshot, FixtureTokenizer.chat_template, 64, 4))
    return {"schema": n.SCHEMA, "kind": "reader", "sharing": "shared",
            "scope": "fixture", "purpose": "test", "generation": "one", "cell": "a",
            "snapshot": snapshot, "model_path": "model", "maximum_tokens": 64,
            "maximum_new_tokens": 4, "bindings": bindings}


class CompositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.material = tempfile.TemporaryDirectory()
        backend = FixtureReader(Path(cls.material.name), base_manifest()["snapshot"], 64)
        cls.receipt = fit_response_adapter(backend, response_fixtures.examples(), Path(cls.material.name)/"candidate", epochs=1)
        cls.trained = backend.loaded

    @classmethod
    def tearDownClass(cls):
        cls.material.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        shutil.copytree(Path(self.material.name)/"candidate", self.root/"candidate")
        self.base = base_manifest()
        self.composed = a.compose(self.root, self.base, "candidate/adapter", "candidate/training-receipt.json")
        FixtureReader.loads = 0

    def tearDown(self):
        self.tmp.cleanup()

    def packet(self, manifest=None):
        m = self.composed if manifest is None else manifest
        return {"request": {"question": "Fixture?", "options": [], "evidence": []},
                "checkpoint_sha256": put(self.root, m), "bindings": deepcopy(m["bindings"]),
                "timeout_seconds": 10}

    def session(self):
        return n.NativeSession(self.root)

    def mutate_candidate(self, relative, change):
        path = self.root/relative
        value = c.load(path); change(value)
        path.write_bytes(c.canonical(value))

    def variant_copy(self, *, bind_new_tensors=True):
        """A fixture-only alternative, not a forged real training receipt.

        Safetensors CPU tensors may reference the loaded file. Never truncate
        that inode while serializing tensors derived from it. Materialize owned
        tensors, save a NEW file, verify all bytes/tensors, then replace the copy.
        """
        original = self.root/"candidate/adapter/adapter_model.safetensors"
        original_file_sha = c.file_sha(original)
        shutil.copytree(self.root/"candidate", self.root/"candidate2")
        path = self.root/"candidate2/adapter/adapter_model.safetensors"
        tensors = {k: v.detach().clone().contiguous() for k, v in load_file(str(path)).items()}
        before = a.state_digest(tensors)
        key = sorted(tensors)[0]
        tensors[key].add_(.01)
        expected = a.state_digest(tensors)
        self.assertNotEqual(before, expected)
        temporary = self.root/"candidate2/replacement.safetensors"
        save_file(tensors, str(temporary))
        restored = load_file(str(temporary))
        self.assertEqual(a.state_digest(restored), expected)
        self.assertEqual(set(restored), set(tensors))
        self.assertTrue(all(torch.equal(restored[k], tensors[k]) for k in tensors))
        temporary.replace(path)
        self.assertEqual(a.state_digest(load_file(str(path))), expected)
        self.assertEqual(c.file_sha(original), original_file_sha)
        receipt_path = self.root/"candidate2/training-receipt.json"
        receipt = c.load(receipt_path)
        if bind_new_tensors:
            receipt["adapter_tensor_sha256"] = expected
        receipt["files"]["adapter/adapter_model.safetensors"] = c.file_sha(path)
        receipt_path.write_bytes(c.canonical(receipt))
        return a.compose(self.root, self.base, "candidate2/adapter", "candidate2/training-receipt.json")

    def test_base_binding_stays_byte_compatible(self):
        self.assertEqual(n.reader_bindings(self.base["snapshot"], FixtureTokenizer.chat_template, 64, 4)["reader"],
                         c.digest(self.base["snapshot"]))

    def test_composition_changes_only_schema_adapter_and_reader_identity(self):
        self.assertNotEqual(self.composed["bindings"]["reader"], self.base["bindings"]["reader"])
        self.assertEqual(self.base, base_manifest())
        for name in c.BINDINGS:
            if name != "reader":
                self.assertEqual(self.composed["bindings"][name], self.base["bindings"][name])
        self.assertEqual(n.reader_bindings(self.base["snapshot"], FixtureTokenizer.chat_template, 64, 4,
                                          self.composed["response_adapter"])["reader"], self.composed["bindings"]["reader"])

    def test_v1_never_ignores_an_adapter(self):
        bad = deepcopy(self.composed); bad["schema"] = n.SCHEMA
        with self.assertRaises(c.Invalid):
            self.session().descriptor(put(self.root, bad))

    def test_v2_requires_reader_and_adapter(self):
        for change in (lambda x: x.pop("response_adapter"), lambda x: x.update(kind="head")):
            bad = deepcopy(self.composed); change(bad)
            with self.assertRaises(c.Invalid): self.session().descriptor(put(self.root, bad))

    def test_real_trained_adapter_materializes_exactly_and_preserves_base(self):
        backend = FixtureReader(self.root, self.base["snapshot"], 64)
        result = a.attach(backend, self.root, self.composed["response_adapter"], self.base["snapshot"])
        x = torch.tensor([[1, 2, 3, 5]])
        with torch.no_grad():
            expected = self.trained(input_ids=x).logits
            observed = backend.loaded(input_ids=x).logits
        self.assertTrue(torch.equal(expected, observed))
        self.assertEqual(result["adapter_parameters"], self.receipt["trainable_parameters"])
        self.assertFalse(result["production_accepted"])
        a.verify_resident(backend)

    def test_generation_counts_actual_peft_base_forwards(self):
        with patch.object(n, "LocalTextGenerator", FixtureReader):
            owner = self.session(); result = owner.answer(self.packet())
            c.validate_result(result, result["request_sha256"])
            self.assertGreater(result["resources"]["model_calls"], 0)
            self.assertEqual(result["resources"]["model_calls"], owner.observations[0]["generated_tokens"])
            self.assertIn("owner_wall_ns_including_load_and_verification", owner.observations[0])
            self.assertEqual(owner.close()["resident_model_objects"], 1)

    def test_same_composition_two_cells_reuses_one_frozen_owner(self):
        other = deepcopy(self.composed); other["cell"] = "b"
        with patch.object(n, "LocalTextGenerator", FixtureReader):
            owner = self.session()
            owner.answer(self.packet()); owner.answer(self.packet(other))
            self.assertEqual(FixtureReader.loads, 1)
            self.assertEqual(len(owner.models), 1)
            self.assertEqual(owner.observations[0]["output_token_sha256"], owner.observations[1]["output_token_sha256"])

    def test_base_only_and_adapted_reader_never_share_owner(self):
        with patch.object(n, "LocalTextGenerator", FixtureReader):
            owner = self.session(); owner.answer(self.packet(self.base)); owner.answer(self.packet())
            self.assertEqual(FixtureReader.loads, 2)
            self.assertEqual(len(owner.models), 2)

    def test_distinct_adapter_compositions_never_alias(self):
        other = self.variant_copy()
        self.assertNotEqual(other["bindings"]["reader"], self.composed["bindings"]["reader"])
        with patch.object(n, "LocalTextGenerator", FixtureReader):
            owner = self.session(); owner.answer(self.packet()); owner.answer(self.packet(other))
            self.assertEqual(len(owner.models), 2)
            self.assertEqual(FixtureReader.loads, 2)
            self.assertEqual({b.response_adapter_spec["adapter_tensor_sha256"] for b in owner.models.values()},
                             {self.composed["response_adapter"]["adapter_tensor_sha256"],
                              other["response_adapter"]["adapter_tensor_sha256"]})
            for backend in owner.models.values():
                a.verify_resident(backend)

    def test_updated_file_hash_cannot_replace_stale_tensor_receipt(self):
        other = self.variant_copy(bind_new_tensors=False)
        backend = FixtureReader(self.root, self.base["snapshot"], 64)
        with self.assertRaisesRegex(c.Invalid, "serialized adapter tensor mismatch"):
            a.attach(backend, self.root, other["response_adapter"], self.base["snapshot"])
        self.assertFalse(hasattr(backend.loaded, "peft_config"))

    def test_reenabled_trainable_resident_is_not_silently_healed(self):
        with patch.object(n, "LocalTextGenerator", FixtureReader):
            owner = self.session(); packet = self.packet(); owner.answer(packet)
            backend = next(iter(owner.models.values()))
            with backend.loaded.disable_adapter():
                with self.assertRaises(c.Invalid): owner.answer(packet)
            self.assertTrue(any(p.requires_grad for p in backend.loaded.parameters()))
            with self.assertRaises(c.Invalid): owner.answer(packet)
            self.assertEqual(len(owner.observations), 1)
            self.assertTrue(any(p.requires_grad for p in backend.loaded.parameters()))

    def test_scope_and_replica_are_not_shared_implicitly(self):
        for field, value in (("scope", "other"), ("generation", "next"), ("purpose", "other")):
            other = deepcopy(self.composed); other[field] = value
            with patch.object(n, "LocalTextGenerator", FixtureReader):
                owner = self.session(); owner.answer(self.packet()); owner.answer(self.packet(other))
                self.assertEqual(len(owner.models), 2)
        other = deepcopy(self.composed); other.update(sharing="replicated", cell="b")
        first = deepcopy(other); first["cell"] = "a"
        with patch.object(n, "LocalTextGenerator", FixtureReader):
            owner = self.session(); owner.answer(self.packet(first)); owner.answer(self.packet(other))
            self.assertEqual(len(owner.models), 2)

    def test_old_base_only_reader_identity_rejected_before_load(self):
        bad = deepcopy(self.composed); bad["bindings"]["reader"] = self.base["bindings"]["reader"]
        with patch.object(n, "LocalTextGenerator", FixtureReader):
            with self.assertRaises(c.Invalid): self.session().answer(self.packet(bad))
            self.assertEqual(FixtureReader.loads, 0)

    def test_changed_adapter_file_rejected_even_after_cache_hit(self):
        with patch.object(n, "LocalTextGenerator", FixtureReader):
            owner = self.session(); packet = self.packet(); owner.answer(packet)
            (self.root/"candidate/adapter/adapter_model.safetensors").write_bytes(b"changed")
            with self.assertRaises(c.Invalid): owner.answer(packet)
            self.assertEqual(len(owner.observations), 1)

    def test_receipt_tampering_does_not_get_cached_exemption(self):
        with patch.object(n, "LocalTextGenerator", FixtureReader):
            owner = self.session(); packet = self.packet(); owner.answer(packet)
            self.mutate_candidate("candidate/training-receipt.json", lambda r: r.update(base_unchanged=False))
            with self.assertRaises(c.Invalid): owner.answer(packet)

    def test_missing_receipt_or_weights_is_not_base_fallback(self):
        (self.root/"candidate/training-receipt.json").unlink()
        with patch.object(n, "LocalTextGenerator", FixtureReader):
            with self.assertRaises(c.Invalid): self.session().answer(self.packet())
            self.assertEqual(FixtureReader.loads, 0)

    def test_pickle_and_symlinks_are_rejected(self):
        bad = self.root/"candidate/adapter/adapter_model.bin"; bad.write_bytes(b"not-used")
        with self.assertRaises(c.Invalid): a.validate_material(self.root, self.composed["response_adapter"], self.base["snapshot"])
        bad.unlink()
        config = self.root/"candidate/adapter/adapter_config.json"
        config.rename(config.with_suffix(".saved")); config.symlink_to(config.with_suffix(".saved"))
        with self.assertRaises(c.Invalid): a._config(self.root/"candidate/adapter") if False else a.validate_material(self.root, self.composed["response_adapter"], self.base["snapshot"])

    def test_actual_wrong_base_is_rejected(self):
        backend = FixtureReader(self.root, self.base["snapshot"], 64)
        with torch.no_grad(): next(backend.loaded.parameters()).add_(.01)
        with self.assertRaises(c.Invalid): a.attach(backend, self.root, self.composed["response_adapter"], self.base["snapshot"])
        self.assertFalse(hasattr(backend.loaded, "peft_config"))

    def test_changed_resident_adapter_and_base_are_rejected(self):
        for which in ("adapter", "base"):
            backend = FixtureReader(self.root, self.base["snapshot"], 64)
            a.attach(backend, self.root, self.composed["response_adapter"], self.base["snapshot"])
            tensor = (next(p for name, p in backend.loaded.named_parameters() if "lora_" in name)
                      if which == "adapter" else next(iter(backend.response_adapter_base_tensors.values())))
            with torch.no_grad(): tensor.add_(.01)
            with self.assertRaises(c.Invalid): a.verify_resident(backend)

    def test_disabled_adapter_is_not_the_selected_reader(self):
        backend = FixtureReader(self.root, self.base["snapshot"], 64)
        a.attach(backend, self.root, self.composed["response_adapter"], self.base["snapshot"])
        with backend.loaded.disable_adapter():
            with self.assertRaises(c.Invalid): a.verify_resident(backend)
        # Pinned PEFT 0.17.1 re-enables active LoRA gradients on context exit.
        # That is NOT a valid frozen resident. Keep rejecting it; recovery is
        # a newly loaded candidate, not automatic alteration during verification.
        self.assertTrue(any(p.requires_grad for p in backend.loaded.parameters()))
        with self.assertRaises(c.Invalid): a.verify_resident(backend)
        restored = FixtureReader(self.root, self.base["snapshot"], 64)
        a.attach(restored, self.root, self.composed["response_adapter"], self.base["snapshot"])
        a.verify_resident(restored)
        self.assertTrue(all(not p.requires_grad for p in restored.loaded.parameters()))

    def test_invalid_effective_adapter_config_is_rejected(self):
        self.mutate_candidate("candidate/adapter/adapter_config.json", lambda r: r.update(lora_alpha=99))
        with self.assertRaises(c.Invalid): a._config(self.root/"candidate/adapter")

    def test_existing_adapter_cannot_be_stacked(self):
        backend = FixtureReader(self.root, self.base["snapshot"], 64)
        a.attach(backend, self.root, self.composed["response_adapter"], self.base["snapshot"])
        with self.assertRaises(c.Invalid): a.attach(backend, self.root, self.composed["response_adapter"], self.base["snapshot"])

    def test_model_capacity_rejected_before_second_composed_load(self):
        other = deepcopy(self.composed); other["scope"] = "other"
        with patch.object(n, "LocalTextGenerator", FixtureReader):
            owner = n.NativeSession(self.root, max_models=1); owner.answer(self.packet())
            with self.assertRaises(c.Invalid): owner.answer(self.packet(other))
            self.assertEqual(FixtureReader.loads, 1)

    def test_receipt_does_not_make_a_formal_reader_review(self):
        from test_five_causal_experiments import bundle_fixture, review_fixture
        bundle = bundle_fixture(); review = review_fixture(bundle)
        with self.assertRaises(c.Invalid):
            n.admit_stage(bundle, review, c.digest(review), "ndu", self.receipt, c.digest(self.receipt))


if __name__ == "__main__":
    unittest.main()
