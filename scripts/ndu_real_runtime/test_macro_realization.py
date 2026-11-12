"""Retained-byte integration fixtures; no native execution or policy efficacy."""

import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from ndu_real_materials import common, evaluator
from . import macro_realization as realization
from .content_identity import SELECTION_SCHEMA, selection_receipt
from .metacontrol_macro_contract import SEQUENCES, digest, sha
from .test_macro_wire_delivery_admission import case


def save(path, value):
    path.write_text(json.dumps(value, sort_keys=True) + "\n")


def sync_steps(directory, steps):
    launch = json.loads((directory / "launch.json").read_text())
    ready = json.loads(launch["stdout"].splitlines()[0])
    lines = [json.dumps(event) for event in (ready, *steps)]
    launch["stdout"] = "\n".join(lines) + "\n"
    for line, exchange in zip(lines, launch["host_exchanges"]):
        exchange["event_sha256"] = sha(line.encode())
    save(directory / "launch.json", launch)
    save(directory / "trajectory.json", {"steps": steps})


def fixture(root, *, macro="READ", selected_index=1, modern=True):
    config, directory, result = case(root, SEQUENCES[macro])
    config["evaluator_sha256"] = sha(Path(evaluator.__file__).read_bytes())
    candidates = [
        {"text": text, "bbox": [0, 0, 2, 2], "origin": "pixel_ocr"}
        for text in ("ACME LTD", "WRONG LTD")
    ]
    text = candidates[selected_index]["text"]
    steps = json.loads((directory / "trajectory.json").read_text())["steps"]
    for step in steps:
        step["candidate_metadata"] = copy.deepcopy(candidates)
        step["candidate_features"] = [[1.0], [0.0]]
        if step["action"]["action"] == "WRITE_TEXT":
            step["action"]["arguments"] = {"text": text}
            if modern:
                step["content_selection"] = selection_receipt(
                    candidates, selected_index, step["action"]
                )
    sync_steps(directory, steps)
    truth = {
        "case_id": "c",
        "source_group": "s",
        "role": "train",
        "field": "company",
        "expected_text": "ACME LTD",
    }
    save(directory / "reference.json", truth)
    reference = common.binding(directory / "reference.json", directory)
    snapshot = directory / f"delivery-{len(steps):02d}"
    save(
        snapshot / "delivery.json",
        {"schema": "ndu.real.delivery.v1", "case_id": "c", "text": text, "image": None},
    )
    score = {
        "schema": "ndu.real.independent-evaluation.v1",
        "case_id": "c",
        "source_group": "s",
        "role": "train",
        "quality": float(selected_index == 0),
        "text_quality": float(selected_index == 0),
        "reference_sha256": reference["sha256"],
        "delivery_sha256": sha((snapshot / "delivery.json").read_bytes()),
        "evaluator_source_sha256": config["evaluator_sha256"],
        "rubric_sha256": config["rubric_sha256"],
    }
    save(snapshot / "evaluation.json", score)
    result.update(
        score_components=score,
        gross_score=score["quality"],
        output_text_sha256=digest(text),
    )
    save(directory / "result.json", result)
    image = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(image, format="PNG")
    (directory / "public" / "observed.png").write_bytes(image.getvalue())
    index = SEQUENCES[macro].index("WRITE_TEXT")
    public = {
        "schema": "ndu.real.actor-step.v1",
        "case_id": "c",
        "step": index,
        "remaining_seconds": 10.0,
        "prepared_roi": [0, 0, 2, 2],
        "observation": {
            "path": "observed.png",
            "sha256": sha(image.getvalue()),
            "bbox": [0, 0, 2, 2],
            "kind": "roi",
        },
        "delivery": {
            "schema": "ndu.real.delivery.v1",
            "case_id": "c",
            "text": None,
            "image": None,
        },
        "text_committed": False,
        "forced_action": "WRITE_TEXT",
    }
    save(directory / "public-input.json", public)
    public_pin = common.binding(directory / "public-input.json", directory)
    launch = json.loads((directory / "launch.json").read_text())
    events = [json.loads(line) for line in launch["stdout"].splitlines()]
    if modern:
        events[0]["content_identity_profile"] = SELECTION_SCHEMA
    lines = [json.dumps(event) for event in events]
    launch["stdout"] = "\n".join(lines) + "\n"
    launch["host_exchanges"] = [
        {"event_sha256": sha(line.encode()), "reply_sha256": None, "reply_bytes": 0}
        for line in lines
    ]
    launch["host_exchanges"][index].update(
        reply_sha256=public_pin["sha256"], reply_bytes=public_pin["bytes"]
    )
    save(directory / "launch.json", launch)
    return dict(
        directory=directory,
        result=result,
        macro=macro,
        wall_seconds=0.2,
        tariff=0.01,
        config=config,
        expected_source_sha256=digest(realization.source_manifest()),
        public_input=public_pin,
        reference=reference,
    )


