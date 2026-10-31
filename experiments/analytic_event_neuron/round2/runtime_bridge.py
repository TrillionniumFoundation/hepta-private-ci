"""Durable signed-event decoder feeding the original native typed owner.

The two owners are not an atomic cross-owner transaction. Pending work blocks
further execution after a partial commit. Only reopened decoder counts feed
the native head; encoder residuals are never a downstream inference input.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from .. import learners, task
from ..analytic import event_log_probs, event_probs
from ..native_adapter import Native
from ..runtime import _atomic, _lock, digest
from . import adaptation
from .pulse import EventDecoder, PulseConfig, SignedEventNeuron, probability_error_bound


SCHEMA = "hepta.signed-event.composite-owner.v1"
ZERO = "0" * 64


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read(path):
    envelope = json.loads(Path(path).read_text())
    if set(envelope) != {"document", "sha256"} or digest(envelope["document"]) != envelope["sha256"]:
        raise ValueError("Corrupt composite owner envelope")
    return envelope["document"]


def _write(path, document):
    _atomic(Path(path), {"document": document, "sha256": digest(document)})


def density_bound(mean, variance, anchor_mean, anchor_variance):
    """Supremum of NLL(candidate)-NLL(anchor), including unbounded cases."""
    c = variance / anchor_variance
    d = (mean - anchor_mean) / math.sqrt(anchor_variance)
    if c < 1 or (c == 1 and d != 0):
        return {"finite": False, "upper_bound": None}
    value = 0.0 if c == 1 else 0.5 * math.log(c) + d * d / (2 * (c - 1))
    return {"finite": True, "upper_bound": value}


class AdaptiveEventRuntime:
    """A frozen model and versioned event receiver coupled to a native owner."""

    def __init__(self, models_file, model_key, dataset_digest, native, directory,
                 *, expected_model_sha256, config=None, generation=1, maximum_ticks=1024,
                 runtime_mode="count_only"):
        self.models_file, self.model_sha256 = Path(models_file), file_sha(models_file)
        if self.model_sha256 != expected_model_sha256:
            raise ValueError("Frozen model file mismatch")
        self.model = json.loads(self.models_file.read_text())
        if model_key:
            for key in model_key.split("."):
                self.model = self.model[key]
        if self.model.get("kind") not in ("filter", "protected_filter", "fixed_mixture", "likelihood_mixture"):
            raise ValueError("Unsupported frozen conditional model")
        if len(dataset_digest) != 64 or any(x not in "0123456789abcdef" for x in dataset_digest):
            raise ValueError("Dataset SHA256 required")
        if type(generation) is not int or generation < 1 or type(maximum_ticks) is not int or not 1 <= maximum_ticks <= 1024:
            raise ValueError("Invalid generation or bounded lifetime")
        self.model_key, self.model_digest = model_key, digest(self.model)
        if runtime_mode not in ("count_only", "anchor_guarded") or (runtime_mode == "anchor_guarded" and self.model["kind"] != "protected_filter"):
            raise ValueError("Guarded runtime requires an explicitly bound protected anchor")
        self.runtime_mode = runtime_mode
        self.dataset_digest, self.native = dataset_digest, native
        self.directory, self.config = Path(directory), config or PulseConfig()
        self.generation, self.maximum_ticks = generation, maximum_ticks

    def step(self, history, horizon, tick_id, sequence, *, expected_checkpoint=ZERO,
             observation_kind=None, fail_stage=None):
        started = time.perf_counter_ns()
        if file_sha(self.models_file) != self.model_sha256 or digest(self.model) != self.model_digest:
            raise ValueError("Frozen model changed after initialization")
        if set(history) != {"id", "observations", "times", "mask", "obs_var"}:
            raise ValueError("Only declared public history fields accepted")
        observations, times, variances = [np.asarray(history[k], dtype=float) for k in ("observations", "times", "obs_var")]
        mask = np.asarray(history["mask"])
        if (observations.ndim != 1 or not 1 <= len(observations) <= 8 or times.shape != observations.shape
                or variances.shape != observations.shape or mask.shape != observations.shape or mask.dtype != bool
                or not np.isfinite([observations, times, variances]).all() or np.any(variances <= 0)
                or np.any(times < 0) or np.any(np.diff(times) < 0) or not isinstance(history["id"], str) or not history["id"]):
            raise ValueError("Invalid public history")
        if horizon not in tuple(task.HORIZONS) or type(sequence) is not int or not 1 <= sequence <= self.maximum_ticks or not isinstance(tick_id, str) or not tick_id:
            raise ValueError("Invalid registered horizon or sequence")
        kind = observation_kind or ("observed" if mask[-1] else "missing")
        if kind not in ("observed", "missing", "propagation") or fail_stage not in (None, "after_pending", "after_native", "after_commit"):
            raise ValueError("Invalid event kind or interruption stage")
        observations = np.where(mask, observations, 0.0)
        public = {"id": history["id"], "observations": observations.tolist(), "times": times.tolist(), "mask": mask.tolist(), "obs_var": variances.tolist()}
        h = {"obs": observations[None, :], "times": times[None, :], "mask": mask[None, :],
             "obs_var": variances[None, :], "occupied": np.ones((1, len(times)), bool), "ids": np.asarray([public["id"]])}
        forecast = learners.forecast if self.model["kind"] == "filter" else adaptation.forecast
        means, predicted_variances = forecast(self.model, h, horizon)
        mean, variance = float(means[0]), float(predicted_variances[0])
        subject = digest([self.model_sha256, self.model_key, self.model_digest, public["id"], horizon,
                          self.dataset_digest, self.generation, asdict(self.config), self.runtime_mode, self.maximum_ticks])
        owner = self.directory / subject
        owner.mkdir(parents=True, exist_ok=True)
        state_path, pending_path = owner / "state.json", owner / "pending.json"
        witness_path = owner / "delivery.witness.json"
        request = {"schema": SCHEMA, "subject": subject, "model_file_sha256": self.model_sha256,
                   "model_entry_sha256": self.model_digest, "model_key": self.model_key, "dataset_sha256": self.dataset_digest,
                   "generation": self.generation, "tick_id": tick_id, "sequence": sequence,
                   "history_sha256": digest(public), "conditioning_time": float(times[-1]),
                   "target_time": float(times[-1] + horizon), "horizon": float(horizon), "observation_kind": kind,
                   "runtime_mode": self.runtime_mode}
        request_sha = digest(request)
        with _lock(owner / "owner.lock"):
            state = _read(state_path) if state_path.exists() else {"schema": SCHEMA, "subject": subject,
                "checkpoint": ZERO, "native_checkpoint": ZERO, "sequence": 0, "time": None,
                "encoder": SignedEventNeuron(self.config).snapshot(), "decoder": EventDecoder(self.config).snapshot(), "entries": {}}
            if state["schema"] != SCHEMA or state["subject"] != subject:
                raise ValueError("Owner identity mismatch")
            witness = _read(witness_path) if witness_path.exists() else {
                "schema": "hepta.signed-event.delivery-witness.v1", "subject": subject, "records": []}
            if witness["schema"] != "hepta.signed-event.delivery-witness.v1" or witness["subject"] != subject:
                raise ValueError("Delivery witness identity mismatch")
            if len(witness["records"]) != state["sequence"]:
                raise ValueError("Delivery witness and composite state sequence disagree")
            if witness["records"] and (witness["records"][-1]["checkpoint"] != state["checkpoint"]
                    or witness["records"][-1]["state_sha256"] != digest(state)):
                raise ValueError("Independent delivery witness rejects state rollback or corruption")
            predecessor = ZERO
            for i, item in enumerate(witness["records"], 1):
                if item["sequence"] != i or item["predecessor"] != predecessor:
                    raise ValueError("Invalid delivery witness ancestry")
                predecessor = item["checkpoint"]
            if tick_id in state["entries"]:
                previous = state["entries"][tick_id]
                if previous["request_sha256"] != request_sha:
                    raise ValueError("Duplicate tick ID has different public request")
                return previous
            if pending_path.exists():
                raise RuntimeError("Partial cross-owner commit requires explicit reconciliation")
            if state["checkpoint"] != expected_checkpoint or state["sequence"] + 1 != sequence:
                raise ValueError("Composite checkpoint CAS or sequence mismatch")
            if state["time"] is not None and float(times[-1]) < state["time"]:
                raise ValueError("Conditioning clock regression")
            neuron = SignedEventNeuron.restore(state["encoder"])
            decoder = EventDecoder.restore(state["decoder"])
            if neuron.decoder.snapshot() != decoder.snapshot() or decoder.sequence != state["sequence"]:
                raise ValueError("Encoder/receiver ancestry mismatch")
            packet = neuron.update(mean, variance, float(times[-1]), kind)
            decoder.apply(packet)
            proposed = {"request": request, "request_sha256": request_sha, "predecessor": state["checkpoint"],
                        "encoder": neuron.snapshot(), "decoder": decoder.snapshot(), "packet": packet, "stage": "prepared"}
            _write(pending_path, proposed)
            if fail_stage == "after_pending":
                raise RuntimeError("Injected interruption before native commit")
            durable = _read(pending_path)
            decoded_mean, decoded_variance = EventDecoder.restore(durable["decoder"]).readout()
            head_mean, head_variance, guard = decoded_mean, decoded_variance, None
            anchor_mean = anchor_variance = None
            if self.model["kind"] == "protected_filter":
                am, av = learners.forecast(self.model["anchor"], h, horizon)
                anchor_mean, anchor_variance = float(am[0]), float(av[0])
            if self.runtime_mode == "anchor_guarded":
                from .quantized_guard import guard_quantized_scalar as guard_quantized
                guard = guard_quantized(anchor_mean, anchor_variance, decoded_mean, self.model["epsilon"])
                head_mean, head_variance = float(guard["mean"]), float(guard["variance"])
            native = self.native.typed("round2." + subject, owner / "native", head_mean,
                                       head_variance, task.LOWER, task.UPPER,
                                       expected_checkpoint=state["native_checkpoint"])
            if native["sequence"] != sequence:
                raise RuntimeError("Native sequence mismatch; pending work retained")
            proposed.update(native=native, stage="native_committed")
            _write(pending_path, proposed)
            if fail_stage == "after_native":
                raise RuntimeError("Injected interruption after native commit")
            original_probabilities = event_probs(mean, variance, task.LOWER, task.UPPER)
            decoded_probabilities = event_probs(decoded_mean, decoded_variance, task.LOWER, task.UPPER)
            head_probabilities = event_probs(head_mean, head_variance, task.LOWER, task.UPPER)
            reference = event_probs(*native["head"]["parameters_q24_decoded"])
            bound = probability_error_bound(mean, variance, decoded_mean, decoded_variance)
            protected_bound = None
            if self.model["kind"] == "protected_filter":
                quantized = native["head"]["parameters_q24_decoded"]
                protected_bound = {"epsilon": self.model["epsilon"],
                    "anchor_mean": anchor_mean, "anchor_variance": anchor_variance,
                    "before_encoding": density_bound(mean, variance, anchor_mean, anchor_variance),
                    "after_event_encoding": density_bound(decoded_mean, decoded_variance, anchor_mean, anchor_variance),
                    "after_native_q24_input": density_bound(quantized[0], quantized[1], anchor_mean, anchor_variance),
                    "inherits_fp64_guarantee": False}
                actual_bound = protected_bound["after_native_q24_input"]
                if self.runtime_mode == "anchor_guarded" and (not actual_bound["finite"] or actual_bound["upper_bound"] > self.model["epsilon"] + 1e-12
                        or quantized[:2] != [head_mean, head_variance]):
                    raise RuntimeError("Actual native parameters violate numerical guard; pending retained")
            delivered_q24 = list(native["head"]["probabilities_q24"])
            event_guard, anchor_log_probability = None, None
            if self.runtime_mode == "anchor_guarded":
                from .quantized_guard import protected_event_quantize_scalar
                anchor_log_probability = event_log_probs(anchor_mean, anchor_variance, task.LOWER, task.UPPER).tolist()
                event_guard = protected_event_quantize_scalar(anchor_log_probability,
                    np.asarray(delivered_q24) / (1 << 24), self.model["epsilon"])
                delivered_q24 = list(event_guard["counts"])
                if not event_guard["exact_mass"] or event_guard["maximum_event_nll_excess"] > self.model["epsilon"] + 1e-12:
                    raise RuntimeError("Post-native categorical protection failed; pending retained")
            after = digest({"subject": subject, "predecessor": state["checkpoint"], "request": request_sha,
                            "decoder": durable["decoder"], "native_checkpoint": native["checkpoint_after"],
                            "delivered_probabilities_q24": delivered_q24, "anchor_log_probabilities": anchor_log_probability})
            receipt = {**request, "request_sha256": request_sha, "public_history": public,
                       "source_forecast": {"mean": mean, "variance": variance}, "packet": packet,
                       "decoder": durable["decoder"], "decoded_mean": decoded_mean, "decoded_variance": decoded_variance,
                       "decoded_probabilities": decoded_probabilities.tolist(), "source_probabilities": original_probabilities.tolist(),
                       "head_mean": head_mean, "head_variance": head_variance, "head_probabilities": head_probabilities.tolist(),
                       "guard_certificate": guard, "explicit_frozen_anchor_reference": self.runtime_mode == "anchor_guarded",
                       "delivered_probabilities_q24": delivered_q24,
                       "delivered_probabilities": (np.asarray(delivered_q24) / (1 << 24)).tolist(),
                       "delivered_probability_source": "post_native_research_adapter" if event_guard else "native_head",
                       "anchor_log_probabilities": anchor_log_probability,
                       "anchor_log_probabilities_sha256": digest(anchor_log_probability) if anchor_log_probability is not None else None,
                       "categorical_guard_certificate": event_guard,
                       "original_rust_witness_binds_post_projection": False,
                       "codec_probability_bound": bound, "codec_probability_error": np.abs(original_probabilities - decoded_probabilities).tolist(),
                       "native_cdf_error": float(np.max(np.abs(np.asarray(native["head"]["probabilities"]) - reference))),
                       "native_output_q24_error": float(np.max(np.abs(np.asarray(native["head"]["probabilities_q24"]) / (1 << 24) - reference))),
                       "input_q24_probability_error": float(np.max(np.abs(reference - head_probabilities))),
                       "guard_probability_change": float(np.max(np.abs(head_probabilities - decoded_probabilities))),
                       "protected_density_bounds": protected_bound,
                       "native": native, "native_binary_sha256": self.native.receipt["binary_sha256"],
                       "checkpoint_before": state["checkpoint"], "checkpoint_after": after,
                       "decoder_reopened_from_disk_before_native": True, "encoder_residual_used_by_native": False,
                       "logical_unit_events": sum(abs(value) for value in packet["counts"]),
                       "packet_bytes": len(json.dumps(packet, sort_keys=True, separators=(",", ":")).encode()),
                       "compute_ns_before_commit": time.perf_counter_ns() - started,
                       "authority": "DENY_ALL", "production_agentd_owner": False, "cross_owner_atomicity": False}
            state.update(checkpoint=after, native_checkpoint=native["checkpoint_after"], sequence=sequence,
                         time=float(times[-1]), encoder=neuron.snapshot(), decoder=durable["decoder"])
            state["entries"][tick_id] = receipt
            witness["records"].append({"sequence": sequence, "predecessor": receipt["checkpoint_before"],
                "checkpoint": after, "state_sha256": digest(state), "native_checkpoint": native["checkpoint_after"],
                "delivered_output_sha256": digest(delivered_q24), "request_sha256": request_sha})
            # Independent delivery witness precedes state acknowledgement. A crash
            # between these owners remains pending and cannot silently advance.
            _write(witness_path, witness)
            _write(state_path, state)
            pending_path.unlink()
            if fail_stage == "after_commit":
                raise RuntimeError("Injected lost acknowledgement after durable composite commit")
            return receipt


def worker(job_path, output):
    job = json.loads(Path(job_path).read_text())
    with Native(job.pop("native_binary"), job.pop("native_receipt")) as native:
        step = job.pop("step")
        config = job.pop("config", None)
        adapter = AdaptiveEventRuntime(native=native, config=PulseConfig(**config) if config else None, **job)
        receipt = adapter.step(**step)
        document = {"receipt": receipt, "native_requests_this_process": native.calls,
                    "native_ticks_this_process": native.original_sparse_ticks}
    _atomic(Path(output), document)


def qualify(models_file, model_key, dataset_file, output, native_binary, native_receipt, runtime_mode="count_only"):
    """Use a frozen model and developmental histories; never confirmation labels."""
    began, parent_cpu = time.perf_counter_ns(), time.process_time_ns()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    checks, records, recovery, stress_records = [], [], [], []
    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append({"name": name, "passed": True})
    model_sha, data_sha = file_sha(models_file), file_sha(dataset_file)
    with np.load(dataset_file, allow_pickle=False) as source:
        check("development split only", str(source["split"].item()) == "development")
        histories = []
        for i in range(min(4, len(source["ids"]))):
            histories.append({"id": str(source["ids"][i]), "observations": source["obs"][i].tolist(),
                              "times": source["times"][i].tolist(), "mask": source["mask"][i].tolist(),
                              "obs_var": source["obs_var"][i].tolist()})
    settings = {"models_file": str(Path(models_file).resolve()), "model_key": model_key,
                "dataset_digest": data_sha, "directory": str((output / "owners").resolve()),
                "expected_model_sha256": model_sha, "runtime_mode": runtime_mode}
    with Native(native_binary, native_receipt) as native:
        adapter = AdaptiveEventRuntime(native=native, **settings)
        for history in histories:
            for horizon in (0.5, 1.0, 2.0):
                record = adapter.step(history, horizon, "forecast.1", 1)
                records.append(record)
                check("reopened receiver feeds declared head", record["decoder_reopened_from_disk_before_native"] and not record["encoder_residual_used_by_native"]
                      and bool(np.allclose(record["native"]["input_parameters_fp64"][:2],
                                           [record["head_mean"], record["head_variance"]], rtol=0.0, atol=2e-15)))
                if runtime_mode == "anchor_guarded":
                    bound = record["protected_density_bounds"]["after_native_q24_input"]
                    check("actual native Q24 Gaussian has certified old-loss envelope", bound["finite"] and bound["upper_bound"] <= adapter.model["epsilon"] + 1e-12
                          and record["explicit_frozen_anchor_reference"])
                    check("delivered Q24 events have their own protection certificate",
                          record["categorical_guard_certificate"]["exact_mass"]
                          and record["categorical_guard_certificate"]["maximum_event_nll_excess"] <= adapter.model["epsilon"] + 1e-12
                          and record["delivered_probability_source"] == "post_native_research_adapter"
                          and not record["original_rust_witness_binds_post_projection"])
                check("codec probability bound", bool(np.all(np.asarray(record["codec_probability_error"]) <= np.asarray(record["codec_probability_bound"]) + 2e-15)))
                check("qualified numerical head", record["native_cdf_error"] <= 2e-15 and record["native_output_q24_error"] <= 1 / (1 << 24) + 2e-15)
                check("non-authorizing original runtime", record["native"]["abstain"] and record["native"]["legacy_runtime_confidence_ppm"] == 0
                      and record["native"]["original_neuron_runtime"] and record["native"]["independent_anchor_witness"])
        first = records[0]
        try:
            adapter.step(histories[0], 0.5, "stale", 2, expected_checkpoint=ZERO)
        except ValueError:
            check("stale CAS rejected before native", native.calls == len(records))
        else:
            raise AssertionError("stale CAS accepted")
        changed = {**histories[0], "observations": list(histories[0]["observations"])}
        observed_index = next(i for i, present in enumerate(changed["mask"]) if present)
        changed["observations"][observed_index] += 0.01
        try:
            adapter.step(changed, 0.5, "forecast.1", 1)
        except ValueError:
            check("duplicate identity with changed public evidence rejected", native.calls == len(records))
        else:
            raise AssertionError("Changed duplicate accepted")
    for index, step in enumerate([
        {"history": histories[0], "horizon": 0.5, "tick_id": "forecast.1", "sequence": 1},
        {"history": histories[0], "horizon": 0.5, "tick_id": "forecast.2", "sequence": 2,
         "expected_checkpoint": first["checkpoint_after"], "observation_kind": "propagation"},
    ]):
        job = {**settings, "native_binary": str(Path(native_binary).resolve()),
               "native_receipt": str(Path(native_receipt).resolve()), "step": step}
        path, result_path = output / f"recovery_job_{index}.json", output / f"recovery_{index}.json"
        _atomic(path, job)
        completed = subprocess.run([sys.executable, "-m", "experiments.analytic_event_neuron.round2.runtime_bridge", "worker",
                                    "--job", str(path), "--output", str(result_path)], capture_output=True, text=True, check=False)
        if completed.returncode:
            raise RuntimeError(completed.stderr)
        result = json.loads(result_path.read_text())
        recovery.append(result)
    check("fresh-process duplicate produces no native tick", recovery[0]["receipt"] == first and recovery[0]["native_requests_this_process"] == 0)
    second = recovery[1]["receipt"]
    check("fresh-process continuation uses native ancestry", recovery[1]["native_ticks_this_process"] == 1
          and second["native"]["checkpoint_before"] == first["native"]["checkpoint_after"])
    check("unchanged forecast yields zero events, not a neutral label", second["packet"]["counts"] == [0, 0]
          and second["packet"]["observation_kind"] == "propagation" and second["decoded_probabilities"] == first["decoded_probabilities"])
    with Native(native_binary, native_receipt) as native:
        adapter = AdaptiveEventRuntime(native=native, **settings)
        ack = dict(histories[0], id=histories[0]["id"] + "/ack")
        try:
            adapter.step(ack, 1.0, "ack.1", 1, fail_stage="after_commit")
        except RuntimeError:
            pass
        acknowledged = adapter.step(ack, 1.0, "ack.1", 1)
        check("lost acknowledgement replays committed receipt", native.calls == 1 and acknowledged["sequence"] == 1)
        missing = {**histories[0], "id": histories[0]["id"] + "/missing",
                   "observations": list(histories[0]["observations"]), "mask": list(histories[0]["mask"])}
        missing["mask"][-1], missing["observations"][-1] = False, 12345.0
        absent = adapter.step(missing, 1.0, "missing.1", 1)
        calls = native.calls
        missing["observations"][-1] = -99999.0
        same = adapter.step(missing, 1.0, "missing.1", 1)
        check("missing storage does not become a zero observation or extra evidence",
              same == absent and native.calls == calls and absent["packet"]["observation_kind"] == "missing")
        rollback_case = dict(histories[0], id=histories[0]["id"] + "/rollback")
        before = adapter.step(rollback_case, 1.0, "rollback.1", 1)
        state_path = Path(settings["directory"]) / before["subject"] / "state.json"
        delivery_witness_path = state_path.with_name("delivery.witness.json")
        old_bytes = state_path.read_bytes()
        old_delivery_witness = delivery_witness_path.read_bytes()
        after = adapter.step(rollback_case, 1.0, "rollback.2", 2, expected_checkpoint=before["checkpoint_after"])
        new_bytes = state_path.read_bytes()
        new_delivery_witness = delivery_witness_path.read_bytes()
        state_path.write_bytes(old_bytes)
        calls = native.calls
        try:
            adapter.step(rollback_case, 1.0, "rollback.3", 3, expected_checkpoint=after["checkpoint_after"])
        except ValueError:
            check("independent delivery witness rejects composite-state rollback", native.calls == calls)
        else:
            raise AssertionError("Rollback accepted")
        finally:
            state_path.write_bytes(new_bytes)
        delivery_witness_path.write_bytes(old_delivery_witness)
        try:
            adapter.step(rollback_case, 1.0, "witness_rollback", 3, expected_checkpoint=after["checkpoint_after"])
        except ValueError:
            check("composite state rejects independent delivery-witness rollback", native.calls == calls)
        else:
            raise AssertionError("Delivery witness rollback accepted")
        finally:
            delivery_witness_path.write_bytes(new_delivery_witness)
        damaged = bytearray(new_bytes)
        damaged[0] = ord("[")
        state_path.write_bytes(damaged)
        try:
            adapter.step(rollback_case, 1.0, "corrupt", 3, expected_checkpoint=after["checkpoint_after"])
        except (ValueError, KeyError):
            check("corrupt composite state rejected", native.calls == calls)
        else:
            raise AssertionError("Corrupt state accepted")
        finally:
            state_path.write_bytes(new_bytes)
        witness_case = dict(histories[0], id=histories[0]["id"] + "/native_rollback")
        before = adapter.step(witness_case, 1.0, "witness.1", 1)
        journal_path = Path(settings["directory"]) / before["subject"] / "native/state.journal"
        first_journal = journal_path.read_bytes()
        after = adapter.step(witness_case, 1.0, "witness.2", 2, expected_checkpoint=before["checkpoint_after"])
        second_journal = journal_path.read_bytes()
        journal_path.write_bytes(first_journal)
        calls = native.calls
        try:
            adapter.step(witness_case, 1.0, "witness.3", 3, expected_checkpoint=after["checkpoint_after"])
        except ValueError:
            check("independent native witness rejects journal rollback", native.calls == calls)
        else:
            raise AssertionError("Native rollback accepted")
        finally:
            journal_path.write_bytes(second_journal)
        for stage in ("after_pending", "after_native"):
            case = dict(histories[0], id=histories[0]["id"] + "/" + stage)
            try:
                adapter.step(case, 1.0, "partial.1", 1, fail_stage=stage)
            except RuntimeError:
                pass
            calls = native.calls
            try:
                adapter.step(case, 1.0, "partial.1", 1)
            except RuntimeError:
                check("partial commit remains blocked: " + stage, native.calls == calls)
            else:
                raise AssertionError("Partial commit silently retried")
        bounded = AdaptiveEventRuntime(native=native, maximum_ticks=1, **settings)
        case = dict(histories[0], id=histories[0]["id"] + "/capacity")
        before = bounded.step(case, 1.0, "capacity.1", 1)
        calls = native.calls
        try:
            bounded.step(case, 1.0, "capacity.2", 2, expected_checkpoint=before["checkpoint_after"])
        except ValueError:
            check("bounded lifetime rejects additional ticks", native.calls == calls)
        else:
            raise AssertionError("Capacity exceeded")
        if runtime_mode == "anchor_guarded":
            # A numerical qualification fixture, not sampled efficacy evidence:
            # all observations share time zero and precise public noise.
            sensor_variance = 0.006 / adapter.model["anchor"]["parameters"][2]
            stress_history = {"id": histories[0]["id"] + "/categorical_tail_fixture",
                "observations": [2.0] * 6, "times": [0.0] * 6, "mask": [True] * 6,
                "obs_var": [sensor_variance] * 6}
            stress = adapter.step(stress_history, 0.0, "tail.1", 1)
            stress_records.append(stress)
            check("actual native tail rounding loses positive event support",
                  0 in stress["native"]["head"]["probabilities_q24"])
            check("post-native projection restores positive support and exact mass",
                  min(stress["delivered_probabilities_q24"]) > 0
                  and sum(stress["delivered_probabilities_q24"]) == 1 << 24
                  and stress["delivered_probabilities_q24"] != stress["native"]["head"]["probabilities_q24"])
            check("corrected delivered tail has certified event logscore bound",
                  stress["categorical_guard_certificate"]["maximum_event_nll_excess"] <= adapter.model["epsilon"] + 1e-12)
            witness = _read(Path(settings["directory"]) / stress["subject"] / "delivery.witness.json")
            check("independent delivery witness binds corrected tail and original native anchor",
                  witness["records"][-1]["delivered_output_sha256"] == digest(stress["delivered_probabilities_q24"])
                  and witness["records"][-1]["native_checkpoint"] == stress["native"]["checkpoint_after"])
    check("frozen source artifacts unchanged", file_sha(models_file) == model_sha and file_sha(dataset_file) == data_sha)
    protected = [r["protected_density_bounds"] for r in records if r["protected_density_bounds"] is not None]
    summary = {"schema": "hepta.signed-event.runtime-qualification.v1", "passed": True,
               "model_file_sha256": model_sha, "model_key": model_key, "dataset_file_sha256": data_sha,
               "native_binary_sha256": file_sha(native_binary), "current_session_fresh_build": False,
               "forecasts": len(records), "fresh_python_processes": len(recovery), "checks": checks,
               "deterministic_tail_fixtures": len(stress_records),
               "maximum_native_cdf_error": max(r["native_cdf_error"] for r in records),
               "maximum_output_q24_error": max(r["native_output_q24_error"] for r in records),
               "maximum_delivered_event_nll_excess": max((r["categorical_guard_certificate"]["maximum_event_nll_excess"]
                    for r in records if r["categorical_guard_certificate"] is not None), default=None),
               "runtime_mode": runtime_mode, "protected_postcodec_guarantee_claimed": runtime_mode == "anchor_guarded",
               "protected_density_bounds": protected,
               "source_sha256": file_sha(__file__), "production_agentd_owner": False,
               "wall_ns": time.perf_counter_ns() - began, "parent_cpu_ns": time.process_time_ns() - parent_cpu,
               "cost_scope": "Whole qualification including fresh processes and negative interventions; native timings and file sizes in per-tick receipts",
               "limitation": "Pending partial transactions require explicit reconciliation; no cross-owner atomicity claim"}
    for name, document in (("RUNTIME_QUALIFICATION.json", summary), ("FORECAST_RECEIPTS.json", records),
                           ("RECOVERY_RECEIPTS.json", recovery), ("STRESS_RECEIPTS.json", stress_records)):
        _atomic(output / name, document)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("worker", "qualify"))
    for name in ("job", "output", "models-file", "model-key", "dataset-file", "native-binary", "native-receipt"):
        parser.add_argument("--" + name)
    parser.add_argument("--runtime-mode", default="count_only")
    args = vars(parser.parse_args())
    operation = args.pop("operation")
    if operation == "worker":
        worker(args["job"], args["output"])
    else:
        args.pop("job")
        summary = qualify(**args)
        print(json.dumps({"passed": summary["passed"], "forecasts": summary["forecasts"], "checks": len(summary["checks"])}))
