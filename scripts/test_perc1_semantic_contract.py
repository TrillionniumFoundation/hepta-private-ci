"""Counterfactual and corruption checks for the PERC semantic boundary."""

import copy
import unittest

from perc1.schema import sha
from perc1.semantic_contract import (
    extract_span,
    grid_candidates,
    neutral_capture_id,
    public_packet,
    validate_arm_budgets,
    validate_split_registry,
    validate_text_evidence,
)


def task():
    capture = dict(
        sha256=sha(b"original raster"),
        width=80,
        height=60,
        frame_index=0,
        timestamp_micros=0,
    )
    capture["capture_id"] = neutral_capture_id(capture)
    return dict(
        schema="perc1.semantic-task.v1",
        task_id="semantic-0",
        instruction="Read the code beside the red circle.",
        captures=[capture],
        grid=[2, 2],
        candidates=grid_candidates([capture], [2, 2]),
        context=["Preserve digits."],
        modalities=dict(
            image="present",
            video="missing",
            source_text="present",
            dom="unknown",
            ocr="unknown",
        ),
        read_budget=3,
    )


def text_evidence(raw, kind="source_text"):
    start = raw.index(b"42.50")
    reference = dict(
        kind="dom" if kind == "dom" else "bytes",
        origin_sha256=sha(raw),
        start=start,
        end=start + 5,
        total=len(raw),
    )
    if kind == "dom":
        reference["node_id"] = "snapshot-node-4"
    return dict(
        schema="perc1.semantic-text.v1",
        kind=kind,
        content_sha256=sha(raw),
        fidelity="source_bytes_preserved",
        spans=[
            dict(span_id="amount", start=start, end=start + 5, references=[reference])
        ],
    )


def groups():
    return [
        dict(
            task_id=split,
            split=split,
            document_group=sha([split, "document"]),
            template_group=sha([split, "template"]),
            source_group=sha([split, "source"]),
            parent_task_id=None,
        )
        for split in ("train", "dev", "confirmation")
    ]


