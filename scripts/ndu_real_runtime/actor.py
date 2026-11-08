"""Long-lived, per-episode actor with a current-public-observation JSONL API.

The independent host launches this program inside the actual filesystem/network
boundary, supplies only a public case directory, and executes proposed actions.
The actor cannot open the source registry or reference directory. A new process
is required for every episode; hidden evaluator results never enter this stream.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import torch

from .controllers import ACTIONS, ControlPlan, Controller, PublicState
from .metering import Meter, atomic_json, file_sha, transport_receipt, canonical_sha
from .neural import FittedPredictor, ReceiptPortfolioModel
from .objective import utility_profile
from .ocr import FIELDS, candidate_features, extract_ocr, requested_field


def parameter_sha(model):
    digest = hashlib.sha256()
    for name, value in sorted(model.state_dict().items()):
        tensor = value.detach().cpu().contiguous()
        digest.update(name.encode())
        digest.update(str((str(tensor.dtype), tuple(tensor.shape))).encode())
        digest.update(tensor.numpy().tobytes())
    return digest.hexdigest()


def memory_sha(memory):
    if memory is None:
        return None
    digest = hashlib.sha256()
    for layer in memory:
        for name, value in sorted(layer.items()):
            digest.update(name.encode())
            digest.update(value.detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def public_path(root, name):
    if not isinstance(name, str) or Path(name).name != name or name in {".", ".."}:
        raise ValueError("Public paths must be a single file name")
    path = root / name
    if path.is_symlink() or not path.is_file():
        raise ValueError("Public input must be a regular file")
    return path


def metadata(packet, state, budget):
    field = requested_field(packet["prompt"])
    delivery, requirements = state["delivery"], packet["requirements"]
    return [*[float(field == name) for name in FIELDS],
            float(delivery["text"] is not None), float(delivery["image"] is not None),
            float(requirements["text"]), float(requirements["image"]),
            float(state["prepared_roi"] is not None), float(state["observation"]["kind"] == "roi"),
            0.0, 0.0, min(state["ocr_line_count"] / 100, 1), min(state["step"] / 8, 1),
            max(0.0, min(state["remaining_seconds"] / budget, 1)),
            float(bool(state["delivery"]["text"]) and len(state["delivery"]["text"]) < 256)]


def make_action(action, selected, delta, source_size, state):
    width, height = source_size
    box = np.asarray(selected["bbox"], dtype=float) + np.asarray(delta) * [width, height, width, height]
    x1, y1, x2, y2 = [int(round(v)) for v in box]
    x1, y1 = min(max(0, x1), width-1), min(max(0, y1), height-1)
    x2, y2 = min(max(x1+1, x2), width), min(max(y1+1, y2), height)
    arguments = {}
    if action == "WRITE_TEXT":
        # A committed handoff is public; preserving it does not require a target.
        arguments["text"] = state["delivery"]["text"] if state.get("text_committed") else selected["text"]
        if arguments["text"] is None:
            arguments["text"] = ""
    elif action in {"PREPARE_ROI", "RENDER_IMAGE"}:
        arguments["bbox"] = [x1, y1, x2, y2]
    return {"schema": "ndu.real.actor-action.v1", "action": action, "arguments": arguments}


_active_meter = None
_last_meter_receipt = None


def finish_meter(meter):
    global _last_meter_receipt
    _last_meter_receipt = transport_receipt(meter.finish())
    return _last_meter_receipt


def run():
    global _active_meter
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-dir", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--expected-weights-sha256", required=True)
    parser.add_argument("--core", choices=("ordinary", "hepta"), required=True)
    parser.add_argument("--controller", choices=("initial", "light", "ndu", "ndu_policy", "tuned_fixed", "voi", "mpc"), required=True)
    parser.add_argument("--control-plan", type=Path, required=True)
    parser.add_argument("--deployment-profile", type=Path)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--tesseract", default="tesseract")
    parser.add_argument("--tessdata-dir")
    parser.add_argument("--ocr-library-dir")
    parser.add_argument("--start-step", type=int, default=0)
    parser.add_argument("--max-decisions", type=int, default=8)
    parser.add_argument("--training-exploration", action="store_true")
    args = parser.parse_args()
    torch.set_num_threads(1)
    if torch.get_num_interop_threads() != 1:
        torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    if file_sha(args.weights) != args.expected_weights_sha256:
        raise ValueError("Actor model bytes differ from the host pin")
    plan_json = json.loads(args.control_plan.read_text())
    if set(plan_json) != {"control", "episode_wall_seconds", "fixed_schedule", "seed"}:
        raise ValueError("Unexpected public control-plan fields")
    plan = ControlPlan(**plan_json["control"])
    profile_digest = canonical_sha(utility_profile(plan))
    control_digest = canonical_sha(asdict(plan))
    if args.deployment_profile:
        deployment = json.loads(args.deployment_profile.read_text())
        if (set(deployment) != {"schema", "weights_sha256", "core", "memory_mode", "utility_profile_sha256",
                               "rubric_sha256", "recursive_policy_trained", "control_profile_sha256"}
                or deployment.get("schema") != "ndu.real.deployment-profile.v1"
                or deployment.get("weights_sha256") != args.expected_weights_sha256
                or deployment.get("core") != args.core or deployment.get("memory_mode") != plan.memory_mode
                or deployment.get("utility_profile_sha256") != profile_digest
                or deployment.get("control_profile_sha256") != control_digest
                or args.controller == "ndu_policy" and not deployment.get("recursive_policy_trained")):
            raise ValueError("Training/deployment model or objective profile differs")
    elif plan.memory_mode != "reset" or args.controller == "ndu_policy":
        raise ValueError("Persistent or learned NDU policy requires its training deployment profile")
    if plan.memory_mode == "persistent" and args.start_step != 0:
        raise ValueError("Persistent actor cannot resume without its complete episode memory")
    root = args.public_dir.resolve(strict=True)
    packet = json.loads(public_path(root, "case.json").read_text())
    expected = {"schema", "case_id", "prompt", "public_text", "overview", "source_size", "initial_delivery", "requirements", "action_contract"}
    if set(packet) != expected or packet["schema"] != "ndu.real.public-case.v1":
        raise ValueError("Invalid public case projection")
    model = ReceiptPortfolioModel(args.core)
    model.load_state_dict(torch.load(args.weights, map_location="cpu", weights_only=True), strict=True)
    model.eval()
    if not 0 <= args.start_step < 8 or not 1 <= args.max_decisions <= 8 - args.start_step:
        raise ValueError("Decision window exceeds the frozen episode bound")
    baseline_parameters = parameter_sha(model)
    cache, memory = {}, None
    fixed_schedule = [action for action in plan_json["fixed_schedule"]
                      if not (action == "WRITE_TEXT" and packet["initial_delivery"]["text"] is not None)
                      and not (action == "RENDER_IMAGE" and (not packet["requirements"]["image"]
                               or packet["initial_delivery"]["image"] is not None))]
    print(json.dumps({"schema": "ndu.real.actor-ready.v1", "case_id": packet["case_id"],
                      "weights_sha256": args.expected_weights_sha256,
                      "utility_profile_sha256": profile_digest, "memory_mode": plan.memory_mode,
                      "control_profile_sha256": control_digest,
                      "parameters_sha256": baseline_parameters}), flush=True)
    for sequence, line in enumerate(sys.stdin, args.start_step):
        if len(line.encode()) > 131072 or sequence >= args.start_step + args.max_decisions:
            raise ValueError("Actor public stream exceeds the locked bound")
        state = json.loads(line)
        required = {"schema", "case_id", "step", "remaining_seconds", "prepared_roi", "observation", "delivery", "text_committed", "forced_action"}
        if (set(state) != required or state["schema"] != "ndu.real.actor-step.v1"
                or state["case_id"] != packet["case_id"] or state["step"] != sequence):
            raise ValueError("Unexpected episode input, label or future field")
        meter = Meter(f"{args.operation_id}/decision/{sequence:02d}",
                      journal_path=Path.cwd() / f"decision-{sequence:02d}.meter.jsonl")
        _active_meter = meter
        if not args.training_exploration and (args.controller == "initial"
                or (args.controller == "tuned_fixed" and sequence >= len(fixed_schedule))):
            # An initial-delivery baseline/final fixed STOP does no unnecessary
            # encoding. Actual process/model loading remains host-metered.
            print(json.dumps({"schema": "ndu.real.actor-observation.v1", "case_id": packet["case_id"],
                "step": sequence, "action": {"schema": "ndu.real.actor-action.v1", "action": "STOP", "arguments": {}},
                "public_features": [], "public_metadata": [], "controller": {"forecast_calls": 0},
                "utility_profile_sha256": profile_digest, "memory_mode": plan.memory_mode,
                "control_profile_sha256": control_digest,
                "meter": finish_meter(meter), "ocr": None, "weights_sha256": args.expected_weights_sha256,
                "parameters_unchanged": parameter_sha(model) == baseline_parameters}, separators=(",", ":")), flush=True)
            break
        observed = state["observation"]
        if set(observed) != {"path", "sha256", "bbox", "kind"} or observed["kind"] not in {"overview", "roi"}:
            raise ValueError("Invalid currently available image observation")
        image_path = public_path(root, observed["path"])
        with meter.stage("codec", "current image binding"):
            if file_sha(image_path) != observed["sha256"]:
                raise ValueError("Current image bytes changed")
        if observed["sha256"] not in cache:
            with meter.stage("encoder", "actual pixel OCR"):
                lines, ocr_record = extract_ocr(image_path, executable=args.tesseract,
                    tessdata_dir=args.tessdata_dir, library_dir=args.ocr_library_dir,
                    evidence_dir=Path.cwd(), evidence_prefix=f"ocr-{sequence:02d}")
            with meter.stage("encoder", "public content features"):
                candidates, features = candidate_features(lines, prompt=packet["prompt"], image_path=image_path,
                    source_size=(packet["source_size"]["width"], packet["source_size"]["height"]),
                    observation_bbox=observed["bbox"], public_text=packet["public_text"])
            cache[observed["sha256"]] = (candidates, features, len(lines), ocr_record)
        candidates, features, line_count, ocr_record = cache[observed["sha256"]]
        state["ocr_line_count"] = line_count
        meta = metadata(packet, state, plan_json["episode_wall_seconds"])
        with torch.inference_mode():
            public, logits, delta, memory = model.public_state_step(torch.from_numpy(features), meta,
                memory=memory, memory_mode=plan.memory_mode, meter=meter)
            selected_index = int(logits.argmax().item())
        legal = tuple(action for action in ACTIONS
                      if not (action == "READ_ROI" and state["prepared_roi"] is None)
                      and not (action == "WRITE_TEXT" and state["text_committed"])
                      and not (action == "RENDER_IMAGE" and (not packet["requirements"]["image"]
                               or packet["initial_delivery"]["image"] is not None)))
        public_state = PublicState(tuple(float(v) for v in public.tolist()), state["remaining_seconds"], sequence, legal)
        controller = Controller(args.controller, FittedPredictor(model, meter=meter, memory_mode=plan.memory_mode), plan,
                                fixed_schedule=fixed_schedule, seed=plan_json["seed"])
        if state["forced_action"] is not None:
            if not args.training_exploration or state["forced_action"] not in legal:
                raise ValueError("Only the separate training exploration permits a forced legal action")
            action = state["forced_action"]
            details = {"training_exploration_override": True, "forecast_calls": 0,
                       "prediction_is_external_evidence": False}
        else:
            with meter.stage("planning", "deployed controller"):
                action, details = controller.choose(public_state)
        output = make_action(action, candidates[selected_index], delta[selected_index].tolist(),
                             (packet["source_size"]["width"], packet["source_size"]["height"]), state)
        result = {"schema": "ndu.real.actor-observation.v1", "case_id": packet["case_id"], "step": sequence,
                  "action": output, "public_features": list(public_state.features),
                  "public_metadata": meta, "controller": details, "meter": finish_meter(meter),
                  "remaining_seconds": state["remaining_seconds"], "legal_actions": list(legal),
                  "memory_mode": plan.memory_mode, "memory_sha256": memory_sha(memory),
                  "utility_profile_sha256": profile_digest,
                  "control_profile_sha256": control_digest,
                  "ocr": ocr_record, "weights_sha256": args.expected_weights_sha256,
                  "parameters_unchanged": parameter_sha(model) == baseline_parameters}
        if args.training_exploration:
            result.update(candidate_features=features.tolist(), candidate_metadata=candidates)
        print(json.dumps(result, separators=(",", ":"), allow_nan=False), flush=True)
        if action == "STOP":
            break
    return 0


def main():
    try:
        return run()
    except BaseException as error:
        measured = _last_meter_receipt
        if _active_meter is not None and not _active_meter.closed and not _active_meter.stack:
            measured = finish_meter(_active_meter)
        # A killed process cannot execute this path; the host explicitly marks
        # such subcategory measurements unknown while retaining total elapsed.
        atomic_json(Path.cwd() / "actor-failure.json", {"schema": "ndu.real.actor-failure.v1",
            "error_type": type(error).__name__, "message": str(error), "meter": measured})
        raise


if __name__ == "__main__":
    raise SystemExit(main())
