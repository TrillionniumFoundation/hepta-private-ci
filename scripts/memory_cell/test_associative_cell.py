"""Pure mechanics and negative-contract tests; not capability evidence."""

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

import torch

from associative_cell import (
    AssociativeCell, Experience, ExperimentalBank, ReadQuery,
    TrainingCut, propose_split, sha256,
)
from associative_cell_trial import fixture, run_trial


def example(kind="semantic", identity="event:a", root="source:a"):
    return Experience(
        identity=identity, scope="scope:a", family="family:a", root=root,
        kind=kind, encoder_identity="encoder:pinned", observed_at=20,
        cue=(1.0, 0.0, 0.0, 1.0),
        value=(0.0, 0.0, 1.0, 0.0),
    )


def cut():
    return TrainingCut(
        scope="scope:a", encoder_identity="encoder:pinned", through=21,
        allowed_roots=frozenset({"source:a", "source:b"}),
        allowed_families=frozenset({"family:a"}),
        forbidden_roots=frozenset({"heldout:root"}),
        forbidden_families=frozenset({"heldout:family"}),
        admission_digest="admission:mock-pinned",
    )


def query(kind="semantic", as_of=30):
    return ReadQuery("scope:a", kind, "encoder:pinned", as_of,
                     (1.0, 0.0, 0.0, 1.0))


