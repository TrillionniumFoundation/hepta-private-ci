"""Trusted real-image action host and separately executed, pinned scorer.

The host can read references for source-image routing. Only its strict public
projection crosses the mandatory Linux actor boundary. All reference scoring
runs after the actor exits; no score or future observation is returned to it.
"""

import argparse
import copy
import io
import json
from pathlib import Path
import resource
import shutil
import subprocess
import time
import traceback

from PIL import Image

from ndu_real_materials.common import read_bound, strict_json
from ndu_real_materials.isolate import run_actor
from .controllers import ACTIONS
from .metering import Meter, atomic_json, canonical_sha, file_sha
from .interval_costs import actor_receipts, close_observer_tail, reconcile


def bootstrap(config, module):
    roots = [config["pillow_path"], config["scripts_root"], config["repository_root"]]
    return [config["python"], "-c", "import sys;sys.path[:0]=" + repr(roots)
            + ";from " + module + " import main;raise SystemExit(main())"]


def png_bytes(image):
    stream = io.BytesIO()
    image.save(stream, format="PNG", optimize=False)
    return stream.getvalue()


def write_bytes_once(path, raw):
    with Path(path).open("xb") as stream:
        stream.write(raw)


class EpisodeHost:
    def __init__(self, config, case, profile, output, *, training=False, exploration=()):
        self.config, self.case, self.profile = config, case, profile
        self.root, self.output = Path(config["material_root"]), Path(output)
        self.output.mkdir(parents=True, exist_ok=False)
        self.public, self.actor_output = self.output / "public", self.output / "actor-output"
        self.public.mkdir()
        self.actor_output.mkdir()
        self.training, self.exploration = training, list(exploration)
        if case["role"] not in {"train", "development", "retention_validation"}:
            raise PermissionError("Sealed confirmation has no release in this pilot host")
        if training and case["role"] != "train":
            raise PermissionError("Training exploration accepts registered train sources only")
        self.operation_id = profile["original_operation_id"]
        self.meter = Meter(self.operation_id, journal_path=self.output / "deployment.meter.jsonl")
        self.started = time.perf_counter()
        with self.meter.stage("sync", "copy exact registered public packet"):
            packet_bytes = read_bound(self.root, case["packet"])
            self.packet = strict_json(packet_bytes)
            if self.packet["case_id"] != case["id"]:
                raise ValueError("Case packet identity mismatch")
            source_dir = (self.root / case["packet"]["path"]).parent
            write_bytes_once(self.public / "case.json", packet_bytes)
            for binding in [self.packet["overview"], self.packet["initial_delivery"]["image"]]:
                if binding is not None:
                    raw = read_bound(source_dir, {key: binding[key] for key in ("path", "sha256", "bytes")})
                    write_bytes_once(self.public / binding["path"], raw)
        # The source route is private host state, never part of actor input.
        self.reference = strict_json(read_bound(self.root, case["reference"]))
        if (self.reference["role"] != case["role"] or self.reference["case_id"] != case["id"]
                or self.reference["source_group"] != case["source_id"]
                or self.reference["episode_group"] != case["episode_group"]):
            raise ValueError("Private reference binding mismatch")
        self.source_binding = self.reference["source_image"]
        self.delivery = {"schema": "ndu.real.delivery.v1", "case_id": case["id"],
                         "text": self.packet["initial_delivery"]["text"], "image": None}
        initial_image = self.packet["initial_delivery"]["image"]
        if initial_image is not None:
            self.delivery["image"] = {key: initial_image[key] for key in ("path", "sha256", "bytes", "bbox")}
        size = self.packet["source_size"]
        self.source_size = (size["width"], size["height"])
        self.observation = {"path": "overview.png", "sha256": self.packet["overview"]["sha256"],
                            "bbox": [0, 0, *self.source_size], "kind": "overview"}
        self.prepared, self.steps, self.snapshots = None, [], []
        self.ready, self.stopped, self.budget_stop = False, False, False
        self.last_send = self.started
        if training:
            self.exploration = [action for action in self.exploration
                if not (action == "WRITE_TEXT" and self.delivery["text"] is not None)
                and not (action == "RENDER_IMAGE" and (not self.packet["requirements"]["image"]
                         or self.delivery["image"] is not None))]
            if not self.exploration or self.exploration[-1] != "STOP" or len(self.exploration) > 8:
                raise ValueError("Predeclared exploration must end in STOP within eight actions")
        self.snapshot()

    def snapshot(self):
        directory = self.output / f"delivery-{len(self.snapshots):02d}"
        directory.mkdir()
        delivery = copy.deepcopy(self.delivery)
        if delivery["image"] is not None:
            source = self.public / delivery["image"]["path"]
            shutil.copyfile(source, directory / "delivered.png")
            delivery["image"]["path"] = "delivered.png"
        atomic_json(directory / "delivery.json", delivery)
        self.snapshots.append(directory)

    def public_step(self):
        step = len(self.steps)
        remaining = max(0.0, self.config["episode_wall_seconds"] - (time.perf_counter() - self.started))
        if step >= 8 or remaining <= 0:
            self.budget_stop = True
            return None
        forced = self.exploration[step] if self.training else None
        value = {"schema": "ndu.real.actor-step.v1", "case_id": self.case["id"], "step": step,
                 "remaining_seconds": remaining, "prepared_roi": self.prepared,
                 "observation": self.observation, "delivery": self.delivery,
                 "text_committed": self.packet["initial_delivery"]["text"] is not None,
                 "forced_action": forced}
        self.last_send = time.perf_counter()
        return (json.dumps(value, separators=(",", ":"), allow_nan=False) + "\n").encode()

    def callback(self, line):
        value = line if isinstance(line, dict) else strict_json(line.encode() if isinstance(line, str) else line)
        if value.get("schema") == "ndu.real.actor-ready.v1":
            if self.ready or value["weights_sha256"] != self.profile["model_sha256"]:
                raise ValueError("Invalid actor readiness or actual model pin")
            self.ready = True
            self.ready_receipt = value
            self.startup_seconds = time.perf_counter() - self.started
            return self.public_step()
        if (not self.ready or self.stopped or value.get("schema") != "ndu.real.actor-observation.v1"
                or value.get("case_id") != self.case["id"] or value.get("step") != len(self.steps)
                or value.get("weights_sha256") != self.profile["model_sha256"]
                or value.get("parameters_unchanged") is not True):
            raise ValueError("Unexpected actor message or model mutation")
        if self.training != ("candidate_features" in value and "candidate_metadata" in value):
            raise ValueError("Deployment/training feature disclosure differs from the locked phase")
        action = value["action"]
        if set(action) != {"schema", "action", "arguments"} or action["schema"] != "ndu.real.actor-action.v1":
            raise ValueError("Action is outside the frozen interface")
        name, arguments = action["action"], action["arguments"]
        if name not in ACTIONS or not isinstance(arguments, dict):
            raise ValueError("Unknown action")
        expected = {"text"} if name == "WRITE_TEXT" else {"bbox"} if name in {"PREPARE_ROI", "RENDER_IMAGE"} else set()
        if set(arguments) != expected:
            raise ValueError("Action contains unexpected arguments")
        with self.meter.stage("codec", "execute real " + name):
            if name in {"PREPARE_ROI", "RENDER_IMAGE"}:
                box = arguments["bbox"]
                width, height = self.source_size
                if (not isinstance(box, list) or len(box) != 4 or any(type(v) is not int for v in box)
                        or not 0 <= box[0] < box[2] <= width or not 0 <= box[1] < box[3] <= height):
                    raise ValueError("Actor requested an invalid source region")
                if name == "PREPARE_ROI":
                    self.prepared = box
                else:
                    if not self.packet["requirements"]["image"] or self.packet["initial_delivery"]["image"] is not None:
                        raise ValueError("Render would violate the public output contract")
                    self.delivery["image"] = self.crop(box, f"rendered-{len(self.steps):02d}.png")
            elif name == "READ_ROI":
                if self.prepared is None:
                    raise ValueError("READ_ROI requires an executed preparation")
                image = self.crop(self.prepared, f"observed-{len(self.steps):02d}.png")
                self.observation = {key: image[key] for key in ("path", "sha256", "bbox")}
                self.observation["kind"] = "roi"
            elif name == "WRITE_TEXT":
                text = arguments["text"]
                if not isinstance(text, str) or len(text.encode()) > 8192:
                    raise ValueError("Invalid bounded text output")
                committed = self.packet["initial_delivery"]["text"]
                if committed is not None and text != committed:
                    raise ValueError("Actor changed committed public text")
                self.delivery["text"] = text
            else:
                self.stopped = True
        self.steps.append(value)
        with self.meter.stage("sync", "persist actual delivery snapshot"):
            self.snapshot()
        value["observed_action_seconds"] = time.perf_counter() - self.last_send
        return None if self.stopped else self.public_step()

    def crop(self, box, name):
        raw = read_bound(self.root, self.source_binding)
        with Image.open(io.BytesIO(raw)) as source:
            if source.size != self.source_size:
                raise ValueError("Registered canonical source dimensions changed")
            output = png_bytes(source.convert("RGB").crop(box))
        path = self.public / name
        write_bytes_once(path, output)
        return {"path": name, "sha256": file_sha(path), "bytes": len(output), "bbox": box}

    def command(self):
        command = bootstrap(self.config, "ndu_real_runtime.actor")
        command += ["--public-dir", str(self.public), "--weights", self.profile["weights"],
                    "--expected-weights-sha256", self.profile["model_sha256"],
                    "--core", self.profile["core"], "--controller", self.profile["controller"],
                    "--control-plan", self.profile["control_plan"], "--operation-id", self.operation_id,
                    "--tesseract", self.config["tesseract"], "--tessdata-dir", self.config["tessdata_dir"],
                    "--ocr-library-dir", self.config["ocr_library_dir"]]
        if self.training:
            command += ["--training-exploration"]
        return command

    def run(self):
        launch, error = None, None
        try:
            with self.meter.stage("sync", "mandatory isolated actor lifetime"):
                launch = run_actor(self.command(), public_root=self.public, output_root=self.actor_output,
                    runtime_roots=[*self.config["runtime_roots"], self.profile["weights"], self.profile["control_plan"]],
                    private_roots=[self.root / "private"], input_bytes=b"",
                    timeout_seconds=self.config["episode_wall_seconds"], max_output_bytes=4 * 1024 * 1024,
                    host_callback=self.callback)
                if (launch["exit_code"] != 0 or not launch["enforced_before_actor_exec"]
                        or not self.ready or launch.get("callback_error")):
                    raise RuntimeError("Mandatory isolated actor did not complete successfully")
                if not self.stopped and not self.budget_stop:
                    raise RuntimeError("Actor exited before a terminal action or bounded budget stop")
        except BaseException as exception:
            error = {"type": type(exception).__name__, "message": str(exception), "traceback": traceback.format_exc()}
        measured = self.meter.finish("FAILED" if error else "BUDGET_STOP" if self.budget_stop else "SUCCEEDED")
        try:
            observed = actor_receipts([step["meter"] for step in self.steps], self.actor_output)
            measured = reconcile(measured, observed)
        except (ValueError, KeyError, OSError) as exception:
            measured["interval_reconciliation"] = "FAILED; raw evidence retained"
            measured["costs"] = {key: None for key in measured["costs"]}
            measured["observed_unclassified_overhead_seconds"] = measured["wall_seconds"]
            error = {"type": "MeterReconciliationError", "message": str(exception), "original_error": error}
        measured = close_observer_tail(measured)
        atomic_json(self.output / "launch.json", launch)
        atomic_json(self.output / "trajectory.json", {"steps": self.steps})
        result = {"schema": "ndu.real.episode-result.v1", **self.profile,
            "case_id": self.case["id"], "source_group_id": self.case["source_id"],
            "episode_group": self.case["episode_group"], "split": self.case["role"],
            "task_family": self.case["task_family"], "source_sha256": self.source_binding["sha256"],
            "terminal_status": "Failed" if error else "BudgetStop" if self.budget_stop else "Completed",
            "retry_of": self.profile.get("retry_of"), "error": error, "deployment_meter": measured,
            "startup_seconds": getattr(self, "startup_seconds", None), "actions": [step["action"]["action"] for step in self.steps],
            "budget_overrun_seconds": max(0.0, measured["wall_seconds"]-self.config["episode_wall_seconds"]),
            "output_text_sha256": canonical_sha(self.delivery["text"]),
            "output_image_sha256": None if self.delivery["image"] is None else self.delivery["image"]["sha256"],
            "native_owner_authentication": "SEPARATE_REQUIRED", "confirmation_evaluated": False}
        if error is None:
            try:
                scores, score_cost = self.score()
                result.update(gross_score=scores[-1]["quality"], score_components=scores[-1], evaluation_meter=score_cost,
                              net_latency_utility=scores[-1]["quality"] - self.config["latency_weight"] * measured["wall_seconds"])
                if self.training:
                    self.training_rows(scores)
            except BaseException as exception:
                result.update(terminal_status="Failed", error={"type": type(exception).__name__, "message": str(exception),
                              "traceback": traceback.format_exc()})
                if hasattr(self, "evaluation_meter"):
                    result["evaluation_meter"] = self.evaluation_meter
        atomic_json(self.output / "result.json", result)
        return result

    def score(self):
        meter = Meter(self.operation_id + "/external-evaluation",
                      journal_path=self.output / "evaluation.meter.jsonl")
        scores = []
        meter_status = "FAILED"
        directories = self.snapshots if self.training else self.snapshots[-1:]
        try:
            for directory in directories:
                output = directory / "evaluation.json"
                command = bootstrap(self.config, "ndu_real_runtime.score_worker") + [
                    "--root", str(self.root), "--case-id", self.case["id"], "--delivery-root", str(directory),
                    "--delivery", str(directory / "delivery.json"), "--reference-index-sha256", self.config["reference_index_sha256"],
                    "--rubric-sha256", self.config["rubric_sha256"], "--output", str(output)]
                try:
                    with meter.stage("critic", "independent post-actor reference scorer"):
                        run = subprocess.run(command, capture_output=True, timeout=30, check=False)
                        if run.returncode != 0:
                            write_bytes_once(directory / "evaluation.stdout", run.stdout)
                            write_bytes_once(directory / "evaluation.stderr", run.stderr)
                            raise RuntimeError(f"External scorer exited {run.returncode}")
                except subprocess.TimeoutExpired as error:
                    write_bytes_once(directory / "evaluation.stdout", error.stdout or b"")
                    write_bytes_once(directory / "evaluation.stderr", error.stderr or b"")
                    raise
                write_bytes_once(directory / "evaluation.stdout", run.stdout)
                write_bytes_once(directory / "evaluation.stderr", run.stderr)
                score = strict_json(output.read_bytes())
                if score["evaluator_source_sha256"] != self.config["evaluator_sha256"]:
                    raise ValueError("External scorer source differs from the predeclared pin")
                scores.append(score)
            meter_status = "SUCCEEDED"
        finally:
            self.evaluation_meter = meter.finish(meter_status)
            atomic_json(self.output / "evaluation-meter.json", self.evaluation_meter)
        return scores, self.evaluation_meter

    def training_rows(self, scores):
        rows = []
        for index, step in enumerate(self.steps):
            following = self.steps[min(index + 1, len(self.steps) - 1)]
            terminal = step["action"]["action"] == "STOP" or index + 1 == len(self.steps)
            rows.append({"schema": "ndu.real.training-transition.v1",
                "record_id": self.operation_id + f"/transition/{index:02d}", "episode_id": self.case["id"],
                "source_group": self.case["source_id"], "split": "train", "origin_run_id": self.operation_id,
                "candidate_features": step["candidate_features"],
                "candidate_metadata": step["candidate_metadata"], "public_metadata": step["public_metadata"],
                "next_candidate_features": None if terminal else following["candidate_features"],
                "next_public_metadata": None if terminal else following["public_metadata"],
                "reference_field": self.reference["field"], "expected_text": self.reference["expected_text"],
                "target_boxes": self.reference["target_boxes"],
                "source_size": {"width": self.source_size[0], "height": self.source_size[1]},
                "action": step["action"]["action"], "before_score": scores[index]["quality"],
                "after_score": scores[index+1]["quality"], "duration_seconds": step["observed_action_seconds"],
                "execution_status": "completed", "behavior_controller": "predeclared_exploration",
                "terminal_reason": "actor_stop" if step["action"]["action"] == "STOP" else "budget_stop" if terminal else None,
                "behavior_weights_sha256": self.profile["model_sha256"]})
        with (self.output / "training-rows.jsonl").open("x") as stream:
            for row in rows:
                stream.write(json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args()
    request = strict_json(args.request.read_bytes())
    result = EpisodeHost(request["config"], request["case"], request["profile"], request["output"],
                         training=request.get("training", False), exploration=request.get("exploration", ())).run()
    print(json.dumps({key: result.get(key) for key in ("original_operation_id", "case_id", "terminal_status", "gross_score", "error")},
                     separators=(",", ":"), allow_nan=False), flush=True)
    return 1 if result["terminal_status"] == "Failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
