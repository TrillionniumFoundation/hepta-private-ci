"""Matched frozen-kernel temporal pilot; this is not full network training.

The HCSN arm calls the exact PR5343 FP64 probability/content implementation.
The other arms are a GRU, a diagonal continuous-time SSM and a fixed LIF
voltage/event-trace reservoir. The last arm is NOT an EventProp replication.
Only identical linear heads learn. Synthetic cue retention and delay-shift
adaptation exercise the comparison contract; none qualifies real-task benefit,
HCSN fidelity, optimal NDU control or an energy/performance advantage.
"""

import copy
from dataclasses import dataclass
import hashlib
import io
import json
import math
from pathlib import Path
import platform
import time

import torch
from torch import nn
from torch.nn import functional as F


HCSN_COMMIT = "bb048cb811c2b755b7e54e97d24c63ec7ec8d1b7"
HCSN_HASHES = {
    "__init__.py": "bcde159e1a07a1da1df4b22caccae7f974443d34bbd071a6e845791f3e8b4123",
    "checkpoint.py": "9565cba284f479bbab7c8ee61ca7a5330ddb9a9c4efed7786d92a37f7a93c793",
    "contract.py": "35338e23a8809c1d5ec83159247e3ae7a3511b2857e60dbc78098bdedb8ec41f",
    "encoder.py": "8297a3a994e0ff7b97e4d73b4ac92f8bdc8a691dfdf145fc8fcc45be5cad7b18",
    "network.py": "5b92871b84f24e6b3ccb8231e8068b1d834b5edb4b351a8caa684e52c80611bd",
    "operator.py": "75a81f620c954433ad14ae4b3253038bc88af69f300052495cec8eb782ba58c5",
}
KINDS = ("gru", "diagonal_ssm", "hcsn", "lif_event")
WIDTH = 9
MAX_DT = 0.1


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


def _tensor_digest(tensors):
    digest = hashlib.sha256()
    for name, tensor in sorted(tensors.items()):
        tensor = tensor.detach().cpu().contiguous()
        digest.update(
            json.dumps([name, list(tensor.shape), str(tensor.dtype)]).encode()
        )
        digest.update(tensor.numpy().tobytes())
    return digest.hexdigest()


def verify_hcsn_source(directory=None):
    """Bind the imported source closure, not a branch name or an old test pass."""
    directory = (
        Path(__file__).resolve().parents[1] / "hcsn_differentiable"
        if directory is None
        else Path(directory)
    )
    actual = {
        name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
        for name in HCSN_HASHES
    }
    if actual != HCSN_HASHES:
        raise ValueError("HCSN source differs from the declared PR5343 exact commit")
    return {
        "repository": "TrillionniumFoundation/hepta-private-ci",
        "commit": HCSN_COMMIT,
        "sha256": actual,
    }


@dataclass(frozen=True)
class TemporalBatch:
    values: torch.Tensor
    dt: torch.Tensor
    targets: torch.Tensor

    def encoded(self):
        # The same parameter-free, causal encoder is used by every arm.
        # There is no target, final elapsed time or future observation input.
        return torch.cat((self.values, self.dt[..., None] / MAX_DT), dim=-1)

    def identity(self):
        return _tensor_digest(
            {"values": self.values, "dt": self.dt, "targets": self.targets}
        )


def make_temporal_batch(size, steps, seed, *, shifted=False):
    """Balanced delayed-cue recall with independent distractors and time gaps.

    The shifted condition changes the physical gaps, not the label definition.
    It measures adaptation to a delay distribution, not timeout calibration.
    All positions are observations. Long gaps are NOT silently subdivided.
    """
    if size < 2 or steps < 3:
        raise ValueError("a batch needs at least two episodes and three positions")
    generator = torch.Generator(device="cpu").manual_seed(seed)
    targets = (torch.arange(size) % 2).to(torch.float64)
    targets = targets[torch.randperm(size, generator=generator)]
    values = torch.zeros(size, steps, 3, dtype=torch.float64)
    values[:, :, 0] = 0.12 * torch.randn(
        size, steps, generator=generator, dtype=torch.float64
    )
    values[:, 0, 0] = 2.0 * targets - 1.0
    values[:, 0, 1] = 1.0
    values[:, -1, 0] = 0.0
    values[:, -1, 2] = 1.0
    choices = torch.tensor(
        [0.06, 0.075, 0.09] if shifted else [0.02, 0.035, 0.05], dtype=torch.float64
    )
    dt = choices[torch.randint(3, (size, steps), generator=generator)]
    return TemporalBatch(values, dt, targets)


