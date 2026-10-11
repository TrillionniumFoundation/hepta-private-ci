"""Actual NumPy SGD learning and Q24 export for the Rust dynamic Cell gate.

Frozen Stem features are provided by an externally approved encoder/dataset.
No synthetic metric from this module may authorize model promotion.
"""
from __future__ import annotations

import copy
import hashlib
import math
from dataclasses import dataclass

import numpy as np

Q24 = 1 << 24
MAX_Q24 = 8 * Q24
MAX_HEAD_PARAMETERS = 262_144


class LearningContractError(ValueError):
    pass


def _group_indices(width: int, groups: int) -> np.ndarray:
    return np.arange(width, dtype=np.int64) * groups // width


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return np.exp(-np.logaddexp(0.0, -x))


@dataclass
class DynamicCell:
    """All parameters are owned by one Cell, including its private state."""

    cell_id: str
    encoder_digest: str
    width: int
    groups: int
    rank: int
    down: np.ndarray
    up: np.ndarray
    gate_bias: np.ndarray
    cell_state: np.ndarray
    drive_weights: np.ndarray
    prediction_weights: np.ndarray
    drive_bias: float = 0.0
    prediction_bias: float = 0.0

    @classmethod
    def initialize(
        cls, cell_id: str, encoder_digest: str, width: int,
        groups: int, rank: int, seed: int,
    ) -> "DynamicCell":
        if not 1 <= width <= 512 or not 1 <= groups <= min(64, width) or not 1 <= rank <= 32:
            raise LearningContractError("unsupported dimensions")
        if not isinstance(encoder_digest, str) or len(encoder_digest) != 64:
            raise LearningContractError("missing pinned encoder digest")
        rng = np.random.default_rng(seed)
        return cls(
            cell_id, encoder_digest, width, groups, rank,
            rng.normal(0.0, 0.08 / np.sqrt(width), (rank, width)),
            rng.normal(0.0, 0.1 / np.sqrt(rank), (groups, rank)),
            np.zeros(groups, dtype=np.float64),
            np.zeros(groups, dtype=np.float64),
            rng.normal(0.0, 0.03 / np.sqrt(width), width),
            rng.normal(0.0, 0.03 / np.sqrt(width), width),
        )

    def clone_frozen(self) -> "DynamicCell":
        return copy.deepcopy(self)

    def parameter_count(self) -> int:
        return (
            self.rank * self.width + self.groups * self.rank
            + 2 * self.groups + 2 * self.width + 2
        )

    def _forward(self, features: np.ndarray):
        x = np.asarray(features, dtype=np.float64)
        if x.ndim != 2 or x.shape[1] != self.width or not np.isfinite(x).all():
            raise LearningContractError("wrong feature shape or nonfinite input")
        if np.abs(x).max() > 8:
            raise LearningContractError("feature Q24 range")
        group_index = _group_indices(self.width, self.groups)
        low = x @ self.down.T
        logits = low @ self.up.T + self.gate_bias + self.cell_state
        gates = np.clip(0.5 + logits / 4.0, 0.0, 1.0)
        gated = x * gates[:, group_index]
        prediction = gated @ self.prediction_weights + self.prediction_bias
        drive = gated @ self.drive_weights + self.drive_bias
        return prediction, drive, (x, low, logits, gates, gated, group_index)

    def predict(self, features: np.ndarray) -> np.ndarray:
        return self._forward(features)[0]

    def learn(self, features: np.ndarray, labels: np.ndarray, lr: float = 0.1) -> float:
        if not 0 < lr <= 1:
            raise LearningContractError("invalid learning rate")
        y = np.asarray(labels, dtype=np.float64)
        prediction, drive, (x, low, logits, gates, gated, group_index) = self._forward(features)
        if y.shape != (len(x),) or not np.isin(y, [0.0, 1.0]).all():
            raise LearningContractError("binary labels required")
        # The same task signal trains both typed projections without a hidden
        # trainable shared adapter or touching another Cell's optimizer.
        error_prediction = (_sigmoid(prediction) - y) / len(x)
        error_drive = (_sigmoid(drive) - y) / len(x)
        grad_prediction_w = gated.T @ error_prediction
        grad_drive_w = gated.T @ error_drive
        grad_prediction_b = float(error_prediction.sum())
        grad_drive_b = float(error_drive.sum())
        grad_features = (
            error_prediction[:, None] * self.prediction_weights[None, :]
            + error_drive[:, None] * self.drive_weights[None, :]
        ) * x
        grad_gate = np.zeros((len(x), self.groups), dtype=np.float64)
        for group in range(self.groups):
            grad_gate[:, group] = grad_features[:, group_index == group].sum(axis=1)
        unsaturated = (gates > 0) & (gates < 1)
        grad_logits = grad_gate * unsaturated / 4.0
        grad_up = grad_logits.T @ low
        grad_down = (grad_logits @ self.up).T @ x
        grad_bias = grad_logits.sum(axis=0)
        gradients = [
            grad_down, grad_up, grad_bias, grad_bias.copy(),
            grad_drive_w, grad_prediction_w,
            np.asarray([grad_drive_b]), np.asarray([grad_prediction_b]),
        ]
        norm = math.sqrt(sum(float((g * g).sum()) for g in gradients))
        multiplier = min(1.0, 1.0 / max(norm, 1e-12))
        self.down -= lr * multiplier * grad_down
        self.up -= lr * multiplier * grad_up
        self.gate_bias -= lr * multiplier * grad_bias
        self.cell_state -= lr * multiplier * grad_bias
        self.drive_weights -= lr * multiplier * grad_drive_w
        self.prediction_weights -= lr * multiplier * grad_prediction_w
        self.drive_bias -= lr * multiplier * grad_drive_b
        self.prediction_bias -= lr * multiplier * grad_prediction_b
        return float(np.logaddexp(0.0, prediction).mean() - (y * prediction).mean())

    def export_q24(self) -> dict:
        if self.parameter_count() > MAX_HEAD_PARAMETERS:
            raise LearningContractError("Cell parameters exceed Rust bound")

        def quant(values) -> list[int]:
            a = np.asarray(values, dtype=np.float64)
            if not np.isfinite(a).all() or np.abs(a).max() > 8:
                raise LearningContractError("trained weight beyond Q24 bound")
            return np.rint(a.reshape(-1) * Q24).astype(np.int64).tolist()

        return {
            "cell_identity": self.cell_id,
            "encoder_digest": self.encoder_digest,
            "input_width": self.width,
            "output_width": 1,
            "rank": self.rank,
            "groups": self.groups,
            "down_q24": quant(self.down),
            "up_q24": quant(self.up),
            "gate_bias_q24": quant(self.gate_bias),
            "cell_state_q24": quant(self.cell_state),
            "drive_weights_q24": quant(self.drive_weights),
            "prediction_weights_q24": quant(self.prediction_weights),
            "drive_bias_q24": quant([self.drive_bias]),
            "prediction_bias_q24": quant([self.prediction_bias]),
        }



