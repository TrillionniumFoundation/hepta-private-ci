"""Integration contracts for controlled semantic routing; model runs are separate."""

import base64
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from perc1 import semantic_benchmark as bench
from perc1.native import wire_bytes
from perc1.schema import Invalid, sha
from perc1.semantic_contract import extract_span, public_packet, validate_text_evidence
from perc1.semantic_data import make_panel
from perc1.semantic_policy import (
    current_candidates,
    execute,
    fit_head,
    head_scores,
    rank,
    rule_scores,
    vectors,
)


class SemanticBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "data"
        self.panel = make_panel(self.root, counts=dict(train=1, dev=1, confirmation=1))
        self.task = next(t for t in self.panel["tasks"] if t["family"] == "semantic")
        self.packet = self.task["packet"]
        self.record = self.panel["records"][self.packet["task_id"]]
        self.images, _ = bench._images(self.root, self.task, self.record)
        self.labels = {
            t["task_id"]: t
            for t in json.loads((self.root / "train-targets.json").read_bytes())
        }

    def test_private_evaluator_changes_cannot_change_public_decision(self):
        ordering = rank(self.packet, rule_scores(self.packet, self.images))
        before = execute(self.packet, ordering, bench._reader(self.root, self.record))
        labels = list(self.labels.values())
        labels[0]["answer"] = "changed-private-answer"
        labels[0]["candidate_id"] = "changed-private-target"
        (self.root / "train-targets.json").write_text(json.dumps(labels))
        after = execute(self.packet, ordering, bench._reader(self.root, self.record))
        self.assertEqual(before["answer"], after["answer"])
        self.assertEqual(before["reads"], after["reads"])
        self.assertEqual(
            ordering, rank(self.packet, rule_scores(self.packet, self.images))
        )

    def test_catalog_order_does_not_change_policy(self):
        shuffled = copy.deepcopy(self.packet)
        shuffled["captures"].reverse()
        shuffled["candidates"].reverse()
        normalized = public_packet(shuffled)
        self.assertEqual(normalized, self.packet)
        self.assertEqual(
            rule_scores(normalized, self.images), rule_scores(self.packet, self.images)
        )

    def test_read_budget_prevents_third_source_effect(self):
        target = self.labels[self.packet["task_id"]]["candidate_id"]
        ordering = [
            c["candidate_id"]
            for c in current_candidates(self.packet)
            if c["candidate_id"] != target
        ] + [target]
        called = []
        read = bench._reader(self.root, self.record)

        def counted(candidate):
            called.append(candidate)
            return read(candidate)

        result = execute(self.packet, ordering, counted)
        self.assertIsNone(result["answer"])
        self.assertEqual(called, ordering[: self.packet["read_budget"]])

    def test_terminal_number_is_exactly_cited_and_tampering_rejected(self):
        target = self.labels[self.packet["task_id"]]
        ordering = [target["candidate_id"]] + [
            c["candidate_id"]
            for c in current_candidates(self.packet)
            if c["candidate_id"] != target["candidate_id"]
        ]
        result = execute(self.packet, ordering, bench._reader(self.root, self.record))
        action = result["actions"][0]
        raw = action["raw_text"].encode()
        self.assertEqual(
            extract_span(action["evidence"], raw, "code", self.packet["captures"]),
            target["answer"],
        )
        self.assertEqual(result["answer"]["text"], target["answer"])
        with self.assertRaises(Invalid):
            validate_text_evidence(
                action["evidence"],
                raw.replace(b"code=", b"fake="),
                self.packet["captures"],
            )

    def test_temporal_change_is_observed_without_target_input(self):
        task = next(
            t
            for t in self.panel["tasks"]
            if t["family"] == "temporal" and t["split"] == "train"
        )
        packet = task["packet"]
        record = self.panel["records"][packet["task_id"]]
        images, _ = bench._images(self.root, task, record)
        result = execute(
            packet,
            rank(packet, rule_scores(packet, images)),
            bench._reader(self.root, record),
        )
        self.assertEqual(
            result["answer"]["candidate_id"],
            self.labels[packet["task_id"]]["candidate_id"],
        )

    def test_original_source_and_capture_hashes_are_enforced(self):
        path = self.root / next(iter(self.record["captures"].values()))
        path.write_bytes(path.read_bytes() + b"changed")
        with self.assertRaises(Invalid):
            bench._images(self.root, self.task, self.record)

    def test_seeded_training_has_real_distinct_reproducible_updates(self):
        rng = np.random.default_rng(55)
        x = rng.normal(size=(16, 4, 12))
        labels = x[:, :, 0].argmax(axis=1)
        a = fit_head(x, labels, seed=11, steps=12)
        b = fit_head(x, labels, seed=22, steps=12)
        again = fit_head(x, labels, seed=11, steps=12)
        self.assertEqual(a["parameters"], again["parameters"])
        self.assertNotEqual(
            a["training"]["initial_sha256"], b["training"]["initial_sha256"]
        )
        self.assertNotEqual(
            a["training"]["final_sha256"], a["training"]["initial_sha256"]
        )
        self.assertEqual(len(head_scores(a, x[0])), 4)

    def test_neural_online_path_dispatches_each_frame_and_retains_receipts(self):
        worker = SimpleNamespace(calls=0)
        embeddings = [np.zeros((4, 16))]
        x = vectors(self.packet, embeddings, "dense")
        head = fit_head(np.repeat(x[None], 2, axis=0), [0, 1], seed=5, steps=2)

        def producer(_worker, request, projection):
            _worker.calls += 1
            # Nonalphabetical fields make canonical JSON lose the wire order.
            observation = dict(
                scope_digest=[1] * 32,
                latents=[dict(values_q24=[0] * 16) for _ in request["regions"]],
                encoder_digest=[2] * 32,
            )
            return dict(
                receipt_sha256=sha(request),
                observation=observation,
                observation_sha256=sha(wire_bytes(observation)),
            )

        archive = io.BytesIO()
        with patch.object(bench, "produce", producer):
            result = bench._run_actor(
                self.root,
                self.task,
                self.record,
                worker,
                {},
                "dense",
                head,
                "unit-test-stub",
                archive,
            )
        self.assertEqual(result["encoder_calls"], len(self.packet["captures"]))
        self.assertEqual(
            len(archive.getvalue().splitlines()), len(self.packet["captures"])
        )
        self.assertEqual(result["public_packet_sha256"], sha(self.packet))
        for line in archive.getvalue().splitlines():
            item = json.loads(line)
            wire = base64.b64decode(item["native_wire_base64"], validate=True)
            self.assertEqual(sha(wire), item["native_wire_sha256"])
            self.assertEqual(sha(wire), item["receipt"]["observation_sha256"])
            self.assertEqual(json.loads(wire), item["receipt"]["observation"])
            self.assertNotEqual(wire, wire_bytes(item["receipt"]["observation"]))

    def test_priority_context_is_required_and_changes_selection(self):
        task = next(t for t in self.panel["tasks"] if t["family"] == "text_image")
        packet, record = (
            task["packet"],
            self.panel["records"][task["packet"]["task_id"]],
        )
        images, _ = bench._images(self.root, task, record)
        read = bench._reader(self.root, record)
        original = execute(packet, rank(packet, rule_scores(packet, images)), read)
        colors = set()
        for candidate in current_candidates(packet):
            fields = dict(
                line.split("=", 1)
                for line in read(candidate["candidate_id"]).decode().splitlines()
            )
            colors.add(fields["color"])
        other = next(color for color in colors if color not in packet["context"][0])
        changed = copy.deepcopy(packet)
        changed["context"] = [f"Priority color: {other}."]
        result = execute(changed, rank(changed, rule_scores(changed, images)), read)
        self.assertNotEqual(
            original["answer"]["candidate_id"], result["answer"]["candidate_id"]
        )
        changed["context"] = []
        with self.assertRaises(Invalid):
            rule_scores(changed, images)

    def test_duplicate_or_embedded_source_fields_rejected(self):
        ordering = [c["candidate_id"] for c in current_candidates(self.packet)]
        raw = bench._reader(self.root, self.record)(ordering[0])
        for bad in (raw + b"code=99999\n", raw.replace(b"color=", b"color=code=")):
            with self.assertRaises(Invalid):
                execute(self.packet, ordering, lambda candidate: bad)

    def test_panel_reproducible_and_fresh_output_required(self):
        other = make_panel(
            Path(self.temp.name) / "other", counts=dict(train=1, dev=1, confirmation=1)
        )
        self.assertEqual(other, self.panel)
        with self.assertRaises(Invalid):
            make_panel(self.root, counts=dict(train=1, dev=1, confirmation=1))


if __name__ == "__main__":
    unittest.main()
