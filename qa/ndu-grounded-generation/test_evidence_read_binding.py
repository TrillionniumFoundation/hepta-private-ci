"""Synthetic negative controls for immutable evidence intake; no model execution."""

import copy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from PIL import Image, ImageDraw

import capability_gate
import cohort_firewall
import overlay_audit
from test_capability_gate import make_fixtures


class EvidenceReadBindingTests(unittest.TestCase):
    def make_bundle(self, root):
        report, protocol, episodes = make_fixtures()
        report["engineering_pass"] = False
        raw = {
            "report": json.dumps(report).encode(),
            "protocol": json.dumps(protocol).encode(),
            "episodes": b"".join(json.dumps(row).encode() + b"\n" for row in episodes),
        }
        paths = {
            "report": root / "results" / "summary-report.json",
            "protocol": root / "code" / "protocol.json",
            "episodes": root / "raw" / "test.episodes.jsonl",
        }
        for key, path in paths.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw[key])
        pins = {key: hashlib.sha256(data).hexdigest() for key, data in raw.items()}
        return report, raw, paths, pins

    def test_capability_hash_and_consumption_share_one_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report, raw, paths, pins = self.make_bundle(root)
            replacement = {**report, "engineering_pass": True}
            changed = False
            real_sha256 = hashlib.sha256

            def replace_after_final_hash(data=b"", *args, **kwargs):
                nonlocal changed
                if data == raw["episodes"] and not changed:
                    changed = True
                    paths["report"].write_text(
                        json.dumps(replacement), encoding="utf-8"
                    )
                return real_sha256(data, *args, **kwargs)

            output = root / "receipt.json"
            # Inject synthetic identities only in this temporary unit fixture.
            with (
                mock.patch.object(capability_gate, "PINNED_V1_SHA256", pins),
                mock.patch.object(
                    capability_gate.hashlib,
                    "sha256",
                    side_effect=replace_after_final_hash,
                ),
            ):
                status = capability_gate.main(
                    ["--bundle-root", str(root), "--output", str(output)]
                )
            self.assertEqual(status, 2)
            self.assertTrue(changed)
            self.assertTrue(json.loads(paths["report"].read_text())["engineering_pass"])
            receipt = json.loads(output.read_text())
            self.assertFalse(receipt["v1_engineering_pass"])
            self.assertEqual(receipt["measurement_receipt_hashes"], pins)
            self.assertTrue(receipt["pinned_v1_evidence_verified"])
            self.assertFalse(receipt["all_scientific_gates_closed"])

    @staticmethod
    def png_bytes(with_rectangle):
        image = Image.new("RGB", (32, 32), "white")
        if with_rectangle:
            ImageDraw.Draw(image).rectangle(
                (4, 4, 24, 24), outline=(255, 30, 30), width=1
            )
        stream = BytesIO()
        image.save(stream, format="PNG")
        return stream.getvalue()

    def test_png_hash_and_pixels_share_one_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            original = self.png_bytes(False)
            replacement = self.png_bytes(True)
            digest = hashlib.sha256(original).hexdigest()
            artifact = root / (digest + ".png")
            artifact.write_bytes(original)
            episodes = root / "episodes.jsonl"
            episodes.write_text(
                json.dumps(
                    {
                        "task_id": "fixture",
                        "method": "base",
                        "artifact_sha256": digest,
                        "boxes": [[0.125, 0.125, 0.75, 0.75]],
                    }
                )
                + "\n"
            )
            real_open = Image.open
            replaced = False

            def replace_before_decode(source, *args, **kwargs):
                nonlocal replaced
                replaced = True
                artifact.write_bytes(replacement)
                return real_open(source, *args, **kwargs)

            with mock.patch.object(
                overlay_audit.Image, "open", side_effect=replace_before_decode
            ):
                receipt = overlay_audit.audit(episodes, root)
            self.assertTrue(replaced)
            self.assertEqual(artifact.read_bytes(), replacement)
            self.assertEqual(receipt["status"], "fail")
            self.assertEqual(len(receipt["low_coverage_boxes"]), 1)
            self.assertFalse(receipt["independent_pixel_generation_proven"])

    def test_duplicate_unknown_json_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ambiguous.json"
            path.write_bytes(b'{"unused":{"key":1,"key":2}}\n')
            for loader in (
                capability_gate._load_json,
                lambda p: list(overlay_audit._read_jsonl(p)),
            ):
                with (
                    self.subTest(loader=loader),
                    self.assertRaisesRegex(ValueError, "duplicate JSON"),
                ):
                    loader(path)

    def test_each_reader_enforces_its_declared_byte_bound(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "oversized.json"
            wire = b'{"value":"' + b"x" * 80 + b'"}\n'
            path.write_bytes(wire)
            for module, loader in (
                (capability_gate, capability_gate._load_json),
                (overlay_audit, lambda p: list(overlay_audit._read_jsonl(p))),
            ):
                with self.subTest(module=module.__name__):
                    with mock.patch.object(
                        module, "MAX_EVIDENCE_BYTES", 64, create=True
                    ):
                        with self.assertRaisesRegex(ValueError, "byte limit"):
                            loader(path)
                    self.assertEqual(path.read_bytes(), wire)

    def test_nonfinite_aggregate_cannot_reconcile_as_pass(self):
        report, protocol, episodes = make_fixtures()
        for field in (
            "episodes",
            "source_groups",
            "quality",
            "wall_seconds",
            "coverage",
            "severe",
            "cvar",
        ):
            for nonfinite in (float("nan"), float("inf"), float("-inf")):
                altered = copy.deepcopy(report)
                altered["points"][0][field] = nonfinite
                with self.subTest(field=field, value=nonfinite):
                    with self.assertRaises(capability_gate.EvidenceError):
                        capability_gate.evaluate_capabilities(
                            altered, protocol, episodes
                        )

    def test_empty_overlay_journal_does_not_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "empty.jsonl"
            path.write_bytes(b"")
            with self.assertRaisesRegex(ValueError, "empty episode journal"):
                overlay_audit.audit(path, root)

    def test_capability_output_cannot_replace_input_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, raw, paths, pins = self.make_bundle(root)
            with mock.patch.object(capability_gate, "PINNED_V1_SHA256", pins):
                status = capability_gate.main(
                    ["--bundle-root", str(root), "--output", str(paths["report"])]
                )
            self.assertEqual(status, 2)
            for key, path in paths.items():
                self.assertEqual(path.read_bytes(), raw[key])

    def test_overlay_output_cannot_replace_artifact_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            artifacts = root / "artifacts"
            artifacts.mkdir()
            raw = self.png_bytes(False)
            digest = hashlib.sha256(raw).hexdigest()
            path = artifacts / (digest + ".png")
            path.write_bytes(raw)
            journal = root / "episodes.jsonl"
            journal.write_text(
                json.dumps(
                    {
                        "task_id": "fixture",
                        "method": "base",
                        "artifact_sha256": digest,
                        "boxes": [],
                    }
                )
                + "\n"
            )
            with mock.patch(
                "sys.argv",
                [
                    "overlay_audit.py",
                    "--episodes",
                    str(journal),
                    "--artifact-root",
                    str(artifacts),
                    "--output",
                    str(path),
                ],
            ):
                with self.assertRaisesRegex(ValueError, "overlaps frozen"):
                    overlay_audit.main()
            self.assertEqual(path.read_bytes(), raw)

    def test_unknown_claim_flags_cannot_close_scientific_gates(self):
        report, protocol, episodes = make_fixtures()
        report.update(all_scientific_gates_closed=True, qualified=True, production=True)
        protocol["qualified"] = True
        receipt = capability_gate.evaluate_capabilities(report, protocol, episodes)
        self.assertFalse(receipt["all_scientific_gates_closed"])
        self.assertEqual(
            receipt["gates"]["confirmatory_frontier_advantage"]["status"], "open"
        )

    def test_unhashable_history_schema_is_a_typed_denial(self):
        with self.assertRaises(cohort_firewall.CohortContractError):
            cohort_firewall.verify_pinned_history_bytes(
                [b"{}", b"{}"], [{"schema": []}, {"schema": "unknown"}]
            )


if __name__ == "__main__":
    unittest.main()
