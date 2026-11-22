"""Read-only checkpoint and selection checks for the frozen P4 sensor study."""

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import torch
from torch.torch_version import TorchVersion


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_checkpoint(path):
    # Runtime receipts can contain this known str subclass; never disable the
    # weights-only loader or permit arbitrary checkpoint-defined globals.
    with torch.serialization.safe_globals([TorchVersion]):
        return torch.load(path, map_location="cpu", weights_only=True)


def tensor_digest(values):
    result = hashlib.sha256()
    for name, value in sorted(values.items()):
        tensor = value.detach().cpu().contiguous()
        descriptor = json.dumps([name, str(tensor.dtype), list(tensor.shape)]).encode()
        result.update(len(descriptor).to_bytes(8, "big"))
        result.update(descriptor)
        result.update(tensor.numpy().tobytes())
    return result.hexdigest()


def array_digest(values):
    result = hashlib.sha256()
    for name, value in sorted(values.items()):
        result.update(json.dumps([name, str(value.dtype), list(value.shape)]).encode())
        result.update(np.ascontiguousarray(value).tobytes())
    return result.hexdigest()


def close(a, b):
    return (
        a is not None
        and b is not None
        and math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-12)
    )


class Checks:
    def __init__(self):
        self.rows = []

    def check(self, condition, label, details=None):
        self.rows.append(
            {"check": label, "passed": bool(condition), "details": details}
        )

    @property
    def ok(self):
        return all(row["passed"] for row in self.rows)


