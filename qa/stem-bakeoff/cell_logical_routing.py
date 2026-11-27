"""Route immutable learned states before fanning predictions out to Cell IDs.

Exact replicas share serving work only. A Cell publishing newly trained private
parameters needs a new snapshot; this wrapper never ties or performs updates.
Selective unserved outputs are canonical zeros accompanied by a false mask.
"""

import time

import numpy as np

from cell_batch_runtime import BatchRuntimeError, BatchedCellRuntime, _digest, _frozen, _integer
from cell_learning_models import NumpyCellHead, normalize_features

MAX_OUTPUT_BYTES = 64 * 1024**2


class LogicalCellRouter:
    """Deduplicate (task, full parameter digest, feature identity) before top-K."""

    def __init__(self, heads, cell_ids, task_ids, feature_identity, *, generation=1,
                 router_keys=None, cache_bytes=0):
        heads, self.cell_ids, self.task_ids = tuple(heads), tuple(cell_ids), tuple(task_ids)
        count = _integer(len(heads), 1, 4096)
        self.feature_identity = _digest(feature_identity)
        self.generation = _integer(generation, 1, 2**63 - 1)
        if (len(self.cell_ids) != count or len(self.task_ids) != count
                or len(set(self.cell_ids)) != count
                or any(type(value) is not str or not 1 <= len(value) <= 256
                       for value in (*self.cell_ids, *self.task_ids))):
            raise BatchRuntimeError("bounded unique physical Cell IDs and task IDs required")
        groups, representatives, mapping, members, states = {}, [], [], [], []
        checked = {}
        for index, (head, task) in enumerate(zip(heads, self.task_ids, strict=True)):
            if id(head) not in checked:
                if type(head) is not NumpyCellHead or head.feature_identity != self.feature_identity:
                    raise BatchRuntimeError("every serving Head must bind the exact feature identity")
                state = head.digest()
                if (head.report.get("trained_tensor_sha256") != state
                        or type(head.report.get("optimizer_steps")) is not int
                        or head.report["optimizer_steps"] < 1):
                    raise BatchRuntimeError("learned serving state must match its training receipt")
                checked[id(head)] = state
            key = (task, checked[id(head)], self.feature_identity)
            if key not in groups:
                groups[key] = len(representatives)
                representatives.append(index)
                members.append([])
                states.append(key)
            group = groups[key]
            members[group].append(index)
            mapping.append(group)
        self.representative_indices = tuple(representatives)
        self.logical_state_keys = tuple(states)
        self.members = tuple(tuple(group) for group in members)
        self.physical_to_logical = np.frombuffer(np.array(mapping, dtype=np.int64).tobytes(), dtype=np.int64)
        self.logical_task_ids = tuple(self.task_ids[index] for index in representatives)
        self.runtime = BatchedCellRuntime([heads[i] for i in representatives],
            [self.cell_ids[i] for i in representatives], self.logical_task_ids,
            self.feature_identity, generation=self.generation, cache_bytes=cache_bytes)
        self._router = None
        if router_keys is not None:
            keys = _frozen(router_keys)
            if keys.shape != (count, self.runtime.width):
                raise BatchRuntimeError("one physical routing prototype per Cell required")
            for group in self.members:
                if any(keys[index].tobytes() != keys[group[0]].tobytes() for index in group[1:]):
                    raise BatchRuntimeError("identical learned state has conflicting routing prototypes")
            self._router = _frozen(normalize_features(keys[representatives]))

    def predict(self, features, *, source_digests, feature_identity, generation,
                top_k=None, router_scores=None):
        started = time.perf_counter_ns()
        self.runtime._guard(feature_identity, generation)
        x, sources = _frozen(features), tuple(source_digests)
        if (x.ndim != 2 or not 1 <= len(x) <= 64 or x.shape[1] != self.runtime.width
                or len(sources) != len(x)):
            raise BatchRuntimeError("source-bound feature rows required for logical routing")
        for source in sources:
            _digest(source)
        logical, physical = len(self.members), len(self.cell_ids)
        k = logical if top_k is None else _integer(top_k, 1, logical)
        output_bytes = len(x) * ((physical + 2 * logical) * self.runtime.classes * 8 + physical + logical)
        if output_bytes > MAX_OUTPUT_BYTES:
            raise BatchRuntimeError("logical fanout output exceeds byte budget")
        routed_at = time.perf_counter_ns()
        if router_scores is not None:
            scores = _frozen(router_scores)
            route_mode = "explicit_logical_scores"
        elif k < logical and self._router is not None:
            scores = normalize_features(x) @ self._router.T
            route_mode = "logical_training_prototype_dot"
        elif k < logical:
            raise BatchRuntimeError("selective logical routing needs scores or training prototypes")
        else:
            scores = np.zeros((len(x), logical))
            route_mode = "all_unique_states"
        if scores.shape != (len(x), logical):
            raise BatchRuntimeError("scores must bind every row and unique learned state")
        outer_routing_ns = time.perf_counter_ns() - routed_at
        dispatch_at = time.perf_counter_ns()
        result = self.runtime.predict(x, source_digests=sources, feature_identity=feature_identity,
                                      generation=generation, top_k=k, router_scores=scores)
        dispatch_ns = time.perf_counter_ns() - dispatch_at
        scatter_at = time.perf_counter_ns()
        unique_logits = np.zeros((len(x), logical, self.runtime.classes))
        unique_valid = np.zeros((len(x), logical), dtype=np.bool_)
        rows = np.arange(len(x))[:, None]
        unique_logits[rows, result["selected_indices"]] = result["logits"]
        unique_valid[rows, result["selected_indices"]] = True
        logits = unique_logits[:, self.physical_to_logical]
        valid = unique_valid[:, self.physical_to_logical]
        selected_cells = [[self.cell_ids[i] for i in np.flatnonzero(row)] for row in valid]
        scatter_ns = time.perf_counter_ns() - scatter_at
        return {"logits": logits, "served_mask": valid, "physical_cell_ids": self.cell_ids,
            "selected_cell_ids": selected_cells, "selected_logical_indices": result["selected_indices"],
            "logical_logits": unique_logits, "logical_served_mask": unique_valid,
            "logical_task_ids": self.logical_task_ids, "source_digests": result["source_digests"],
            "feature_identity": result["feature_identity"], "generation": generation,
            "route_mode": route_mode, "computed_states_per_row": k,
            "head_evaluations": result["head_evaluations"], "served_physical_predictions": int(valid.sum()),
            "encoder_invocations_by_runtime": result["encoder_invocations_by_runtime"],
            "private_parameter_updates": 0, "outer_routing_ns": outer_routing_ns,
            "dispatch_ns": dispatch_ns, "scatter_ns": scatter_ns,
            "elapsed_ns": time.perf_counter_ns() - started}

    def accounting(self):
        inner = self.runtime.accounting()
        return {"physical_cell_ids": len(self.cell_ids), "retained_private_head_states": len(self.members),
            "declared_task_count": len(set(self.task_ids)), "copies_are_independent_learning": False,
            "owned_parameter_tensor_bytes": inner["private_parameter_tensor_bytes"],
            "logical_router_tensor_bytes": 0 if self._router is None else self._router.nbytes,
            "physical_mapping_tensor_bytes": self.physical_to_logical.nbytes,
            "cache_tensor_bytes": inner["cache_tensor_bytes"],
            "metadata_bytes_measured": False, "encoder_instances_owned": 0,
            "private_parameter_updates": 0, "snapshot": "immutable; publish new digest after private learning",
            "runtime": inner}
