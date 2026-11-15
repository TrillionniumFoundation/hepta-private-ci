"""Offline, source-separated continuation targets and metered critic fitting.

Success labels are used only after each public-only trajectory has executed.
Observed callback maxima and residual radii are empirical measurements, not
certified future support. The target is candidate correctness, not MultiRC F1.
"""

import time

import torch

from execution_meter import POLICY_SCHEMA, WorkLedger
from group_critic import fit_critic, row_features
from group_encoder import digest_json
from paired_execution import PHASES
from reader_execution import _features, _frozen, _tensor_digest, observed_verifier_feedback


def _ledger(wall_time_ns):
    return WorkLedger(dict(schema=POLICY_SCHEMA, mode="strict", wall_time_ns=wall_time_ns,
                           max_process_rss_bytes=None, rapl_zone=None, rapl_max_power_watts=None),
                      dict.fromkeys(PHASES, 10**18))


def _measured(meter, phase, component, callback):
    key = phase + ":" + component
    previous = meter.rows.get(key, {})
    before = {name: previous.get(name, 0) for name in ("formula_flops", "cpu_ns", "elapsed_ns")}
    with meter.scope(phase, component):
        result = callback()
    after = meter.rows[key]
    return result, dict(formula_flops=after["formula_flops"] - before["formula_flops"],
                        cpu_ns=after["cpu_ns"] - before["cpu_ns"],
                        wall_ns=after["elapsed_ns"] - before["elapsed_ns"])


def _maxima(records):
    return {name: max((record[name] for record in records), default=0)
            for name in ("formula_flops", "wall_ns", "cpu_ns")}


