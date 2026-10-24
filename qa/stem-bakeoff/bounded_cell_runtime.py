"""Serve immutable learned Heads with their bounded prior-mixture calibrators.

This shadow runtime owns no Encoder or optimizer. Physical replicas may share
an exact task, parameter, and full calibration state; they are not new skills.
Unserved probability slots are canonical zeros with an explicit false mask.
"""

import hashlib
import json
import time

import numpy as np

from cell_batch_runtime import BatchRuntimeError, _digest, _integer
from cell_calibration_bounded import apply_bounded_calibrator, validate_bounded_calibrator
from cell_learning_models import NumpyCellHead, canonical
from cell_logical_routing import LogicalCellRouter


MAX_CALIBRATION_RECORD_BYTES = 1024**2
MAX_UNIQUE_CALIBRATION_BYTES = 32 * 1024**2


class BoundedCalibratedCellRuntime:
    """Bind externally pinned calibration contexts before any Head dispatch.

Expected calibration-context digests must come from the caller's frozen plan,
not from the calibration records being checked. Digests establish consistency
with those pins, not publisher authenticity or production admission.
"""

    def __init__(self, heads, calibrators, cell_ids, task_ids, feature_identity, *,
                 expected_calibration_context_digests, generation=1, cache_bytes=0,
                 router_keys=None):
        heads, calibrators = tuple(heads), tuple(calibrators)
        count = _integer(len(heads), 1, 4096)
        self.feature_identity = _digest(feature_identity)
        self.generation = _integer(generation, 1, 2**63 - 1)
        self.task_ids = tuple(task_ids)
        contexts = tuple(expected_calibration_context_digests)
        if len(calibrators) != count or len(self.task_ids) != count or len(contexts) != count:
            raise BatchRuntimeError("one calibration, task and external context pin per Cell required")
        if any(type(task) is not str or not 1 <= len(task) <= 256 for task in self.task_ids):
            raise BatchRuntimeError("bounded task IDs required")
        contexts = tuple(_digest(value) for value in contexts)
        records, physical_record_digests, bindings, keys, states = {}, [], [], [], []
        retained_bytes = 0
        for head, fitted, task, context in zip(heads, calibrators, self.task_ids, contexts, strict=True):
            if (type(head) is not NumpyCellHead or head.classes != 2
                    or head.feature_identity != self.feature_identity):
                raise BatchRuntimeError("binary learned Heads must bind the exact feature identity")
            state = head.digest()
            expected = {"feature_identity": self.feature_identity,
                        "predictor_sha256": state, "calibration_context_sha256": context}
            try:
                blob = canonical(fitted)
                if len(blob) > MAX_CALIBRATION_RECORD_BYTES:
                    raise BatchRuntimeError("bounded calibration record exceeds metadata budget")
                frozen = json.loads(blob)
                if (not isinstance(frozen, dict)
                        or frozen.get("fit_role") not in ("calibration", "out_of_fold_calibration")
                        or frozen.get("holdout_supplied_to_fit") is not False
                        or frozen.get("quality_qualified") is not False
                        or frozen.get("authority") != "DENY_ALL"):
                    raise BatchRuntimeError("frozen heldout-independent shadow calibration required")
                if any(type(frozen[name]) not in (int, float) for name in
                       ("alpha", "prior_positive", "mixture_weight", "training_log_odds")):
                    raise BatchRuntimeError("calibration scalars must be numbers, never booleans")
                validate_bounded_calibrator(frozen, expected_bindings=expected)
            except (KeyError, TypeError, ValueError, OverflowError) as error:
                raise BatchRuntimeError(f"invalid bounded calibration: {error}") from error
            record_digest = hashlib.sha256(blob).hexdigest()
            if record_digest not in records:
                retained_bytes += len(blob)
                if retained_bytes > MAX_UNIQUE_CALIBRATION_BYTES:
                    raise BatchRuntimeError("unique calibration records exceed metadata budget")
                records[record_digest] = blob
            physical_record_digests.append(record_digest)
            bindings.append((state, context))
            states.append(state)
            keys.append(hashlib.sha256(canonical({"task_id": task,
                        "calibration_sha256": record_digest})).hexdigest())
        self.router = LogicalCellRouter(heads, cell_ids, keys, self.feature_identity,
            generation=self.generation, cache_bytes=cache_bytes, router_keys=router_keys)
        if any(head.digest() != state for head, state in zip(heads, states, strict=True)):
            raise BatchRuntimeError("private Head changed while constructing the frozen snapshot")
        selected = self.router.representative_indices
        self.logical_task_ids = tuple(self.task_ids[index] for index in selected)
        self.logical_calibration_sha256 = tuple(physical_record_digests[index] for index in selected)
        self._records = tuple(records[digest] for digest in dict.fromkeys(self.logical_calibration_sha256))
        record_index = {hashlib.sha256(blob).hexdigest(): index for index, blob in enumerate(self._records)}
        self._logical_record_indices = tuple(record_index[digest] for digest in self.logical_calibration_sha256)
        self._logical_bindings = tuple(bindings[index] for index in selected)

    def predict(self, features, *, source_digests, feature_identity, generation,
                threshold=.7, top_k=None, router_scores=None):
        if (type(threshold) not in (int, float) or not np.isfinite(threshold)
                or not .5 <= threshold <= 1):
            raise BatchRuntimeError("explicit finite confidence threshold in [.5,1] required")
        started = time.perf_counter_ns()
        self.router.runtime._guard(feature_identity, generation)
        features = np.asarray(features)
        if (features.ndim != 2 or not 1 <= len(features) <= 64
                or features.shape[1] != self.router.runtime.width or features.dtype.kind not in "fiu"):
            raise BatchRuntimeError("one to 64 bounded real feature rows required before copying")
        if router_scores is not None:
            router_scores = np.asarray(router_scores)
            if (router_scores.shape != (len(features), len(self.logical_task_ids))
                    or router_scores.dtype.kind not in "fiu"):
                raise BatchRuntimeError("bounded real scores for each row and logical state required before copying")
        result = self.router.predict(features, source_digests=source_digests,
            feature_identity=feature_identity, generation=generation,
            top_k=top_k, router_scores=router_scores)
        calibration_started = time.perf_counter_ns()
        raw, valid = result["logical_logits"], result["logical_served_mask"]
        logical = np.zeros_like(raw)
        decoded = {}
        for index, (state, context) in enumerate(self._logical_bindings):
            eligible = valid[:, index]
            if not bool(eligible.any()):
                continue
            record_index = self._logical_record_indices[index]
            if record_index not in decoded:
                decoded[record_index] = json.loads(self._records[record_index])
            logical[eligible, index] = apply_bounded_calibrator(
                raw[eligible, index, 1] - raw[eligible, index, 0], decoded[record_index],
                expected_bindings={"feature_identity": self.feature_identity,
                    "predictor_sha256": state, "calibration_context_sha256": context})
        probabilities = logical[:, self.router.physical_to_logical]
        served = result["served_mask"]
        classified = served & (np.max(probabilities, axis=2) >= threshold)
        positive = served & (probabilities[:, :, 1] >= threshold)
        return {**result, "logical_task_ids": self.logical_task_ids, "task_ids": self.task_ids,
            "probabilities": probabilities, "logical_probabilities": logical,
            "predictions": np.where(served, probabilities.argmax(axis=2), -1),
            "classification_accepted_mask": classified, "positive_action_mask": positive,
            "threshold": threshold, "calibration_parameter_updates": 0,
            "calibration_row_evaluations": int(valid.sum()),
            "calibration_ns": time.perf_counter_ns() - calibration_started,
            "elapsed_ns": time.perf_counter_ns() - started,
            "mode": "SHADOW_ONLY", "authority": "DENY_ALL", "quality_qualified": False}

    def predict_cached(self, source_digests, *, feature_identity, generation, **options):
        self.router.runtime._guard(feature_identity, generation)
        sources = tuple(source_digests)
        _integer(len(sources), 1, 64)
        sources = tuple(_digest(source) for source in sources)
        cache = self.router.runtime.cache
        features = [cache.get((self.feature_identity, generation, source)) for source in sources]
        if any(row is None for row in features):
            raise BatchRuntimeError("cache miss requires explicit source re-encoding")
        return self.predict(np.stack(features), source_digests=sources,
            feature_identity=feature_identity, generation=generation, **options)

    def accounting(self):
        result = self.router.accounting()
        result.update(declared_task_count=len(set(self.task_ids)),
            physical_cell_count=len(self.router.cell_ids), logical_state_count=len(self.logical_task_ids),
            unique_head_and_calibration_states=len(self.logical_task_ids),
            physical_calibration_references=len(self.router.cell_ids),
            retained_calibration_record_count=len(self._records),
            serialized_calibration_bytes=sum(len(blob) for blob in self._records),
            owned_calibration_tensor_bytes=0, calibration_storage="immutable canonical JSON bytes",
            total_owned_tensor_bytes=(result["owned_parameter_tensor_bytes"]
                + result["physical_mapping_tensor_bytes"] + result["logical_router_tensor_bytes"]
                + result["cache_tensor_bytes"]),
            serialized_calibration_bytes_are_total_python_heap=False,
            metadata_bytes_measured=False, calibration_parameter_updates=0,
            mode="SHADOW_ONLY", authority="DENY_ALL", quality_qualified=False)
        return result
