"""Execute the new NDU host actor through unchanged original-owner gates.

The meter begins before per-episode public preparation. It ends only after the
owner has stopped, final physical scoring and binding checks have completed.
"""

from dataclasses import asdict
import inspect
import json
import math
from pathlib import Path
import time

from ..continuation_20261027.control.client import sha
from ..unified_20261028.control import ControlTariff, NativeController
from ..unified_20261028.profile import CostEvent, DeliveredOutcome, canonical, digest, net_return
from .control_actor import features
from .profile_contract import ACTIONS, FEATURE_DIMENSION, Prices, WorkBudget, cpu_seconds, support_status


class MediaFailure(Exception):
    """A sampled codec/transport failure that must remain in the outcome law."""


def _number(score):
    value = float(score.detach()) if hasattr(score, "detach") else float(score)
    if not math.isfinite(value):
        raise ValueError("A sampled complete-action log density must be finite")
    return value


def execute_episode(*, profile, actor, prepare, emit, terminal_score, binary, readout,
                    calibration, checkpoint, directory, case, implementation_paths,
                    episode_started_cpu, budget=None, prices=None, expires=7, media_budget=2, forced_action=None):
    """Return ``(trajectory_log_probability, complete_net_return, receipt)``.

``prepare()`` returns the immutable JSON public context. The emitter receives
``(action, public, directory, register_sample, write_file)``. It must register
each actually sampled density BEFORE serialization, and use the controlled
writer for all four deliverable files. No private observer result enters actor
features. A retry advances the emitter's RNG and registers one fresh density.
``terminal_score(final_receipt)`` reopens actual final files after owner stop.
"""
    measured_entry, wall_start = cpu_seconds(), time.perf_counter()
    if (isinstance(episode_started_cpu, bool) or not math.isfinite(episode_started_cpu)
            or not 0 <= episode_started_cpu <= measured_entry):
        raise ValueError("Pass the actual meter reading from before all per-episode caller preparation")
    cpu_start = episode_started_cpu
    budget, prices = budget or WorkBudget(), prices or Prices()
    if (forced_action not in (None, *ACTIONS) or not case
            or not isinstance(media_budget, int) or isinstance(media_budget, bool)
            or media_budget < 1):
        raise ValueError("A valid actual policy/action and scoped episode are required")
    paths = tuple(dict.fromkeys(Path(p).resolve() for p in
                               (__file__, Path(__file__).with_name("control_actor.py"),
                                Path(__file__).with_name("profile_contract.py"), *implementation_paths)))
    for callback in (prepare, emit, terminal_score):
        source = inspect.getsourcefile(callback)
        if source is None or Path(source).resolve() not in paths:
            raise ValueError("Every actual callback source must be bound before execution")
    implementation_hashes = {str(p): sha(p) for p in paths}
    public = prepare()
    if (not isinstance(public, dict) or len(canonical(public)) > budget.max_public_bytes
            or any(not isinstance(public.get(k), str) or not public[k]
                   for k in ("event_id", "source_id", "split"))):
        raise ValueError("Public context requires bounded source/event/split identities")
    public_hash = digest(public)
    if forced_action is None:
        if actor is None or actor.profile_sha256 != profile.digest:
            raise ValueError("The fitted actor and this complete episode must share one profile")
        policy_sha = actor.digest
    else:
        policy_sha = digest({"profile_sha256": profile.digest,
                             "training_intervention": forced_action, "actor_source": sha(paths[1])})
    tariff = ControlTariff(native_kernel=prices.native_kernel,
                          generator_call=prices.generator_call, delivery=prices.delivery,
                          refused_proposal=prices.refused_proposal,
                          python_cpu_second=0.0, native_cpu_second=0.0, wall_second=0.0)
    controller = NativeController(binary=binary, readout=readout, calibration=calibration,
                                  generator_checkpoint=checkpoint, profile=profile,
                                  policy_sha256=policy_sha, tariff=tariff, implementation_paths=paths)
    samples, scores, emissions, decisions = [], [], [], []
    arrived_features = (0.0,) * FEATURE_DIMENSION
    written_bytes, host_refusals = 0, 0

    def dispatch(action, supplied_public, output_dir):
        nonlocal arrived_features, written_bytes, host_refusals
        if digest(supplied_public) != public_hash:
            raise ValueError("Public input changed within its bound episode")
        if (len(emissions) >= budget.max_emissions
                or cpu_seconds() - cpu_start >= budget.cpu_admission_seconds):
            host_refusals += 1
            return {"artifact_refs": {}, "artifact_sha256": {}, "public_feedback": -1,
                    "final_state_digest": digest({"case": case, "budget_refusal": action}),
                    "terminal_kind": "failed", "generator_calls": 0, "delivery_units": 0,
                    "failure": "work_or_cpu_admission_budget_exhausted"}
        index = len(emissions)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=False)
        refs, hashes, bytes_this_emission = {}, {}, 0
        before_samples = len(samples)
        emission = {"index": index, "action": action, "registered_draw": False}
        emissions.append(emission)  # Failed forward/codec work still consumes a slot.

        def register_sample(score, descriptor):
            if len(samples) != before_samples:
                raise ValueError("One joint emission must register its joint density once")
            if not isinstance(descriptor, dict) or any(
                    not isinstance(descriptor.get(key), str) or len(descriptor[key]) != 64
                    for key in ("sampled_sha256", "rng_before_sha256", "rng_after_sha256")):
                raise ValueError("Actual sampled-action identity is required before codec")
            value = _number(score)
            if (descriptor["rng_before_sha256"] == descriptor["rng_after_sha256"]
                    or (samples and samples[-1]["descriptor"]["rng_after_sha256"]
                        != descriptor["rng_before_sha256"])):
                raise ValueError("Fresh retry draws must advance the actual episode RNG chain")
            samples.append({"emission_index": index, "descriptor": json.loads(canonical(descriptor)),
                            "log_probability": value})
            scores.append(score)
            emission["registered_draw"] = True

        def write_file(modality, suffix, payload):
            nonlocal written_bytes, bytes_this_emission
            allowed = {"text": ".txt", "image": ".png", "audio": ".wav", "video": ".mkv"}
            if modality not in allowed or suffix != allowed[modality] or modality in refs:
                raise ValueError("Only one registered four-media output per modality is writable")
            if not isinstance(payload, bytes):
                raise ValueError("The bounded serializer accepts complete encoded byte strings")
            if bytes_this_emission + len(payload) > budget.max_bundle_bytes:
                raise MediaFailure("Actual bundle exceeds its frozen output-byte capacity")
            path = output_dir / (modality + suffix)
            # Exclusive creation prevents unmetered replacement writes. A short
            # write retains the physical bytes and fails the delivered bundle.
            write_error, count = None, 0
            try:
                with path.open("xb") as stream:
                    count = stream.write(payload)
                    stream.flush()
            except OSError as exc:
                write_error = exc
            if path.exists():
                actual_size = path.stat().st_size
                bytes_this_emission += actual_size
                written_bytes += actual_size
                refs[modality], hashes[modality] = str(path), sha(path)
            if write_error is not None or count != len(payload):
                raise MediaFailure("A physical delivery write was incomplete")
            return str(path)

        failure = None
        try:
            receipt = emit(action, supplied_public, output_dir, register_sample, write_file)
            if not isinstance(receipt, dict):
                raise ValueError("An emitter must return its real media receipt")
        except MediaFailure as exc:
            failure = {"kind": "actual_media_failure", "message": str(exc)[:300]}
            receipt = {"terminal_kind": "failed", "public_feedback": -1}
        # The emitter may expose a deterministic declared route, which has no
        # sampled density. Stochastic routes must register before any codec.
        if not emission["registered_draw"] and receipt.get("stochastic", True):
            raise ValueError("Actual stochastic generation omitted its sampled-action density")
        actual_files = {p.name: p.stat().st_size for p in output_dir.iterdir() if p.is_file()}
        if (sum(actual_files.values()) != bytes_this_emission
                or set(actual_files) != {Path(path).name for path in refs.values()}):
            raise ValueError("Emitter wrote files outside the bounded physical writer")
        hashes = {name: sha(path) for name, path in refs.items()}
        if receipt.get("artifact_refs", refs) != refs or receipt.get("artifact_sha256", hashes) != hashes:
            raise ValueError("Emitter's claimed files differ from its actual delivery")
        terminal = receipt.get("terminal_kind")
        if terminal == "delivered" and set(refs) != set(profile.required_modalities):
            raise ValueError("A delivered joint bundle must physically contain all required modalities")
        if terminal not in {"delivered", "failed"}:
            raise ValueError("Emitter must preserve its actual success/failure branch")
        arrived_features = tuple(float(v) for v in receipt.get("public_features", arrived_features))
        if len(arrived_features) != FEATURE_DIMENSION or not all(map(math.isfinite, arrived_features)):
            raise ValueError("Emitter public features changed dimension or became nonfinite")
        emission.update(terminal_kind=terminal, written_bytes=bytes_this_emission,
                        artifact_sha256=hashes, failure=failure or receipt.get("failure"))
        return {"artifact_refs": refs, "artifact_sha256": hashes,
                "terminal_kind": terminal, "generator_calls": 1,
                "delivery_units": int(terminal == "delivered"),
                "public_features": arrived_features,
                "public_feedback": receipt.get("public_feedback", 1 if terminal == "delivered" else -1),
                "failure": failure or receipt.get("failure"),
                "final_state_digest": receipt.get("final_state_digest", digest(emission))}

    def host_actor(native_context):
        nonlocal host_refusals
        context = {**native_context, "emission_public_features": arrived_features}
        budget_exhausted = cpu_seconds() - cpu_start >= budget.cpu_admission_seconds
        if budget_exhausted or len(emissions) >= budget.max_emissions:
            context["media_units_remaining"] = 0
        features(context)  # Shared train/planner/deployment representation.
        if forced_action is None:
            proposed, report = actor.choose(context)
        else:
            proposed = forced_action
            report = {"policy_sha256": policy_sha, "selected_action": proposed,
                      "training_intervention": True, "predicted_complete_moments": None}
        host_refused = proposed == "swap" and context["media_units_remaining"] == 0
        if host_refused:
            host_refusals += 1
        returned = "keep" if host_refused else proposed
        decisions.append({**report, "boundary_context": context, "host_refused": host_refused,
                          "actual_host_action": returned, "cpu_budget_exhausted": budget_exhausted})
        return returned

    native = controller.execute(directory=directory, case=case, public_state=public,
                                dispatch=dispatch, actor=host_actor, expires=expires,
                                media_budget=min(media_budget, budget.max_emissions),
                                forecast="none", recovery="cold")
    owner_closed = time.monotonic_ns()
    scoring_started = time.monotonic_ns()
    terminal = native["final"]["terminal_kind"]
    observed = terminal_score(native["final"]) if terminal == "delivered" else {"utility": 0.0}
    utility = float(observed["utility"])
    if (digest(public) != public_hash
            or implementation_hashes != {str(p): sha(p) for p in paths}):
        raise ValueError("Bound context or implementation changed before actual terminal scoring")
    controller.verify()
    if native["measurements"]["actual_generator_calls"] != len(emissions):
        raise ValueError("Physical generation counts and metered work slots differ")
    cpu_used, wall_used = cpu_seconds() - cpu_start, time.perf_counter() - wall_start
    costs = tuple(CostEvent(**entry) for entry in native["costs"])
    costs += (CostEvent(case + ":complete-cpu", cpu_used * prices.cpu_second, profile.cost_unit, "complete_self_children_cpu"),
              CostEvent(case + ":physical-bytes", written_bytes * prices.written_byte, profile.cost_unit, "written_bytes"),
              CostEvent(case + ":host-refusals", host_refusals * prices.refused_proposal, profile.cost_unit, "host_refused_proposal"))
    outcome = DeliveredOutcome(public["event_id"], case, public["source_id"], utility, costs,
                               tuple(sorted(native["final"]["artifact_sha256"].items())),
                               profile.observer_sha256, profile.objective_sha256,
                               profile.continuation_sha256, terminal)
    value = net_return(profile, outcome)
    record = {"schema": "hepta.ndu.selected-host-episode.v1", "event_id": case,
              "context_id": public["event_id"], "source_id": public["source_id"], "split": public["split"],
              "profile_sha256": profile.digest, "policy_sha256": policy_sha,
              "selected_action": decisions[0]["selected_action"], "executed_action": native["executed_action"],
              "boundary_context": decisions[0]["boundary_context"], "decision": decisions[0],
              "emissions": emissions, "samples": samples, "trajectory_log_probability": sum(r["log_probability"] for r in samples),
              "terminal_kind": terminal, "terminal_observer": observed, "outcome": asdict(outcome),
              "net_return": value, "complete_costs": [asdict(c) for c in costs],
              "cpu_seconds": cpu_used, "wall_seconds": wall_used, "written_bytes": written_bytes,
              "caller_preparation_cpu_seconds": measured_entry - cpu_start,
              "cpu_admission_threshold_exceeded": cpu_used > budget.cpu_admission_seconds,
              "cpu_overshoot_seconds": max(0.0, cpu_used - budget.cpu_admission_seconds),
              "host_refusals": host_refusals, "owner_closed_ns": owner_closed,
              "private_scoring_started_ns": scoring_started, "native_execution": native,
              "resource_support": support_status(budget, prices),
              "native_readout_selected_host_action": False, "native_authority": "DENY_ALL"}
    return sum(scores), value, record