@dataclass(frozen=True)
class TemporalState:
    payload: object
    elapsed: torch.Tensor
    position: int
    signature: str


class FrozenTemporalKernel(nn.Module):
    """One explicit retained-state interface; every temporal parameter is frozen."""

    def __init__(self, kind, seed):
        super().__init__()
        if kind not in KINDS:
            raise ValueError(f"unknown temporal kernel: {kind}")
        self.kind, self.seed = kind, seed
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed)
            if kind == "hcsn":
                self.source = verify_hcsn_source()
                from qualification.hcsn_differentiable.contract import GridSpec
                from qualification.hcsn_differentiable.network import (
                    ContinuousSpikingNetwork,
                )

                self.model = ContinuousSpikingNetwork(
                    4,
                    content_dim=WIDTH - 5,
                    output_dim=WIDTH,
                    layer_count=2,
                    grid=GridSpec(active_cells=6, phase_cells=3, quadrature_order=8),
                )
                # Expose the native final content+physical channels through an
                # identity readout, then train the same external head as other arms.
                with torch.no_grad():
                    self.model.readout.weight.copy_(
                        torch.eye(WIDTH, dtype=torch.float64)
                    )
                    self.model.readout.bias.zero_()
            elif kind == "gru":
                self.model = nn.GRUCell(4, WIDTH).double()
            else:
                self.model = nn.Linear(4, WIDTH).double()
                self.register_buffer(
                    "rates", torch.logspace(-0.5, 1.0, WIDTH, dtype=torch.float64)
                )
        self.requires_grad_(False)

    def signature(self):
        config = self.model.configuration() if self.kind == "hcsn" else {"width": WIDTH}
        return _digest(
            {
                "kind": self.kind,
                "seed": self.seed,
                "configuration": config,
                "state_dict": _tensor_digest(self.state_dict()),
            }
        )

    def initial_state(self, batch_size):
        if self.kind == "hcsn":
            payload = self.model.initial_state(
                batch_size, absolute_initial=math.exp(0.18)
            )
        else:
            payload = {"hidden": torch.zeros(batch_size, WIDTH, dtype=torch.float64)}
            if self.kind == "lif_event":
                payload["events"] = torch.zeros_like(payload["hidden"])
        return TemporalState(
            payload, torch.zeros(batch_size, dtype=torch.float64), 0, self.signature()
        )

    def forward(self, features, dt, *, state):
        if (
            features.ndim != 3
            or features.shape[-1] != 4
            or features.shape[1] < 1
            or features.dtype != torch.float64
            or features.device.type != "cpu"
            or dt.shape != features.shape[:2]
            or dt.dtype != torch.float64
            or dt.device.type != "cpu"
            or not bool(torch.isfinite(features).all())
            or not bool(torch.isfinite(dt).all())
            or bool(((dt < 0) | (dt > MAX_DT)).any())
        ):
            raise ValueError(
                "pilot requires finite FP64 CPU features and 0 <= dt <= 0.1"
            )
        if (
            not isinstance(state, TemporalState)
            or state.signature != self.signature()
            or state.elapsed.shape != (features.shape[0],)
            or state.elapsed.dtype != torch.float64
            or state.elapsed.device.type != "cpu"
            or not bool(torch.isfinite(state.elapsed).all())
            or bool((state.elapsed < 0).any())
            or isinstance(state.position, bool)
            or not isinstance(state.position, int)
            or state.position < 0
        ):
            raise ValueError("incompatible retained state or changed frozen kernel")
        if not torch.equal(features[..., -1], dt / MAX_DT):
            raise ValueError(
                "encoded time channel must match the actual physical duration"
            )
        if self.kind == "hcsn":
            if (
                not torch.equal(state.payload.elapsed, state.elapsed)
                or state.payload.sequence_position != state.position
            ):
                raise ValueError("inconsistent retained HCSN clocks")
            result = self.model(features, dt, state=state.payload)
            outputs, payload, diagnostics = (
                result.predictions,
                result.state,
                result.diagnostics,
            )
        else:
            hidden = state.payload["hidden"]
            event_trace = state.payload.get("events")
            rows, event_count = [], 0
            for index in range(features.shape[1]):
                x, gap = features[:, index], dt[:, index, None]
                if self.kind == "gru":
                    hidden = self.model(x, hidden)
                elif self.kind == "diagonal_ssm":
                    decay = torch.exp(-gap * self.rates)
                    hidden = decay * hidden + (1.0 - decay) * torch.tanh(self.model(x))
                else:
                    decay = torch.exp(-gap * self.rates * 4.0)
                    voltage = decay * hidden + (1.0 - decay) * (
                        1.5 * torch.sigmoid(self.model(x))
                    )
                    events = (voltage >= 0.5).to(torch.float64)
                    hidden = voltage - 0.5 * events
                    event_trace = torch.exp(-gap * 2.0) * event_trace + events
                    event_count += int(events.sum())
                rows.append(hidden if event_trace is None else hidden + event_trace)
            outputs = torch.stack(rows, dim=1)
            payload = {"hidden": hidden}
            if event_trace is not None:
                payload["events"] = event_trace
            diagnostics = {
                "actual_binary_events": event_count
                if self.kind == "lif_event"
                else None
            }
        if not bool(torch.isfinite(outputs).all()):
            raise FloatingPointError("nonfinite temporal representation")
        # Preserve the native clock's exact summation convention so a wrapped
        # HCSN checkpoint cannot disagree by one ULP with its own inner clock.
        elapsed = payload.elapsed if self.kind == "hcsn" else state.elapsed + dt.sum(1)
        successor = TemporalState(
            payload, elapsed, state.position + features.shape[1], state.signature
        )
        return outputs, successor, diagnostics

    def checkpoint(self, state):
        if state.signature != self.signature():
            raise ValueError("cannot checkpoint a changed kernel")
        payload = (
            self.model.checkpoint(state.payload)
            if self.kind == "hcsn"
            else copy.deepcopy(state.payload)
        )
        return {
            "schema": "frozen-temporal-state-v1",
            "signature": state.signature,
            "payload": payload,
            "elapsed": state.elapsed.clone(),
            "position": state.position,
        }

    def restore_checkpoint(self, checkpoint):
        if (
            checkpoint.get("schema") != "frozen-temporal-state-v1"
            or checkpoint.get("signature") != self.signature()
        ):
            raise ValueError("checkpoint belongs to another frozen kernel")
        elapsed, position = checkpoint["elapsed"], checkpoint["position"]
        if (
            elapsed.ndim != 1
            or elapsed.dtype != torch.float64
            or elapsed.device.type != "cpu"
            or not bool(torch.isfinite(elapsed).all())
            or bool((elapsed < 0).any())
            or isinstance(position, bool)
            or not isinstance(position, int)
            or position < 0
        ):
            raise ValueError("invalid checkpoint clocks")
        payload = copy.deepcopy(checkpoint["payload"])
        if self.kind == "hcsn":
            # The native API can restore weights. This frozen-kernel adapter
            # must reject a payload that substitutes another model under the
            # unchanged outer signature, before any model/RNG mutation occurs.
            if _tensor_digest(payload["model"]) != _tensor_digest(
                self.model.state_dict()
            ):
                raise ValueError("checkpoint changed the frozen HCSN model")
            if (
                not torch.equal(payload["elapsed"], elapsed)
                or payload["sequence_position"] != position
            ):
                raise ValueError("inconsistent HCSN checkpoint clocks")
            payload = self.model.restore_checkpoint(payload)
            if (
                not torch.equal(payload.elapsed, elapsed)
                or payload.sequence_position != position
            ):
                raise ValueError("inconsistent HCSN checkpoint clocks")
        else:
            keys = {"hidden", "events"} if self.kind == "lif_event" else {"hidden"}
            if (
                not isinstance(payload, dict)
                or payload.keys() != keys
                or any(
                    tensor.shape != (elapsed.numel(), WIDTH)
                    or tensor.dtype != torch.float64
                    or tensor.device.type != "cpu"
                    or not bool(torch.isfinite(tensor).all())
                    for tensor in payload.values()
                )
            ):
                raise ValueError("incomplete checkpoint numerical state")
        return TemporalState(payload, elapsed.clone(), position, self.signature())


