"""Local mechanics only: mock Encoder and indexed port are NOT native scores."""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np
import torch
import torch._dynamo  # Eager import before temporary sys.modules fake source ports.

from associative_cell import AssociativeCell, ReadQuery, sha256
from associative_text_bridge import (
    PinnedTextProjection, direct_read, prepare_experiences, source_facts,
    train_scope,
)
from associative_event_bridge import (
    PROFILE, canonical, public_inputs, read_pinned, review, run,
)


@dataclass(frozen=True)
class Doc:
    identity: str
    root: str
    scope: str
    session: str
    observed_at: str
    content: str
    assets: tuple[str, ...] = ()


class FakeTokenizer:
    def encode(self, value, add_special_tokens=True):
        return list(range(len(value.split()) + 2))


class FakeEncoder:
    """Only a deterministic fake vector port, never evidence of pretrained use."""

    def __init__(self, directory=None):
        self.identity = "fake-encoder-v1"
        self.model = types.SimpleNamespace(parameters=lambda: ())
        self.tokenizer = FakeTokenizer()
        self.truncated_inputs = 0
        self.calls = 0

    def encode(self, texts):
        self.calls += 1
        result = []
        for text in texts:
            digest = hashlib.sha256(text.encode()).digest()
            result.append([(x - 128) / 128 for x in digest[:12]])
        return np.asarray(result, dtype=np.float32)


def event(eid, entity, attribute, value, revision=1, supersedes=(), scope="case_001"):
    payload = dict(schema="hepta.controlled-event.v1", id=eid,
                   entity=entity, attribute=attribute, value=value,
                   revision=revision, supersedes=list(supersedes))
    return Doc(eid, "root_" + eid, scope, scope,
               "2026-10-01T10:00:00+00:00", json.dumps(payload, sort_keys=True))


