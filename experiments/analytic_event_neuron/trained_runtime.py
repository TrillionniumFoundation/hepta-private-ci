"""Frozen trained Gaussian forecasts through real native and pulse owners."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from .analytic import event_probs
from .learners import forecast
from .native_adapter import Native
from .runtime import EventRuntime, Q24, _atomic, _lock, digest


HORIZONS = (0.5, 1.0, 2.0)
LOWER, UPPER = -0.6, 0.6


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class FrozenForecastAdapter:
    """Load an actual MODELS.json analytic filter; accept public histories only.

    The two underlying owners do not share a transaction manager. An interrupted
    partial commit is marked pending and requires explicit reconciliation; this
    adapter never silently appends another native tick after such an interruption.
    """
    def __init__(self, models_file, dataset_digest, native, directory, *, seed, generation=1,
                 expected_model_sha256=None):
        self.models_file = Path(models_file)
        self.model_sha256 = file_sha(self.models_file)
        if expected_model_sha256 is not None and expected_model_sha256 != self.model_sha256:
            raise ValueError("Frozen model artifact mismatch")
        self.model = json.loads(self.models_file.read_text())["analytic"]
        parameters = np.asarray(self.model["parameters"], dtype=float)
        if (self.model.get("kind") != "filter" or parameters.shape != (3,)
                or not np.isfinite(parameters).all() or np.any(parameters[1:] <= 0)):
            raise ValueError("A trained finite Gaussian filter is required")
        self.entry_digest = digest(self.model)
        self.dataset_digest, self.native = dataset_digest, native
        self.directory, self.seed, self.generation = Path(directory), seed, generation

    def step(self, history, horizon, tick_id, sequence, *, expected_native_checkpoint=None,
             expected_pulse_checkpoint=None, observation_kind=None):
        if file_sha(self.models_file) != self.model_sha256 or digest(self.model) != self.entry_digest:
            raise ValueError("Frozen model changed after loading")
        if horizon not in HORIZONS or type(sequence) is not int or sequence < 1:
            raise ValueError("Registered horizon and positive sequence required")
        if set(history) != {"id", "observations", "times", "mask", "obs_var"}:
            raise ValueError("Only the declared public history fields are accepted")
        obs, times, variance = [np.asarray(history[k], dtype=float) for k in ("observations", "times", "obs_var")]
        mask = np.asarray(history["mask"])
        if (obs.ndim != 1 or not 1 <= len(obs) <= 8 or times.shape != obs.shape
                or variance.shape != obs.shape or mask.shape != obs.shape or mask.dtype != np.dtype(bool)
                or not np.isfinite([obs, times, variance]).all() or np.any(times < 0)
                or np.any(np.diff(times) < 0) or np.any(variance <= 0)
                or not isinstance(history["id"], str) or not history["id"]):
            raise ValueError("Invalid public history")
        obs = np.where(mask, obs, 0.)
        public = {"id": history["id"], "observations": obs.tolist(), "times": times.tolist(),
                  "mask": mask.tolist(), "obs_var": variance.tolist()}
        history_digest = digest(public)
        # Archive identity binds ownership, but hidden archive bytes must not
        # become random marks. RNG subject uses only frozen/public identities.
        subject = digest([self.model_sha256, public["id"], horizon, self.generation, self.seed])
        owner_scope = digest([subject, self.dataset_digest])
        owner_path = self.directory / owner_scope
        owner_path.mkdir(parents=True, exist_ok=True)
        h = {"obs": obs[None, :], "times": times[None, :], "mask": mask[None, :],
             "obs_var": variance[None, :], "occupied": np.ones((1, len(obs)), dtype=bool),
             "ids": np.asarray([public["id"]])}
        mean_array, variance_array = forecast(self.model, h, horizon)
        mean, predicted_variance = float(mean_array[0]), float(variance_array[0])
        conditioning, target = float(times[-1]), float(times[-1] + horizon)
        kind = observation_kind or ("observed" if mask[-1] else "prediction_only")
        request = {"model_file_sha256": self.model_sha256, "model_entry_digest": self.entry_digest,
                   "dataset_digest": self.dataset_digest, "history_digest": history_digest,
                   "subject": subject, "owner_scope": owner_scope, "horizon": horizon, "conditioning_time": conditioning,
                   "target_time": target, "tick_id": tick_id, "sequence": sequence, "observation_kind": kind,
                   "generation": self.generation, "rng_seed": self.seed}
        request_digest = digest(request)
        result_path = owner_path / (digest(tick_id) + ".json")
        pending = owner_path / "pending.json"
        with _lock(owner_path / "adapter.lock"):
            if result_path.exists():
                envelope = json.loads(result_path.read_text())
                result = envelope["receipt"]
                if envelope["receipt_digest"] != digest(result) or result["request_digest"] != request_digest:
                    raise ValueError("Combined receipt corruption or duplicate ID conflict")
                return result
            if pending.exists():
                raise RuntimeError("Partial native/pulse commit requires reconciliation; pending receipt retained")
            pulse = EventRuntime(owner_path / "pulse", {"model_digest": self.model_sha256,
                "dataset_digest": self.dataset_digest, "subject_id": subject, "generation": self.generation,
                "seed": self.seed, "lower": LOWER, "upper": UPPER, "forecast_horizon": horizon})
            current = pulse.snapshot()
            expected_pulse = expected_pulse_checkpoint if expected_pulse_checkpoint is not None else "0" * 64
            if sequence != current["state"]["steps"] + 1 or expected_pulse != current["checkpoint"]:
                raise ValueError("Pulse owner sequence/CAS mismatch before native execution")
            if sequence > 1 and expected_native_checkpoint is None:
                raise ValueError("Native caller anchor required after bootstrap")
            _atomic(pending, request)
            native = self.native.typed("trained.aen." + owner_scope, owner_path / "native", mean,
                predicted_variance, LOWER, UPPER, expected_checkpoint=expected_native_checkpoint or "0" * 64)
            probabilities = event_probs(mean, predicted_variance, LOWER, UPPER)
            quantized_input_reference = event_probs(*native["head"]["parameters_q24_decoded"])
            cdf_error = float(np.max(np.abs(native["head"]["probabilities"] - quantized_input_reference)))
            q24_error = float(np.max(np.abs(np.asarray(native["head"]["probabilities_q24"])/Q24 - quantized_input_reference)))
            if native["sequence"] != sequence or cdf_error > 2e-15 or q24_error > 1/Q24 + 2e-15:
                raise RuntimeError("Native forecast qualification failed; pending transaction retained")
            pulse_result = pulse.step(tick_id, sequence, conditioning, mean, predicted_variance,
                history_digest, expected_checkpoint=expected_pulse, target_timestamp=target, observation_kind=kind)
            if not np.array_equal(pulse_result["probabilities"], probabilities):
                raise RuntimeError("Probability mismatch; pending transaction retained")
            result = {"schema": "hepta.trained-forecast.adapter.v1", **request, "request_digest": request_digest,
                "models_file": str(self.models_file), "trained_parameters": self.model["parameters"],
                "native_binary_sha256": self.native.receipt["binary_sha256"], "public_history": public,
                "mean": mean, "variance": predicted_variance, "probabilities": probabilities.tolist(),
                "native_cdf_error": cdf_error, "native_output_q24_error": q24_error,
                "input_parameter_q24_probability_error": float(np.max(np.abs(probabilities-quantized_input_reference))),
                "native": native, "pulse": pulse_result, "authority": "DENY_ALL",
                "qualification_scope": "trained Python filter -> actual typed Rust probability head and durable pulse owner",
                "trained_weights_embedded_in_rust": False, "production_agentd_owner": False}
            _atomic(result_path, {"receipt": result, "receipt_digest": digest(result)})
            pending.unlink()
            return result


def qualify(training_root, output, native_binary, native_receipt):
    root, output = Path(training_root), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    records, recovery, sources, checks, replay_cases = [], [], [], [], []
    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append({"name": name, "passed": True})
    with Native(native_binary, native_receipt) as native:
        for seed in (11, 23, 37, 53, 71):
            directory = root / f"seed_{seed}"
            models, dataset = directory / "MODELS.json", directory / "DEVELOPMENT.npz"
            model_sha, data_sha = file_sha(models), file_sha(dataset)
            sources.append({"seed": seed, "models_file": str(models), "model_sha256": model_sha,
                            "dataset_file": str(dataset), "dataset_sha256": data_sha})
            adapter = FrozenForecastAdapter(models, data_sha, native, output / "owners", seed=seed,
                                             expected_model_sha256=model_sha)
            with np.load(dataset, allow_pickle=False) as data:
                check(f"seed {seed} development split only", str(data["split"].item()) == "development")
                for row in range(4):
                    public = {"id": str(data["ids"][row]), "observations": data["obs"][row].tolist(),
                        "times": data["times"][row].tolist(), "mask": data["mask"][row].tolist(),
                        "obs_var": data["obs_var"][row].tolist()}
                    for horizon in HORIZONS:
                        result = adapter.step(public, horizon, "forecast.1", 1)
                        records.append(result)
                        check(f"trained path seed={seed} row={row} h={horizon}",
                              result["native"]["abstain"] and result["native"]["legacy_runtime_confidence_ppm"] == 0
                              and result["pulse"]["target_timestamp"] == result["target_time"]
                              and result["pulse"]["model_digest"] == model_sha)
                        if row == 0 and horizon == 1.:
                            replay_cases.append((seed, models, data_sha, public, result))
            check(f"seed {seed} model file unchanged", file_sha(models) == model_sha)
    # Both subprocesses and Python owner instances are replaced before recovery.
    with Native(native_binary, native_receipt) as native:
        for seed, models, data_sha, public, before in replay_cases:
            adapter = FrozenForecastAdapter(models, data_sha, native, output / "owners", seed=seed,
                                             expected_model_sha256=before["model_file_sha256"])
            duplicate = adapter.step(public, 1., "forecast.1", 1)
            check(f"seed {seed} replay requires no native append", duplicate == before and native.calls == len(recovery))
            result = adapter.step(public, 1., "forecast.recovery.2", 2, observation_kind="prediction_only",
                expected_native_checkpoint=before["native"]["checkpoint_after"],
                expected_pulse_checkpoint=before["pulse"]["checkpoint_after"])
            check(f"seed {seed} recovered owners preserve forecast and ancestry",
                  result["probabilities"] == before["probabilities"]
                  and result["native"]["head"]["probabilities_q24"] == before["native"]["head"]["probabilities_q24"]
                  and result["native"]["checkpoint_before"] == before["native"]["checkpoint_after"]
                  and result["pulse"]["checkpoint_before"] == before["pulse"]["checkpoint_after"])
            recovery.append(result)
    check("horizon subjects are disjoint", len({r["subject"] for r in records}) == 60)
    summary = {"schema": "hepta.trained-forecast.qualification.v1", "all_passed": True,
        "forecast_cases": len(records), "recovery_ticks": len(recovery), "sources": sources, "checks": checks,
        "native_binary_sha256": file_sha(native_binary), "data_split": "development only; no confirmation",
        "maximum_native_cdf_error": max(r["native_cdf_error"] for r in records),
        "maximum_native_output_q24_error": max(r["native_output_q24_error"] for r in records),
        "maximum_input_parameter_q24_probability_error": max(r["input_parameter_q24_probability_error"] for r in records),
        "new_effect_comparison": False, "trained_weights_embedded_in_rust": False,
        "limit": "paired owners use a pending marker, not a cross-owner atomic transaction manager"}
    for name, value in [("TRAINED_RUNTIME_VALIDATION.json", summary), ("FORECAST_RECEIPTS.json", records), ("RECOVERY_RECEIPTS.json", recovery)]:
        (output / name).write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("training-root", "output", "native-binary", "native-receipt"):
        parser.add_argument("--" + name, required=True)
    result = qualify(**vars(parser.parse_args()))
    print(json.dumps({"all_passed": result["all_passed"], "forecast_cases": result["forecast_cases"],
                      "recovery_ticks": result["recovery_ticks"]}))
