"""Read-only observations of actual old-panel queries and Adam transitions.

The wrapped methods return their original objects unchanged. All instrumentation
cost is charged to the observed call. Methods are restored even after errors.
"""

import copy

import numpy as np

from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import NumpyCellHead, normalize_features
from cell_field_stop_inputs_v8 import canonical, digest


def array_hash(value):
    value = np.ascontiguousarray(value)
    return digest(canonical([value.dtype.str, list(value.shape)])+value.tobytes())


def pair_key(x, y):
    return digest([array_hash(np.asarray(x, dtype=np.float64)), array_hash(np.asarray(y, dtype=np.int64))])


class CallObserver:
    """Bounded transparent observation; no optimizer/search result is modified."""

    def __init__(self, origin, train, old_panels):
        self.origin, self.train, self.old_panels = origin, train, old_panels
        self.panel_keys = {pair_key(normalize_features(x), y): k for k, (x, y) in enumerate(old_panels)}
        self.raw_keys = {pair_key(x, y): k for k, (x, y) in enumerate(old_panels)}
        if len(self.panel_keys) != 4:
            raise ValueError("four distinct normalized old panel identities required")
        self.points, self.point_ids, self.queries, self.transitions = [], {}, [], []
        self.total_head_calls, self.other_head_calls, self.raw_panel_calls = 0, 0, 0
        self.overflow, self.observation_errors, self.head_errors = False, [], []

    def __enter__(self):
        self.original_loss = NumpyCellHead.loss_gradients
        self.original_advance = CellTrainingState.advance
        owner = self

        def observed_loss(head, x, y, l2=.001):
            owner.total_head_calls += 1
            try:
                result = owner.original_loss(head, x, y, l2)
            except Exception as error:
                owner.head_errors.append({"type": type(error).__name__, "message": str(error)})
                raise
            try:
                key = pair_key(x, y)
                if key not in owner.panel_keys:
                    owner.other_head_calls += 1
                    owner.raw_panel_calls += int(key in owner.raw_keys)
                    return result
                if len(owner.queries) >= 8192:
                    owner.overflow = True
                    return result
                theta = np.concatenate([head.params[n].ravel() for n in sorted(head.params)])
                point_hash = array_hash(theta)
                if point_hash not in owner.point_ids:
                    owner.point_ids[point_hash] = len(owner.points)
                    owner.points.append(theta.copy())
                gradients = np.concatenate([result[1][n].ravel() for n in sorted(head.params)])
                owner.queries.append({"panel": owner.panel_keys[key], "point": owner.point_ids[point_hash],
                    "parameter_sha256": point_hash, "loss": float(result[0]), "l2": float(l2),
                    "gradient_sha256": array_hash(gradients), "normalized_panel_sha256": key})
            except Exception as error:
                owner.observation_errors.append({"type": type(error).__name__, "message": str(error)})
            return result

        def observed_advance(state, features, labels, *, indices=None, intervention=None, mask=None):
            before = state.clone()
            delta = np.zeros(state.parameter_count) if intervention is None else np.asarray(intervention).copy()
            row = {"before": before, "intervention": delta, "indices": copy.deepcopy(indices),
                "mask": copy.deepcopy(mask), "dataset_sha256": dataset_digest(features, labels)}
            try:
                result = owner.original_advance(state, features, labels,
                    indices=indices, intervention=intervention, mask=mask)
            except Exception as error:
                row.update(error={"type": type(error).__name__, "message": str(error)}, after=state.clone(), receipt=None)
                if len(owner.transitions) < 256:
                    owner.transitions.append(row)
                else:
                    owner.overflow = True
                raise
            row.update(after=state.clone(), receipt=copy.deepcopy(result), error=None)
            if len(owner.transitions) < 256:
                owner.transitions.append(row)
            else:
                owner.overflow = True
            return result

        NumpyCellHead.loss_gradients = observed_loss
        CellTrainingState.advance = observed_advance
        return self

    def __exit__(self, error_type, value, traceback):
        NumpyCellHead.loss_gradients = self.original_loss
        CellTrainingState.advance = self.original_advance

    def record(self):
        transitions = []
        for row in self.transitions:
            transitions.append({"before_metadata": row["before"]._metadata(),
                "before_state_sha256": row["before"].digest(), "after_state_sha256": row["after"].digest(),
                "after_metadata": row["after"]._metadata(), "dataset_sha256": row["dataset_sha256"],
                "indices": None if row["indices"] is None else np.asarray(row["indices"]).tolist(),
                "mask": None if row["mask"] is None else np.asarray(row["mask"]).tolist(),
                "receipt": row["receipt"], "error": row["error"]})
        return {"schema": "hepta.cell-field-transparent-call-observer.v8",
            "total_head_calls": self.total_head_calls, "other_head_calls": self.other_head_calls,
            "normalized_old_panel_calls": len(self.queries), "raw_old_panel_calls": self.raw_panel_calls,
            "unique_old_parameter_points": len(self.points), "old_queries": self.queries,
            "actual_advance_calls": len(self.transitions), "transitions": transitions,
            "overflow": self.overflow, "observation_errors": self.observation_errors,
            "actual_head_errors": self.head_errors,
            "query_capture_limit": 8192, "transition_capture_limit": 256,
            "timing_scope": "instrumentation included in outer observed call CPU/wall; replay separately charged"}

    def arrays(self):
        p = self.origin.parameter_count
        return {"query_parameter_points": np.asarray(self.points).reshape(-1, p),
            "advance_before_vectors": np.asarray([r["before"].vector() for r in self.transitions]).reshape(-1, 3*p),
            "advance_after_vectors": np.asarray([r["after"].vector() for r in self.transitions]).reshape(-1, 3*p),
            "advance_interventions": np.asarray([r["intervention"] for r in self.transitions]).reshape(-1, p)}