class SourceTests(unittest.TestCase):
    def test_admitted_single_source_is_trainable_without_labels(self):
        docs = (event("event_a", "service_1", "location", "site_alpha"),
                event("event_b", "service_1", "owner", "person_beta"))
        facts, omissions = source_facts(docs)
        self.assertEqual(len(facts), 2)
        self.assertEqual(omissions["corrected_or_multi_root"], 0)
        encoder = FakeEncoder()
        projector = PinnedTextProjection(encoder, dimension=6)
        rows = prepare_experiences(facts, projector, scope="case_001")
        before_rng = torch.random.get_rng_state().clone()
        model, receipt = train_scope(rows, docs, projector, steps=80, rank=2)
        self.assertEqual(before_rng.tolist(), torch.random.get_rng_state().tolist())
        self.assertGreater(receipt["tensor_delta_squared_norm"], 0)
        self.assertEqual(model.roots, {"root_event_a", "root_event_b"})
        self.assertEqual(model.encoder_identity, projector.identity)
        self.assertNotIn(b"site_alpha", model.export())
        self.assertNotIn(b"Recorded identifier", model.export())
        prediction = direct_read(
            model, projector, "What location is associated with service_1?",
            kind="semantic", as_of=2000000000, revoked=set(),
        )
        self.assertEqual(len(prediction), 6)
        self.assertTrue(all(math.isfinite(x) for x in prediction))
        with self.assertRaises(ValueError):
            direct_read(model, projector, "question", kind="semantic",
                        as_of=2000000000, revoked={"root_event_a"})

    def test_conservative_lineage_revokes_even_an_untrained_source(self):
        d1 = event("current", "service_1", "location", "site_current")
        d2 = event("future", "service_1", "location", "site_future", 3)
        facts, _ = source_facts((d1, d2), logical_revision=2)
        self.assertEqual({f.identity for f in facts}, {"current"})
        projector = PinnedTextProjection(FakeEncoder(), dimension=6)
        rows = prepare_experiences(facts, projector, scope="case_001")
        candidate, receipt = train_scope(rows, (d1, d2), projector,
                                         steps=8, rank=2)
        self.assertEqual(candidate.roots, {"root_current", "root_future"})
        self.assertTrue(receipt["complete_inspected_scope_roots_bound"])
        self.assertEqual(receipt["candidate"], sha256(candidate.export()))
        read = ReadQuery(candidate.scope, "semantic", candidate.encoder_identity,
                         2000000000, rows[0].cue)
        with self.assertRaises(ValueError):
            candidate.read(read, revoked={"root_future"})

    def test_corrected_and_conflicting_heads_not_mislabelled_single_root(self):
        original = event("old", "service_1", "location", "site_old")
        updated = event("new", "service_1", "location", "site_new", 2, ("old",))
        facts, omissions = source_facts((original, updated))
        self.assertFalse(facts)
        self.assertEqual(omissions["corrected_or_multi_root"], 1)
        other = event("other", "service_1", "location", "site_other")
        facts, omissions = source_facts((original, other))
        self.assertFalse(facts)
        self.assertEqual(omissions["conflicting"], 1)

    def test_invalid_source_duplicate_and_untrusted_bytes(self):
        d = event("a", "x", "location", "site_a")
        wrong = (
            replace(d, root="other/escape"),
            replace(d, observed_at="2026-10-01T10:00:00"),
            replace(d, content=d.content.replace('"id": "a"', '"id": "b"')),
            replace(d, content=d.content.replace('"value": "site_a"',
                                                 '"value":"a","value":"b"')),
            replace(d, content=d.content.replace('"revision": 1', '"revision": 2.0')),
        )
        for w in wrong:
            with self.subTest(w=w), self.assertRaises(ValueError):
                source_facts((w,))
        with self.assertRaises(ValueError):
            source_facts((d, d))
        with self.assertRaises(ValueError):
            source_facts((d, replace(d, scope="another", identity="b")))
        with self.assertRaisesRegex(ValueError, "revoked"):
            source_facts((d,), revoked={d.root})

    def test_projection_pinned_cached_numerically_stable_and_no_truncation(self):
        e = FakeEncoder()
        p = PinnedTextProjection(e, dimension=6, seed=90)
        first = p.encode(["First event", "Second event", "First event"])
        self.assertEqual(first[0], first[2])
        self.assertEqual(e.calls, 1)
        self.assertEqual(p.encoded_texts, 2)
        self.assertEqual(first, p.encode(["First event", "Second event", "First event"]))
        self.assertEqual(e.calls, 1)
        second = PinnedTextProjection(FakeEncoder(), dimension=6, seed=90)
        self.assertEqual(first, second.encode(["First event", "Second event", "First event"]))
        self.assertEqual(p.identity, second.identity)
        with self.assertRaisesRegex(ValueError, "truncate"):
            p.encode(["a " * 260])
        self.assertEqual(e.calls, 1)

    def test_projection_rejects_encoder_width_drift(self):
        e = FakeEncoder()
        p = PinnedTextProjection(e, dimension=6)
        p.encode(["one"])
        def broken(_):
            return np.ones((1, 11), dtype=np.float32)
        e.encode = broken
        with self.assertRaisesRegex(ValueError, "width"):
            p.encode(["two"])

    def test_source_artifact_clean_process_no_raw_value(self):
        docs = (event("event_a", "service_1", "location", "site_alpha"),)
        p = PinnedTextProjection(FakeEncoder(), dimension=6)
        rows = prepare_experiences(source_facts(docs)[0], p, scope="case_001")
        cell, _ = train_scope(rows, docs, p, steps=12, rank=2)
        raw = cell.export()
        child_script = (
            "import json,sys; from associative_cell import AssociativeCell,ReadQuery,sha256;"
            "raw=sys.stdin.buffer.read(); obj=json.loads(raw);"
            "m=AssociativeCell.restore(raw,expected_sha256=sha256(raw),"
            "encoder_identity=obj['encoder_identity'],scope=obj['scope'],"
            "allowed_roots=set(obj['roots']),revoked=set());"
            "print(json.dumps(m.read(ReadQuery(m.scope,'semantic',m.encoder_identity,2000000000,"
            + repr(rows[0].cue) + "),revoked=set())))"
        )
        completed = subprocess.run(
            [sys.executable, "-c", child_script], input=raw,
            cwd=Path(__file__).parent, capture_output=True,
            env={**os.environ, "PYTHONPATH": str(Path(__file__).parent)+":"+
                 str(Path(__file__).parent.parent / "hepta_associative_impl")},
            check=True,
        )
        self.assertEqual(tuple(json.loads(completed.stdout)), cell.read(
            ReadQuery(cell.scope, "semantic", cell.encoder_identity, 2000000000,
                      rows[0].cue), revoked=set()
        ))


@dataclass(frozen=True)
class FakeQuestion:
    identity: str
    family: str
    scope: str
    content: str
    observed_at: str


class FakeProjection:
    def __init__(self, documents):
        self.facts = {d.identity: json.loads(d.content) for d in documents}
        self.frontier = sha256(canonical({k: v for k, v in self.facts.items()}))


