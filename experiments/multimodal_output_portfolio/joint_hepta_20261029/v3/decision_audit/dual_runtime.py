"""Bounded image/text development execution; semantic acceptance is separate.

Only the public view reaches a controller. Every attempted action is retained,
including unselected drafts and failure costs. This is a synchronous CPU pilot;
the deadline is checked on return, not a preemptive execution guarantee.
"""

from dataclasses import dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import time


ACTIONS = ("perceive", "text", "draft", "revise", "refine", "verify", "stop")


def digest_file(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


@dataclass(frozen=True)
class Request:
    source_id: str
    image_path: str
    image_sha256: str
    instruction: str


@dataclass(frozen=True)
class View:
    """Public online state; contains no reference answer or future outcome."""

    instruction: str
    plan: str
    plan_version: int
    text: str | None
    image_path: str | None
    critique: str
    history: tuple
    remaining_decisions: int
    remaining_seconds: float


class FixedSchedule:
    """A registered schedule needs no learned actor or critic invocation."""

    def __init__(self, actions):
        self.actions = tuple(actions)
        if not self.actions or any(a not in ACTIONS for a in self.actions):
            raise ValueError("Unknown or empty fixed schedule")

    def choose(self, view):
        index = len(view.history)
        return self.actions[index] if index < len(self.actions) else "stop"


def run(request, backend, controller, output, *, seed=17, horizon=10,
        deadline_seconds=600.0, cpu_tariff=0.0, wall_tariff=0.0, recorder=None):
    """Execute actual provider operations, preserving buffered immutable bytes.

    Zero default tariffs mean no declared conversion into utility, not free
    compute. Raw CPU/wall costs are always reported; net NDU is not inferred.
    The final JSON write is outside the episode clock and metered separately.
    """
    if (type(horizon) is not int or not 1 <= horizon <= 32 or type(seed) is not int
            or not 0 <= seed < 2**63 or not math.isfinite(deadline_seconds)
            or deadline_seconds <= 0 or any(not math.isfinite(x) or x < 0
                                         for x in (cpu_tariff, wall_tariff))):
        raise ValueError("Invalid horizon, seed, deadline or tariffs")
    if not request.source_id or not 1 <= len(request.instruction) <= 4096:
        raise ValueError("Bounded public instruction and source identity required")
    if recorder is not None:
        recorder.claim(request)
    out = Path(output)
    out.mkdir(parents=True, exist_ok=False)
    started = previous = (time.process_time(), time.perf_counter())
    events, artifacts, history = [], [], []
    plan, version, critique = request.instruction, 0, ""
    text_value = image_path = last_image = None
    status, error, selected, action = "incomplete", None, [], "preflight"

    def record(name, outcome, detail=None):
        nonlocal previous
        now = time.process_time(), time.perf_counter()
        cpu, wall = now[0] - previous[0], now[1] - previous[1]
        row = {"event_id": len(events), "action": name, "status": outcome,
               "cpu_seconds": cpu, "wall_seconds": wall,
               "tariff_amount": cpu * cpu_tariff + wall * wall_tariff,
               "detail": detail, "plan_version": version}
        events.append(row)
        previous = now
        # The next interval includes this completed journal write.
        with (out / "events.jsonl").open("a") as handle:
            handle.write(json.dumps(row, allow_nan=False) + "\n")

    def keep(kind, path):
        item = {"kind": kind, "path": Path(path).name,
                "sha256": digest_file(path), "bytes": Path(path).stat().st_size,
                "plan_version": version, "event_id": len(events)}
        artifacts.append(item)
        return item

    def capture(phase, **detail):
        if recorder is not None:
            recorder.observe(phase, {
                "instruction": request.instruction, "plan": plan, "plan_version": version,
                "text": text_value, "image_path": image_path, "last_image": last_image,
                "critique": critique, "history": history, "action": action,
                "episode_status_so_far": status, "episode_error_so_far": error,
            }, events, artifacts, selected, detail)

    try:
        if recorder is not None:
            recorder.start(request, out, {
                "seed": seed, "horizon": horizon, "deadline_seconds": deadline_seconds,
                "cpu_tariff": cpu_tariff, "wall_tariff": wall_tariff,
                "observer_admission": "fresh-after-capture-v1",
            }, __file__, started)
        if digest_file(request.image_path) != request.image_sha256:
            raise ValueError("Input bytes do not match the frozen request")
        from PIL import Image
        with Image.open(request.image_path) as picture:
            if picture.width * picture.height > 16_000_000:
                raise ValueError("Input exceeds the declared pixel bound")
            picture.verify()
        identity = backend.identity()
        write_json(out / "request.json", vars(request))
        write_json(out / "backend.json", identity)
        record(action, "ok")
        for step in range(horizon):
            if time.perf_counter() - started[1] >= deadline_seconds:
                status = "timeout"
                record("deadline", status, {"check": "before_controller"})
                break
            action = "controller"
            view = View(request.instruction, plan, version, text_value, image_path,
                        critique, tuple(history), horizon - step,
                        deadline_seconds - (time.perf_counter() - started[1]))
            capture("before_controller", step=step, view=vars(view))
            if recorder is not None:
                remaining = deadline_seconds - (time.perf_counter() - started[1])
                if remaining <= 0:
                    status = "timeout"
                    record("deadline", status, {"check": "after_before_controller_capture"})
                    break
                view = replace(view, remaining_seconds=remaining)
            chosen = controller.choose(view)
            record(action, "ok", {"choice": chosen})
            if recorder is None:
                capture("choice", step=step, chosen=chosen)
            else:
                capture("choice", step=step, chosen=chosen, controller_view=vars(view))
            if chosen not in ACTIONS:
                raise ValueError("Controller selected an unknown action")
            action = chosen
            if time.perf_counter() - started[1] >= deadline_seconds:
                status = "timeout"
                record("deadline", status, {"check": "after_controller"})
                break
            capture("before_action", step=step)
            if recorder is not None and time.perf_counter() - started[1] >= deadline_seconds:
                status = "timeout"
                record("deadline", status, {"check": "after_before_action_capture"})
                break
            detail = None
            if action == "stop":
                if text_value is not None and image_path is not None:
                    # Re-open and bind the complete current pair before delivery.
                    matches = [a for a in artifacts if a["plan_version"] == version]
                    selected = [next(a for a in reversed(matches) if a["kind"] == k)
                                for k in ("text", "image")]
                    for item in selected:
                        if digest_file(out / item["path"]) != item["sha256"]:
                            raise ValueError("Candidate bytes changed before delivery")
                    status = "delivered"
                else:
                    status = "abstained"
            elif action in ("perceive", "revise"):
                prompt = ("Describe visible objects and their spatial relations for a "
                          "simple explanatory diagram. " + request.instruction)
                if action == "revise":
                    prompt = ("Revise the common plan for an explanation and a simple "
                              "diagram. Preserve visible facts. Request: "
                              + request.instruction + "\nPrevious plan: " + plan
                              + "\nCritique: " + critique)
                plan = backend.describe(request.image_path, prompt)
                if not isinstance(plan, str) or not 1 <= len(plan) <= 8192:
                    raise ValueError("Missing or oversized common plan")
                version += 1
                text_value = image_path = None
                critique = ""
                path = out / f"{step:02d}-{action}.txt"
                path.write_text(plan)
                keep("plan", path)
            elif action == "text":
                text_value = backend.describe(
                    request.image_path, "Write a concise explanation grounded in this "
                    "image and shared diagram plan. Request: " + request.instruction
                    + "\nPlan: " + plan)
                if not isinstance(text_value, str) or not 1 <= len(text_value) <= 8192:
                    raise ValueError("Missing or oversized generated explanation")
                path = out / f"{step:02d}-text.txt"
                path.write_text(text_value)
                keep("text", path)
                critique = ""
            elif action in ("draft", "refine"):
                if action == "refine" and last_image is None:
                    raise ValueError("Refinement requires an actual previous draft")
                path = out / f"{step:02d}-{action}.png"
                detail = backend.draw("Simple clear scientific illustration, no written labels. "
                                      + request.instruction + "\nShared plan: " + plan,
                                      path, seed + step, initial_image=last_image
                                      if action == "refine" else None)
                with Image.open(path) as picture:
                    picture.verify()
                image_path = last_image = str(path)
                keep("image", path)
                critique = ""
            elif action == "verify":
                if text_value is None or image_path is None:
                    raise ValueError("Verification requires a current text/image pair")
                critique = backend.describe(
                    image_path, "Check whether this generated diagram matches the "
                    "explanation and common plan. State any mismatch. Explanation: "
                    + text_value + "\nPlan: " + plan)
                if not isinstance(critique, str) or len(critique) > 8192:
                    raise ValueError("Invalid public critique")
                path = out / f"{step:02d}-critique.txt"
                path.write_text(critique)
                keep("public_critique_not_independent_score", path)
            backend.synchronize()
            record(action, "ok", detail)
            history.append((action, "ok"))
            capture("after_action", step=step)
            if time.perf_counter() - started[1] > deadline_seconds:
                status, selected = "timeout", []
                record("deadline", status, {"check": "after_action"})
                break
            if action == "stop":
                break
    except (Exception, KeyboardInterrupt) as exc:
        status = ("cancelled" if isinstance(exc, KeyboardInterrupt) else
                  "timeout" if isinstance(exc, TimeoutError) else "failed")
        error = {"type": type(exc).__name__, "message": str(exc)}
        record(action, status, error)
        selected = []
        capture("failure")
    # Preserve provider identity after lazy loads and any partially written files.
    inventory = []
    try:
        write_json(out / "backend_final.json", backend.identity())
        inventory = [{"path": p.name, "bytes": p.stat().st_size, "sha256": digest_file(p)}
                     for p in sorted(out.iterdir()) if p.is_file() and p.suffix in (".png", ".txt")]
    except (Exception, KeyboardInterrupt) as exc:
        status = ("cancelled" if isinstance(exc, KeyboardInterrupt) else
                  "timeout" if isinstance(exc, TimeoutError) else "failed")
        selected = []
        error = {"type": type(exc).__name__, "message": str(exc)}
        record("final_identity_and_inventory", status, error)
    record("finalize", "ok")
    if status not in ("failed", "cancelled", "timeout") and time.perf_counter() - started[1] > deadline_seconds:
        status, selected = "timeout", []
        record("deadline", status, {"check": "after_finalization"})
    capture("episode_end")
    report = {"schema": "hepta.dual-generation.development.v1", "status": status,
              "error": error, "seed": seed, "horizon": horizon,
              "source_id": request.source_id, "events": events, "artifacts": artifacts,
              "selected": selected, "history": history, "retained_files": inventory,
              "cpu_seconds": math.fsum(e["cpu_seconds"] for e in events),
              "wall_seconds": math.fsum(e["wall_seconds"] for e in events),
              "tariff_amount": math.fsum(e["tariff_amount"] for e in events),
              "tariffs": {"cpu_second": cpu_tariff, "wall_second": wall_tariff},
              "semantic_acceptance": "pending_independent_evaluation",
              "hard_deadline_guarantee": False, "training_performed": False,
              "production_qualified": False, "all_blockers_closed": False,
              "cost_scope": "exclusive_current_process_intervals_through_finalize_including_lazy_loads",
              "unknown_costs": ["energy", "training", "network_acquisition",
                                "independent_semantic_evaluation", "child_process_CPU",
                                "outer_report_construction_and_writes"]}
    before = time.process_time(), time.perf_counter()
    write_json(out / "report.json", report)
    write_json(out / "report_write_cost.json",
               {"cpu_seconds": time.process_time() - before[0],
                "wall_seconds": time.perf_counter() - before[1],
                "scope": "report construction and last event journal write are outer overhead"})
    if recorder is not None:
        recorder.finish(report, out)
    return report
