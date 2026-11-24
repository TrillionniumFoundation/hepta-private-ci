"""Owner-bound, episodic GRU/CfC/diagonal candidates for Cell research.

Reuses PRED-1 heads/Adam with a separate exact CfC BPTT implementation. This is not the
HCSN localization formal study or an implementation of S4/Mamba. Whole training
episodes start with fresh hidden state; a candidate never mutates its parent.
"""

from dataclasses import asdict, dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import time
import zipfile

import numpy as np

from hepta_pred1.models import Model

from .cfc import CfCModel


UPSTREAM_COMMIT = "3959aac6829a345ef674b7901cbdd62316305d89"
HCSN_PROTOCOL = "https://github.com/TrillionniumFoundation/hepta-private-ci/blob/5f7f55e015dde7fab0c174081fef090ff45501de/proposals/localization-v2/formal_protocol.json"
KERNELS = {
    "gru": "implemented; default mature recurrent baseline",
    "cfc": "implemented equation; default ncps mode, no backbone; last input is dt seconds",
    "diag_ssm": "implemented; simple stable diagonal recurrence, not S4/Mamba",
    "hcsn": "research candidate; separate numerical and formal-study admission required",
}


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest_arrays(arrays):
    return hashlib.sha256(
        _json(
            [
                (
                    key,
                    value.dtype.str,
                    value.shape,
                    hashlib.sha256(value.tobytes()).hexdigest(),
                )
                for key, value in sorted(arrays.items())
            ]
        ).encode()
    ).hexdigest()


@dataclass(frozen=True)
class TemporalConfig:
    input_dim: int
    action_dim: int
    output_dim: int
    hidden_dim: int = 16
    seed: int = 0
    kind: str = "gru"

    def __post_init__(self):
        if self.kind == "hcsn":
            raise ValueError(f"HCSN has no admitted Cell adapter: {HCSN_PROTOCOL}")
        if self.kind not in ("gru", "diag_ssm", "cfc"):
            raise ValueError("unknown implemented temporal kernel")
        dims = (self.input_dim, self.action_dim, self.output_dim, self.hidden_dim)
        if (
            any(type(v) is not int or not 1 <= v <= 1024 for v in dims)
            or self.hidden_dim > 256
        ):
            raise ValueError(
                "bounded kernels require dimensions 1..1024 and hidden width <=256"
            )
        if type(self.seed) is not int or not 0 <= self.seed < 2**64:
            raise ValueError("seed must be an unsigned 64-bit integer")

    @property
    def sha256(self):
        return hashlib.sha256(_json(asdict(self)).encode()).hexdigest()


class TrainingAttemptError(ValueError):
    """Retains measured failed-attempt costs; callers must keep the receipt."""

    def __init__(self, message, receipt):
        super().__init__(message)
        self.receipt = receipt