class FakePolicy:
    def __init__(self, **kwargs):
        self.values = kwargs


class FakeIndex:
    def __init__(self, path, cut, revoked, *, expected_file_digest,
                 expected_encoder):
        self.path, self.cut, self.encoder = path, cut, expected_encoder
        assert sha256(path.read_bytes()) == expected_file_digest
        self.documents = self._all[path.name]

    _all = {}

    @classmethod
    def build(cls, path, documents, vectors, encoder, cut):
        path.write_bytes(b"fake-test-index")
        cls._all[path.name] = documents
        return sha256(path.read_bytes())

    def query(self, query, vector, policy, *, current_cut, revoked):
        if query.scope != self.documents[0].scope or current_cut != self.cut:
            raise ValueError("wrong source query")
        return list(self.documents), dict(
            query_ns=1, index_file_bytes=self.path.stat().st_size,
            policy=policy.values, encoder_identity=self.encoder,
        )

    def close(self):
        pass


def fake_closure(projection, lookup, candidates, *, revoked, limit=8):
    active = {k: row for k, row in projection.facts.items()
              if row["revision"] <= lookup.revision}
    obsolete = {key for row in active.values() for key in row["supersedes"]}
    heads = {k: row for k, row in active.items() if k not in obsolete}
    selected, entities = [], {lookup.entity}
    for attribute in lookup.path:
        nxt = set()
        for entity in entities:
            matching = {k: row for k, row in heads.items()
                        if row["entity"] == entity and row["attribute"] == attribute}
            if len(matching) != 1:
                return tuple(selected), dict(incomplete=True, conflicts=1)
            for key, row in matching.items():
                if key not in candidates:
                    return tuple(selected), dict(incomplete=True, conflicts=0)
                selected.append(key)
                nxt.add(row["value"])
        entities = nxt
    return tuple(selected), dict(incomplete=False, conflicts=0)


