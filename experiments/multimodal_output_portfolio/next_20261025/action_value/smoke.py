"""Mechanism check on four already-open historical selection pairs."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

import torch

from ...abc_next.sensor_run import load_sensor
from ...abc_next.value import load_controller
from ...abc_recovery.base_recovery import file_sha, write_json
from ...closure_20261025.control.registry import load_model
from ...v6.data import Observation
from ...v7.data import VIEWS, make_batch
from ...v7.sources import load_roles
from .evaluate import counterfactuals, request
from .model import load


def run(asset, development, output):
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    fitted = json.loads((development / "result.json").read_text())
    record = fitted["records"][0]; chosen = record["candidates"][record["selected_index"]]
    if record["seed"] != 17 or file_sha(Path(chosen["checkpoint"])) != chosen["checkpoint_sha256"]:
        raise ValueError("Frozen selected seed17 candidate required")
    policy = load(Path(chosen["checkpoint"]))
    teacher = load_controller(asset / "abc3-runs/controllers-001/seed-17/output_ndu/controller.pt")
    sensor = load_sensor(asset / "abc3-runs/public-sensor-001/sensor.pt")
    model = load_model(asset, 17)
    corpus = load_roles(asset / "abc2-assets/mnist", asset / "abc2-runs/source-recovery-001/source-manifest.json", roles=("forecast_calibration",))
    spec = {"initial_namespace": "rich-value-old-smoke-initial", "future_namespace": "rich-value-old-smoke-future"}
    requests, diagnostic_nodes, media_references = [], [], []
    with (output / "media.bin").open("x+b") as media, gzip.open(output / "commitments.jsonl.gz", "xt") as commits, gzip.open(output / "diagnostic-commitments.jsonl.gz", "xt") as offline_commits:
        for view in VIEWS:
            batch = make_batch(corpus, "forecast_calibration", 4, 202610251899, view=view, offset=448)
            for case in range(4):
                observation = Observation(*(getattr(batch.observation, k)[case:case + 1].clone() for k in ("pixels", "mask", "text_tokens")))
                values, retained = {}, None
                for name in ("cached_teacher", "rich_paired"):
                    row, diagnostic = request(model._model, observation, teacher, policy, sensor, policy=name,
                        seed=17, case=case, view=view, draw=0, spec=spec, media=media, commitments=commits)
                    if row["status"] != "completed": raise ValueError(row)
                    values[name] = row; requests.append(row)
                    media_references.extend([row["terminal"], row["root_stop"]])
                    if name == "rich_paired": retained = diagnostic
                a, b = values.values()
                if a["decisions"][0]["public_sha256"] != b["decisions"][0]["public_sha256"]:
                    raise ValueError("Initial public state differs")
                if a["path"] == b["path"] and a["terminal"]["sha256"] != b["terminal"]["sha256"]:
                    raise ValueError("Shared actual path differs")
                if retained:
                    value = counterfactuals(model._model, teacher, retained, b, spec, media, offline_commits)
                    if len(value["alternatives"]) != 5 or sum(x["reused_actual_selected_result"] for x in value["alternatives"]) != 1:
                        raise ValueError("H1 counterfactual branch census differs")
                    diagnostic_nodes.append(value)
                    media_references.extend(x["media"] for x in value["alternatives"])
    model.verify_integrity()
    with (output / "media.bin").open("rb") as media:
        for saved in media_references:
            media.seek(saved["offset"])
            if hashlib.sha256(media.read(204)).hexdigest() != saved["sha256"]: raise ValueError("Actual archived media differs")
    write_json(output / "requests.json", requests); write_json(output / "counterfactuals.json", diagnostic_nodes)
    result = {"status": "passed", "historical_source_pairs": 4, "new_independent_sources": 0, "requests": len(requests),
        "counterfactual_nodes": len(diagnostic_nodes), "actual_media_references_checked": len(media_references),
        "checkpoint_sha256": chosen["checkpoint_sha256"], "parameter_or_threshold_updates": False,
        "selection_was_not_repeated": True, "scope": "Mechanism, causality, matching paths and actual media retention only; not new quality evidence",
        "files_sha256": {p.name: file_sha(p) for p in output.iterdir() if p.is_file()}}
    write_json(output / "result.json", result); print(json.dumps(result))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--asset-root", type=Path, required=True); p.add_argument("--development", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args(); run(a.asset_root, a.development, a.output)
