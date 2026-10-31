"""Research-only frozen trained head; terminal FP64 law and Q24 release are separate."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import numpy as np

from .. import task
from ..round4 import calibration as cal, runtime_law
from . import interop, selection_study as study


PUBLIC_FIELDS = ("obs", "times", "mask", "occupied", "obs_var")
CHECKPOINT_SCHEMA = "hepta.research-terminal-head.v1"


@dataclass(frozen=True)
class PublicHistory:
    """Only acquired values and their schedule/missingness; no targets or IDs."""

    obs: np.ndarray
    times: np.ndarray
    mask: np.ndarray
    occupied: np.ndarray
    obs_var: np.ndarray

    def __post_init__(self):
        raw = {key: np.array(getattr(self, key), copy=True) for key in PUBLIC_FIELDS}
        public = cal.public_history(raw)
        if (len(public["obs"]) == 0 or not 1 <= public["obs"].shape[1] <= 8
                or np.any(raw["mask"] & ~raw["occupied"])
                or any(np.any(np.diff(t[active]) < 0) for t, active in zip(raw["times"], raw["occupied"]))):
            raise ValueError("Nonempty histories with up to eight chronological slots and valid occupancy required")
        for key in PUBLIC_FIELDS:
            public[key].setflags(write=False)
            object.__setattr__(self, key, public[key])


class PredictionHead:
    """A verified, stateless selected-model handle, not a production activation."""

    def __init__(self, run_dir, *, seed, window, arm, expected_freeze_sha256, freeze_path=None):
        run_dir = Path(run_dir)
        freeze_path = Path(freeze_path) if freeze_path is not None else run_dir / "FREEZE.json"
        if study.sha(freeze_path) != expected_freeze_sha256:
            raise ValueError("The independently expected freeze identity is required")
        prepared = study.verify_prepared(run_dir, freeze_path)
        if (type(seed) is not int or seed not in prepared["registration"]["seeds"]
                or type(window) is not int or not 0 <= window < len(prepared["registration"]["windows"])
                or arm not in study.ARMS):
            raise ValueError("An explicitly registered seed, window and arm are required")
        relative = f"seed_{seed}/window_{window:02d}_CHECKPOINT.json"
        payload = (run_dir / "prepared" / relative).read_bytes()
        checkpoint_sha = hashlib.sha256(payload).hexdigest()
        if checkpoint_sha != prepared["artifacts_sha256"][relative]:
            raise ValueError("Selected checkpoint changed after preparation verification")
        checkpoint = json.loads(payload)
        model = checkpoint["models"][arm]
        if (checkpoint["seed"] != seed or checkpoint["window"] != window
                or model["context_count"] != 0 or model["parameter_q24"] is not False):
            raise ValueError("Only the registered zero-extra-context FP64 model is supported")
        binding = {"seed": seed, "window": window, "arm": arm, "freeze_sha256": expected_freeze_sha256,
                   "prepared_sha256": study.sha(run_dir / "prepared/PREPARED.json"),
                   "checkpoint_path": relative, "checkpoint_sha256": checkpoint_sha,
                   "model_sha256": study.object_sha(model), "registration_sha256": prepared["registration_sha256"],
                   "study_sources_sha256": study.object_sha(prepared["sources_sha256"]),
                   "adapter_sha256": study.sha(__file__), "interop_sha256": study.sha(interop.__file__)}
        self._model_json = json.dumps(model, sort_keys=True, allow_nan=False)
        self._binding_json = json.dumps(binding, sort_keys=True, allow_nan=False)

    def checkpoint(self):
        """Identity only; restoring reopens the verified source model and evidence."""
        return {"schema": CHECKPOINT_SCHEMA, "binding": json.loads(self._binding_json)}

    @classmethod
    def restore(cls, checkpoint, run_dir, *, freeze_path=None):
        if set(checkpoint) != {"schema", "binding"} or checkpoint["schema"] != CHECKPOINT_SCHEMA:
            raise ValueError("An explicit trained-head identity checkpoint is required")
        binding = checkpoint["binding"]
        restored = cls(run_dir, seed=binding["seed"], window=binding["window"], arm=binding["arm"],
                       expected_freeze_sha256=binding["freeze_sha256"], freeze_path=freeze_path)
        if restored.checkpoint() != checkpoint:
            raise ValueError("Restoration source/model/checkpoint binding differs")
        return restored

    def forecast(self, history, *, row, horizon, lower=task.LOWER, upper=task.UPPER):
        """Select an already propagated endpoint; reject unrepresentable positive tails."""
        if type(history) is not PublicHistory:
            raise TypeError("Only PublicHistory is accepted; no target-bearing dictionaries")
        if (type(row) is not int or not 0 <= row < len(history.obs)
                or type(horizon) not in (int, float) or horizon not in task.HORIZONS):
            raise ValueError("Valid row and an exact registered horizon 0, .5, 1 or 2 required")
        public = {key: getattr(history, key) for key in PUBLIC_FIELDS}
        distribution = cal.predict_distribution(json.loads(self._model_json), public)
        law = cal.law_at(distribution, row, int(np.flatnonzero(task.HORIZONS == horizon)[0]))
        result = interop.TerminalForecast(law, float(task.latest_time(public)[row]), float(horizon), lower, upper)
        interop.forecast(result)  # Validate physical clock, strict boundaries and terminal law.
        return result


def release_q24(forecast):
    """Actual inherited positive-Hamilton release, separate from physical tails."""
    if type(forecast) is not interop.TerminalForecast:
        raise TypeError("An explicit terminal forecast is required")
    interop.forecast(forecast)
    return runtime_law.release_law(forecast.law, forecast.lower, forecast.upper)
