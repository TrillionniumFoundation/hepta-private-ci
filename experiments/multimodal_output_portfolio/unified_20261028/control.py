"""Semantic-boundary control over the existing, unchanged native owner host.

Native DENY_ALL authority and native abstention remain unchanged. The NDU
profile is bound by host receipts; the old Rust scope does not learn new NDU
semantics. Only the registered keep/swap generation actions are dispatched.
"""

from dataclasses import asdict, dataclass
import inspect
import math
from pathlib import Path
import resource
import time

from ..continuation_20261027.control.client import Native, Q, numerical_projection, sha
from .profile import CostEvent, digest, total_cost


@dataclass(frozen=True)
class ControlTariff:
    native_kernel: float = 0.0001
    generator_call: float = 0.01
    delivery: float = 0.002
    refused_proposal: float = 0.005
    python_cpu_second: float = 0.0001
    native_cpu_second: float = 0.0001
    wall_second: float = 0.0001

    def __post_init__(self):
        if any(isinstance(v, bool) or not math.isfinite(v) or v < 0 for v in asdict(self).values()):
            raise ValueError("Every physical tariff must be finite and nonnegative")


class NativeController:
    """Hash-bind actual artifacts, then execute native ticks and real dispatch.

``actor(context)`` returns keep/swap. It receives only arrived public feedback,
the original owner's recurrent state/readout and caller-supplied public state.
``dispatch(action, public_state, output_dir)`` returns artifact_refs (modality to
path), artifact_sha256, public_feedback, final_state_digest and terminal_kind.
It may additionally return actual generator_calls, delivery_units and extra
CostEvents in costs; standard generation/delivery charges are added here once.
A failed dispatch must return its actual failure/cost receipt. An exception
invalidates the episode rather than silently substituting a successful return.
"""

    def __init__(self, *, binary, readout, calibration, generator_checkpoint,
                 profile, policy_sha256, tariff=None, implementation_paths=()):
        self.profile = profile
        self.paths = {"owner_binary": Path(binary), "owner_readout": Path(readout),
                      "owner_calibration": Path(calibration),
                      "generator_checkpoint": Path(generator_checkpoint)}
        code_paths = (Path(__file__), Path(__file__).with_name("profile.py"),
                      *(Path(path) for path in implementation_paths))
        self.paths.update({f"implementation:{path.resolve()}": path for path in code_paths})
        if (not isinstance(policy_sha256, str) or len(policy_sha256) != 64
                or any(c not in "0123456789abcdef" for c in policy_sha256)):
            raise ValueError("The frozen actor/dispatch implementation requires a SHA-256 binding")
        self.tariff = tariff or ControlTariff()
        self.identities = {name: sha(path) for name, path in self.paths.items()}
        self.binding = {"schema": "hepta.ndu.native-host-binding.v1", **self.identities,
                        "profile_sha256": profile.digest, "policy_sha256": policy_sha256,
                        "tariff": asdict(self.tariff), "actions": ["keep", "swap"],
                        "native_scope_objective": "continuation.complete-delivered-return.v1",
                        "profile_binding_level": "host event receipt",
                        "owner_authority": "DENY_ALL"}
        self.fingerprint = digest(self.binding)

    def verify(self):
        if {name: sha(path) for name, path in self.paths.items()} != self.identities:
            raise ValueError("Runtime/checkpoint changed: refit and recalibrate this policy")

    @staticmethod
    def _delivery(receipt, directory):
        if not isinstance(receipt, dict) or receipt.get("terminal_kind") not in {"delivered", "failed"}:
            raise ValueError("Dispatch must return an actual delivered/failed receipt")
        refs, hashes = receipt.get("artifact_refs", {}), receipt.get("artifact_sha256", {})
        if set(refs) != set(hashes) or (receipt["terminal_kind"] == "delivered" and not refs):
            raise ValueError("A delivery requires matching artifact references and readback hashes")
        for modality, path in refs.items():
            actual = Path(path).resolve()
            if (not actual.is_relative_to(directory.resolve()) or not actual.is_file()
                    or sha(actual) != hashes[modality]):
                raise ValueError("Artifact is outside the scoped dispatch or fails actual readback")
        feedback = receipt.get("public_feedback")
        if feedback not in {-1, 0, 1} or isinstance(feedback, bool):
            raise ValueError("The registered keep/swap continuation requires feedback -1/0/+1")
        state = receipt.get("final_state_digest", "")
        if len(state) != 64 or any(c not in "0123456789abcdef" for c in state):
            raise ValueError("A bound generator state is required")
        for field, default in (("generator_calls", 1), ("delivery_units", int(bool(refs)))):
            value = receipt.get(field, default)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("Dispatch work counters must be actual nonnegative integers")
        return {**receipt, "artifact_refs": refs, "artifact_sha256": hashes,
                "generator_calls": receipt.get("generator_calls", 1),
                "delivery_units": receipt.get("delivery_units", int(bool(refs)))}

    def execute(self, *, directory, case, public_state, dispatch, actor=None,
                expires=7, media_budget=2, forecast="none", recovery="cold"):
        """Run seven actual ticks; full forecasting adds 33 replay/branch kernels.

The cold restore re-executes five journal and five ledger entries. Thus the
normal fast and full modes cost 17 and 50 kernels respectively. Keeping the
same live owner instead of a deployment recovery costs 7 and 40. Timings include
identity checks, actor execution, codec readback, all native work and teardown.
"""
        if (forecast not in {"none", "full"} or recovery not in {"cold", "live"}
                or isinstance(expires, bool) or not isinstance(expires, int) or expires < 4
                or isinstance(media_budget, bool) or not isinstance(media_budget, int) or media_budget < 1):
            raise ValueError("Invalid registered continuation execution contract")
        wall, cpu = time.perf_counter(), time.process_time()
        children_before = resource.getrusage(resource.RUSAGE_CHILDREN)
        self.verify()
        bound_paths = {path.resolve() for path in self.paths.values()}
        for callback in (actor, dispatch):
            if callback is not None:
                source_path = inspect.getsourcefile(callback)
                if source_path is None or Path(source_path).resolve() not in bound_paths:
                    raise ValueError("Actual callback source is absent from implementation_paths")
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=False)
        native = Native(self.paths["owner_binary"])
        transcript, branches, cold_steps = [], {}, 0
        dispatches, costs = [], []
        context_binding = {"binding_sha256": self.fingerprint, "public_state_sha256": digest(public_state)}
        try:
            native.open(directory / "owner", case, expires, self.paths["owner_readout"],
                        self.paths["owner_calibration"])
            first = [native.tick(0, 0, {**context_binding, "candidate": index, "stage": "current_scan"})
                     for index in range(4)]
            if any(row["native_abstain"] for row in first):
                raise ValueError("Original owner refused initial delivery")
            initial_dir = directory / "initial"
            initial = self._delivery(dispatch("keep", public_state, initial_dir), initial_dir)
            dispatches.append(initial)
            feedback = initial["public_feedback"]
            evidence = {**context_binding, "artifact_sha256": initial["artifact_sha256"],
                        "generator_state": initial["final_state_digest"], "feedback": feedback,
                        "terminal_kind": initial["terminal_kind"]}
            if forecast == "full":
                branches = {str(symbol): native.call({"command": "Forecast", "feedback_q24": symbol * Q,
                            "branch": f"scalar-{symbol + 1}"}) for symbol in (-1, 0, 1)}
                if not all(b["committed_parent_unchanged"] for b in branches.values()):
                    raise ValueError("Forecast mutated the committed original owner")
            feedback_tick = native.tick(1, feedback, evidence)
            restored = None
            if recovery == "cold":
                before_close = native.close()
                transcript.extend(native.transcript)
                native.finish()
                native = Native(self.paths["owner_binary"])
                native.case = case
                restored = native.call({"command": "Resume", "directory": str(directory / "owner"),
                    "case": case, "expires": expires, "model": str(self.paths["owner_readout"]),
                    "model_sha256": self.identities["owner_readout"],
                    "calibration": str(self.paths["owner_calibration"]),
                    "calibration_sha256": self.identities["owner_calibration"]})
                if restored != before_close or restored["durable_event_count"] != 5:
                    raise ValueError("Cold native recovery differs from the committed state")
                cold_steps = 2 * restored["durable_event_count"]
            hold, decision = native.tick(2, 0, evidence), native.tick(3, 0, evidence)
            ticks = [feedback_tick, hold, decision]
            context = {"public_state": public_state, "feedback": feedback,
                       "native_readout_proposal": decision["proposed_repair"],
                       "eligibility_q24": tuple(decision["eligibility_before_q24"]),
                       "owner_abstained": any(t["native_abstain"] for t in ticks),
                       "profile_sha256": self.profile.digest, "binding_sha256": self.fingerprint,
                       "media_units_remaining": media_budget - 1}
            actor_start = time.perf_counter_ns()
            action = actor(context) if actor is not None else ("swap" if decision["proposed_repair"] else "keep")
            actor_ns = time.perf_counter_ns() - actor_start
            if digest(public_state) != context_binding["public_state_sha256"]:
                raise ValueError("Actor mutated the bound public input")
            if action not in {"keep", "swap"}:
                raise ValueError("Action is outside the registered original generator action set")
            proposed = action == "swap"
            admitted = proposed and not context["owner_abstained"] and media_budget >= 2
            permit = {"action": action, "proposed": proposed, "execution_admitted": admitted,
                      "scope": str(directory.resolve()), "owner_authority": "DENY_ALL",
                      "native_nonabstention": not context["owner_abstained"],
                      "media_units_remaining": media_budget - 1,
                      "authorization_source": "user-authorized scoped research dispatch",
                      "production_authorization": False, "binding_sha256": self.fingerprint}
            final = initial
            if admitted:
                self.verify()
                final_dir = directory / "continuation"
                final = self._delivery(dispatch("swap", public_state, final_dir), final_dir)
                dispatches.append(final)
            end = native.close()
            transcript.extend(native.transcript)
            native.finish()
            native = None
        finally:
            if native is not None and native.process.poll() is None:
                native.finish()
        api_ticks = sum(int(row["response"]["result"].get("native_transition_executed", False))
                        for row in transcript if row["request"]["command"] == "Tick")
        branch_ticks = sum(len(b["ticks"]) for b in branches.values())
        forecast_replay = sum(b["ledger_validation_kernel_steps"] + b["original_journal_replayed_prefix_steps"]
                              for b in branches.values())
        kernels = api_ticks + branch_ticks + forecast_replay + cold_steps
        expected = 7 + (33 if forecast == "full" else 0) + (10 if recovery == "cold" else 0)
        if kernels != expected:
            raise ValueError("Actual original kernel executions differ from the declared cost")
        matched = not branches or numerical_projection(ticks) == numerical_projection(branches[str(feedback)]["ticks"])
        if not matched:
            raise ValueError("Forecast numerical state differs from actual selected continuation")
        children_after = resource.getrusage(resource.RUSAGE_CHILDREN)
        measured = {"python_cpu_seconds": time.process_time() - cpu,
                    "native_cpu_seconds": children_after.ru_utime + children_after.ru_stime
                                          - children_before.ru_utime - children_before.ru_stime,
                    "wall_seconds": time.perf_counter() - wall, "actor_nanoseconds": actor_ns,
                    "actual_original_kernel_executions": kernels, "actual_owner_api_ticks": api_ticks,
                    "forecast_branch_ticks": branch_ticks, "forecast_replay_kernel_steps": forecast_replay,
                    "cold_recovery_kernel_steps": cold_steps,
                    "actual_generator_calls": sum(d["generator_calls"] for d in dispatches),
                    "actual_delivery_units": sum(d["delivery_units"] for d in dispatches)}
        quantities = {"native_kernel": kernels, "generator_call": measured["actual_generator_calls"],
                      "delivery": measured["actual_delivery_units"], "refused_proposal": int(proposed and not admitted),
                      "python_cpu_second": measured["python_cpu_seconds"],
                      "native_cpu_second": measured["native_cpu_seconds"], "wall_second": measured["wall_seconds"]}
        costs.extend(CostEvent(f"{case}.control.{kind}", amount * getattr(self.tariff, kind),
                               self.profile.cost_unit, kind) for kind, amount in quantities.items())
        for receipt in dispatches:
            costs.extend(receipt.get("costs", ()))
        charge = total_cost(self.profile, costs)
        initial_report = {**initial, "costs": [asdict(c) for c in initial.get("costs", ())]}
        final_report = {**final, "costs": [asdict(c) for c in final.get("costs", ())]}
        return {"schema": "hepta.ndu.actual-native-continuation.v1", "case": case,
                "binding": self.binding, "binding_sha256": self.fingerprint,
                "forecast": forecast, "recovery": recovery, "initial": initial_report, "final": final_report,
                "selected_action": action, "executed_action": "swap" if admitted else "keep",
                "continuation_kind": "refused" if proposed and not admitted else final["terminal_kind"],
                "permit": permit, "actual_ticks": ticks, "forecast_branches": branches,
                "forecast_matches_actual": matched, "cold_restored_state": restored,
                "final_owner_state": end, "measurements": measured, "costs": [asdict(c) for c in costs],
                "total_cost": charge, "transcript": transcript,
                "native_kernel_parameters_trained": False,
                "native_scope_objective_changed": False, "private_truth_access_by_wrapper": False}