class AssociativeCellTests(unittest.TestCase):
    def setUp(self):
        self.cell = AssociativeCell(4, 2, "encoder:pinned", "scope:a", seed=100)
        self.row = example()

    def fit(self, rows=None, **kwargs):
        return self.cell.propose_update(
            (self.row,) if rows is None else rows, cut(),
            revoked=set(), steps=100, **kwargs,
        )

    def test_parameter_memory_updates_and_parent_immutable(self):
        before = self.cell.export()
        candidate, receipt = self.fit(lr=0.3)
        self.assertEqual(self.cell.export(), before)
        self.assertNotEqual(candidate.export(), before)
        self.assertGreater(receipt["tensor_delta_squared_norm"], 0)
        self.assertFalse(receipt["production_accepted"])
        self.assertFalse(receipt["superiority_claim"])
        self.assertLess(receipt["loss_last"], receipt["loss_first"])
        self.assertEqual(candidate.steps, 100)
        self.assertEqual(candidate.roots, {"source:a"})
        self.assertEqual(receipt["persistent_optimizer_bytes"], 0)

    def test_query_contains_no_gold_or_authority(self):
        self.assertEqual(set(ReadQuery.__dataclass_fields__), {
            "scope", "kind", "encoder_identity", "as_of", "cue"
        })

    def test_candidate_update_is_deterministic_without_global_rng(self):
        torch.manual_seed(901)
        before_rng = torch.random.get_rng_state().clone()
        second = AssociativeCell(4, 2, "encoder:pinned", "scope:a", seed=100)
        self.assertTrue(torch.equal(before_rng, torch.random.get_rng_state()))
        first_candidate, _ = self.fit()
        second_candidate, _ = second.propose_update(
            (self.row,), cut(), revoked=set(), steps=100
        )
        self.assertEqual(first_candidate.export(), second_candidate.export())

    def test_encoder_kind_scope_future_read_denied(self):
        cell, _ = self.fit()
        for bad in (
            replace(query(), encoder_identity="different"),
            replace(query(), scope="scope:b"),
            replace(query(), as_of=19),
            replace(query(), kind="unregistered"),
            replace(query(), cue=(float("nan"), 0.0, 0.0, 1.0)),
        ):
            with self.assertRaises(ValueError):
                cell.read(bad, revoked=set())
        with self.assertRaisesRegex(ValueError, "revoked"):
            cell.read(query(), revoked={"source:a"})

    def test_no_grad_caller_training_and_inference_mode_rejected(self):
        with torch.no_grad():
            candidate, _ = self.fit()
        self.assertNotEqual(candidate.export(), self.cell.export())
        old = self.cell.export()
        with torch.inference_mode():
            with self.assertRaisesRegex(ValueError, "inference-mode"):
                self.fit()
        self.assertEqual(old, self.cell.export())

    def test_all_rows_validated_before_mutation(self):
        old = self.cell.export()
        invalid = (
            replace(self.row, identity="event:b", root="heldout:root"),
            replace(self.row, identity="event:b", observed_at=22),
            replace(self.row, identity="event:b", scope="other"),
            replace(self.row, identity="event:b", family="heldout:family"),
            replace(self.row, identity="event:b", value=(float("inf"), 0., 0., 0.)),
            replace(self.row, identity="event:b", cue=(True, 0., 0., 0.)),
        )
        for bad in invalid:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.fit((self.row, bad))
        with self.assertRaises(ValueError):
            self.fit((self.row, self.row))
        self.assertEqual(self.cell.export(), old)

    def test_admission_rejects_cross_scope_cuts_and_revoked(self):
        for bad in (
            replace(cut(), scope="another"),
            replace(cut(), encoder_identity="other"),
            replace(cut(), forbidden_roots=frozenset({"source:a"})),
            replace(cut(), forbidden_families=frozenset({"family:a"})),
            replace(cut(), admission_digest=""),
        ):
            with self.assertRaises(ValueError):
                self.cell.propose_update((self.row,), bad, revoked=set())
        with self.assertRaises(ValueError):
            self.cell.propose_update((self.row,), cut(), revoked={"source:a"})

    def test_kind_specific_cell_rejects_other_kind(self):
        parent = self.cell
        semantic, procedural = propose_split(parent)
        self.assertEqual(semantic.kind, "semantic")
        self.assertEqual(procedural.kind, "procedural")
        with self.assertRaises(ValueError):
            semantic.propose_update((example(kind="procedural"),), cut(), revoked=set())
        with self.assertRaises(ValueError):
            semantic.read(query(kind="procedural"), revoked=set())

    def test_split_same_parameter_budget_and_additive_reconstruction(self):
        fitted, _ = self.fit()
        a, b = propose_split(fitted)
        self.assertEqual(sum(c.parameter_count() for c in (a, b)), fitted.parameter_count())
        self.assertEqual(a.split_from, sha256(fitted.export()))
        self.assertEqual(b.split_from, a.split_from)
        self.assertEqual(a.roots, {"source:a"})
        self.assertEqual(b.roots, {"source:a"})
        cue = torch.tensor(query().cue)
        with torch.no_grad():
            torch.testing.assert_close(fitted(cue), a(cue) + b(cue), atol=1e-7, rtol=1e-6)
        with self.assertRaises(ValueError):
            b.read(query(kind="procedural"), revoked={"source:a"})

    def test_split_is_proposal_not_zero_delta_routed_equivalence(self):
        a, b = propose_split(self.cell)
        bank = ExperimentalBank((a, b))
        chosen = bank.read(query(), revoked=set())
        crossed = bank.read(query(), revoked=set(), ablation="swapped")
        self.assertNotEqual(chosen, crossed)
        with self.assertRaises(ValueError):
            bank.read(query(), revoked=set(), ablation="invalid")
        with self.assertRaises(ValueError):
            ExperimentalBank((a, a))

    def test_split_denies_incompatible_parent(self):
        single = AssociativeCell(4, 2, "encoder:pinned", "scope:a", "semantic")
        with self.assertRaises(ValueError):
            propose_split(single)
        odd = AssociativeCell(4, 3, "encoder:pinned", "scope:a")
        with self.assertRaises(ValueError):
            propose_split(odd)

    def test_restore_artifact_only_and_no_raw_vectors(self):
        fitted, _ = self.fit()
        raw = fitted.export()
        self.assertNotIn(b'"cue"', raw)
        self.assertNotIn(b'"value"', raw)
        reloaded = AssociativeCell.restore(
            raw, expected_sha256=sha256(raw), encoder_identity="encoder:pinned",
            scope="scope:a", allowed_roots={"source:a"}, revoked=set(),
        )
        self.assertEqual(fitted.read(query(), revoked=set()), reloaded.read(query(), revoked=set()))
        self.assertEqual(raw, reloaded.export())
        with self.assertRaises(ValueError):
            AssociativeCell.restore(
                raw, expected_sha256=sha256(raw), encoder_identity="encoder:pinned",
                scope="scope:a", allowed_roots={"source:a"}, revoked={"source:a"},
            )

    def test_restore_rejects_corrupt_metadata_tensors_and_duplicate_json(self):
        fitted, _ = self.fit()
        data = json.loads(fitted.export())
        for change in (
            {"schema": "unknown"},
            {"production_accepted": True},
            {"encoder_identity": "other"},
            {"scope": "wrong"},
            {"roots": ["source:a", "source:a"]},
            {"steps": -1},
            {"state": {"down": [[1.]], "up": [[2.]]}},
        ):
            value = dict(data, **change)
            raw = json.dumps(value, sort_keys=True, allow_nan=False).encode()
            with self.subTest(change=change), self.assertRaises(ValueError):
                AssociativeCell.restore(
                    raw, expected_sha256=sha256(raw), encoder_identity="encoder:pinned",
                    scope="scope:a", allowed_roots={"source:a"}, revoked=set(),
                )
        duplicate = fitted.export().replace(b'"rank":2', b'"rank":2,"rank":2')
        with self.assertRaises(ValueError):
            AssociativeCell.restore(
                duplicate, expected_sha256=sha256(duplicate),
                encoder_identity="encoder:pinned", scope="scope:a",
                allowed_roots={"source:a"}, revoked=set(),
            )
        with self.assertRaises(ValueError):
            AssociativeCell.restore(
                fitted.export(), expected_sha256="0" * 64,
                encoder_identity="encoder:pinned", scope="scope:a",
                allowed_roots={"source:a"}, revoked=set(),
            )

    def test_clean_process_artifact_only_parity(self):
        cell, _ = self.fit()
        raw = cell.export()
        code = (
            "import json,sys;from associative_cell import AssociativeCell,ReadQuery,sha256;"
            "raw=sys.stdin.buffer.read();"
            "m=AssociativeCell.restore(raw,expected_sha256=sha256(raw),"
            "encoder_identity='encoder:pinned',scope='scope:a',"
            "allowed_roots={'source:a'},revoked=set());"
            "print(json.dumps(m.read(ReadQuery('scope:a','semantic','encoder:pinned',30,"
            "(1.,0.,0.,1.)),revoked=set())))"
        )
        root = str(Path(__file__).resolve().parent)
        child = subprocess.run(
            [sys.executable, "-c", code], input=raw, capture_output=True,
            cwd=root, env={**os.environ, "PYTHONPATH": root}, check=True,
        )
        self.assertEqual(tuple(json.loads(child.stdout)), cell.read(query(), revoked=set()))

    def test_restore_accepts_realistic_unix_observation_seconds(self):
        recent = replace(self.row, observed_at=1_800_000_000)
        permitted = replace(cut(), through=1_800_000_100)
        trained, _ = self.cell.propose_update((recent,), permitted,
                                              revoked=set(), steps=2)
        raw = trained.export()
        restored = AssociativeCell.restore(
            raw, expected_sha256=sha256(raw), encoder_identity="encoder:pinned",
            scope="scope:a", allowed_roots={"source:a"}, revoked=set(),
        )
        self.assertEqual(restored.latest_observed, 1_800_000_000)
        with self.assertRaises(ValueError):
            restored.read(query(as_of=1_799_999_999), revoked=set())

    def test_incremental_lineage_revocation_inherited(self):
        first, _ = self.fit()
        row = example(identity="event:b", root="source:b")
        other, _ = first.propose_update((row,), cut(), revoked=set(), steps=20)
        self.assertEqual(other.roots, {"source:a", "source:b"})
        for root in other.roots:
            with self.assertRaises(ValueError):
                other.read(query(), revoked={root})
        self.assertEqual(first.roots, {"source:a"})

    def test_vector_and_training_limits(self):
        with self.assertRaises(ValueError):
            self.cell.propose_update((self.row,), cut(), revoked=set(), steps=3000)
        with self.assertRaises(ValueError):
            self.cell.propose_update((self.row,), cut(), revoked=set(), steps=10, lr=5)
        with self.assertRaises(ValueError):
            self.cell.read(replace(query(), cue=(0., 0.)), revoked=set())

    def test_synthetic_trial_full_accounting_and_no_promotion(self):
        data = run_trial(steps=16)
        self.assertEqual(data["trainable_parameters"]["shared"],
                         data["trainable_parameters"]["typed"])
        self.assertEqual(data["sgd_sample_updates"]["shared"],
                         data["sgd_sample_updates"]["typed"])
        self.assertEqual(data["trainable_parameter_touches_estimate"]["typed"],
                         data["trainable_parameter_touches_estimate"]["equal_touch_shared"])
        self.assertTrue(data["disjoint_source_roots"])
        self.assertTrue(data["disjoint_families"])
        self.assertFalse(data["production_qualified"])
        self.assertFalse(data["statistical_superiority"])
        self.assertFalse(data["strong_rag_comparison_executed"])
        self.assertEqual(set(data["arms"]), {
            "frozen", "same_capacity_shared", "equal_touch_shared",
            "typed_split", "swapped_type_route"
        })

    def test_fixture_has_no_gold_in_read_query(self):
        train, future, the_cut = fixture()
        self.assertFalse({r.identity for r in train} & {r.identity for r in future})
        self.assertTrue(all(r.root not in the_cut.allowed_roots for r in future))
        self.assertTrue(all(r.observed_at > the_cut.through for r in future))


if __name__ == "__main__":
    unittest.main()
