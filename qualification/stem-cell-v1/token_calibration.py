"""Source-disjoint token continuation targets from completed public trajectories.

All public trajectories finish before the first outcome is read. The target is
next-hop candidate correctness, not MultiRC F1; observed work maxima and critic
residuals do not certify future support. Natural final labels are inadmissible.
"""
import time

from group_encoder import digest_json
from reader_calibration import fit_critic_metered
from reader_execution import _frozen
from token_execution import execute_token_reader


def _maximum(records):
    return {key: (max(record[key] for record in records)
                  if records and all(record[key] is not None for record in records) else None)
            for key in ("formula_flops", "wall_ns", "cpu_ns")}


def collect_token_critic_rows(model, verifier, bank, cases, *, max_steps=3,
                             split="validation_fit", profile_bounds=None):
    """Score fixed3 trajectories after execution, with declared training sources.

    The same independent verifier, public boundary and strict execution meter as
    online inference are reused. Reader/verifier training sources are recorded
    by fit_token_reader; explicit profile declarations may supply them for other
    frozen artifacts. Those declarations are checked, not authenticated here.
    """
    started_wall, started_cpu = time.perf_counter_ns(), time.process_time_ns()
    split = {"fit": "validation_fit", "calibration": "validation_calibration"}.get(split, split)
    cases = tuple(cases)
    if (split not in ("validation_fit", "validation_calibration")
            or type(max_steps) is not int or max_steps != 3
            or not 1 <= len(cases) <= 8192 or verifier is None):
        raise ValueError("bounded fixed3 inner-split calibration required")
    if any(case.source_split != "train" or case.paragraph_id.startswith("binding-v4/")
           or case.segmentation.startswith("synthetic-") for case in cases):
        raise ValueError("only natural official-train sources may fit the critic")
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("duplicate calibration candidate")
    bounds = dict(profile_bounds or {})
    for key, artifact in (("reader_source_groups", model), ("verifier_source_groups", verifier)):
        declared = getattr(artifact, "training_source_groups", ())
        if key not in bounds:
            bounds[key] = list(declared)
        if declared and set(bounds[key]) != set(declared):
            raise ValueError("profile substitutes declared artifact training sources")
        if not bounds[key] or {case.source_hash for case in cases} & set(bounds[key]):
            raise ValueError("critic sources must be disjoint from reader/verifier training")
    before = dict(model_sha256=_frozen(model), verifier_sha256=_frozen(verifier))
    public_trajectories = []
    for case in cases:
        prepared_wall, prepared_cpu = time.perf_counter_ns(), time.process_time_ns()
        public = bank.public(case)
        preparation = dict(wall_ns=time.perf_counter_ns() - prepared_wall,
                           cpu_ns=time.process_time_ns() - prepared_cpu)
        if public.get("source_sha256") != case.source_hash:
            raise ValueError("feature snapshot belongs to another source paragraph")
        result = execute_token_reader(public, model, verifier, mode="fixed3",
            profile_bounds=bounds, collect_critic_features=True)
        if (result["steps"] != max_steps
                or len(result["step_records"]) != max_steps
                or len(result["verifier_observations"]) != max_steps
                or any(len(record.get("critic_features", ())) != 6 for record in result["step_records"][:-1])):
            raise ValueError("complete public fixed3 trajectory required before scoring")
        public_trajectories.append((case, result, preparation))
    trajectories_finished_ns = time.time_ns()
    # No source outcome is accessed above this point, across the entire cohort.
    rows, trajectories, profile_records = [], [], []
    callbacks = {component: [] for component in ("proposer", "verifier", "value")}
    for case, result, preparation in public_trajectories:
        label = case.label
        if type(label) is not int or label not in (0, 1):
            raise ValueError("typed binary offline outcome required")
        records = result["step_records"]
        for index, record in enumerate(records[:-1]):
            rows.append(dict(features=record["critic_features"],
                stop_success=record["prediction"] == label,
                continue_success=records[index + 1]["prediction"] == label,
                source_group=case.source_hash, split=split, observed_at_ns=time.time_ns()))
        costs, work = result["request_costs"], result["work_observation"]
        formula = costs["complete_formula_flops"] if not work["unknown_operators"] else None
        profile_records.append(dict(formula_flops=formula, wall_ns=costs["wall_ns"], cpu_ns=costs["self_cpu_ns"]))
        for component in callbacks:
            for record in records:
                observed = record.get("callback_costs", {}).get(component)
                if observed is not None:
                    callbacks[component].append({**observed,
                        "formula_flops": None if work["unknown_operators"] else observed["formula_flops"]})
        trajectories.append(dict(case_id=case.case_id, source_group=case.source_hash,
            source_split=case.source_split, offline_label=label,
            preparation_cost=preparation, execution=result, steps=records))
    after = dict(model_sha256=_frozen(model), verifier_sha256=_frozen(verifier))
    if before != after:
        raise ValueError("calibration mutated a selected frozen artifact")
    receipt = dict(schema="hepta.token-reader.offline-critic-trajectories.v1", split=split,
        max_steps=max_steps, cases=len(cases), rows=len(rows), trajectories=trajectories,
        source_groups=sorted({case.source_hash for case in cases}), rows_sha256=digest_json(rows),
        model_digests_before=before, model_digests_after=after,
        callback_empirical_maxima={key: _maximum(value) for key, value in callbacks.items()},
        empirical_next_hop_maximum={**_maximum(profile_records), "observed_segments": len(profile_records)},
        profile_measurement="maximum_full_trajectory_is_conservative_observed_segment_upper_no_division",
        profile_kind="observed_maxima_not_certified_future_support",
        future_support_guaranteed=False, confidence_bound_established=False,
        public_trajectories_finished_at_ns=trajectories_finished_ns,
        labels_used_only_after_public_trajectory=True, all_public_trajectories_precede_any_label=True,
        official_validation_labels_used=False, target="binary_candidate_correctness_not_benchmark_f1",
        verifier_acceptance_is_semantic_truth=False, training_provenance_authenticated=False,
        cpu_ns=time.process_time_ns() - started_cpu, wall_ns=time.perf_counter_ns() - started_wall,
        execution_cpu_ns=sum(result["request_costs"]["self_cpu_ns"] for _, result, _ in public_trajectories),
        execution_wall_ns=sum(result["request_costs"]["wall_ns"] for _, result, _ in public_trajectories),
        formula_flops=(sum(record["formula_flops"] for record in profile_records)
                       if all(record["formula_flops"] is not None for record in profile_records) else None),
        formula_scope="executed_tensor_callbacks_excludes_public_bank_and_Python_scoring",
        gradient_updates=0, production_authorized=False)
    return rows, receipt


def fit_token_critic_metered(rows, calibration, **kwargs):
    """Reuse the existing strict, actual SGD fit and frozen empirical critic."""
    critic, receipt = fit_critic_metered(rows, calibration, **kwargs)
    receipt["schema"] = "hepta.token-reader.metered-critic-fit.v1"
    return critic, receipt
