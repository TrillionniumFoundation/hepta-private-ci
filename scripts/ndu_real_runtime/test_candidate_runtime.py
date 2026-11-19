"""Candidate admission and actual actor/host wiring, without efficacy claims."""

from dataclasses import asdict
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from .candidate_memory import CandidateMemoryError, CandidateScope
from .candidate_runtime import (
    CandidateRuntime,
    PROFILE_SCHEMA,
    read_audit,
    validate_activation,
)
from .objective import canonical_sha


def profile(mode="bounded", *, entries=3, size=32_000):
    return {
        "schema": PROFILE_SCHEMA,
        "mode": mode,
        "max_entries": entries,
        "max_serialized_bytes": size,
    }


def candidate(text, box=(10, 20, 90, 50)):
    return {"text": text, "bbox": list(box), "origin": "pixel_ocr"}


SCOPE = CandidateScope("original-attempt", "receipt", "a" * 64, 1000, 800)
BINDINGS = {
    name: char * 64
    for name, char in (
        ("weights_sha256", "b"),
        ("parameters_sha256", "c"),
        ("control_profile_sha256", "d"),
        ("public_case_sha256", "e"),
    )
}
OBSERVATION = {
    "path": "overview.png",
    "sha256": "f" * 64,
    "bbox": [0, 0, 1000, 800],
    "kind": "overview",
}
STOP = {"schema": "ndu.real.actor-action.v1", "action": "STOP", "arguments": {}}


class CandidateRuntimeTests(unittest.TestCase):
    def test_only_retention_differs_and_exact_actor_selection_is_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            for mode in ("current_only", "bounded"):
                directory = Path(temporary) / mode
                directory.mkdir()
                runtime = CandidateRuntime(profile(mode), SCOPE, BINDINGS)
                old = candidate("42.00")
                runtime.offer(0, [old], [[0.25] * 126])
                first = runtime.record(
                    directory, {"step": 0, "observation": OBSERVATION}, STOP, 0
                )
                current = candidate("new ROI", (400, 300, 500, 350))
                offered, features = runtime.offer(1, [current], [[0.75] * 126])
                expected = [current] + ([old] if mode == "bounded" else [])
                self.assertEqual(offered, expected)
                self.assertEqual(
                    features[-1], [0.25 if mode == "bounded" else 0.75] * 126
                )
                selected = len(offered) - 1
                action = {
                    **STOP,
                    "action": "WRITE_TEXT",
                    "arguments": {"text": offered[selected]["text"]},
                }
                audit = runtime.record(
                    directory, {"step": 1, "observation": OBSERVATION}, action, selected
                )
                value = read_audit(
                    directory,
                    audit,
                    {
                        "step": 1,
                        "previous_audit_sha256": first["sha256"],
                        "action": action,
                    },
                )
                self.assertEqual(value["raw_candidates"], [current])
                self.assertEqual(value["offered_candidates"], expected)
                self.assertEqual(value["selected_index"], selected)
                self.assertEqual(
                    value["offered_observed_steps"],
                    [1, 0] if mode == "bounded" else [1],
                )
                self.assertEqual(
                    value["offered_features_sha256"], canonical_sha(features)
                )

    def test_same_caps_evict_and_empty_pool_does_not_fallback(self):
        for mode in ("current_only", "bounded"):
            runtime = CandidateRuntime(profile(mode, entries=1), SCOPE, BINDINGS)
            offered, _ = runtime.offer(
                0, [candidate("first"), candidate("second")], [[0.0] * 126] * 2
            )
            self.assertEqual(offered, [candidate("first")])
            too_small = CandidateRuntime(profile(mode, size=600), SCOPE, BINDINGS)
            with self.assertRaises(CandidateMemoryError) as caught:
                too_small.offer(0, [candidate("cannot fit")], [[0.0] * 126])
            self.assertEqual(caught.exception.receipt.resident_entries, 0)

    def test_rebinding_mutation_duplicate_step_and_wrong_write_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = CandidateRuntime(profile(), SCOPE, BINDINGS)
            original, features = candidate("copied"), [[0.25] * 126]
            runtime.offer(0, [original], features)
            original["text"], features[0][0] = "mutated", 99.0
            wrong = {**STOP, "action": "WRITE_TEXT", "arguments": {"text": "mutated"}}
            with self.assertRaisesRegex(ValueError, "selected candidate"):
                runtime.record(
                    directory, {"step": 0, "observation": OBSERVATION}, wrong, 0
                )
            receipt = runtime.record(
                directory, {"step": 0, "observation": OBSERVATION}, STOP, 0
            )
            value = read_audit(directory, receipt, {"step": 0})
            self.assertEqual(value["raw_candidates"][0]["text"], "copied")
            for key, item in (
                ("scope", {**asdict(SCOPE), "case_id": "other"}),
                ("weights_sha256", "0" * 64),
                ("action", wrong),
                ("previous_audit_sha256", "0" * 64),
            ):
                with self.assertRaises(ValueError):
                    read_audit(directory, receipt, {"step": 0, key: item})
            with self.assertRaises(ValueError):
                runtime.offer(0, [candidate("repeat")], [[0.0] * 126])
            with self.assertRaises(ValueError):
                read_audit(directory, {**receipt, "path": "../elsewhere"}, {"step": 0})
            Path(directory, receipt["path"]).write_text("{}\n")
            with self.assertRaises(ValueError):
                read_audit(directory, receipt, {"step": 0})

    def test_no_selection_stop_and_incomplete_resume_are_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = CandidateRuntime(profile(), SCOPE, BINDINGS)
            receipt = runtime.record(
                directory, {"step": 0, "observation": OBSERVATION}, STOP
            )
            value = read_audit(directory, receipt, {"step": 0})
            self.assertFalse(value["observation_processed"])
            self.assertIsNone(value["selected_index"])
            self.assertIsNone(value["memory_receipt"])
        for arguments in (
            dict(start_step=1, checkpoint_requested=False, training_exploration=False),
            dict(start_step=0, checkpoint_requested=True, training_exploration=False),
            dict(start_step=0, checkpoint_requested=False, training_exploration=True),
        ):
            with self.assertRaises(ValueError):
                validate_activation(**arguments)