def _fit_head(features, targets, steps, head=None, progress=None):
    if head is None:
        head = nn.Linear(WIDTH, 1).double()
        nn.init.zeros_(head.weight)
        nn.init.zeros_(head.bias)
    optimizer = torch.optim.SGD(head.parameters(), lr=0.1)
    for _ in range(steps):
        optimizer.zero_grad(set_to_none=True)
        loss = F.binary_cross_entropy_with_logits(head(features).squeeze(-1), targets)
        loss.backward()
        if not bool(torch.isfinite(loss)) or any(
            not bool(torch.isfinite(p.grad).all()) for p in head.parameters()
        ):
            raise FloatingPointError("head loss or gradient is nonfinite")
        optimizer.step()
        if progress is not None:
            progress["head_updates_completed"] += 1
    return head


def _score(head, features, targets):
    with torch.no_grad():
        logits = head(features).squeeze(-1)
        return {
            "accuracy": float(((logits >= 0) == targets.bool()).double().mean()),
            "bce": float(F.binary_cross_entropy_with_logits(logits, targets)),
            "brier": float((torch.sigmoid(logits) - targets).square().mean()),
            "episodes": targets.numel(),
        }


def checkpoint_difference(kernel, batch, whole=None):
    """Serialize complete state, then consume the suffix in an identical new kernel."""
    features, split = batch.encoded(), batch.dt.shape[1] // 2
    with torch.no_grad():
        if whole is None:
            whole, _, _ = kernel(
                features, batch.dt, state=kernel.initial_state(len(batch.targets))
            )
        _, first, _ = kernel(
            features[:, :split],
            batch.dt[:, :split],
            state=kernel.initial_state(len(batch.targets)),
        )
        archive = io.BytesIO()
        torch.save(kernel.checkpoint(first), archive)
        archive.seek(0)
        recovered = FrozenTemporalKernel(kernel.kind, kernel.seed)
        state = recovered.restore_checkpoint(torch.load(archive, weights_only=True))
        suffix, final, _ = recovered(
            features[:, split:], batch.dt[:, split:], state=state
        )
    return {
        "maximum_feature_error": float((suffix - whole[:, split:]).abs().max()),
        "elapsed_maximum_error": float((final.elapsed - batch.dt.sum(1)).abs().max()),
        "checkpoint_bytes": archive.getbuffer().nbytes,
        "autograd_tape_restored": False,
    }


