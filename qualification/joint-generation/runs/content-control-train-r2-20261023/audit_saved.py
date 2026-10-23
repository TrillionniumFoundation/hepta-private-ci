"""Read saved new TRAIN artifacts only; no model training or formal data."""

import base64
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from PIL import Image

from data import parse_caption, templates
from independent.learning import CONTENT_PARAMETERS
from model import JointModel


started = time.process_time()
run = Path(__file__).resolve().parent
build = json.loads((run / "build.json").read_text())
result = json.loads((run / "train-result.json").read_text())
bases = {s: JointModel.load(run / f"base-{s}.npz") for s in (11, 23, 47)}
parameters, decoded = [], []
for arm, rows in build["candidates"].items():
    for row in rows:
        folder, seed = run / row["name"], row["seed"]
        with np.load(folder / "gradient-updates.npz", allow_pickle=False) as raw:
            names = sorted(k.split("/", 1)[1] for k in raw.files if k.startswith("first_gradient/"))
            first = {k: raw["first_gradient/" + k].copy() for k in names}
            norm = np.sqrt(sum(float(np.sum(g*g)) for g in first.values()))
            scale = min(1, 5/max(norm, 1e-300))
            errors = []
            norms = {}
            for key in names:
                g = first[key] * scale
                expected = -row["lr"] * g/(np.abs(g)+1e-8)
                errors.append(float(np.max(np.abs(raw["first_delta/"+key]-expected))))
                norms[key] = {name: float(np.linalg.norm(raw[name+"/"+key])) for name in
                              ("first_gradient", "last_gradient", "first_delta", "final_delta")}
            if max(errors) > 1e-12 or any(v["final_delta"] == 0 for v in norms.values()):
                raise RuntimeError("invalid/missing actual gradient update evidence: " + row["name"])
            if len(raw["loss"]) != row["updates"]:
                raise RuntimeError("loss/update count mismatch")
        if not arm.endswith("_R"):
            trained = JointModel.load(folder / "model.npz")
            if any(not np.array_equal(trained.params[k], bases[seed].params[k]) for k in ("decoder", "decoder_bias")):
                raise RuntimeError("decoder changed")
            if any(np.array_equal(trained.params[k], bases[seed].params[k]) for k in CONTENT_PARAMETERS):
                raise RuntimeError("dense content parameter did not change")
        parameters.append({"name": row["name"], "updates": row["updates"], "first_adam_delta_max_error": max(errors),
                           "parameter_norms": norms})
for arm, choice in result["selected"].items():
    for seed in (11, 23, 47):
        folder = run / f"{arm}-{seed}-{choice['lr']}"
        obj = json.loads((folder / "external-output.json").read_text())
        png = (folder / "external-output.png").read_bytes()
        if hashlib.sha256(png).hexdigest() != obj["png_sha256"] or base64.b64decode(obj["png_base64"]) != png:
            raise RuntimeError("external PNG/hash mismatch")
        pixels = np.asarray(Image.open(folder / "external-output.png").convert("RGB"), dtype=np.float64).reshape(-1)/255
        distances = np.mean((templates()-pixels)**2, axis=1)
        text, image = parse_caption(obj["caption"]), int(np.argmin(distances))
        decoded.append({"arm": arm, "seed": seed, "caption": obj["caption"], "observed_text": text,
                        "observed_png_scene": image, "hand_target": 1, "joint_correct": text == image == 1,
                        "minimum_template_mse": float(distances.min()), "png_sha256": obj["png_sha256"]})
report = {"all_45_candidates_checked": len(parameters) == 45, "parameter_updates": parameters,
          "external_actual_png_observations": decoded, "audit_cpu_seconds_before_receipt": time.process_time()-started,
          "scope": "post-build read-only evidence audit; not another TRAIN or formal evaluation"}
(run / "evidence-audit.json").write_text(json.dumps(report, indent=2, sort_keys=True)+"\n")
print(json.dumps({"candidates_checked": len(parameters), "all_first_delta_checks_pass": True,
                  "external_joint_correct": sum(r["joint_correct"] for r in decoded), "external_outputs": len(decoded),
                  "audit_cpu_seconds": report["audit_cpu_seconds_before_receipt"]}))