def check_p4(directory, entry, plan, source_map, checks):
    prefix = f"adaptation/{entry['arm']}/{entry['seed']}"
    arm, seed = entry["arm"], entry["seed"]
    check = lambda value, label: checks.check(value, prefix + "/" + label)
    study = read(directory / "STUDY.json")
    check(
        study["state"] == "completed" and study["planned_trials"] == 1,
        "complete_single_trial",
    )
    check(
        study["plan"] == plan and read(directory / "PLAN.json") == plan, "frozen_plan"
    )
    check(
        study["plan_sha256"]
        == hashlib.sha256(
            json.dumps(plan, sort_keys=True, allow_nan=False).encode()
        ).hexdigest(),
        "canonical_plan_hash",
    )
    check(
        study["test_evaluations"] == 0
        and plan["test_evaluations"] == 0
        and plan["occupancy_labels_used"] is False,
        "restricted_label_scope",
    )
    check(
        len(study["source_code_sha256"]) == 12
        and all(
            source_map.get("qualification/" + name) == value
            for name, value in study["source_code_sha256"].items()
        ),
        "bound_source_files",
    )
    data = study["data"]
    check(
        data["source_csv_sha256"]
        == "c090ee5c94b61762bfec9d22767864490b51030f98cca030f02822468db25d9c"
        and data["normalizer_and_clock_exclude_preservation"],
        "source_and_preservation_normalization_scope",
    )
    check(
        digest(directory / "prepared_inputs.npz") == study["prepared_inputs_sha256"],
        "prepared_artifact_hash",
    )
    with np.load(directory / "prepared_inputs.npz", allow_pickle=False) as saved:
        arrays = {name: saved[name] for name in saved.files}
    row_sets = {}
    for name in ("train", "dev", "preservation"):
        x, dt, ids = (arrays[f"{name}_{key}"] for key in ("x", "dt", "ids"))
        check(
            ids.tolist() == data["ids"][name] and len(x) == data["used_windows"][name],
            name + "_ids_count",
        )
        check(
            dt.shape == x.shape[:2]
            and np.isfinite(x).all()
            and np.isfinite(dt).all()
            and (dt > 0).all(),
            name + "_finite_clock",
        )
        times = np.concatenate(
            (arrays[name + "_input_times"], arrays[name + "_target_times"][:, None]),
            axis=1,
        )
        check(np.array_equal(dt, np.diff(times, axis=1)), name + "_actual_seconds")
        row_sets[name] = {
            row
            for identity in ids
            for row in range(
                int(identity.split(":")[1]), int(identity.split(":")[2]) + 1
            )
        }
    check(
        not (
            row_sets["train"] & row_sets["dev"]
            or row_sets["train"] & row_sets["preservation"]
            or row_sets["dev"] & row_sets["preservation"]
        ),
        "disjoint_source_rows",
    )
    check(
        data["used_windows"]["train"] <= plan["max_train_windows"]
        and data["used_windows"]["dev"] <= plan["max_dev_windows"]
        and data["used_windows"]["preservation"] == plan["preservation_windows"],
        "sample_caps",
    )
    check(
        close(data["clock_scale_seconds"], np.median(arrays["train_dt"][:, :-1])),
        "train_only_clock",
    )
    seed_dir = directory / f"seed_{seed}"
    incumbent = load_checkpoint(seed_dir / "incumbent.pt")
    initial = incumbent["state_dict"]
    initial_sha = tensor_digest(initial)
    check(
        incumbent["seed"] == seed
        and initial_sha == study["incumbents"][str(seed)]["state_digest"],
        "incumbent_hash",
    )
    result_path = seed_dir / arm
    result = read(result_path / "RESULT.json")
    ledger = result["ledger"]
    check(
        result["state"] == "completed"
        and result["arm"] == arm
        and result["seed"] == seed,
        "result_identity",
    )
    check(
        len(study["trials"]) == 1
        and all(
            study["trials"][0][key] == result[key]
            for key in (
                "arm",
                "seed",
                "state",
                "adoption",
                "selected_dev_mse",
                "rejected_candidates",
                "preservation_rejections",
                "arm_total_seconds",
            )
        ),
        "study_result_consistency",
    )
    check(
        result["initial_state_digest"] == initial_sha == ledger["initial_state_digest"],
        "common_incumbent",
    )
    check(
        digest(result_path / "candidates.pt") == result["candidate_artifact_sha256"],
        "candidate_file_hash",
    )
    payload = load_checkpoint(result_path / "candidates.pt")
    check(
        payload["ledger"] == ledger
        and payload["model_identity"] == incumbent["identity"],
        "checkpoint_ledger_identity",
    )
    check(
        ledger["method"] == arm
        and ledger["config"] == plan["adaptation"]
        and ledger["editable_names"] == plan["editable_names"]
        and ledger["test_queries"] == 0
        and ledger["preservation_scope"] == "supplied next-sensor windows only",
        "method_and_scope",
    )
    states = payload["states_by_digest"]
    candidates = ledger["candidates"]
    for key, state in states.items():
        check(
            tensor_digest(state) == key and set(state) == set(initial),
            "candidate_state_hash/" + key,
        )
        check(
            all(
                torch.equal(value, initial[name])
                for name, value in state.items()
                if name not in plan["editable_names"]
                and not name.startswith("predictor.")
            ),
            "frozen_parameters/" + key,
        )
    best, selected_index = candidates[0]["dev_mse"], 0
    baseline = candidates[0]["preservation_mse"]
    check(
        candidates[0]["state_digest"] == initial_sha
        and candidates[0]["kind"] == "keep"
        and math.isfinite(best)
        and math.isfinite(baseline),
        "keep_candidate",
    )
    edits = load_checkpoint(seed_dir / "edit_candidates.pt")
    edit_plan = read(seed_dir / "EDIT_PLAN.json")
    check(
        len(edits) == len(edit_plan) == len(plan["edit_directions"]),
        "declared_edit_count",
    )
    for i, (edit, description, direction) in enumerate(
        zip(edits, edit_plan, plan["edit_directions"])
    ):
        delta = edit["feedback.projection.weight"]
        expected = torch.zeros_like(delta)
        expected[0].fill_(direction[0])
        expected[2].fill_(direction[1])
        expected *= plan["edit_l2"] / expected.norm()
        check(
            torch.equal(delta, expected)
            and tensor_digest(edit) == description["parameter_digest"]
            and close(delta.norm(), plan["edit_l2"])
            and delta.norm() <= plan["adaptation"]["max_edit_l2"]
            and delta.abs().max() <= plan["adaptation"]["max_edit_linf"],
            f"edit_direction_bound/{i}",
        )
    for i, candidate in enumerate(candidates):
        check(
            candidate["index"] == i and candidate["state_digest"] in states,
            f"candidate_index/{i}",
        )
        if i == 0:
            continue
        d, p = candidate["dev_mse"], candidate["preservation_mse"]
        finite = (
            d is not None and p is not None and math.isfinite(d) and math.isfinite(p)
        )
        preserved = (
            finite and p <= baseline + plan["adaptation"]["preservation_tolerance"]
        )
        improves = preserved and d < best - plan["adaptation"]["min_dev_improvement"]
        reason = (
            "nonfinite evaluation"
            if not finite
            else "preservation tolerance exceeded"
            if not preserved
            else "selected"
            if improves
            else "no required dev improvement"
        )
        check(
            candidate["admissible"] == preserved
            and candidate["selected_when_seen"] == improves
            and candidate["reason"] == reason,
            f"gate_replay/{i}",
        )
        if improves:
            best, selected_index = d, i
        state = states[candidate["state_digest"]]
        if candidate["kind"] == "conditional_readout":
            check(
                all(
                    torch.equal(value, initial[name])
                    for name, value in state.items()
                    if not name.startswith("predictor.")
                ),
                f"direct_encoder_fixed/{i}",
            )
        if arm == "bounded_edit":
            edit = edits[candidate["edit_index"]]
            check(
                candidate["edit"]["edit_digest"] == tensor_digest(edit)
                and torch.equal(
                    state["feedback.projection.weight"],
                    initial["feedback.projection.weight"]
                    + edit["feedback.projection.weight"],
                ),
                f"independent_edit/{i}",
            )
    chosen = candidates[selected_index]
    check(
        ledger["selected_index"] == selected_index
        and close(ledger["selected_dev_mse"], best)
        and close(result["selected_dev_mse"], best)
        and ledger["selected_state_digest"]
        == chosen["state_digest"]
        == tensor_digest(payload["selected_state_dict"]),
        "selected_state_and_gate",
    )
    check(
        result["adoption"] == ("KEEP" if selected_index == 0 else "Candidate"),
        "keep_outcome",
    )
    steps, proposals = plan["adaptation"]["steps"], len(edits)
    training, fits, backwards = {
        "keep": (0, 0, 0),
        "direct": (1, 1, 0),
        "profile_bp": (1 + 2 * steps, 1 + 2 * steps, steps),
        "joint_bp": (1 + steps, 1, steps),
        "bounded_edit": (proposals, proposals, 0),
    }[arm]
    expected_candidates = {
        "keep": 1,
        "direct": 2,
        "profile_bp": steps + 2,
        "joint_bp": steps + 2,
        "bounded_edit": proposals + 1,
    }[arm]
    check(
        len(candidates) == expected_candidates
        and (
            backwards == 0
            or [row["step"] for row in candidates if row["kind"] == arm]
            == list(range(1, steps + 1))
        ),
        "fixed_update_schedule",
    )
    cost = ledger["cost"]
    visits = len(candidates)
    length = arrays["train_x"].shape[1] - 1
    expected = {
        "backward_evaluations": backwards,
        "conditional_solves": fits,
        "factorizations": fits,
        "conditional_rhs": fits * arrays["train_x"].shape[2],
        "dev_queries": visits,
        "preservation_queries": visits,
        "feature_forward_calls": training + 2 * visits,
        "sensor_transition_rows": length
        * (
            training * len(arrays["train_x"])
            + visits * (len(arrays["dev_x"]) + len(arrays["preservation_x"]))
        ),
    }
    check(all(cost[key] == value for key, value in expected.items()), "work_counts")
    rejects = sum(not row["selected_when_seen"] for row in candidates[1:])
    preservation_rejects = sum(
        row["reason"] == "preservation tolerance exceeded" for row in candidates[1:]
    )
    check(
        result["rejected_candidates"] == rejects
        and result["preservation_rejections"] == preservation_rejects,
        "rejection_totals",
    )
    check(
        0
        <= cost["total_seconds"]
        <= result["arm_total_seconds"]
        <= study["study_wall_seconds"]
        <= entry["cold_wall_seconds"],
        "nested_wall_costs",
    )
    check(
        all(0 <= row["elapsed_seconds"] <= cost["total_seconds"] for row in candidates)
        and [row["elapsed_seconds"] for row in candidates]
        == sorted(row["elapsed_seconds"] for row in candidates),
        "candidate_clocks",
    )
    return {
        "study": "adaptation",
        "arm": arm,
        "seed": seed,
        "state": result["state"],
        "adoption": result["adoption"],
        "cold_wall_seconds": entry["cold_wall_seconds"],
        "work_wall_seconds": study["study_wall_seconds"],
        "cpu_seconds": study["study_cpu_seconds"],
        "initial_dev_mse": candidates[0]["dev_mse"],
        "selected_dev_mse": best,
        "dev_improvement": candidates[0]["dev_mse"] - best,
        "preservation_initial_mse": baseline,
        "preservation_selected_mse": chosen["preservation_mse"],
        "preservation_delta": chosen["preservation_mse"] - baseline,
        "candidate_count": len(candidates),
        "rejected_candidates": rejects,
        "preservation_rejections": preservation_rejects,
        **expected,
        "parameters": incumbent["identity"]["parameters"],
        "state_bytes": incumbent["identity"]["persistent_state_bytes_per_stream"],
        "initial_state_digest": initial_sha,
        "prepared_data_digest": array_digest(arrays),
        "normalizer_digest": hashlib.sha256(
            json.dumps(
                data["contract"]["normalization_train_only"], sort_keys=True
            ).encode()
        ).hexdigest(),
        "selected_state_digest": chosen["state_digest"],
        "selected_index": selected_index,
        "selected_candidate_kind": chosen["kind"],
        "artifact": f"adaptation/{arm}-{seed}/seed_{seed}/{arm}/candidates.pt",
    }


