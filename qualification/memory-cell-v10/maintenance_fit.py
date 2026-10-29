"""Persist every correction/rebuild attempt; no held reads or owner claims."""

import copy
from pathlib import Path

import numpy as np

from cells import Cell, SEMANTIC_OUTPUTS, fit
from corpus import source_id, targets
from export_native import canonical, sha


def train_maintenance(parent, x, rows, protocol, seed, output, encoder_sha):
    output = Path(output)
    output.mkdir()
    values = np.asarray([row["value"] for row in rows], dtype=np.int64)
    versions, active = np.zeros(len(rows), dtype=np.int64), list(range(len(rows)))
    models = {name: copy.deepcopy(parent) for name in ("full_replay", "reservoir16")}
    result = {"schema": "hepta.memory.v10.maintenance-fit.v1", "cycles": [],
              "native_owner_execution_claimed": False, "historical_artifacts_retained": True,
              "incremental_lineage_is_historical_not_a_live_owner_authorization": True}
    pending = None
    initialization = Cell(384, 12, 4, seed).identity()
    for cycle in range(1, protocol["budget"]["maintenance_cycles"] + 1):
        old_values = values.copy()
        if cycle % 8 == 0:
            index = ((cycle // 8) * 13) % len(rows)
            active.remove(index)
            pending, event = index, "delete_clean_rebuild"
        elif pending is not None:
            index, pending, event = pending, None, "insert_new_version"
            active.append(index)
            active.sort()
            versions[index] += 1
            values[index] = (values[index] + np.asarray([3, 5, 7])) % 16
        else:
            index, event = (cycle * 7) % len(rows), "correct"
            versions[index] += 1
            values[index] = (values[index] + np.asarray([3, 5, 7])) % 16
        directory = output / f"cycle-{cycle:02d}"
        directory.mkdir()
        record = {"cycle": cycle, "event": event, "index": index, "active_indices": active.copy(),
                  "values": values.tolist(), "previous_values": old_values.tolist(), "versions": versions.tolist(),
                  "arms": {}, "delete_deny_before_read_required": event == "delete_clean_rebuild"}
        for name, model in models.items():
            if event == "delete_clean_rebuild":
                model = Cell(384, 12, 4, seed)
                models[name] = model
                selected = active.copy()
            elif name == "full_replay":
                selected = active.copy()
            else:
                candidates = [i for i in active if i != index]
                rng = np.random.default_rng(seed + cycle * 13)
                selected = [index] + sorted(rng.choice(candidates, min(15, len(candidates)), replace=False).tolist())
            source_ids = [source_id("semantic", i, int(versions[i])) for i in selected]
            # Matching presentation counts; the reservoir intentionally changes support coverage.
            schedule = np.random.default_rng(seed + cycle * 1701).integers(len(selected), size=(protocol["budget"]["maintenance_steps"], 32), dtype=np.int64)
            np.save(directory / f"{name}-schedule.npy", schedule, allow_pickle=False)
            receipt = fit(model, x[selected], targets(values[selected].tolist(), "semantic"), SEMANTIC_OUTPUTS,
                          schedule, lr=0.01, source_ids=source_ids, label=f"maintenance-{name}-{cycle}")
            saved = model.save(directory / name, encoder_sha256=encoder_sha, outputs=SEMANTIC_OUTPUTS,
                               extra={"cycle": cycle, "active_source_ids": [source_id("semantic", i, int(versions[i])) for i in active],
                                      "service_authorization_requires_real_owner_revalidation": True})
            record["arms"][name] = {"fit": receipt, "checkpoint": saved, "replay_indices": selected,
                                     "rebuild_initialization_sha256": initialization if event == "delete_clean_rebuild" else None,
                                     "clean_rebuild_identity_equal": receipt["initial_parameter_sha256"] == initialization if event == "delete_clean_rebuild" else None,
                                     "lineage_contains_deleted_source": any(source_id("semantic", index, version) in model.lineage
                                                                           for version in range(int(versions[index]) + 1)) if event == "delete_clean_rebuild" else None}
        (directory / "CYCLE.json").write_bytes(canonical(record))
        result["cycles"].append(record)
    (output / "MAINTENANCE.json").write_bytes(canonical(result))
    return result