class TemporalKernel:
    """One owner's small kernel; parameter adoption requires a fresh episode.

    State is JSON-safe and caller-owned. Cursors count consumed observations;
    observe accepts exactly the next cursor. Predict never advances that cursor.
    The caller supplies authenticated observations and training-only datasets;
    these consistency checks do not authenticate the source or prove task benefit.
    """

    def __init__(self, cell_id, config):
        if not isinstance(cell_id, str) or not 1 <= len(cell_id) <= 128:
            raise ValueError("cell_id must be a nonempty bounded string")
        if not isinstance(config, TemporalConfig):
            raise TypeError("config must be TemporalConfig")
        self.cell_id, self.config = cell_id, config
        factory = CfCModel if config.kind == "cfc" else Model
        self._model = factory(**asdict(config))
        if self._model.parameter_count > 1_000_000:
            raise ValueError("small-kernel parameter budget exceeded")

    @property
    def weights_sha256(self):
        return _digest_arrays(self._model.params)

    @property
    def kernel_sha256(self):
        return _digest_arrays(
            {
                k: v
                for k, v in self._model.params.items()
                if k not in ("Wh", "bh", "Wy", "by")
            }
        )

    @property
    def heads_sha256(self):
        return _digest_arrays(
            {k: self._model.params[k] for k in ("Wh", "bh", "Wy", "by")}
        )

    @property
    def parameter_count(self):
        return self._model.parameter_count

    @property
    def optimizer_sha256(self):
        arrays = {
            prefix + key: value
            for prefix, group in (("m_", self._model.m), ("v_", self._model.v))
            for key, value in group.items()
        }
        arrays["steps"] = np.asarray(self._model.steps, dtype=np.int64)
        return _digest_arrays(arrays)

    def initial_state(self, episode_id):
        if not isinstance(episode_id, str) or not 1 <= len(episode_id) <= 128:
            raise ValueError("episode_id must be a nonempty bounded string")
        return {
            "schema": "hepta.cell.temporal-state.v1",
            "cell_id": self.cell_id,
            "config_sha256": self.config.sha256,
            "weights_sha256": self.weights_sha256,
            "episode_id": episode_id,
            "cursor": 0,
            "hidden": {k: v.tolist() for k, v in self._model.initial_state().items()},
        }

    def _state_arrays(self, state, episode_id):
        expected = self.initial_state(episode_id)
        if not isinstance(state, dict) or set(state) != set(expected):
            raise ValueError("invalid temporal state schema")
        if any(
            state[k] != expected[k] for k in expected if k not in ("hidden", "cursor")
        ):
            raise ValueError(
                "state owner, configuration, weights or episode mismatch; reset required"
            )
        if type(state["cursor"]) is not int or not 0 <= state["cursor"] < 2**53:
            raise ValueError("invalid observation cursor")
        if not isinstance(state["hidden"], dict) or set(state["hidden"]) != {"fast"}:
            raise ValueError("invalid hidden state keys")
        hidden = {
            k: np.asarray(v, dtype=np.float64) for k, v in state["hidden"].items()
        }
        if any(
            v.shape != (1, self.config.hidden_dim) or not np.isfinite(v).all()
            for v in hidden.values()
        ):
            raise ValueError("invalid hidden state shape or values")
        return hidden

    def observe(self, state, observation, *, episode_id, cursor):
        hidden = self._state_arrays(state, episode_id)
        if type(cursor) is not int or cursor != state["cursor"] or cursor >= 2**53 - 1:
            raise ValueError("observation replay or cursor gap")
        x = np.asarray(observation, dtype=np.float64)
        if x.shape != (self.config.input_dim,) or not np.isfinite(x).all():
            raise ValueError("observation must be one finite input vector")
        updated = self._model.observe(x[None], hidden)
        if not all(np.isfinite(v).all() for v in updated.values()):
            raise FloatingPointError("nonfinite state transition")
        return {
            **state,
            "cursor": cursor + 1,
            "hidden": {k: v.tolist() for k, v in updated.items()},
        }

    def predict(self, state, action, *, episode_id):
        hidden = self._state_arrays(state, episode_id)
        action = np.asarray(action, dtype=np.float64)
        if action.shape != (self.config.action_dim,) or not np.isfinite(action).all():
            raise ValueError("candidate action must be one finite vector")
        logits = self._model.predict_from_state(hidden, action[None])[0]
        if not np.isfinite(logits).all():
            raise FloatingPointError("nonfinite prediction")
        return logits.copy()

    def resources(self, state):
        hidden = self._state_arrays(state, state["episode_id"])
        return {
            "parameters": self._model.parameter_count,
            "parameter_array_bytes": sum(v.nbytes for v in self._model.params.values()),
            "optimizer_array_bytes": sum(
                v.nbytes for g in (self._model.m, self._model.v) for v in g.values()
            ),
            "persistent_state_array_bytes": sum(v.nbytes for v in hidden.values()),
            "serialized_state_bytes": len(_json(state).encode()),
            "energy_joules": None,
            "peak_ram_bytes": None,
            "peak_vram_bytes": None,
        }

    def train_candidate(
        self, episodes, actions, allowed_mask, *, updates=1, lr=0.003, clip=5.0
    ):
        """Fit full past-only episodes with fresh state; return an isolated candidate.

        The coarsened-label NLL ignores all-allowed (unknown) labels. Each Adam
        update follows a complete episode batch, never a live serving state.
        This local learning API does not implement the HCSN AdamW formal recipe.
        """
        wall, cpu = time.perf_counter(), time.process_time()
        receipt = {
            "schema": "hepta.cell.temporal-training.v1",
            "status": "started",
            "upstream_commit": UPSTREAM_COMMIT,
            "cell_id": self.cell_id,
            "config_sha256": self.config.sha256,
            "parent_weights_sha256": self.weights_sha256,
            "parent_optimizer_sha256": self.optimizer_sha256,
            "losses": [],
            "validated_updates": 0,
            "optimizer": "adam",
            "episode_state": "fresh for every complete batch and optimizer update",
            "energy_joules": None,
            "peak_ram_bytes": None,
            "peak_vram_bytes": None,
            "measurement_scope": "local candidate copy and episode fitting; excludes caller data preparation and serving",
        }
        try:
            if any(
                isinstance(v, bool)
                or not isinstance(v, (int, float, np.floating))
                or not np.isfinite(v)
                or v <= 0
                for v in (lr, clip)
            ):
                raise ValueError(
                    "learning rate and gradient cap must be finite positive numbers"
                )
            x, actions = (
                np.asarray(episodes, dtype=np.float64),
                np.asarray(actions, dtype=np.float64),
            )
            allowed = np.asarray(allowed_mask)
            if (
                type(updates) is not int
                or not 1 <= updates <= 1024
                or x.ndim != 3
                or not 1 <= x.shape[0] * x.shape[1] <= 8192
                or x.size > 2**20
                or x.shape[2] != self.config.input_dim
                or actions.shape != (len(x), self.config.action_dim)
                or allowed.shape != (len(x), self.config.output_dim)
                or allowed.dtype != np.bool_
                or not allowed.any(axis=1).all()
                or not np.isfinite(x).all()
                or not np.isfinite(actions).all()
            ):
                raise ValueError("invalid or over-budget complete episode batch")
            receipt.update(
                requested_updates=updates,
                learning_rate=float(lr),
                gradient_norm_cap=float(clip),
                batch_episodes=len(x),
                events_per_episode=x.shape[1],
            )
            receipt["data_sha256"] = _digest_arrays(
                {"episodes": x, "actions": actions, "allowed": allowed}
            )
            candidate = TemporalKernel(self.cell_id, self.config)
            for name in ("params", "m", "v"):
                setattr(
                    candidate._model,
                    name,
                    {k: v.copy() for k, v in getattr(self._model, name).items()},
                )
            candidate._model.steps = self._model.steps
            for _ in range(updates):
                loss = candidate._model.fit_step(x, actions, allowed, lr=lr, clip=clip)
                del candidate._model._cache
                if not all(
                    np.isfinite(v).all()
                    for name in ("params", "m", "v")
                    for v in getattr(candidate._model, name).values()
                ):
                    raise FloatingPointError(
                        "nonfinite candidate parameters or optimizer"
                    )
                receipt["losses"].append(loss)
                receipt["validated_updates"] = (
                    candidate._model.steps - self._model.steps
                )
            receipt.update(
                status="completed_candidate_only",
                candidate_weights_sha256=candidate.weights_sha256,
                candidate_optimizer_sha256=candidate.optimizer_sha256,
                resources=candidate.resources(
                    candidate.initial_state("reset-required")
                ),
            )
        except Exception as error:
            receipt.update(status="failed", error=f"{type(error).__name__}: {error}")
            raise TrainingAttemptError(str(error), receipt) from error
        finally:
            receipt.update(
                wall_seconds=time.perf_counter() - wall,
                process_cpu_seconds=time.process_time() - cpu,
            )
        return candidate, receipt

    def checkpoint(self, path, state):
        """Create one immutable NPZ with model, Adam moments/step and bound state."""
        self._state_arrays(state, state["episode_id"])
        payload = {
            "config": np.asarray(_json(asdict(self.config))),
            "steps": np.asarray(self._model.steps),
            "cell_state": np.asarray(_json(state)),
        }
        for prefix, group in (
            ("p_", self._model.params),
            ("m_", self._model.m),
            ("v_", self._model.v),
        ):
            payload.update({prefix + key: value for key, value in group.items()})
        data = io.BytesIO()
        np.savez_compressed(data, **payload)
        raw = data.getvalue()
        with Path(path).open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        return hashlib.sha256(raw).hexdigest()

    @classmethod
    def restore_checkpoint(cls, path, *, expected_sha256, cell_id, config):
        """Restore only externally identified bytes; checks integrity, not authorship."""
        with Path(path).open("rb") as stream:
            raw = stream.read(64 * 1024 * 1024 + 1)
        if (
            len(raw) > 64 * 1024 * 1024
            or hashlib.sha256(raw).hexdigest() != expected_sha256
        ):
            raise ValueError("checkpoint size or SHA256 mismatch")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if sum(item.file_size for item in archive.infolist()) > 64 * 1024 * 1024:
                raise ValueError("checkpoint expanded size exceeds bound")
        kernel = cls(cell_id, config)
        with np.load(io.BytesIO(raw), allow_pickle=False) as data:
            keys = {
                prefix + k
                for prefix in ("p_", "m_", "v_")
                for k in kernel._model.params
            }
            keys.update(("config", "steps", "cell_state"))
            if (
                len(data.files) != len(keys)
                or set(data.files) != keys
                or json.loads(str(data["config"])) != asdict(config)
            ):
                raise ValueError("checkpoint keys or configuration mismatch")
            if (
                data["steps"].shape != ()
                or data["steps"].dtype.kind not in "iu"
                or not 0 <= int(data["steps"]) < 2**63
            ):
                raise ValueError("invalid optimizer step")
            for prefix in ("p_", "m_", "v_"):
                for key, template in kernel._model.params.items():
                    value = data[prefix + key]
                    if (
                        value.dtype != np.float64
                        or value.shape != template.shape
                        or not np.isfinite(value).all()
                        or (prefix == "v_" and (value < 0).any())
                    ):
                        raise ValueError(
                            "invalid checkpoint parameter or optimizer array"
                        )
            state = json.loads(str(data["cell_state"]))
        kernel._model = type(kernel._model).load(io.BytesIO(raw))
        kernel._state_arrays(state, state["episode_id"])
        return kernel, state
