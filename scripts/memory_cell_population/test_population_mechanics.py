"""Actual tiny-decoder transfer and dependency-balanced gradient mechanics."""

import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import torch
from peft import get_peft_model_state_dict

from parametric_model import SourceMemoryCell, adapter_digest
from parametric_owner import Frontier, ParametricOwner
from population_partition import balanced_partition, source_gradient_sketches
from population_transfer import expand_verified_parent
from pretrained import frozen_digest
import test_parametric_model as tiny_fixture


class PopulationMechanicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tiny_fixture.SourceMemoryCellTests.setUpClass()
        cls.base = tiny_fixture.SourceMemoryCellTests.base

    @classmethod
    def tearDownClass(cls):
        tiny_fixture.SourceMemoryCellTests.tearDownClass()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.facts = [
            tiny_fixture.fact("one", "red", "a"),
            tiny_fixture.fact("two", "blue", "b"),
        ]
        self.parent_path = self.directory / "parent"
        written = self.cell(4)
        written.fit_sources(self.facts, 4, 0.001, tiny_fixture.TEMPLATES)
        self.parent_manifest = written.save(self.parent_path)
        self.parent = self.cell(4)
        self.parent.load(
            self.parent_path,
            expected_manifest_sha256=self.parent_manifest,
            scope="alpha",
            allowed_roots={"a" * 64, "b" * 64},
            revoked=set(),
        )

    def tearDown(self):
        self.temporary.cleanup()

    def cell(self, rank, *, scope="alpha", base=None):
        cell = SourceMemoryCell(self.base if base is None else base, rank=rank)
        cell.reset(scope)
        return cell

    def assert_frozen_unchanged(self, cell, adapter, base):
        self.assertEqual(adapter_digest(cell.reader.model), adapter)
        self.assertEqual(frozen_digest(cell.reader.model), base)
        self.assertFalse(cell.reader.model.training)
        self.assertTrue(
            all(
                not p.requires_grad and p.grad is None
                for p in cell.reader.model.parameters()
            )
        )

    def test_expansion_preserves_products_logits_lineage_and_next_write(self):
        parent_files = {p.name: p.read_bytes() for p in self.parent_path.iterdir()}
        parent_adapter = adapter_digest(self.parent.reader.model)
        base = frozen_digest(self.parent.reader.model)
        source = {
            n: p.detach().clone()
            for n, p in get_peft_model_state_dict(self.parent.reader.model).items()
        }
        self.assertTrue(
            any(torch.count_nonzero(p) for n, p in source.items() if ".lora_B." in n)
        )
        question = "What is the color of one?"
        inputs = torch.tensor([self.parent.prompt_ids(question)], dtype=torch.long)
        with torch.no_grad():
            parent_logits = self.parent.reader.model(
                input_ids=inputs, use_cache=False
            ).logits
        target = self.cell(8)
        initial = {
            n: p.detach().clone()
            for n, p in get_peft_model_state_dict(target.reader.model).items()
        }
        destination = self.directory / "expanded"
        receipt = expand_verified_parent(
            self.parent,
            target,
            destination,
            parent_manifest_sha256=self.parent_manifest,
        )
        expanded = get_peft_model_state_dict(target.reader.model)
        for name, matrix in source.items():
            if ".lora_B." in name:
                a = name.replace(".lora_B.", ".lora_A.")
                torch.testing.assert_close(
                    expanded[name] @ expanded[a], matrix @ source[a], atol=1e-7, rtol=0
                )
                self.assertEqual(
                    torch.count_nonzero(expanded[name][:, matrix.shape[1] :]).item(), 0
                )
            else:
                torch.testing.assert_close(
                    expanded[name][matrix.shape[0] :],
                    initial[name][matrix.shape[0] :],
                    atol=0,
                    rtol=0,
                )
        with torch.no_grad():
            actual_logits = target.reader.model(
                input_ids=inputs, use_cache=False
            ).logits
        torch.testing.assert_close(actual_logits, parent_logits, atol=1e-6, rtol=1e-6)
        self.assertNotEqual(receipt["manifest_sha256"], self.parent_manifest)
        derivation = receipt["derivation"]
        self.assertEqual(
            (
                derivation["parent_manifest_sha256"],
                derivation["roots"],
                derivation["optimizer_updates"],
            ),
            (self.parent_manifest, ["a" * 64, "b" * 64], 0),
        )
        self.assertEqual(
            derivation["adapter_state_sha256"], adapter_digest(target.reader.model)
        )
        self.assertEqual(
            {p.name: p.read_bytes() for p in self.parent_path.iterdir()}, parent_files
        )
        self.assert_frozen_unchanged(self.parent, parent_adapter, base)
        self.assert_frozen_unchanged(target, derivation["adapter_state_sha256"], base)

        owner = ParametricOwner(self.directory / "owner.sqlite3")
        frontier = lambda: Frontier("alpha")
        owner.activate(
            "expanded",
            destination,
            receipt["manifest_sha256"],
            scope="alpha",
            expected_current=None,
            generation=0,
            provider=frontier,
            allowed_roots={"a" * 64, "b" * 64},
        )
        loaded = self.cell(8)

        def admit(active):
            loaded.load(
                active.directory,
                expected_manifest_sha256=active.manifest_sha256,
                scope=active.scope,
                allowed_roots=set(active.roots),
                revoked=set(),
            )
            with torch.no_grad():
                return loaded.reader.model(input_ids=inputs, use_cache=False).logits

        admitted_logits = owner.invoke("expanded", "alpha", frontier, admit)
        torch.testing.assert_close(admitted_logits, parent_logits, atol=1e-6, rtol=1e-6)
        next_write = loaded.fit_sources(
            [tiny_fixture.fact("three", "green", "c")], 1, 0.001, tiny_fixture.TEMPLATES
        )
        self.assertEqual(
            (
                next_write["inherited_roots"],
                next_write["accessed_roots"],
                next_write["roots"],
            ),
            (["a" * 64, "b" * 64], ["c" * 64], ["a" * 64, "b" * 64, "c" * 64]),
        )
        self.assertEqual(
            next_write["learned_parent_manifest_sha256"], receipt["manifest_sha256"]
        )
        self.assertEqual(next_write["initialization"], "verified_adapter")
        self.assertNotEqual(
            loaded.save(self.directory / "next-write"), receipt["manifest_sha256"]
        )
        self.assertEqual(
            {p.name: p.read_bytes() for p in self.parent_path.iterdir()}, parent_files
        )

    def test_expansion_rejects_parent_with_unsaved_postload_training(self):
        self.parent.fit_sources(
            [tiny_fixture.fact("three", "green", "c")], 1, 0.001, tiny_fixture.TEMPLATES
        )
        with self.assertRaises(ValueError):
            expand_verified_parent(
                self.parent,
                self.cell(8),
                self.directory / "invalid",
                parent_manifest_sha256=self.parent_manifest,
            )
        self.assertFalse((self.directory / "invalid").exists())

    def test_expansion_rejects_wrong_identity_rank_scope_or_base(self):
        other_base = self.directory / "other-base"
        shutil.copytree(self.base, other_base)
        config_path = other_base / "config.json"
        config = json.loads(config_path.read_text())
        config["bos_token_id"] = 17
        config_path.write_text(json.dumps(config))
        cases = [
            ("identity", self.cell(8), "0" * 64),
            ("rank", self.cell(4), self.parent_manifest),
            ("scope", self.cell(8, scope="beta"), self.parent_manifest),
            ("base", self.cell(8, base=other_base), self.parent_manifest),
        ]
        for label, target, manifest in cases:
            with self.subTest(case=label), self.assertRaises(ValueError):
                expand_verified_parent(
                    self.parent,
                    target,
                    self.directory / label,
                    parent_manifest_sha256=manifest,
                )
            self.assertFalse((self.directory / label).exists())

    def test_expansion_rejects_modified_or_previously_trained_target(self):
        modified = self.cell(8)
        with torch.no_grad():
            next(iter(get_peft_model_state_dict(modified.reader.model).values())).add_(
                1
            )
        trained = self.cell(8)
        trained.fit_sources(self.facts, 1, 0.001, tiny_fixture.TEMPLATES)
        for label, target in (("modified", modified), ("trained", trained)):
            with self.subTest(case=label), self.assertRaises(ValueError):
                expand_verified_parent(
                    self.parent,
                    target,
                    self.directory / label,
                    parent_manifest_sha256=self.parent_manifest,
                )
            self.assertFalse((self.directory / label).exists())

    def test_revoked_parent_cannot_reload_or_expand(self):
        revoked_parent = self.cell(4)
        with self.assertRaises(ValueError):
            revoked_parent.load(
                self.parent_path,
                expected_manifest_sha256=self.parent_manifest,
                scope="alpha",
                allowed_roots={"a" * 64, "b" * 64},
                revoked={"a" * 64},
            )
        self.assertTrue(revoked_parent.reader.quarantined)
        with self.assertRaises(ValueError):
            expand_verified_parent(
                revoked_parent,
                self.cell(8),
                self.directory / "revoked",
                parent_manifest_sha256=self.parent_manifest,
            )
        self.assertFalse((self.directory / "revoked").exists())

    def test_actual_gradient_sketches_are_repeatable_without_weight_updates(self):
        adapter = adapter_digest(self.parent.reader.model)
        base = frozen_digest(self.parent.reader.model)
        real_grad = torch.autograd.grad
        observed_gradients = []

        def observe_gradients(*args, **kwargs):
            gradients = real_grad(*args, **kwargs)
            observed_gradients.append([value.detach().clone() for value in gradients])
            return gradients

        with (
            patch(
                "population_partition.torch.autograd.grad",
                side_effect=observe_gradients,
            ) as backward,
            patch.object(
                self.parent.reader.model,
                "forward",
                wraps=self.parent.reader.model.forward,
            ) as forward,
            patch.object(
                torch.optim.AdamW,
                "step",
                side_effect=AssertionError("probe must not optimize"),
            ) as optimizer,
        ):
            receipt = source_gradient_sketches(
                self.parent, self.facts, tiny_fixture.TEMPLATES[0], width=16
            )
        self.assertEqual(
            (forward.call_count, backward.call_count, optimizer.call_count), (2, 2, 0)
        )
        self.assertEqual(
            (receipt["model_forwards_and_backwards"], receipt["optimizer_updates"]),
            (2, 0),
        )
        self.assertTrue(
            all(
                torch.isfinite(value).all()
                for row in observed_gradients
                for value in row
            )
        )
        self.assertTrue(
            any(
                torch.count_nonzero(value)
                for row in observed_gradients
                for value in row
            )
        )
        self.assertTrue(np.isfinite(receipt["sketches"]).all())
        self.assertTrue(np.any(receipt["sketches"]))
        self.assertGreater(receipt["input_tokens"], 0)
        self.assert_frozen_unchanged(self.parent, adapter, base)
        repeated = source_gradient_sketches(
            self.parent, self.facts, tiny_fixture.TEMPLATES[0], width=16
        )
        self.assertEqual(receipt["sketches"], repeated["sketches"])
        self.assertEqual(receipt["completion_losses"], repeated["completion_losses"])
        changed_facts = [dict(row, value="green") for row in self.facts]
        changed = source_gradient_sketches(
            self.parent, changed_facts, tiny_fixture.TEMPLATES[0], width=16
        )
        self.assertNotEqual(receipt["sketches"], changed["sketches"])
        self.assert_frozen_unchanged(self.parent, adapter, base)

    def test_gradient_failure_restores_frozen_state(self):
        adapter = adapter_digest(self.parent.reader.model)
        base = frozen_digest(self.parent.reader.model)
        wrong_scope = [self.facts[0], dict(self.facts[1], scope="beta")]
        with self.assertRaises(ValueError):
            source_gradient_sketches(
                self.parent, wrong_scope, tiny_fixture.TEMPLATES[0]
            )
        self.assert_frozen_unchanged(self.parent, adapter, base)
        real_grad = torch.autograd.grad

        def nonfinite_gradient(*args, **kwargs):
            return tuple(value * float("nan") for value in real_grad(*args, **kwargs))

        with (
            patch(
                "population_partition.torch.autograd.grad",
                side_effect=nonfinite_gradient,
            ),
            self.assertRaises(ValueError),
        ):
            source_gradient_sketches(self.parent, self.facts, tiny_fixture.TEMPLATES[0])
        self.assert_frozen_unchanged(self.parent, adapter, base)


