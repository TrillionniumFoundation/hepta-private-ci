"""Actually render all finite semantic endpoints before building their return table."""

import argparse
import json
from pathlib import Path
import resource
import shutil
import time

import torch

from ...abc_recovery.base_recovery import file_sha, write_json
from ...next_20261025.media.repair.cache_audit import CachedFrozenAudit
from ...next_20261025.media.runtime import observe_bundle
from ...next_20261025.media.ensemble_event import score_ensemble_observation
from ...v6.observer import Recognizer
from .model import FrozenPortfolio, regression_matrix


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    settings = json.loads(args.config.read_text())
    args.output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    start, cpu = time.perf_counter_ns(), time.process_time_ns()
    source = Path(__file__).parent
    pins = {str(x.resolve()): file_sha(x) for x in source.glob("*.py")}
    pins[str(args.config.resolve())] = file_sha(args.config)
    codecs = {name: str(Path(shutil.which(name)).resolve()) for name in ("ffmpeg", "ffprobe")}
    pins.update({path: file_sha(Path(path)) for path in codecs.values()})
    write_json(args.output / "REGISTRATION.json", {
        "schema": "hepta.advance.actual-codec-endpoints.v1", "registered_unix_ns": time.time_ns(),
        "actions": list(range(100)), "code": "10*left+right", "source_pins": pins,
        "renderer_assets": settings["renderer_paths"], "codecs": codecs,
        "utility": "Mean of four actual modality success indicators against each possible target",
        "target_order": "Observation is complete and saved before any hypothetical target is scored",
        "source_scope": "No MNIST/XNIST writer or speech input recording is accessed; finite decoder conditions only",
        "observer_scope": "Measured actual-codec return table is used for training. The same metric on new inputs is not an independent observer-family test",
        "unknown_PCM": "Reject, never fill from semantic action or target", "new_confirmation_sources_opened": False})
    portfolio = FrozenPortfolio(settings["renderer_paths"])
    observer = Recognizer().eval().requires_grad_(False)
    observer.load_state_dict(torch.load(settings["image_observer"], weights_only=True, map_location="cpu")["state_dict"])
    audit = CachedFrozenAudit(settings["asr_assets"], args.output / "event-observer", settings["event_cache"])
    write_json(args.output / "OBSERVER.json", audit.receipt)
    utility, strict, rows = [], [], []
    for action in range(100):
        directory = args.output / "raw" / f"action-{action:02d}"
        generated = portfolio.render(action, directory, f"advance:endpoint:{action}")
        observed = observe_bundle({name: row["path"] for name, row in generated["output"]["files"].items()},
                                  observer, audit)
        write_json(directory / "TARGET_FREE_OBSERVATION.json", observed)
        scores = [score_ensemble_observation(observed, [target // 10, target % 10]) for target in range(100)]
        utility.append([sum(row["success"].values()) / 4 for row in scores])
        strict.append([int(row["joint_success"]) for row in scores])
        row = {"action": action, "generation": generated, "target_free_observation": observed,
               "utility_by_target": utility[-1], "strict_success_by_target": strict[-1]}
        write_json(directory / "RETURN_ROW.json", row)
        rows.append(row)
        if action % 20 == 19:
            print(json.dumps({"actual_endpoints": action + 1}), flush=True)
    portfolio.assert_frozen()
    if any(file_sha(Path(path)) != value for path, value in pins.items()):
        raise ValueError("Endpoint execution source or actual codec changed")
    matrix = torch.tensor(utility, dtype=torch.float64)
    _, degeneracy = regression_matrix(matrix, "entropic")
    result = {"schema": "hepta.advance.codec-return-table.v1", "status": "completed",
              "utility_action_by_target": utility, "strict_success_action_by_target": strict,
              "actual_endpoint_count": 100, "actual_output_file_count": 400,
              "asset_sha256": portfolio.asset_sha256,
              "renderer_parameter_sha256": portfolio.parameter_sha256,
              "diagonal_strict_success": sum(strict[i][i] for i in range(100)),
              "degeneracy": degeneracy, "asr_new_event_calls": audit.calls,
              "asr_exact_PCM_cache_hits": audit.hits,
              "clock_all_pass": all(all(row["target_free_observation"]["clock"][key] == value for key, value in
                                         {"audio_samples": 32000, "duration_ns": 4000000000,
                                          "sample_rate": 8000, "video_fps": 5, "video_frames": 20}.items()) for row in rows),
              "row_receipts": {str(args.output / "raw" / f"action-{i:02d}" / "RETURN_ROW.json"):
                               file_sha(args.output / "raw" / f"action-{i:02d}" / "RETURN_ROW.json") for i in range(100)},
              "registration_sha256": file_sha(args.output / "REGISTRATION.json"),
              "wall_ns_main": time.perf_counter_ns() - start, "cpu_ns_main": time.process_time_ns() - cpu,
              "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
              "new_confirmation_sources_opened": False}
    write_json(args.output / "ENDPOINTS.json", result)
    print(json.dumps({key: result[key] for key in ("status", "actual_endpoint_count", "diagonal_strict_success", "degeneracy")}), flush=True)


if __name__ == "__main__":
    main()
