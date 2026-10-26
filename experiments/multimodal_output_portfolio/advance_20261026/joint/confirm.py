"""Execute a frozen eight-branch actual-codec census, then attach offline targets."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import resource
import time
import traceback

import torch

from ...abc_recovery.base_recovery import file_sha, write_json
from ...next_20261025.media.ensemble_event import score_ensemble_observation
from ...next_20261025.media.repair.cache_audit import CachedFrozenAudit
from ...next_20261025.media.runtime import observe_bundle, render_state
from ...v6.neural import parameter_hash
from ...v6.observer import Recognizer
from ..input_codec import video_roundtrip
from .confirmation_data import InputCensus
from .confirmation_metrics import analyze
from .model import FrozenPortfolio, SemanticAdapter, ROUTES, pair_law, select_action
from .nll_model import load_adapter


def check_pins(spec):
    for path, expected in spec["frozen_candidate_sha256"].items():
        with Path(path).open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != expected:
            raise ValueError("Frozen execution dependency changed: " + path)


def load_models(spec):
    models = {}
    for arm in spec["arms"]:
        if arm["kind"] not in ("brier", "nll"):
            continue
        record = torch.load(arm["checkpoint"], weights_only=True, map_location="cpu")
        if arm["kind"] == "nll":
            model = load_adapter(arm["checkpoint"])
        else:
            if record["schema"] != "hepta.advance.semantic-adapter.v1":
                raise ValueError("Wrong retained Brier checkpoint schema")
            model = SemanticAdapter().eval().requires_grad_(False)
            model.load_state_dict(record["state_dict"], strict=True)
        if (record["parameter_sha256"] != parameter_hash(model)
                or record["endpoint_sha256"] != spec["endpoint_sha256"]):
            raise ValueError("Actual adapter identity does not match the measured endpoint table")
        models[arm["name"]] = model
    return models


@torch.inference_mode()
def decision(arm, models, encoding, utility, strict):
    started = time.perf_counter_ns()
    if arm["kind"] == "unchanged":
        return {"action": None, "q": None, "wall_ns": time.perf_counter_ns() - started}
    probability = encoding.raw_probabilities
    if arm["name"] in models:
        probability = models[arm["name"]](encoding.features, probability,
                                          torch.tensor([encoding.route == "text"]))
    q = pair_law(probability)
    action, moments = select_action(q, utility, "entropic")
    code = int(action[0])
    return {"action": code, "q": q[0].double().tolist(),
            "predicted_strict_success": float(q.double() @ strict[code]),
            "predicted_entropic_moment": float(moments[0, code]),
            "wall_ns": time.perf_counter_ns() - started, "targets_available": False}


def run(spec, protocol, output):
    check_pins(spec)
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    settings = json.loads(Path(spec["config"]).read_text())
    endpoint = json.loads(Path(spec["endpoints"]).read_text())
    portfolio = FrozenPortfolio(settings["renderer_paths"])
    if portfolio.parameter_sha256 != endpoint["renderer_parameter_sha256"]:
        raise ValueError("Actual confirmation renderer differs from the measured endpoints")
    models = load_models(spec)
    observer = Recognizer().eval().requires_grad_(False)
    observer.load_state_dict(torch.load(settings["image_observer"], weights_only=True, map_location="cpu")["state_dict"])
    audit = CachedFrozenAudit(settings["asr_assets"], output / "event-observer", settings["event_cache"])
    write_json(output / "OBSERVER.json", audit.receipt)
    # Every executable/model dependency is checked before opening the new census.
    census = InputCensus(settings, spec, protocol)
    utility = torch.tensor(endpoint["utility_action_by_target"], dtype=torch.float64)
    strict = torch.tensor(endpoint["strict_success_action_by_target"], dtype=torch.float64)
    rows, encode_wall_ns, input_wall_ns = [], 0, 0
    clock = {"audio_samples": 32000, "duration_ns": 4000000000, "sample_rate": 8000,
             "video_fps": 5, "video_frames": 20}
    for case in range(spec["pair_count"]):
        input_start = time.perf_counter_ns()
        request = census.case(case, output / "input" / f"case-{case:03d}")
        input_wall_ns += time.perf_counter_ns() - input_start
        if spec["mode"] == "old_smoke" and case == 0:
            _, receipt = video_roundtrip(request.tasks["video"].video, output / "old-video-input-check")
            write_json(output / "OLD_VIDEO_INPUT_ROUNDTRIP.json", receipt)
        for route in spec["routes"]:
            directory = output / "raw" / f"case-{case:03d}" / route
            directory.mkdir(parents=True, exist_ok=False)
            encoding = portfolio.encode(request.tasks[route])
            encode_wall_ns += encoding.wall_ns
            write_json(directory / "PUBLIC_ENCODING.json", {"identity": request.identity,
                "route": route, "features": encoding.features.tolist(),
                "raw_probabilities": encoding.raw_probabilities.tolist(), "encode_wall_ns": encoding.wall_ns,
                "target_supplied": False, "renderer_parameter_sha256": portfolio.parameter_sha256})
            rotation = (case + 2 * ROUTES.index(route)) % len(spec["arms"])
            execution_arms = spec["arms"][rotation:] + spec["arms"][:rotation]
            for position, arm in enumerate(execution_arms):
                arm_dir = directory / arm["name"]
                arm_dir.mkdir(parents=True, exist_ok=False)
                public = decision(arm, models, encoding, utility, strict)
                write_json(arm_dir / "PUBLIC_DECISION.json", public)
                request_id = f"advance:joint:{spec['mode']}:{case}:{route}:{arm['name']}"
                if arm["kind"] == "unchanged":
                    generated = render_state(portfolio.model.core, portfolio.model.speech, portfolio.model.motion,
                                             encoding.state, arm_dir / "output", request_id)
                else:
                    generated = portfolio.render(public["action"], arm_dir / "output", request_id)
                observed = observe_bundle({name: item["path"] for name, item in generated["output"]["files"].items()},
                                          observer, audit)
                write_json(arm_dir / "TARGET_FREE_OBSERVATION.json", observed)
                if observed["target_supplied"] or any(observed["clock"][key] != value for key, value in clock.items()):
                    raise ValueError("Actual target-free observation or physical presentation clock failed")
                scored = score_ensemble_observation(observed, request.expected_for_offline_scoring)
                value, success = sum(scored["success"].values()) / 4, int(scored["joint_success"])
                target = request.expected_for_offline_scoring[0] * 10 + request.expected_for_offline_scoring[1]
                if public["action"] is not None:
                    code = public["action"]
                    if value != float(utility[code, target]) or success != int(strict[code, target]):
                        raise ValueError("New actual codec output disagrees with its frozen endpoint return table")
                    probability = public["q"][target]
                    prediction = {"predicted_strict_success": public["predicted_strict_success"],
                                  "predicted_entropic_moment": public["predicted_entropic_moment"],
                                  "posterior_NLL": -math.log(probability) if probability > 0 else None,
                                  "posterior_Brier": sum((p - int(i == target)) ** 2 for i, p in enumerate(public["q"])),
                                  "endpoint_regret": float(utility[:, target].max()) - value}
                else:
                    prediction = {key: None for key in ("predicted_strict_success", "predicted_entropic_moment",
                                                        "posterior_NLL", "posterior_Brier", "endpoint_regret")}
                row = {**request.identity, "route": route, "arm": arm["name"], "action": public["action"],
                       "physical_execution_order": position, "execution_rotation": rotation,
                       "utility": value, "strict_success": success, "modality_success": scored["success"],
                       **prediction, "shared_input_encode_wall_ns": encoding.wall_ns,
                       "input_preparation_wall_ns": request.input_preparation_wall_ns[route],
                       "decision_wall_ns": public["wall_ns"], "generation_wall_ns": generated["execution_wall_ns"],
                       "codec_wall_ns": generated["output"]["codec_wall_ns"],
                       "generation_verification_wall_ns": generated["output"]["verification_wall_ns"],
                       "audit_wall_ns": observed["audit_wall_ns"],
                       "deployment_wall_ns_charging_full_input": request.input_preparation_wall_ns[route] + encoding.wall_ns + public["wall_ns"] +
                            generated["execution_wall_ns"] + observed["audit_wall_ns"],
                       "record": str(arm_dir / "RECORD.json")}
                write_json(arm_dir / "RECORD.json", {"summary": row, "generation": generated,
                    "observation_sha256": file_sha(arm_dir / "TARGET_FREE_OBSERVATION.json"),
                    "public_decision_sha256": file_sha(arm_dir / "PUBLIC_DECISION.json"),
                    "private_scoring_after_observation": scored})
                rows.append(row)
        print(json.dumps({"completed_source_pairs": case + 1, "actual_four_modal_bundles": len(rows)}), flush=True)
    portfolio.assert_frozen()
    for arm in spec["arms"]:
        if arm["name"] in models and parameter_hash(models[arm["name"]]) != arm["parameter_sha256"]:
            raise ValueError("Frozen posterior adapter changed during execution")
    check_pins(spec)
    write_json(output / "ROWS.json", rows)
    result = {"schema": "hepta.advance.joint-actual-confirmation.v1", "status": "completed",
              "protocol_sha256": file_sha(protocol), "mode": spec["mode"], "analysis": analyze(rows, spec),
              "actual_output_file_count": 4 * len(rows), "all_physical_clocks_pass": True,
              "all_registered_branches_retained": True, "all_frozen_components_unchanged": True,
              "ASR_new_event_calls": audit.calls, "ASR_exact_PCM_cache_hits": audit.hits,
              "shared_encoder_wall_ns": encode_wall_ns, "input_construction_wall_ns": input_wall_ns,
              "runtime_accounting": "Input preparation and encoding are physically shared across branches; per-deployment estimates charge each in full. Codec timings are overlapping components, not extra additive work. No cold-ASR inference was paid when exact historical PCM reuse succeeded. BLAS/Torch and video encoding are single-threaded; the frozen output readback decoder uses its existing defaults.",
              "rows_sha256": file_sha(output / "ROWS.json"), "wall_ns_main": time.perf_counter_ns() - wall,
              "cpu_ns_main": time.process_time_ns() - cpu,
              "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
              "new_confirmation_sources_opened": spec["mode"] == "confirmation"}
    write_json(output / "RESULTS.json", result)
    print(json.dumps({"status": result["status"], "actual_bundles": len(rows),
                      "primary_gate": result["analysis"]["primary_gate"]}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("protocol", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    spec = json.loads(args.protocol.read_text())
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "STARTED.json", {"protocol": str(args.protocol.resolve()),
        "protocol_sha256": file_sha(args.protocol), "started_unix_ns": time.time_ns(), "mode": spec["mode"]})
    try:
        run(spec, args.protocol, args.output)
    except Exception:
        write_json(args.output / "FAILURE.json", {"traceback": traceback.format_exc(),
            "mode": spec["mode"], "partial_outputs_preserved": True, "outcomes_must_not_be_used_to_change_candidate": True})
        raise


if __name__ == "__main__":
    main()