class BalancedPartitionTests(unittest.TestCase):
    def test_dependency_balance_is_deterministic_and_gradient_responsive(self):
        groups = [name for name in "abcd" for _ in range(2)]
        first_vectors = [[1, 0]] * 4 + [[-1, 0]] * 4
        changed_vectors = [[1, 0]] * 2 + [[-1, 0]] * 2 + [[1, 0]] * 2 + [[-1, 0]] * 2
        first = balanced_partition(first_vectors, groups, seed=37)
        self.assertEqual(first, balanced_partition(first_vectors, groups, seed=37))
        changed = balanced_partition(changed_vectors, groups, seed=37)
        for result in (first, changed):
            self.assertEqual(result["cluster_sizes"], [4, 4])
            for name in set(groups):
                self.assertEqual(
                    {
                        result["slots"][i]
                        for i, group in enumerate(groups)
                        if group == name
                    },
                    {result["group_slots"][name]},
                )
        self.assertEqual(first["group_slots"]["a"], first["group_slots"]["b"])
        self.assertNotEqual(first["group_slots"]["a"], first["group_slots"]["c"])
        self.assertEqual(changed["group_slots"]["a"], changed["group_slots"]["c"])
        self.assertNotEqual(changed["group_slots"]["a"], changed["group_slots"]["b"])

    def test_sixty_four_rows_balance_whole_unequal_dependency_groups(self):
        weights = [6, 6, 6, 6, 3, 3, 1, 1] * 2
        groups = [
            f"source-{i:02d}" for i, weight in enumerate(weights) for _ in range(weight)
        ]
        sketches = [
            [1.0 if i < 8 else -1.0, 0.1]
            for i, weight in enumerate(weights)
            for _ in range(weight)
        ]
        receipt = balanced_partition(sketches, groups, seed=43)
        self.assertEqual(receipt["cluster_sizes"], [32, 32])
        self.assertEqual(len(receipt["slots"]), 64)
        for group in set(groups):
            self.assertEqual(
                len(
                    {
                        receipt["slots"][i]
                        for i, value in enumerate(groups)
                        if value == group
                    }
                ),
                1,
            )
        self.assertNotEqual(
            receipt["group_slots"]["source-00"], receipt["group_slots"]["source-08"]
        )

    def test_rejects_infeasible_balance_nonfinite_or_degenerate_input(self):
        valid = [[1, 0], [1, 0], [-1, 0], [-1, 0]]
        groups = ["a", "a", "b", "b"]
        cases = [
            (valid, ["a", "a", "a", "b"], 1),
            ([[float("nan"), 0]] + valid[1:], groups, 1),
            ([[float("inf"), 0]] + valid[1:], groups, 1),
            ([[0, 0]] * 4, groups, 1),
            (valid, ["a"] * 4, 1),
            (valid[:3], groups[:3], 1),
            (valid, groups, True),
        ]
        for vectors, names, seed in cases:
            with (
                self.subTest(vectors=vectors, groups=names, seed=seed),
                self.assertRaises(ValueError),
            ):
                balanced_partition(vectors, names, seed=seed)


if __name__ == "__main__":
    unittest.main()
