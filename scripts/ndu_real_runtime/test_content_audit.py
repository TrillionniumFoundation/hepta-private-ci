"""Pinned synthetic historical artifacts exercise the complete audit CLI."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from ndu_real_materials import evaluator
from .content_audit import SCHEMA, audit
from .content_identity import selection_receipt


class ContentAuditTests(unittest.TestCase):
    def fixture(self, root, *, selected=False, fault=None, launch_fault=None):
        def put(name, value):
            raw = (json.dumps(value, ensure_ascii=False) + "\n").encode()
            (root / name).write_bytes(raw)
            return {
                "path": name,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }

        candidates = [
            {"text": text, "bbox": [0, 0, 1, 1], "origin": "pixel_ocr"}
            for text in ("PRIVATE_DECOY", "PRIVATE_TARGET")
        ]
        action = {
            "schema": "ndu.real.actor-action.v1",
            "action": "WRITE_TEXT",
            "arguments": {"text": candidates[0]["text"]},
        }
        observation = {
            "schema": "ndu.real.actor-observation.v1",
            "case_id": "PRIVATE_CASE",
            "step": 0,
            "action": action,
            "candidate_metadata": candidates,
        }
        if selected:
            observation["content_selection"] = selection_receipt(candidates, 0, action)
        wire = json.dumps(observation, ensure_ascii=False)
        ready = json.dumps(
            {
                "schema": "ndu.real.actor-ready.v1",
                "content_identity_profile": "ndu.real.content-selection.v1",
            }
        )
        launch = put(
            "launch.json",
            {
                "schema": "ndu.real.actor-isolation.v1",
                "stdout": ready + "\n" + wire + "\n",
                "exit_code": {"exit": 1, "boolean": False}.get(launch_fault, 0),
                "enforced_before_actor_exec": launch_fault != "isolation",
                "callback_error": {"type": "synthetic_callback_error"}
                if launch_fault == "callback"
                else None,
                "protocol_error": "synthetic_protocol_error"
                if launch_fault == "protocol"
                else None,
                "limit_reason": "synthetic_limit_reason"
                if launch_fault == "limit"
                else None,
                "host_exchanges": [
                    {"event_sha256": hashlib.sha256(ready.encode()).hexdigest()},
                    {
                        "event_sha256": hashlib.sha256(wire.encode()).hexdigest()
                        if fault != "wire"
                        else "0" * 64
                    },
                ],
            },
        )
        trajectory = put(
            "trajectory.json",
            {"steps": [{**observation, "observed_action_seconds": 0.1}]},
        )
        delivery = put(
            "delivery.json",
            {
                "schema": "ndu.real.delivery.v1",
                "case_id": "PRIVATE_CASE",
                "text": "PRIVATE_OTHER" if fault == "delivery" else "PRIVATE_DECOY",
                "image": None,
            },
        )
        reference = put(
            "reference.json",
            {
                "case_id": "PRIVATE_CASE",
                "role": "train",
                "field": "company",
                "expected_text": "PRIVATE_TARGET",
            },
        )
        source_sha = hashlib.sha256(Path(evaluator.__file__).read_bytes()).hexdigest()
        evaluation = put(
            "evaluation.json",
            {
                "schema": "ndu.real.independent-evaluation.v1",
                "case_id": "PRIVATE_CASE",
                "evaluator_source_sha256": source_sha,
                "rubric_sha256": "b" * 64,
                "delivery_sha256": "0" * 64
                if fault == "evaluation"
                else delivery["sha256"],
                "reference_sha256": reference["sha256"],
                "text_quality": 1.0 if fault == "score" else 0.0,
            },
        )
        manifest = {
            "schema": SCHEMA,
            "evaluator_source_sha256": source_sha,
            "normalizer_source_sha256": source_sha,
            "rubric_sha256": "b" * 64,
            "expected_write_text_count": 1,
            "episodes": [
                {
                    "case_id": "PRIVATE_CASE",
                    "role": "train",
                    "launch": launch,
                    "trajectory": trajectory,
                    "reference": reference,
                    "snapshots": [
                        {"step": 0, "delivery": delivery, "evaluation": evaluation}
                    ],
                }
            ],
        }
        binding = put("manifest.json", manifest)
        return (root / "manifest.json").read_bytes(), binding["sha256"]

    def test_cli_reads_original_pins_and_keeps_legacy_selection_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, pin = self.fixture(root)
            before = {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in root.iterdir()
            }
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ndu_real_runtime.content_audit",
                    "--root",
                    str(root),
                    "--manifest",
                    str(root / "manifest.json"),
                    "--expected-manifest-sha256",
                    pin,
                    "--output",
                    str(root / "audit.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((root / "audit.json").read_bytes())
            row = report["episodes"][0]["rows"][0]
            self.assertEqual(
                (
                    report["denominator_matches"],
                    row["selected_used"],
                    row["first_observed_discrepancy"],
                    row["first_unknown_link"],
                ),
                (True, None, None, "candidate_selection"),
            )
            self.assertEqual(
                row["posthoc_reference_diagnostic"][
                    "candidate_reference_match_present"
                ],
                True,
            )
            self.assertEqual(
                row["posthoc_reference_diagnostic"][
                    "content_failure_present_at_actor_payload"
                ],
                True,
            )
            self.assertNotIn(
                "PRIVATE_", json.dumps(report) + result.stdout + result.stderr
            )
            self.assertEqual(
                before,
                {
                    name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                    for name in before
                },
            )

    def test_cli_refuses_existing_output_without_changing_evidence(self):
        for output_name in ("manifest.json", "delivery.json", "existing-report.json"):
            with (
                self.subTest(output=output_name),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                _, pin = self.fixture(root)
                if output_name == "existing-report.json":
                    (root / output_name).write_bytes(b"retained report bytes\n")
                before = {path.name: path.read_bytes() for path in root.iterdir()}
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "ndu_real_runtime.content_audit",
                        "--root",
                        str(root),
                        "--manifest",
                        str(root / "manifest.json"),
                        "--expected-manifest-sha256",
                        pin,
                        "--output",
                        str(root / output_name),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(
                    json.loads(result.stdout),
                    {
                        "execution_status": "rejected",
                        "error_type": "FileExistsError",
                        "error_code": "AUDIT_OUTPUT_EXISTS",
                    },
                )
                self.assertEqual(result.stderr, "")
                self.assertEqual(
                    before, {path.name: path.read_bytes() for path in root.iterdir()}
                )

    def test_first_observed_discrepancy_is_localized(self):
        for fault, expected in (
            ("wire", "raw_actor_wire_receipt"),
            ("delivery", "action_to_delivery"),
            ("evaluation", "delivery_to_evaluator"),
            ("score", "evaluator_text_score"),
        ):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                raw, pin = self.fixture(root, fault=fault)
                report = audit(root, raw, pin)
                self.assertEqual(
                    report["episodes"][0]["rows"][0]["first_observed_discrepancy"],
                    expected,
                )
                if fault == "wire":
                    self.assertIsNone(
                        report["episodes"][0]["rows"][0][
                            "posthoc_reference_diagnostic"
                        ]["content_failure_present_at_actor_payload"]
                    )

    def test_failed_or_unisolated_launch_cannot_prove_selected_used(self):
        for fault in ("exit", "isolation", "boolean", "callback", "protocol", "limit"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                raw, pin = self.fixture(root, selected=True, launch_fault=fault)
                episode = audit(root, raw, pin)["episodes"][0]
                row = episode["rows"][0]
                self.assertFalse(episode["launch_completed"])
                self.assertIs(row["checks"]["candidate_selection"], True)
                self.assertIs(row["checks"]["isolated_actor_completed"], False)
                self.assertIsNone(row["selected_used"])
                self.assertEqual(
                    row["first_observed_discrepancy"], "isolated_actor_completed"
                )
                self.assertIsNone(
                    row["posthoc_reference_diagnostic"][
                        "content_failure_present_at_actor_payload"
                    ]
                )

    def test_current_witness_is_distinct_from_legacy_and_tampered_input_is_rejected(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw, pin = self.fixture(root, selected=True)
            row = audit(root, raw, pin)["episodes"][0]["rows"][0]
            self.assertEqual((row["selected_used"], row["selected_index"]), (True, 0))
            sealed = json.loads(raw)
            sealed["episodes"][0]["role"] = "confirmation"
            sealed_raw = json.dumps(sealed).encode()
            with self.assertRaisesRegex(ValueError, "AUDIT_REFERENCE_SCOPE_REFUSED"):
                audit(root, sealed_raw, hashlib.sha256(sealed_raw).hexdigest())
            (root / "delivery.json").write_bytes(b"{}")
            with self.assertRaises(ValueError):
                audit(root, raw, pin)

    def test_repeated_case_episodes_are_counted_without_duplicating_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw, _ = self.fixture(root)
            manifest = json.loads(raw)
            duplicate = dict(manifest["episodes"][0])
            trajectory = json.loads((root / "trajectory.json").read_bytes())
            trajectory["steps"][0]["observed_action_seconds"] = 0.2
            repeated_raw = json.dumps(trajectory).encode()
            (root / "repeated-trajectory.json").write_bytes(repeated_raw)
            duplicate["trajectory"] = {
                "path": "repeated-trajectory.json",
                "bytes": len(repeated_raw),
                "sha256": hashlib.sha256(repeated_raw).hexdigest(),
            }
            manifest["episodes"].append(duplicate)
            manifest["expected_write_text_count"] = 2
            raw = json.dumps(manifest).encode()
            report = audit(root, raw, hashlib.sha256(raw).hexdigest())
            self.assertEqual(
                (
                    report["episode_count"],
                    report["distinct_case_count"],
                    report["observed_write_text_count"],
                ),
                (2, 1, 2),
            )
            manifest["episodes"].append(duplicate)
            raw = json.dumps(manifest).encode()
            with self.assertRaisesRegex(ValueError, "AUDIT_DUPLICATE_EPISODE"):
                audit(root, raw, hashlib.sha256(raw).hexdigest())

    def test_missing_text_score_is_unknown_and_invalid_pins_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw, _ = self.fixture(root)
            manifest = json.loads(raw)
            evaluation = json.loads((root / "evaluation.json").read_bytes())
            evaluation.pop("text_quality")
            score_raw = json.dumps(evaluation).encode()
            (root / "evaluation.json").write_bytes(score_raw)
            bound = manifest["episodes"][0]["snapshots"][0]["evaluation"]
            bound.update(
                bytes=len(score_raw), sha256=hashlib.sha256(score_raw).hexdigest()
            )
            raw = json.dumps(manifest).encode()
            row = audit(root, raw, hashlib.sha256(raw).hexdigest())["episodes"][0][
                "rows"
            ][0]
            self.assertIsNone(
                row["posthoc_reference_diagnostic"][
                    "scorer_text_quality_matches_normalizer"
                ]
            )
            self.assertIsNone(row["first_observed_discrepancy"])
            manifest["rubric_sha256"] = "missing-pin"
            raw = json.dumps(manifest).encode()
            with self.assertRaisesRegex(ValueError, "AUDIT_PIN_SHAPE"):
                audit(root, raw, hashlib.sha256(raw).hexdigest())

    def test_actor_stream_requires_one_initial_ready_and_only_observations(self):
        for kind in ("missing", "late", "duplicate", "unexpected", "valid"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                raw, _ = self.fixture(root, selected=True)
                manifest = json.loads(raw)
                launch = json.loads((root / "launch.json").read_bytes())
                observation = next(
                    line
                    for line in launch["stdout"].splitlines()
                    if json.loads(line).get("schema") == "ndu.real.actor-observation.v1"
                )
                ready = json.dumps(
                    {
                        "schema": "ndu.real.actor-ready.v1",
                        "content_identity_profile": "ndu.real.content-selection.v1",
                    }
                )
                unexpected = json.dumps({"schema": "ndu.real.unknown-event.v1"})
                cases = {
                    "missing": [observation],
                    "late": [observation, ready],
                    "duplicate": [ready, ready, observation],
                    "unexpected": [ready, unexpected, observation],
                    "valid": [ready, observation],
                }
                lines = cases[kind]
                launch["stdout"] = "\n".join(lines) + "\n"
                launch["host_exchanges"] = [
                    {"event_sha256": hashlib.sha256(line.encode()).hexdigest()}
                    for line in lines
                ]
                launch_raw = (json.dumps(launch, ensure_ascii=False) + "\n").encode()
                (root / "launch.json").write_bytes(launch_raw)
                manifest["episodes"][0]["launch"] = {
                    "path": "launch.json",
                    "bytes": len(launch_raw),
                    "sha256": hashlib.sha256(launch_raw).hexdigest(),
                }
                manifest_raw = json.dumps(manifest, ensure_ascii=False).encode()
                row = audit(
                    root, manifest_raw, hashlib.sha256(manifest_raw).hexdigest()
                )["episodes"][0]["rows"][0]
                self.assertIs(row["checks"]["raw_actor_wire_receipt"], True)
                self.assertIs(row["checks"]["candidate_selection"], True)
                self.assertIs(row["checks"]["wire_to_trajectory"], kind == "valid")
                self.assertIs(row["selected_used"], True if kind == "valid" else None)
                if kind != "valid":
                    self.assertIsNone(
                        row["posthoc_reference_diagnostic"][
                            "content_failure_present_at_actor_payload"
                        ]
                    )


if __name__ == "__main__":
    unittest.main()
