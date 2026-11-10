"""Real OCR and Torch process wiring; synthetic fixture, no efficacy/isolation claim."""

from dataclasses import asdict
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from .candidate_runtime import read_audit
from .objective import canonical_sha
from .test_candidate_runtime import profile


class PublicRetentionActorProcessTests(unittest.TestCase):
    def test_both_retention_arms_reach_real_ocr_actor_with_fixed_public_selector(self):
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
            for mode in ("current_only", "bounded"):
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
                        "candidate_memory": profile(mode),
                        "candidate_selector": {
                            "schema": SELECTOR_PROFILE["schema"],
                            "mode": "public_rule",
                            "profile_sha256": canonical_sha(SELECTOR_PROFILE),
                        },
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
                    audit = read_audit(host.actor_output, host.steps[2]["candidate_audit"], {"step": 2})
                    selector = json.loads((host.actor_output / host.steps[2]["selector_audit"]["path"]).read_text())
                    self.assertEqual(selector["profile"]["mode"], "public_rule")
                    self.assertEqual(selector["profile"]["profile_sha256"], canonical_sha(SELECTOR_PROFILE))
                    self.assertEqual(selector["candidates"], audit["offered_candidates"])
                    self.assertEqual(audit["selected_index"], selector["receipt"]["public_rule_index"])
                    self.assertEqual(host.delivery["text"], audit["offered_candidates"][audit["selected_index"]]["text"])
                    self.assertEqual(host.selector_audit_tail, host.steps[-1]["selector_audit"]["sha256"])
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