def _peak_process_rss():
    try:
        import resource

        observed = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(observed if platform.system() == "Darwin" else observed * 1024)
    except (ImportError, AttributeError):
        return None


def run_temporal_pilot(
    seeds=(17, 29), horizon=32, size=24, head_steps=40, on_attempt=None
):
    """Return every kernel/seed attempt, including errors; never pass by skipping.

    Three equal-budget head fits per kernel/seed: short recall, long recall,
    then delay-shift adaptation of the long head. The same held-out long panel
    measures retention. No evaluation result selects parameters or stopping.
    RSS is a process-lifetime high water, NOT isolated comparative kernel memory.
    A caller may persist ``started`` and ``finished`` snapshots via on_attempt.
    Callback exceptions propagate: a failed receipt write must not become a
    caught model failure or permit the next attempt to start silently.
    """
    seeds = tuple(seeds)
    if (
        not seeds
        or len(set(seeds)) != len(seeds)
        or any(
            isinstance(s, bool) or not isinstance(s, int) or not 0 <= s < 2**31
            for s in seeds
        )
        or any(
            isinstance(v, bool) or not isinstance(v, int)
            for v in (horizon, size, head_steps)
        )
        or not 8 <= horizon <= 256
        or not 4 <= size <= 4096
        or not 1 <= head_steps <= 10000
    ):
        raise ValueError("invalid seeds or bounded temporal pilot budget")
    if on_attempt is not None and not callable(on_attempt):
        raise TypeError("on_attempt must be callable")
    short = min(8, horizon // 2)
    contract = {
        "encoder": "causal identity [cue/distractor, cue_flag, query_flag, dt/0.1]",
        "head": {
            "kind": "linear",
            "input": WIDTH,
            "output": 1,
            "initialization": "zeros",
            "optimizer": "SGD",
            "learning_rate": 0.1,
            "steps_per_fit": head_steps,
        },
        "ndu": {"profile": "disabled_fixed_sequence_v1", "optimization_claim": False},
        "short_positions": short,
        "long_positions": horizon,
        "episodes_per_panel": size,
        "training_scope": "frozen_temporal_kernels_head_only",
        "head_fits_per_attempt": 3,
        "tuning_trials": 0,
        "dtype": "float64",
        "device": "cpu",
    }
    report = {
        "schema": "cell-common-temporal-pilot-v1",
        "contract": contract,
        "contract_sha256": _digest(contract),
        "attempt_unit": "kernel x independent initialization seed",
        "acceptance": "HOLD",
        "production_qualified": False,
        "real_data": False,
        "full_parameter_training": False,
        "energy_joules": None,
        "energy_status": "not_measured",
        "hardware": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "torch": torch.__version__,
            "cpu_threads": torch.get_num_threads(),
        },
        "attempts": [],
    }
    for seed in seeds:
        panels = {
            "short_train": make_temporal_batch(size, short, seed * 100 + 1),
            "short_test": make_temporal_batch(size, short, seed * 100 + 2),
            "long_train": make_temporal_batch(size, horizon, seed * 100 + 3),
            "long_test": make_temporal_batch(size, horizon, seed * 100 + 4),
            "shift_train": make_temporal_batch(
                size, horizon, seed * 100 + 5, shifted=True
            ),
            "shift_test": make_temporal_batch(
                size, horizon, seed * 100 + 6, shifted=True
            ),
        }
        for kind in KINDS:
            started = time.perf_counter()
            attempt = {
                "kernel": kind,
                "seed": seed,
                "status": "running",
                "cases": {},
                "panel_sha256": {
                    name: batch.identity() for name, batch in panels.items()
                },
                "contract_sha256": report["contract_sha256"],
                "head_updates_completed": 0,
            }
            report["attempts"].append(attempt)
            if on_attempt is not None:
                on_attempt("started", copy.deepcopy(attempt))
            try:
                kernel = FrozenTemporalKernel(kind, seed)
                signature = kernel.signature()
                attempt.update(
                    kernel_sha256=signature,
                    frozen_parameter_count=sum(p.numel() for p in kernel.parameters()),
                    trained_head_parameter_count=WIDTH + 1,
                )
                if kind == "hcsn":
                    attempt.update(
                        hcsn_source=kernel.source,
                        hcsn_configuration=kernel.model.configuration(),
                    )
                representations = {}
                feature_start = time.perf_counter()
                with torch.no_grad():
                    for name, batch in panels.items():
                        outputs, _, diagnostics = kernel(
                            batch.encoded(), batch.dt, state=kernel.initial_state(size)
                        )
                        representations[name] = outputs[:, -1].detach()
                        if name == "long_test":
                            whole = outputs
                            attempt["long_diagnostics"] = diagnostics
                attempt["feature_wall_seconds"] = time.perf_counter() - feature_start
                training_start = time.perf_counter()
                for case in ("short", "long"):
                    head = _fit_head(
                        representations[case + "_train"],
                        panels[case + "_train"].targets,
                        head_steps,
                        progress=attempt,
                    )
                    attempt["cases"][case + "_dependency"] = _score(
                        head,
                        representations[case + "_test"],
                        panels[case + "_test"].targets,
                    )
                # 'head' is the independently fitted long-dependency head.
                before = _score(
                    head, representations["shift_test"], panels["shift_test"].targets
                )
                _fit_head(
                    representations["shift_train"],
                    panels["shift_train"].targets,
                    head_steps,
                    head,
                    progress=attempt,
                )
                after = _score(
                    head, representations["shift_test"], panels["shift_test"].targets
                )
                retention = _score(
                    head, representations["long_test"], panels["long_test"].targets
                )
                attempt["cases"]["delay_adaptation"] = {
                    "before": before,
                    "after": after,
                    "original_delay_panel_after": retention,
                    "original_delay_accuracy_change": retention["accuracy"]
                    - attempt["cases"]["long_dependency"]["accuracy"],
                }
                attempt["head_training_and_scoring_wall_seconds"] = (
                    time.perf_counter() - training_start
                )
                attempt["recovery"] = checkpoint_difference(
                    kernel, panels["long_test"], whole
                )
                if (
                    attempt["recovery"]["maximum_feature_error"] > 1e-11
                    or signature != kernel.signature()
                ):
                    raise AssertionError(
                        "continuation mismatch or frozen temporal parameters changed"
                    )
                attempt["status"] = "completed"
            except Exception as error:
                attempt.update(
                    status="failed",
                    error_type=type(error).__name__,
                    error=str(error)[:1000],
                )
            attempt["total_wall_seconds_including_recovery"] = (
                time.perf_counter() - started
            )
            attempt["process_lifetime_peak_rss_bytes"] = _peak_process_rss()
            if on_attempt is not None:
                on_attempt("finished", copy.deepcopy(attempt))
    report["counts"] = {
        "planned": len(seeds) * len(KINDS),
        "attempted": len(report["attempts"]),
        "completed": sum(a["status"] == "completed" for a in report["attempts"]),
        "failed": sum(a["status"] == "failed" for a in report["attempts"]),
    }
    report["limitations"] = [
        "synthetic finite-budget head-only mechanism pilot",
        "no timeout calibration task",
        "unequal frozen state/parameter counts are reported, not claimed matched",
        "process-lifetime RSS is not isolated per-kernel peak memory",
        "LIF event arm does not implement EventProp",
        "no end-to-end energy measurement",
        "HCSN finite QPR projection and early refractory-release errors remain",
    ]
    return report
