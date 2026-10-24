"""Batch immutable learned Cell states together with their private calibration.

Exact serving replicas may share computation; different calibrators or private
weights remain separate. This runtime owns no encoder and performs no learning.
"""

import hashlib
import time

import numpy as np

from cell_batch_runtime import BatchRuntimeError, _frozen
from cell_learning_models import canonical
from cell_logical_routing import LogicalCellRouter


class CalibratedCellRuntime:
    def __init__(self, heads, calibrators, cell_ids, task_ids, feature_identity,
                 *, generation=1, cache_bytes=0):
        heads, calibrators = tuple(heads), tuple(calibrators)
        self.task_ids = tuple(task_ids)
        if len(heads) != len(calibrators) or len(heads) != len(self.task_ids):
            raise BatchRuntimeError("one private calibration and task per Cell required")
        if any(head.classes != 2 for head in heads):
            raise BatchRuntimeError("binary heads required by binary calibration")
        values, keys = [], []
        for task, fitted in zip(self.task_ids, calibrators):
            if fitted.get("converged") is not True or fitted.get("fit_source") != "calibration_half_only":
                raise BatchRuntimeError("only converged heldout-independent calibration may be served")
            row = np.array([fitted[name] for name in ("alpha", "bias", "center", "scale")], dtype=np.float64)
            if (not np.isfinite(row).all() or not 0 <= row[0] <= 32 or not -12 <= row[1] <= 12
                    or row[3] <= 0 or type(task) is not str or not 1 <= len(task) <= 256):
                raise BatchRuntimeError("bounded task and finite fitted calibration required")
            values.append(row)
            keys.append(hashlib.sha256(canonical({"task_id": task, "calibration": row.tolist()})).hexdigest())
        # The existing router also includes exact parameter and feature identities.
        self.router = LogicalCellRouter(heads, cell_ids, keys, feature_identity,
                                        generation=generation, cache_bytes=cache_bytes)
        self.calibration = _frozen(np.stack(values)[list(self.router.representative_indices)])
        self.logical_task_ids = tuple(self.task_ids[i] for i in self.router.representative_indices)

    def predict(self, features, *, source_digests, feature_identity, generation, threshold=0.7):
        if type(threshold) not in (int, float) or not np.isfinite(threshold) or not .5 <= threshold <= 1:
            raise BatchRuntimeError("explicit bounded confidence threshold required")
        started = time.perf_counter_ns()
        result = self.router.predict(features, source_digests=source_digests,
                                     feature_identity=feature_identity, generation=generation)
        calibration_started = time.perf_counter_ns()
        raw = result["logical_logits"]
        alpha, bias, center, scale = self.calibration.T
        scores = alpha[None, :] * ((raw[:, :, 1] - raw[:, :, 0] - center[None, :]) / scale[None, :]) + bias[None, :]
        if not np.isfinite(scores).all():
            raise BatchRuntimeError("nonfinite calibrated score")
        # Stable binary sigmoid; probability clipping is only for numerical overflow.
        positive = 1 / (1 + np.exp(-np.clip(scores, -700, 700)))
        logical_probabilities = np.stack((1 - positive, positive), axis=2)
        probability = logical_probabilities[:, self.router.physical_to_logical]
        accepted = result["served_mask"] & (np.max(probability, axis=2) >= threshold)
        return {**result, "logical_task_ids": self.logical_task_ids, "task_ids": self.task_ids,
                "probabilities": probability, "logical_probabilities": logical_probabilities,
                "predictions": probability.argmax(axis=2), "accepted_mask": accepted,
                "threshold": threshold, "calibration_ns": time.perf_counter_ns() - calibration_started,
                "elapsed_ns": time.perf_counter_ns() - started, "calibration_parameter_updates": 0}

    def accounting(self):
        result = self.router.accounting()
        result.update(declared_task_count=len(set(self.task_ids)),
                      unique_head_and_calibration_states=len(self.logical_task_ids),
                      owned_calibration_tensor_bytes=self.calibration.nbytes,
                      total_owned_model_tensor_bytes=result["owned_parameter_tensor_bytes"] + self.calibration.nbytes,
                      calibration_stored_scalars_per_state=4,
                      snapshot="immutable head+calibration; new private learning requires new state identity")
        return result