class SemanticContractTest(unittest.TestCase):
    def test_private_counterfactual_and_public_projection(self):
        bundle = {"public": task(), "private": {"target": 0, "answer": "0042"}}
        before = public_packet(bundle["public"])
        bundle["private"] = {
            "target": 3,
            "answer": "9918",
            "rectangle": [40, 30, 40, 30],
        }
        self.assertEqual(public_packet(bundle["public"]), before)
        for field in ("private", "answer", "target_candidate_id"):
            bad = copy.deepcopy(bundle["public"])
            bad[field] = bundle["private"]
            with self.subTest(field=field), self.assertRaises(ValueError):
                public_packet(bad)
        with self.assertRaises(ValueError):
            public_packet(bundle)
        bundle["public"]["context"][0] = "Changed after dispatch"
        self.assertEqual(before["context"], ["Preserve digits."])

    def test_catalog_cannot_mark_omit_duplicate_or_focus_target(self):
        for mutation in ("mark", "omit", "duplicate", "focus"):
            bad = task()
            if mutation == "mark":
                bad["candidates"][0]["candidate_id"] = "answer"
            elif mutation == "omit":
                bad["candidates"].pop()
            elif mutation == "duplicate":
                bad["candidates"][1] = bad["candidates"][0]
            else:
                bad["candidates"][0]["rectangle"] = [0, 0, 3, 3]
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                public_packet(bad)

    def test_catalog_order_is_not_an_answer_channel(self):
        original = task()
        reordered = copy.deepcopy(original)
        reordered["candidates"].reverse()
        self.assertEqual(public_packet(original), public_packet(reordered))

    def test_missing_unknown_modalities_and_limits(self):
        missing = task()
        missing.update(captures=[], candidates=[], read_budget=0)
        missing["modalities"] = dict(
            image="missing",
            video="unknown",
            source_text="unknown",
            dom="missing",
            ocr="unknown",
        )
        self.assertEqual(public_packet(missing), missing)
        for key, value in (("read_budget", True), ("instruction", "x" * 4097)):
            bad = task()
            bad[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                public_packet(bad)
        bad = task()
        bad["modalities"]["image"] = "unknown"
        with self.assertRaises(ValueError):
            public_packet(bad)

    def test_exact_numeric_source_and_dom_spans(self):
        raw = "金额 €42.50; preserve 0042".encode()
        for kind in ("source_text", "dom"):
            record = text_evidence(raw, kind)
            self.assertEqual(validate_text_evidence(record, raw), record)
            self.assertEqual(extract_span(record, raw, "amount"), "42.50")
            with self.assertRaises(ValueError):
                validate_text_evidence(record, raw + b"x")
        with self.assertRaises(ValueError):
            extract_span(text_evidence(raw), raw, "unknown")

    def test_utf8_boundary_digest_and_reference_corruption(self):
        raw = "€42.50".encode()
        original = text_evidence(raw)
        for mutation in ("boundary", "digest", "reference", "duplicate", "oversize"):
            bad = copy.deepcopy(original)
            data = raw
            if mutation == "boundary":
                bad["spans"][0]["start"] = 1
            elif mutation == "digest":
                bad["content_sha256"] = sha(b"other")
            elif mutation == "reference":
                bad["spans"][0]["references"][0]["start"] += 1
            elif mutation == "duplicate":
                bad["spans"].append(copy.deepcopy(bad["spans"][0]))
            else:
                data = b" " * 8193
                bad["content_sha256"] = sha(data)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_text_evidence(bad, data)

    def test_ocr_is_unverified_and_bound_to_original_frame(self):
        captures = task()["captures"]
        raw = b"42.50"
        ref = dict(
            kind="raster",
            capture_id=captures[0]["capture_id"],
            x=4,
            y=6,
            width=20,
            height=10,
            frame_index=0,
            timestamp_micros=0,
        )
        record = dict(
            schema="perc1.semantic-text.v1",
            kind="ocr",
            content_sha256=sha(raw),
            fidelity="ocr_transcription_unverified",
            spans=[dict(span_id="amount", start=0, end=5, references=[ref])],
        )
        self.assertEqual(extract_span(record, raw, "amount", captures), "42.50")
        for field, value in (
            ("frame_index", 1),
            ("timestamp_micros", 1),
            ("width", 90),
            ("capture_id", "capture-unbound"),
        ):
            bad = copy.deepcopy(record)
            bad["spans"][0]["references"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_text_evidence(bad, raw, captures)
        record["fidelity"] = "source_bytes_preserved"
        with self.assertRaises(ValueError):
            validate_text_evidence(record, raw, captures)

    def test_three_split_axes_and_augmentation_inheritance(self):
        registry = groups()
        child = dict(registry[0], task_id="augmented-train", parent_task_id="train")
        registry.append(child)
        self.assertEqual(validate_split_registry(registry), registry)
        for field in ("document_group", "template_group", "source_group"):
            bad = groups()
            bad[2][field] = bad[0][field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_split_registry(bad)
            bad = copy.deepcopy(registry)
            bad[-1][field] = sha("invented independent augmentation")
            with self.subTest(augmentation=field), self.assertRaises(ValueError):
                validate_split_registry(bad)

    def test_lineage_missing_parent_cycles_and_incomplete_registry(self):
        for mutation in ("missing", "cycle", "incomplete", "unknown_group"):
            bad = groups()
            if mutation == "missing":
                bad[0]["parent_task_id"] = "absent"
            elif mutation == "cycle":
                bad[0]["parent_task_id"] = "train"
            elif mutation == "incomplete":
                bad.pop()
            else:
                bad[0]["source_group"] = "0" * 64
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_split_registry(bad)

    def test_equal_information_and_acquisition_budgets(self):
        budget = dict(
            public_packet_sha256=sha(public_packet(task())),
            maximum_reads=3,
            maximum_pixels=14400,
            maximum_text_bytes=8192,
            initial_reads=1,
        )
        arms = {name: dict(budget) for name in ("rules", "global", "dense")}
        self.assertEqual(validate_arm_budgets(arms), arms)
        for key in budget:
            bad = copy.deepcopy(arms)
            bad["dense"][key] = (
                sha("different public information")
                if key.endswith("sha256")
                else budget[key] + 1
            )
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_arm_budgets(bad)
        for name in arms:
            with self.subTest(missing=name), self.assertRaises(ValueError):
                validate_arm_budgets({k: v for k, v in arms.items() if k != name})


if __name__ == "__main__":
    unittest.main()