def portfolio_choice(rows, plan):
    """Post-hoc choice; charge the complete five-method cold-search portfolio."""
    choices = []
    for seed in plan["seeds"]:
        group = [
            row for row in rows if row["study"] == "adaptation" and row["seed"] == seed
        ]
        item = {
            "seed": seed,
            "status": "unavailable_verification_failure",
            "all_method_cold_seconds": sum(
                row.get("cold_wall_seconds", 0.0) for row in group
            ),
            "tie_priority": plan["arms"],
            "tie_tolerance": plan["adaptation"]["min_dev_improvement"],
            "scope": "post-hoc selection among all five executed methods; no early-stop or search-cost savings",
        }
        if (
            len(group) == len(plan["arms"])
            and all(row.get("verified") for row in group)
            and {row["arm"] for row in group} == set(plan["arms"])
            and all(
                len({row[field] for row in group}) == 1
                for field in (
                    "initial_state_digest",
                    "prepared_data_digest",
                    "normalizer_digest",
                )
            )
            and all(
                row["preservation_selected_mse"]
                <= row["preservation_initial_mse"]
                + plan["adaptation"]["preservation_tolerance"]
                for row in group
            )
        ):
            minimum = min(row["selected_dev_mse"] for row in group)
            tied = [
                row
                for row in group
                if row["selected_dev_mse"] <= minimum + item["tie_tolerance"]
            ]
            chosen = min(tied, key=lambda row: plan["arms"].index(row["arm"]))
            item.update(
                status="recorded",
                method=chosen["arm"],
                candidate_kind=chosen["selected_candidate_kind"],
                state_digest=chosen["selected_state_digest"],
                selected_index=chosen["selected_index"],
                artifact=chosen["artifact"],
                dev_mse=chosen["selected_dev_mse"],
                preservation_mse=chosen["preservation_selected_mse"],
                preservation_incumbent_mse=chosen["preservation_initial_mse"],
                incumbent_digest=chosen["initial_state_digest"],
                normalizer_digest=chosen["normalizer_digest"],
            )
        choices.append(item)
    return choices