class CandidateActorProcessTests(unittest.TestCase):
    def test_real_ocr_torch_actor_and_host_delivery_use_offered_candidates(self):
        # This crafted pixel/weight fixture exercises plumbing. It is not a
        # trained-model comparison, an independent task sample or a gain claim.
        import torch
        from PIL import Image, ImageDraw, ImageFont
        from ndu_real_materials.common import binding, write_json
        from .controllers import ControlPlan
        from .episode import EpisodeHost
        from .neural import ReceiptPortfolioModel
        from .candidate_selector import PROFILE as SELECTOR_PROFILE

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = Image.new("RGB", (420, 1000), "white")
            ImageDraw.Draw(source).text(
                (20, 20),
                "TOTAL 42.00",
                fill="black",
                font=ImageFont.load_default(size=28),
            )
            source.save(root / "source.png")
            source.save(root / "overview.png")
            packet = {
                "schema": "ndu.real.public-case.v1",
                "case_id": "receipt",
                "prompt": "Read the total",
                "public_text": "",
                "overview": binding(root / "overview.png", root),
                "source_size": {"width": 420, "height": 1000},
                "initial_delivery": {"text": None, "image": None},
                "requirements": {"text": True, "image": False},
                "action_contract": {},
            }
            write_json(root / "case.json", packet)
            write_json(
                root / "reference.json",
                {
                    "role": "development",
                    "case_id": "receipt",
                    "source_group": "fixture-source",
                    "episode_group": "fixture-episode",
                    "source_image": binding(root / "source.png", root),
                },
            )
            control = ControlPlan()
            write_json(
                root / "control.json",
                {
                    "control": asdict(control),
                    "episode_wall_seconds": 60,
                    "fixed_schedule": ["PREPARE_ROI", "READ_ROI", "WRITE_TEXT"],
                    "seed": 0,
                },
            )
            torch.manual_seed(5)
            model = ReceiptPortfolioModel("ordinary")
            with torch.no_grad():
                model.answer.weight.zero_()
                model.answer.bias.zero_()
                model.box_delta.weight.zero_()
                model.box_delta.bias.copy_(torch.tensor([0.0, 10.0, 0.0, 10.0]))
            torch.save(model.state_dict(), root / "weights.pt")
            repository = Path(__file__).resolve().parents[2]
            tesseract = shutil.which("tesseract")
            self.assertIsNotNone(
                tesseract, "The real OCR integration requires tesseract"
            )
            languages = subprocess.check_output(
                [tesseract, "--list-langs"], stderr=subprocess.STDOUT
            ).decode()
            tessdata = re.search(r'List of available languages in "([^"]+)"', languages)
            self.assertIsNotNone(tessdata, languages)
            outcomes = {}
            for mode in (
                None,
                "current_only",
                "bounded",
                "selector_neural",
                "selector_rule",
            ):
                host = EpisodeHost(
                    {
                        "material_root": str(root),
                        "latency_weight": control.latency_weight,
                        "episode_wall_seconds": 60,
                        "python": sys.executable,
                        "pillow_path": str(Path(Image.__file__).parents[1]),
                        "scripts_root": str(repository / "scripts"),
                        "repository_root": str(repository),
                        "tesseract": tesseract,
                        "tessdata_dir": tessdata.group(1),
                        "ocr_library_dir": str(Path(tesseract).parent),
                    },
                    {
                        "role": "development",
                        "id": "receipt",
                        "source_id": "fixture-source",
                        "episode_group": "fixture-episode",
                        "packet": binding(root / "case.json", root),
                        "reference": binding(root / "reference.json", root),
                    },
                    {
                        "original_operation_id": "fixture-" + str(mode),
                        "control_plan": str(root / "control.json"),
                        "weights": str(root / "weights.pt"),
                        "model_sha256": binding(root / "weights.pt", root)["sha256"],
                        "core": "ordinary",
                        "controller": "tuned_fixed",
                        **(
                            {
                                "candidate_memory": profile(
                                    "bounded" if mode.startswith("selector_") else mode
                                )
                            }
                            if mode
                            else {}
                        ),
                        **(
                            {
                                "candidate_selector": {
                                    "schema": SELECTOR_PROFILE["schema"],
                                    "mode": "frozen_neural"
                                    if mode == "selector_neural"
                                    else "public_rule",
                                    "profile_sha256": canonical_sha(SELECTOR_PROFILE),
                                }
                            }
                            if mode and mode.startswith("selector_")
                            else {}
                        ),
                    },
                    root / str(mode),
                )
                # Host callback executes the actor's actual ROI and WRITE_TEXT;
                # this test does not claim the separate isolation boundary.
                process = subprocess.Popen(
                    host.command(),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=host.actor_output,
                )
                try:
                    for _ in range(5):
                        line = process.stdout.readline()
                        if not line:
                            process.wait(timeout=30)
                            self.fail(process.stderr.read().decode())
                        message = json.loads(line)
                        next_input = host.callback(message)
                        if next_input is None:
                            break
                        process.stdin.write(next_input)
                        process.stdin.flush()
                    process.stdin.close()
                    process.stdin = None
                    stdout, stderr = process.communicate(timeout=30)
                    self.assertEqual(
                        (process.returncode, stdout), (0, b""), stderr.decode()
                    )
                    self.assertTrue(host.stopped)
                    self.assertTrue(
                        all(row["parameters_unchanged"] for row in host.steps)
                    )
                    self.assertGreater(host.steps[0]["ocr"]["recognized_lines"], 0)
                    if mode is None:
                        self.assertNotIn("candidate_audit", host.steps[2])
                    else:
                        audit = read_audit(
                            host.actor_output,
                            host.steps[2]["candidate_audit"],
                            {"step": 2},
                        )
                        self.assertEqual(
                            host.delivery["text"],
                            audit["offered_candidates"][audit["selected_index"]][
                                "text"
                            ],
                        )
                        if mode.startswith("selector_"):
                            selector = json.loads(
                                (
                                    host.actor_output
                                    / host.steps[2]["selector_audit"]["path"]
                                ).read_text()
                            )
                            paired = selector["receipt"]
                            self.assertEqual(
                                selector["candidates"], audit["offered_candidates"]
                            )
                            self.assertEqual(
                                canonical_sha(selector["features"]),
                                audit["offered_features_sha256"],
                            )
                            expected_index = (
                                paired["frozen_neural_index"]
                                if mode == "selector_neural"
                                else paired["public_rule_index"]
                            )
                            self.assertEqual(audit["selected_index"], expected_index)
                            self.assertTrue(paired["same_support_for_both"])
                            self.assertEqual(
                                host.selector_audit_tail,
                                host.steps[-1]["selector_audit"]["sha256"],
                            )
                        outcomes[mode] = audit
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.communicate()
                    for stream in (process.stdin, process.stdout, process.stderr):
                        if stream is not None:
                            stream.close()
                    host.meter.finish()
            self.assertEqual(
                outcomes["current_only"]["raw_candidates"],
                outcomes["bounded"]["raw_candidates"],
            )
            self.assertEqual(
                outcomes["current_only"]["offered_candidates"],
                outcomes["current_only"]["raw_candidates"],
            )
            self.assertGreater(
                len(outcomes["bounded"]["offered_candidates"]),
                len(outcomes["bounded"]["raw_candidates"]),
            )
            self.assertTrue(
                any(step < 2 for step in outcomes["bounded"]["offered_observed_steps"])
            )


if __name__ == "__main__":
    unittest.main()