def collect_critic_rows(model, verifier, bank, cases, *, max_steps=3,
                        split="validation_fit", threshold=.9, wall_time_ns=900_000_000_000):
    """Execute fixed complete trajectories before scoring their next prediction.

    The source cases must come from official train, with source-separated inner
    critic-fit/calibration membership supplied by the campaign. The exact same
    verifier helper and independent single-hop verifier are used at inference.
    No case/label is passed to either model or to the observable feature builder.
    """
    started_wall, started_cpu = time.perf_counter_ns(), time.process_time_ns()
    cases = tuple(cases)
    if (split not in ("validation_fit", "validation_calibration") or type(max_steps) is not int
            or not 2 <= max_steps <= min(8, model.max_hops)
            or not 1 <= len(cases) <= 16384 // (max_steps - 1)
            or type(threshold) not in (float, int) or threshold != .9
            or verifier is None or verifier is model or verifier.input_dim != model.input_dim):
        raise ValueError("bounded inner-split calibration and independent verifier required")
    if any(case.source_split != "train" for case in cases):
        raise ValueError("official validation/final labels cannot fit the critic")
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("duplicate calibration candidate")
    before = dict(model_sha256=_frozen(model), verifier_sha256=_frozen(verifier))
    if {p.data_ptr() for p in model.parameters()} & {p.data_ptr() for p in verifier.parameters()}:
        raise ValueError("reader and verifier cannot share parameter storage")
    meter = _ledger(wall_time_ns)
    trajectories, rows = [], []
    callback_records = {component: [] for component in ("proposer", "verifier", "value")}
    next_hops = []
    for case in cases:
        public, preparation = _measured(meter, "evaluation", "bank", lambda: _features(bank.public(case), model))
        if public["source_sha256"] != case.source_hash:
            raise ValueError("feature snapshot belongs to another source paragraph")
        facts, query, mask = (public[name] for name in ("facts", "query", "mask"))
        tensor_sha256 = _tensor_digest(facts, query, mask)
        has_evidence = bool(mask.any().item())
        state, feedback, steps = None, None, []
        for step in range(1, max_steps + 1):
            hop_wall, hop_cpu = time.perf_counter_ns(), time.process_time_ns()
            def propose():
                with torch.no_grad():
                    next_state, logits = model.step(facts, query, state, feedback, mask)
                    if (next_state.shape != (1, model.hidden_dim) or logits.shape != (1, 2)
                            or not torch.isfinite(next_state).all() or not torch.isfinite(logits).all()
                            or next_state.abs().max().item() > 1.000001):
                        raise ValueError("bounded finite reader state and binary logits required")
                    return next_state.detach().clone(), logits.detach().clone(), int(logits.argmax(-1).item())
            (state, logits, prediction), proposal_cost = _measured(meter, "search", "proposer", propose)
            def check():
                with torch.no_grad():
                    _, verifier_logits = verifier.step(facts, query, state=None, feedback=None, mask=mask)
                    observed = observed_verifier_feedback(verifier_logits, prediction, has_evidence, threshold)
                    observed["feedback"] = observed["feedback"].detach().clone()
                    return observed
            observed, verifier_cost = _measured(meter, "search", "verifier", check)
            feedback = observed.pop("feedback")
            combined = dict(formula_flops=proposal_cost["formula_flops"] + verifier_cost["formula_flops"],
                            wall_ns=time.perf_counter_ns() - hop_wall, cpu_ns=time.process_time_ns() - hop_cpu)
            if step > 1:
                next_hops.append(combined)
            features, value_cost = (None, None)
            if step < max_steps:
                features, value_cost = _measured(meter, "search", "value",
                    lambda: row_features(state, logits, step, max_steps))
                callback_records["value"].append(value_cost)
            callback_records["proposer"].append(proposal_cost)
            callback_records["verifier"].append(verifier_cost)
            steps.append(dict(step=step, prediction=prediction, features=features,
                              state_sha256=_tensor_digest(state), verifier=observed,
                              feedback=feedback.tolist(), proposer_cost=proposal_cost,
                              verifier_cost=verifier_cost, value_cost=value_cost,
                              observed_reader_verifier_cost=combined))
        # This is the only target access. It follows all callbacks for this case.
        label = case.label
        if type(label) is not int or label not in (0, 1):
            raise ValueError("typed binary offline outcome required")
        for i, record in enumerate(steps[:-1]):
            rows.append(dict(features=record["features"], stop_success=record["prediction"] == label,
                continue_success=steps[i + 1]["prediction"] == label, source_group=case.source_hash,
                split=split, observed_at_ns=time.time_ns()))
        if _tensor_digest(facts, query, mask) != tensor_sha256:
            raise ValueError("calibration callback changed its public feature snapshot")
        trajectories.append(dict(case_id=case.case_id, source_group=case.source_hash,
            source_split=case.source_split, feature_sha256=public["feature_sha256"],
            tensor_sha256=tensor_sha256, offline_label=label, steps=steps, preparation_cost=preparation))
    after = dict(model_sha256=_frozen(model), verifier_sha256=_frozen(verifier))
    if before != after:
        raise ValueError("calibration mutated a selected frozen artifact")
    receipt = dict(schema="hepta.reader.offline-critic-trajectories.v1", split=split,
        max_steps=max_steps, verifier_threshold=threshold, cases=len(cases), rows=len(rows),
        source_groups=sorted({case.source_hash for case in cases}), trajectories=trajectories,
        rows_sha256=digest_json(rows), model_digests_before=before, model_digests_after=after,
        callback_empirical_maxima={component: _maxima(records) for component, records in callback_records.items()},
        empirical_next_hop_maximum={**_maxima(next_hops), "observed_segments": len(next_hops)},
        profile_kind="observed_maxima_not_certified_future_support",
        future_support_guaranteed=False, confidence_bound_established=False,
        target="binary_candidate_correctness_not_benchmark_f1", official_validation_labels_used=False,
        labels_used_only_after_public_trajectory=True, verifier_acceptance_is_semantic_truth=False,
        wall_ns=time.perf_counter_ns() - started_wall, cpu_ns=time.process_time_ns() - started_cpu,
        work_observation=meter.report(), gradient_updates=0,
        excluded_formula_work=["feature_encoding", "Python_label_scoring_and_JSON_hashing"],
        production_authorized=False)
    return rows, receipt


def fit_critic_metered(rows, calibration, *, cutoff_ns=None, steps=80, seed=0,
                       wall_time_ns=900_000_000_000):
    """Include admission, actual SGD, freezing and residual calibration work."""
    started_wall, started_cpu = time.perf_counter_ns(), time.process_time_ns()
    cutoff_ns = time.time_ns() if cutoff_ns is None else cutoff_ns
    meter = _ledger(wall_time_ns)
    with meter.scope("train", "value"):
        critic = fit_critic(rows, calibration, cutoff_ns=cutoff_ns, steps=steps, seed=seed)
        critic.assert_frozen()
    receipt = dict(schema="hepta.reader.metered-critic-fit.v1", cutoff_ns=cutoff_ns,
        fit_rows=len(rows), calibration_rows=len(calibration), metadata=critic.metadata,
        params_sha256=critic.params_sha256, metadata_sha256=digest_json(critic.metadata),
        wall_ns=time.perf_counter_ns() - started_wall, cpu_ns=time.process_time_ns() - started_cpu,
        work_observation=meter.report(), target="binary_candidate_correctness_not_benchmark_f1",
        profile_kind="observed_max_residual_not_certified_future_support",
        future_support_guaranteed=False, production_authorized=False)
    return critic, receipt