class MacroRealizationTests(unittest.TestCase):
    def test_candidate_correct_selection_wrong_is_completed_wrong_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = fixture(Path(tmp))
            report = realization.observe_realization(**data)
            stages = report["stages"]
            self.assertTrue(stages["observation"]["acquired"])
            self.assertIsNone(stages["observation"]["answer_available_in_source"])
            self.assertIsNone(stages["observation"]["new_information"])
            self.assertTrue(stages["candidates"]["scorer_match_present"])
            self.assertEqual(stages["selection"]["selected_index"], 1)
            self.assertTrue(stages["selection"]["selected_used"])
            self.assertFalse(stages["selection"]["selected_reference_match"])
            self.assertEqual(
                stages["execution"],
                {
                    "completed": True,
                    "payload_delivered": True,
                    "scored": True,
                    "quality": 0.0,
                    "delivered_reference_match": False,
                    "delivery_sha256": sha(
                        (data["directory"] / "delivery-04/delivery.json").read_bytes()
                    ),
                    "evaluation_sha256": sha(
                        (data["directory"] / "delivery-04/evaluation.json").read_bytes()
                    ),
                    "external_effect_occurred": None,
                },
            )

    def test_stop_and_read_correct_selection_bind_the_same_terminal_contract(self):
        for macro in SEQUENCES:
            with self.subTest(macro=macro), tempfile.TemporaryDirectory() as tmp:
                data = fixture(Path(tmp), macro=macro, selected_index=0)
                report = realization.observe_realization(**data)
                self.assertTrue(
                    report["stages"]["selection"]["selected_reference_match"]
                )
                self.assertTrue(
                    report["stages"]["execution"]["delivered_reference_match"]
                )
                self.assertFalse(report["full_physical_cost_observed"])
                data.update(public_input=None, reference=None)
                unlabelled = realization.observe_realization(**data)["stages"]
                self.assertIsNone(unlabelled["observation"]["acquired"])
                self.assertIsNone(unlabelled["candidates"]["scorer_match_present"])
                self.assertTrue(unlabelled["selection"]["selected_used"])
                self.assertIsNone(unlabelled["selection"]["selected_reference_match"])

    def test_legacy_selection_remains_unknown_despite_scored_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            stages = realization.observe_realization(
                **fixture(Path(tmp), modern=False)
            )["stages"]
            self.assertIsNone(stages["selection"]["selected_index"])
            self.assertIsNone(stages["selection"]["selected_used"])
            self.assertIsNone(stages["selection"]["selected_reference_match"])
            self.assertTrue(stages["candidates"]["scorer_match_present"])
            self.assertFalse(stages["execution"]["delivered_reference_match"])

    def test_raw_wire_and_payload_delivery_disagreements_reject(self):
        for mutation in ("wire", "delivery", "result"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                data = fixture(Path(tmp))
                directory = data["directory"]
                steps = json.loads((directory / "trajectory.json").read_text())["steps"]
                if mutation == "result":
                    data["result"]["gross_score"] = 1.0
                else:
                    steps[2]["action"]["arguments"]["text"] = "UNDELIVERED"
                    save(directory / "trajectory.json", {"steps": steps})
                    if mutation == "delivery":
                        sync_steps(directory, steps)
                with self.assertRaises(ValueError):
                    realization.observe_realization(**data)

    def test_self_consistent_wire_cannot_forge_candidate_selection(self):
        for field in (
            "selected_index",
            "candidate_set_sha256",
            "action_sha256",
            "candidate_metadata",
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                data = fixture(Path(tmp))
                steps = json.loads((data["directory"] / "trajectory.json").read_text())[
                    "steps"
                ]
                if field == "candidate_metadata":
                    steps[2][field][0]["text"] = "SUBSTITUTED"
                else:
                    steps[2]["content_selection"][field] = (
                        0 if field == "selected_index" else "0" * 64
                    )
                sync_steps(data["directory"], steps)
                with self.assertRaises(ValueError):
                    realization.observe_realization(**data)

    def test_selection_requires_original_modern_readiness_profile(self):
        for mode in ("missing", "unknown", "witness_missing"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                data = fixture(Path(tmp))
                directory = data["directory"]
                launch = json.loads((directory / "launch.json").read_text())
                events = [json.loads(line) for line in launch["stdout"].splitlines()]
                if mode == "missing":
                    del events[0]["content_identity_profile"]
                elif mode == "unknown":
                    events[0]["content_identity_profile"] = "unsupported.v9"
                else:
                    del events[3]["content_selection"]
                launch["stdout"] = (
                    "\n".join(json.dumps(event) for event in events) + "\n"
                )
                save(directory / "launch.json", launch)
                sync_steps(directory, events[1:])
                with self.assertRaises(ValueError):
                    realization.observe_realization(**data)

    def test_acquisition_needs_original_reply_and_exact_image_bytes(self):
        for mode in ("reply", "image", "future_field"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                data = fixture(Path(tmp))
                directory = data["directory"]
                if mode == "image":
                    (directory / "public" / "observed.png").write_bytes(b"changed")
                else:
                    launch = json.loads((directory / "launch.json").read_text())
                    if mode == "reply":
                        launch["host_exchanges"][2]["reply_sha256"] = "0" * 64
                    else:
                        path = directory / "public-input.json"
                        public = json.loads(path.read_text())
                        public["expected_text"] = "forbidden policy label"
                        save(path, public)
                        data["public_input"] = common.binding(path, directory)
                        launch["host_exchanges"][2].update(
                            reply_sha256=data["public_input"]["sha256"],
                            reply_bytes=data["public_input"]["bytes"],
                        )
                    save(directory / "launch.json", launch)
                with self.assertRaises(ValueError):
                    realization.observe_realization(**data)

    def test_posthoc_reference_role_source_and_scorer_are_bound(self):
        for field, value in (
            ("role", "confirmation"),
            ("source_group", "other"),
            ("expected_text", "WRONG LTD"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                data = fixture(Path(tmp))
                directory = data["directory"]
                path = directory / "reference.json"
                truth = json.loads(path.read_text())
                truth[field] = value
                save(path, truth)
                data["reference"] = common.binding(path, directory)
                score = data["result"]["score_components"]
                score["reference_sha256"] = data["reference"]["sha256"]
                if field == "role":
                    score["role"] = value
                save(directory / "delivery-04/evaluation.json", score)
                save(directory / "result.json", data["result"])
                with self.assertRaises(ValueError):
                    realization.observe_realization(**data)

    def test_source_identity_checked_before_and_after_inspection(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = fixture(Path(tmp))
            before = realization.source_manifest()
            changed = {**before, "observer_mutated": "0" * 64}
            with patch.object(
                realization, "source_manifest", side_effect=[before, changed]
            ):
                with self.assertRaisesRegex(ValueError, "changed"):
                    realization.observe_realization(**data)
            data["expected_source_sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "identity"):
                realization.observe_realization(**data)

    def test_result_agreement_does_not_admit_invalid_scored_quality(self):
        for quality in (-0.1, 2.0, True):
            with self.subTest(quality=quality), tempfile.TemporaryDirectory() as tmp:
                data = fixture(Path(tmp))
                result, directory = data["result"], data["directory"]
                result["gross_score"] = quality
                result["score_components"]["quality"] = quality
                save(directory / "result.json", result)
                save(
                    directory / "delivery-04/evaluation.json",
                    result["score_components"],
                )
                with self.assertRaisesRegex(ValueError, "quality"):
                    realization.observe_realization(**data)

    def test_sealed_score_role_rejects_before_any_reference_bytes_are_read(self):
        for role in ("confirmation", "retention_test"):
            with self.subTest(role=role), tempfile.TemporaryDirectory() as tmp:
                data = fixture(Path(tmp))
                result, directory = data["result"], data["directory"]
                result["score_components"]["role"] = role
                save(directory / "result.json", result)
                save(
                    directory / "delivery-04/evaluation.json",
                    result["score_components"],
                )
                read_bound, reads = common.read_bound, []

                def record_read(root, binding, **options):
                    if binding == data["reference"]:
                        reads.append(binding["path"])
                    return read_bound(root, binding, **options)

                with patch.object(common, "read_bound", side_effect=record_read):
                    with self.assertRaisesRegex(ValueError, "role"):
                        realization.observe_realization(**data)
                self.assertEqual(reads, [])

    def test_boolean_early_ordinals_reject_despite_matching_wire_and_trajectory(self):
        for index in (0, 1):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as tmp:
                data = fixture(Path(tmp))
                directory = data["directory"]
                steps = json.loads((directory / "trajectory.json").read_text())["steps"]
                steps[index]["step"] = bool(index)
                sync_steps(directory, steps)
                with self.assertRaises(ValueError):
                    realization.observe_realization(**data)

    def test_nested_public_labels_and_boolean_boxes_reject_even_with_reply_binding(
        self,
    ):
        for kind in ("delivery", "image", "bbox"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                data = fixture(Path(tmp))
                directory = data["directory"]
                path = directory / "public-input.json"
                public = json.loads(path.read_text())
                if kind == "delivery":
                    public["delivery"]["expected_text"] = "hidden future answer"
                elif kind == "image":
                    public["delivery"]["image"] = {
                        **common.binding(
                            directory / "public/observed.png", directory / "public"
                        ),
                        "bbox": [0, 0, 2, 2],
                        "expected_text": "hidden future answer",
                    }
                else:
                    public["observation"]["bbox"][0] = False
                save(path, public)
                data["public_input"] = common.binding(path, directory)
                launch = json.loads((directory / "launch.json").read_text())
                launch["host_exchanges"][2].update(
                    reply_sha256=data["public_input"]["sha256"],
                    reply_bytes=data["public_input"]["bytes"],
                )
                save(directory / "launch.json", launch)
                with self.assertRaises(ValueError):
                    realization.observe_realization(**data)


if __name__ == "__main__":
    unittest.main()