class IntegrationTests(unittest.TestCase):
    def input_bundle(self, root):
        full = root / "full"
        public = root / "public"
        full.mkdir()
        public.mkdir()
        source = []
        specs = []
        labels = []
        for i in range(16):
            scope = f"case_{i:03d}"
            eid = f"event_{i:03d}"
            value = f"site_{i:03d}"
            source.append(event(eid, "service_"+str(i), "location", value,
                                scope=scope).__dict__ | {"assets": []})
            kind = ("new_fact", "correction", "composition", "procedure")[i % 4]
            spec = dict(id=scope, phase="calibration" if i < 8 else "test",
                        kind=kind, entity="service_"+str(i), path=["location"], revision=2)
            specs.append(spec)
            labels.append(spec | dict(expected=value, support=[eid], procedure=None))
        bodies = {"sources.json": source, "questions.json": specs,
                  "labels.json": labels, "worker-receipts.json": []}
        file_hashes = {}
        for name, data in bodies.items():
            blob = json.dumps(data, sort_keys=True, indent=2).encode()
            (full / name).write_bytes(blob)
            file_hashes[name] = sha256(blob)
            if name != "labels.json":
                (public / name).write_bytes(blob)
        collection = dict(profile="fake-event-development", cases=16,
                          future_windows=0, files=file_hashes)
        for dest in (full, public):
            (dest / "collection.json").write_bytes(canonical(collection))
        return public, full

    def fake_modules(self):
        event_module = types.ModuleType("event_experience")
        event_module.SEED = "fake-event-development"
        def question(spec, observed):
            q = FakeQuestion(
                identity=spec["id"], family=spec["id"], scope=spec["id"],
                content=f"At revision 2, what location belongs to {spec['entity']}?",
                observed_at=observed,
            )
            return q, types.SimpleNamespace(entity=spec["entity"],
                                             path=tuple(spec["path"]), revision=2)
        event_module.question = question
        projection_module = types.ModuleType("event_projection")
        projection_module.EventProjection = FakeProjection
        closure_module = types.ModuleType("event_revision_closure")
        closure_module.select_current = fake_closure
        idx = types.ModuleType("index")
        idx.PersistentIndex = FakeIndex
        idx.RetrievalPolicy = FakePolicy
        native = types.ModuleType("native")
        native.Document = Doc
        native.digest = lambda x: sha256(canonical(x))
        pretrained = types.ModuleType("pretrained")
        pretrained.Encoder = FakeEncoder
        pretrained.frozen_digest = lambda _: "mock-frozen-weights"
        pretrained.file_inventory = lambda _: {"model": {"bytes": 2, "sha256": "mock"}}
        # Same identity as FakeEncoder, not the actual pretrained source pin.
        native.digest = lambda _: "fake-encoder-v1"
        return dict(event_experience=event_module, event_projection=projection_module,
                    event_revision_closure=closure_module, index=idx,
                    native=native, pretrained=pretrained)

    def test_sealed_public_generation_then_independent_review(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            public, full = self.input_bundle(root)
            self.assertFalse((public / "labels.json").exists())
            modules = self.fake_modules()
            with patch.dict(sys.modules, modules):
                collection, _, sources, queries, _, _ = public_inputs(public)
                self.assertEqual(len(sources), 16)
                self.assertEqual(len(queries), 16)
                output = root / "run"
                receipt = run(public, root, output,
                              commit="a" * 40, steps=8, rank=2, dimension=6)
                self.assertFalse(receipt["heldout_answer_file_opened"])
                self.assertTrue(receipt["pretrained_encoder_executed"])
                self.assertFalse(receipt["pretrained_reader_executed"])
                self.assertTrue((output / "journal.json").is_file())
                journal = json.loads((output / "journal.json").read_text())
                self.assertTrue(all(len(x["frozen_latent"]) == len(x["latent"])
                                    for x in journal))
                self.assertTrue(all(x["frozen_parent_sha256"]
                                    != x["frozen_control_sha256"] for x in journal))
                report = review(full, output, root / "review.json")
                self.assertTrue(report["frozen_initialization_as_matched_control"])
                self.assertIn("mean_delta_mse", report["score_by_phase"]["test"])
                self.assertEqual(report["score_by_phase"]["test"]["cases"], 8)
                self.assertEqual(report["score_by_phase"]["test"]["privileged_full_source_exact"], 8)
                self.assertEqual(report["score_by_phase"]["test"]["indexed_hybrid_exact"], 8)
                self.assertFalse(report["model_plus_reader_tested"])
                self.assertFalse(report["production_accepted"])

    def test_review_marks_missing_source_catalogue_as_coverage_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            public, full = self.input_bundle(root)
            with patch.dict(sys.modules, self.fake_modules()):
                output = root / "run"
                run(public, root, output, commit="b" * 40,
                    steps=5, rank=2, dimension=6)
                journal = json.loads((output / "journal.json").read_text())
                # Correction-like case not representable in the single-root
                # parameter catalogue. The reviewer must abstain, not fabricate.
                journal[0]["permitted_source_catalogue"] = [
                    dict(value="unrelated", vector=[0.1] * 6)
                ]
                raw = canonical(journal) + b"\n"
                (output / "journal.json").write_bytes(raw)
                manifest = json.loads((output / "manifest.json").read_text())
                manifest["journal_sha256"] = sha256(raw)
                (output / "manifest.json").write_bytes(canonical(manifest))
                reviewed = review(full, output, root / "review.json")
                self.assertEqual(
                    reviewed["score_by_phase"]["calibration"]["source_catalogue_covered"],
                    7,
                )
                self.assertFalse(reviewed["scored_rows"][0]["target_in_source_catalogue"])
                self.assertIsNone(reviewed["scored_rows"][0]["latent_mse"])
                self.assertFalse(reviewed["scored_rows"][0]["catalogue_decode_top1"])
                self.assertIsNone(reviewed["scored_rows"][0]["delta_mse"])

    def test_public_rejects_target_fields_and_tampering(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            public, full = self.input_bundle(root)
            modules = self.fake_modules()
            with patch.dict(sys.modules, modules):
                bad = json.loads((public / "questions.json").read_text())
                bad[0]["expected"] = "hidden"
                (public / "questions.json").write_text(json.dumps(bad))
                with self.assertRaisesRegex(ValueError, "digest"):
                    public_inputs(public)
                collection = json.loads((public / "collection.json").read_text())
                collection["files"]["questions.json"] = sha256(
                    (public / "questions.json").read_bytes()
                )
                (public / "collection.json").write_bytes(canonical(collection))
                with self.assertRaisesRegex(ValueError, "label-contaminated"):
                    public_inputs(public)

    def test_pinned_file_rejects_digest_and_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.json").write_text('{"a":1}')
            with self.assertRaisesRegex(ValueError, "digest"):
                read_pinned(root / "a.json", expected_sha="0" * 64)
            (root / "b.json").symlink_to(root / "a.json")
            with self.assertRaisesRegex(ValueError, "regular"):
                read_pinned(root / "b.json")


if __name__ == "__main__":
    unittest.main()
