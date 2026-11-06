"""Development-only greedy control using the pinned one-step net-gain model.

No evaluator, generator or training input is available to choose(View). Unknown
or failed predictions cause STOP; they are never converted to zero-valued scores.
"""

from dataclasses import asdict
from pathlib import Path
import re
import time

from . import r2_action_value as av
from .dual_runtime import ACTIONS, View
from .transition_capture import file_identity, write_new
from .transition_capture_read import require


def legal_actions(view):
    """Mirror the original runner's public preconditions, including old drafts."""
    require(type(view) is View, "Policy accepts only the original public View")
    av.features(view)  # Validate bounded fields without opening image_path.
    require(not any(action == "stop" for action, _ in view.history), "Episode already stopped")
    had_draft = any(action in ("draft", "refine") for action, _ in view.history)
    return tuple(action for action in ACTIONS
                 if (action != "refine" or had_draft)
                 and (action != "verify" or (view.text is not None and view.image_path is not None)))


class DevelopmentGreedy:
    """Load actual C weights lazily inside the runner's controller cost interval.

    Only complete legal-action coverage can continue. STOP participates in the
    same scoring order and also remains the unscored fallback when coverage or
    predictions fail. A fallback is not a model estimate of zero STOP utility.
    """

    def __init__(self, checkpoint, checkpoint_sha256, fit_sha256, trace_directory,
                 *, maximum_decisions=32):
        for pin in (checkpoint_sha256, fit_sha256):
            require(isinstance(pin, str) and re.fullmatch("[0-9a-f]{64}", pin), "Missing checkpoint/FIT pin")
        require(type(maximum_decisions) is int and 1 <= maximum_decisions <= 32, "Invalid decision cap")
        self.checkpoint, self.trace = Path(checkpoint), Path(trace_directory)
        self.checkpoint_sha256, self.fit_sha256 = checkpoint_sha256, fit_sha256
        self.maximum_decisions = maximum_decisions
        self.predictor, self.decisions = None, []
        self.trace_started = False
        self.fenced = False

    def choose(self, view):
        require(not self.fenced, "Failed policy instance is fenced; use a fresh trace directory")
        require(len(self.decisions) < self.maximum_decisions, "Policy decision cap reached")
        started = time.process_time(), time.perf_counter()
        row = {"schema": "hepta.r2.development-greedy-decision.v1", "index": len(self.decisions),
               "status": "failed", "choice": None, "reason": None, "prediction_calls": 0,
               "candidates": [{"action": action, "legal": None, "status": "not_attempted",
                               "predicted_one_step_net_gain": None, "selected": False,
                               "prediction_metering": None} for action in ACTIONS],
               "production_qualified": False, "baseline_qualified": False,
               "independent_observation": False, "no_update": True}
        self.decisions.append(row)
        try:
            if not self.trace_started:
                self.trace.mkdir(parents=True, exist_ok=False)
                self.trace_started = True
                write_new(self.trace / "POLICY.json", {
                    "schema": "hepta.r2.development-greedy-policy.v1",
                    "checkpoint_sha256": self.checkpoint_sha256, "fit_sha256": self.fit_sha256,
                    "source_pins": {**av.source_pins(), "r2_greedy_policy.py": file_identity(__file__)["sha256"]},
                    "maximum_predictions_per_decision": 7, "maximum_decisions": self.maximum_decisions,
                    "tie_break": list(ACTIONS), "unknown_or_prediction_failure": "stop_without_imputation",
                    "target": "C one-step utility increment already net of historical controller/action costs",
                    "additional_subtraction": "none; current physical costs remain in original runner ledger",
                    "production_qualified": False, "baseline_qualified": False, "no_update": True,
                    "hard_deadline_guarantee": False})
            legal = legal_actions(view)
            row["view"] = asdict(view)
            row["view_sha256"] = av.digest(row["view"])
            for candidate in row["candidates"]:
                candidate["legal"] = candidate["action"] in legal
                if not candidate["legal"]:
                    candidate["status"] = "illegal"
            if self.predictor is None:
                self.predictor = av.ActionValue(self.checkpoint, self.checkpoint_sha256, self.fit_sha256)
            row["trained_actions"] = list(self.predictor.trained_actions)
            best, choice, incomplete = 0.0, "stop", set()
            for candidate in row["candidates"]:
                action = candidate["action"]
                if not candidate["legal"]:
                    continue
                if action not in self.predictor.trained_actions:
                    candidate["status"] = "unknown_untrained_action"
                    incomplete.add("unknown_legal_action")
                    continue
                if view.remaining_decisions <= 0 or time.perf_counter() - started[1] >= view.remaining_seconds:
                    candidate["status"] = "not_scored_budget"
                    incomplete.add("decision_budget")
                    continue
                before = time.process_time(), time.perf_counter()
                row["prediction_calls"] += 1
                try:
                    score = av.finite(self.predictor.predict(view, action), "predicted net gain")
                    candidate.update(status="scored", predicted_one_step_net_gain=score)
                    if score > best:  # Strict comparison preserves exact ACTIONS-order ties.
                        best, choice = score, action
                except (Exception, KeyboardInterrupt) as error:
                    candidate.update(status="prediction_failed", error={"type": type(error).__name__, "message": str(error)})
                    incomplete.add("prediction_failed")
                    if isinstance(error, KeyboardInterrupt):
                        raise
                finally:
                    candidate["prediction_metering"] = {
                        "cpu_seconds": time.process_time() - before[0],
                        "wall_seconds": time.perf_counter() - before[1]}
            if incomplete:
                choice, reason = "stop", "+".join(sorted(incomplete))
            else:
                reason = "highest_strictly_positive_prediction" if best > 0 else "no_strictly_positive_prediction"
            row.update(status="fallback" if incomplete else "completed", choice=choice, reason=reason)
            for candidate in row["candidates"]:
                candidate["selected"] = candidate["action"] == choice
            return choice
        except (Exception, KeyboardInterrupt) as error:
            self.fenced = True
            row.update(status="cancelled" if isinstance(error, KeyboardInterrupt) else "failed",
                       error={"type": type(error).__name__, "message": str(error)})
            raise
        finally:
            row["metering"] = {"cpu_seconds": time.process_time() - started[0],
                               "wall_seconds": time.perf_counter() - started[1],
                               "scope": "diagnostic subset of original controller interval; never add to runner totals",
                               "excluded_here": ["this_trace_write", "constructor_and_outer_orchestration"],
                               "unknown": ["energy_joules", "physical_disk_bytes"]}
            if self.trace_started:
                try:
                    write_new(self.trace / f"decision-{row['index']:03d}.json", row)
                except (Exception, KeyboardInterrupt) as error:
                    self.fenced = True
                    row["trace_write_error"] = {"type": type(error).__name__, "message": str(error)}
                    if "error" not in row:
                        raise  # Never dispatch a choice whose decision trace could not be retained.