def budgeted_cell(
    cell_id: str, encoder_digest: str, width: int, ceiling: int, seed: int,
) -> DynamicCell:
    """Pick a real dynamic gate capacity within a pre-registered Cell budget."""
    if ceiling not in (2048, 8192, 16384):
        raise LearningContractError("unknown primary capacity tier")
    candidates = []
    for rank in range(1, 33):
        for groups in (1, 2, 4, 8, 16, 32, 64):
            if groups > width:
                continue
            parameter_count = rank * width + groups * rank + 2 * groups + 2 * width + 2
            if parameter_count <= ceiling:
                candidates.append((parameter_count, rank, groups))
    if not candidates:
        raise LearningContractError("budget too small for declared feature width")
    _, rank, groups = max(candidates)
    cell = DynamicCell.initialize(cell_id, encoder_digest, width, groups, rank, seed)
    if cell.parameter_count() > ceiling:
        raise LearningContractError("unadmitted Cell capacity")
    return cell


def rust_candidate_digest(candidate: dict) -> str:
    """Exact field order/domain separator of DynamicGateArtifactV3::new."""
    h = hashlib.sha256(b"hepta.infer.dynamic-cell-gate.v3")
    for field in ("cell_identity", "encoder_digest"):
        raw = candidate[field].encode("utf-8")
        h.update(len(raw).to_bytes(8, "big"))
        h.update(raw)
    for field in ("input_width", "output_width", "rank", "groups"):
        h.update(candidate[field].to_bytes(8, "big"))
    for field in (
        "down_q24", "up_q24", "gate_bias_q24", "cell_state_q24",
        "drive_weights_q24", "prediction_weights_q24",
        "drive_bias_q24", "prediction_bias_q24",
    ):
        tensor = candidate[field]
        h.update(len(tensor).to_bytes(8, "big"))
        for v in tensor:
            h.update(int(v).to_bytes(8, "big", signed=True))
    return h.hexdigest()


def q24_reference(candidate: dict, input_q24: list[int]) -> tuple[list[int], list[int]]:
    """Integer parity oracle, no float shortcuts in gate or dense kernels."""
    width, groups, rank = (candidate[k] for k in ("input_width", "groups", "rank"))
    if len(input_q24) != width or any(abs(v) > MAX_Q24 for v in input_q24):
        raise LearningContractError("invalid reference input")

    def round_checked(raw: int) -> int:
        floor, remainder = divmod(raw, Q24)
        result = floor + int(2 * remainder > Q24 or (2 * remainder == Q24 and floor % 2 != 0))
        if abs(result) > MAX_Q24:
            raise LearningContractError("Q24 overflow")
        return result

    def dense(x: list[int], weights: list[int], bias: list[int]) -> list[int]:
        result = []
        for row, b in enumerate(bias):
            offset = row * len(x)
            raw = b * Q24 + sum(xi * wi for xi, wi in zip(x, weights[offset:offset + len(x)]))
            result.append(round_checked(raw))
        return result

    low = dense(input_q24, candidate["down_q24"], [0] * rank)
    group_logits = dense(low, candidate["up_q24"], candidate["gate_bias_q24"])
    gates = []
    for logit, state in zip(group_logits, candidate["cell_state_q24"]):
        summed = logit + state
        toward_zero = summed // 4 if summed >= 0 else -((-summed) // 4)
        gates.append(min(Q24, max(0, Q24 // 2 + toward_zero)))
    gated = [round_checked(x * gates[i * groups // width]) for i, x in enumerate(input_q24)]
    return (
        dense(gated, candidate["drive_weights_q24"], candidate["drive_bias_q24"]),
        dense(gated, candidate["prediction_weights_q24"], candidate["prediction_bias_q24"]),
    )


def paired_future_score(
    trained: DynamicCell, frozen: DynamicCell, future_x: np.ndarray,
    future_y: np.ndarray, no_change_probabilities: np.ndarray,
) -> dict[str, float]:
    """A strict three-way *scoring* seam, not a signed independent Evaluator."""
    if trained.cell_id != frozen.cell_id or trained.encoder_digest != frozen.encoder_digest:
        raise LearningContractError("frozen control identity mismatch")
    if (trained.width, trained.groups, trained.rank) != (
        frozen.width, frozen.groups, frozen.rank
    ):
        raise LearningContractError("frozen control architecture mismatch")
    if no_change_probabilities is None:
        raise LearningContractError("real frozen production no-change required")
    features = np.asarray(future_x, dtype=np.float64)
    y = np.asarray(future_y, dtype=np.float64)
    no_change = np.asarray(no_change_probabilities, dtype=np.float64)
    if (
        features.ndim != 2 or features.shape[1] != trained.width
        or len(features) == 0 or not np.isfinite(features).all()
        or y.shape != (len(features),) or no_change.shape != y.shape
        or not np.isfinite(y).all() or not np.isin(y, [0.0, 1.0]).all()
    ):
        raise LearningContractError("future labels/features or baseline are not aligned binary rows")
    if np.any((no_change <= 0) | (no_change >= 1)) or not np.isfinite(no_change).all():
        raise LearningContractError("invalid production baseline")
    def bce(logits: np.ndarray) -> float:
        return float(np.logaddexp(0, logits).mean() - np.mean(y * logits))

    def brier(probabilities: np.ndarray) -> float:
        return float(np.mean(np.square(probabilities - y)))

    def ece(probabilities: np.ndarray) -> float:
        # Fixed ten-bin reliability estimate; bins and future sample
        # membership must be frozen before scoring, never optimized on labels.
        bin_ids = np.minimum((probabilities * 10).astype(np.int64), 9)
        calibration_error = 0.0
        for bin_index in range(10):
            selected = bin_ids == bin_index
            if selected.any():
                calibration_error += float(
                    selected.mean()
                    * abs(probabilities[selected].mean() - y[selected].mean())
                )
        return calibration_error

    frozen_logits = frozen.predict(features)
    trained_logits = trained.predict(features)
    if (
        frozen_logits.shape != y.shape or trained_logits.shape != y.shape
        or not np.isfinite(frozen_logits).all()
        or not np.isfinite(trained_logits).all()
    ):
        raise LearningContractError("nonfinite or misaligned future prediction logits")
    frozen_probabilities = _sigmoid(frozen_logits)
    trained_probabilities = _sigmoid(trained_logits)
    no_change_loss = float((-y * np.log(no_change) - (1 - y) * np.log1p(-no_change)).mean())
    return {
        "no_change_bce": no_change_loss,
        "frozen_bce": bce(frozen_logits),
        "trained_bce": bce(trained_logits),
        "no_change_brier": brier(no_change),
        "frozen_brier": brier(frozen_probabilities),
        "trained_brier": brier(trained_probabilities),
        "no_change_ece": ece(no_change),
        "frozen_ece": ece(frozen_probabilities),
        "trained_ece": ece(trained_probabilities),
        "synthetic_or_offline_only": 1.0,
    }
