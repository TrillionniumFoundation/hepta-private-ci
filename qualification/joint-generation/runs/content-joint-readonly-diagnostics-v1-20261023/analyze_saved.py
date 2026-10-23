"""Read-only saved-state diagnosis. No model class, data generator or optimizer."""

import csv
import hashlib
import io
import json
from pathlib import Path
import resource

import numpy as np


OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
RUN = ROOT / "runs/content-joint-train-v1-20261023"
FAMILIES, SEEDS = ("S", "H", "A", "N"), (11, 23, 47)
INPUTS, RAW, CACHE = {}, {}, {}
REVIEW_COUNTS = dict(probability_rows_examined=0, derived_logit_gradient_rows=0,
                     recorded_parameter_groups_examined=0)


def bind(path):
    path = Path(path)
    raw = path.read_bytes()
    INPUTS[str(path.relative_to(ROOT))] = hashlib.sha256(raw).hexdigest()
    return raw


def js(path):
    return json.loads(bind(path))


def arrays(path, keys):
    path = Path(path)
    if path not in RAW:
        RAW[path] = bind(path)
        CACHE[path] = {}
    missing = [key for key in keys if key not in CACHE[path]]
    if missing:
        with np.load(io.BytesIO(RAW[path]), allow_pickle=False) as data:
            for key in missing:
                CACHE[path][key] = data[key]
    return {key: CACHE[path][key] for key in keys}


def norm(x):
    return float(np.linalg.norm(x))


def cosine(x, y):
    denominator = norm(x) * norm(y)
    return None if denominator == 0 else float(np.sum(x * y) / denominator)


def entropy(probabilities):
    return -np.sum(probabilities * np.log(np.maximum(probabilities, 1e-300)), axis=1)


ENDPOINTS = ("ce", "raw_reward", "joint_success", "both_wrong", "wrong_agreement",
             "text_correct", "image_correct")


def state(path, recipe, law, take):
    probability_keys = ("s",) if recipe == "native" else ("p", "q")
    fields = list(probability_keys) + ["labels", "source_ids"]
    fields += [law + "/" + key for key in ENDPOINTS]
    if law == "log2":
        fields += [law + "/Q"]
    data = arrays(path, fields)
    labels = data["labels"][take]
    rows = np.arange(len(labels))
    result = {key: float(data[law + "/" + key][take].mean()) for key in ENDPOINTS}
    if recipe == "native":
        s = data["s"][take]
        ce = -np.log(np.maximum(s[rows, labels], 1e-300))
        result.update(anchor_CE=float(ce.mean()), probability_entropy=float(entropy(s).mean()),
            mean_max_probability=float(s.max(1).mean()),
            mean_target_probability=float(s[rows, labels].mean()),
            greedy_correct=float((s.argmax(1) == labels).mean()))
    else:
        p, q = data["p"][take], data["q"][take]
        ce = -(np.log(np.maximum(p[rows, labels], 1e-300))
               + np.log(np.maximum(q[rows, labels], 1e-300))) / 2
        law_entropy = (entropy(p) + entropy(q) if law == "KEEP"
                       else entropy(data[law + "/Q"][take].reshape(len(labels), 144)))
        result.update(anchor_CE=float(ce.mean()), probability_entropy=float(law_entropy.mean()),
            original_head_mean_entropy=float(((entropy(p) + entropy(q)) / 2).mean()),
            mean_max_probability=float(((p.max(1) + q.max(1)) / 2).mean()),
            mean_target_probability=float(((p[rows, labels] + q[rows, labels]) / 2).mean()))
    result.update(A_objective=.2 * result["anchor_CE"] - result["raw_reward"],
                  N_objective=.2 * result["anchor_CE"] - result["ce"], rows=len(labels))
    REVIEW_COUNTS["probability_rows_examined"] += len(labels)
    return result


def logit_components(s, labels, reward):
    n, rows = len(s), np.arange(len(s))
    r = np.diagonal(reward, axis1=1, axis2=2)[labels]
    anchor = s.copy()
    anchor[rows, labels] -= 1
    anchor *= .2 / n
    expectation = np.sum(s * r, axis=1)
    additive = -s * (r - expectation[:, None]) / n
    kernel = np.exp(-1.5 * (r - r.min(1, keepdims=True)))
    tilted = s * kernel
    tilted /= tilted.sum(1, keepdims=True)
    entropic = (tilted - s) / (1.5 * n)
    ga, gn = anchor + additive, anchor + entropic
    REVIEW_COUNTS["derived_logit_gradient_rows"] += n
    py = s[rows, labels]
    bins = []
    for low, high in ((0., .5), (.5, .9), (.9, .99), (.99, 1.0000001)):
        mask = (py >= low) & (py < high)
        an, nn = np.linalg.norm(additive[mask], axis=1), np.linalg.norm(entropic[mask], axis=1)
        bins.append(dict(low=low, high=min(high, 1.), rows=int(mask.sum()),
            mean_N_over_A_utility_norm=None if not mask.any() else float(np.mean(nn / np.maximum(an, 1e-300)))))
    return dict(anchor_norm=norm(anchor), A_utility_norm=norm(additive), N_utility_norm=norm(entropic),
        A_total_norm=norm(ga), N_total_norm=norm(gn),
        utility_N_over_A_norm=norm(entropic) / max(norm(additive), 1e-300),
        total_N_over_A_norm=norm(gn) / max(norm(ga), 1e-300),
        A_anchor_utility_cosine=cosine(anchor, additive),
        N_anchor_utility_cosine=cosine(anchor, entropic),
        A_N_total_cosine=cosine(ga, gn), fixed_target_probability_bins=bins)


def main():
    build = js(RUN / "build.json")
    quality = js(RUN / "quality-summary.json")
    zero = js(RUN / "zero-summary.json")
    old_final = js(RUN / "evidence/final-status.json")
    final_costs = js(RUN / "evidence/final-costs.json")
    execution = js(Path(str(RUN) + ".execution.json"))
    audit = js(RUN / "evidence/audit-result.json")
    bind(ROOT / "content_joint/frozen-v1.json")
    bind(ROOT / "content_joint/retained-train-v1.json")
    slot = {(s["family"], s["recipe"], s["seed"]): s for s in build["slot_results"]}
    curves, matched, initial_sharpness, gap_reversal = [], {}, {}, {}
    for seed in SEEDS:
        native0 = state(RUN / f"zero-native-{seed}.npz", "native", "native", slice(None))
        independent0 = state(RUN / f"zero-independent-{seed}.npz", "independent", "log2", slice(None))
        initial_sharpness[str(seed)] = dict(native=native0, independent_log2=independent0)
        gap0 = {key: native0[key] - independent0[key] for key in ("ce", "joint_success", "anchor_CE", "probability_entropy")}
        for family in FAMILIES:
            pair = {}
            for recipe in ("native", "independent"):
                row = slot[family, recipe, seed]
                laws = ("native",) if recipe == "native" else ("KEEP", "log2")
                path0 = RUN / f"zero-{recipe}-{seed}.npz"
                states = {0: {law: state(path0, recipe, law, slice(0, 128)) for law in laws}}
                for checkpoint in row["checkpoints"]:
                    update = checkpoint["update"]
                    path = RUN / f"{family}-{recipe}-{seed}/checkpoint-{update}.npz"
                    cp = arrays(path, ["source_ids", "labels"])
                    baseline = arrays(path0, ["source_ids", "labels"])
                    np.testing.assert_array_equal(cp["source_ids"][128:256], baseline["source_ids"][:128])
                    states[update] = {law: state(path, recipe, law, slice(128, 256)) for law in laws}
                    for partition, take in (("fit", slice(0, 128)), ("inner", slice(128, 256))):
                        for law in laws:
                            curves.append(dict(family=family, seed=seed, recipe=recipe, law=law,
                                stage="checkpoint", update=update, partition=partition, **state(path, recipe, law, take)))
                final_path = RUN / f"{family}-{recipe}-{seed}/quality.npz"
                final = {law: state(final_path, recipe, law, slice(None)) for law in laws}
                final_inner128 = {law: state(final_path, recipe, law, slice(0, 128)) for law in laws}
                pair[recipe] = dict(states=states, final=final, final_inner128=final_inner128, updates=row["updates"])
                for law in laws:
                    curves.append(dict(family=family, seed=seed, recipe=recipe, law=law,
                        stage="zero", update=0, partition="inner", **states[0][law]))
                    curves.append(dict(family=family, seed=seed, recipe=recipe, law=law,
                        stage="final", update=row["updates"], partition="inner", **final_inner128[law]))
            shared_updates = sorted(set(pair["native"]["states"]) & set(pair["independent"]["states"]))
            matched[f"{family}-{seed}"] = dict(common_updates=shared_updates,
                differences={str(update): {key: pair["native"]["states"][update]["native"][key]
                    - pair["independent"]["states"][update]["log2"][key]
                    for key in ("ce", "joint_success", "anchor_CE", "probability_entropy")}
                    for update in shared_updates},
                final_updates={recipe: pair[recipe]["updates"] for recipe in pair})
            end_gap = {key: pair["native"]["final"]["native"][key] - pair["independent"]["final"]["log2"][key]
                       for key in gap0}
            gap_reversal[f"{family}-{seed}"] = dict(zero_full768_gap=gap0, final_full768_gap=end_gap,
                change_in_gap={key: end_gap[key] - gap0[key] for key in gap0})

    target_analysis, trace_analysis, first_parameter = {}, {}, {}
    for seed in SEEDS:
        reward = arrays(ROOT / f"runs/content-reconcile-probe-v1-20261023/R-{seed}.npz", ["reward"])["reward"]
        trace = {}
        for family in ("A", "N"):
            folder = RUN / f"{family}-native-{seed}"
            fields = ["loss", "ce", "utility", "total_gradient_norm", "clip_scale", "group_names", "squared_gradient_norm_by_group"]
            fields += [prefix + key for prefix in ("first_gradient/", "last_gradient/", "first_delta/", "final_delta/", "moment1/", "moment2/", "clock/")
                       for key in ("encoder", "bias", "shared", "shared_bias")]
            trace[family] = arrays(folder / "gradient-updates.npz", fields)
            expected = .2 * trace[family]["ce"] - trace[family]["utility"]
            assert np.max(np.abs(expected - trace[family]["loss"])) < 1e-12
            assert all(int(trace[family]["clock/" + key]) == slot[family, "native", seed]["updates"]
                       for key in ("encoder", "bias", "shared", "shared_bias"))
        common = min(len(trace["A"]["loss"]), len(trace["N"]["loss"]))
        trace_analysis[str(seed)] = dict(actual_updates={f: len(trace[f]["loss"]) for f in trace},
            common_prefix_updates=common, clipped_steps={f: int(np.count_nonzero(trace[f]["clip_scale"] < 1)) for f in trace}, windows=[])
        for start in range(0, common, 64):
            stop = min(start + 64, common)
            trace_analysis[str(seed)]["windows"].append(dict(first_update=start + 1, last_update=stop,
                **{f: {key: float(trace[f][key][start:stop].mean())
                       for key in ("loss", "ce", "utility", "total_gradient_norm")} for f in trace}))
        first_parameter[str(seed)] = {}
        for key in ("encoder", "bias", "shared", "shared_bias"):
            ga, gn = trace["A"]["first_gradient/" + key], trace["N"]["first_gradient/" + key]
            da, dn = trace["A"]["first_delta/" + key], trace["N"]["first_delta/" + key]
            first_parameter[str(seed)][key] = dict(A_gradient_norm=norm(ga), N_gradient_norm=norm(gn),
                N_over_A_gradient_norm=norm(gn) / max(norm(ga), 1e-300), gradient_cosine=cosine(ga, gn),
                A_delta_norm=norm(da), N_delta_norm=norm(dn), delta_cosine=cosine(da, dn),
                sign_disagreement_fraction=float(np.mean(np.sign(ga) != np.sign(gn))))
            REVIEW_COUNTS["recorded_parameter_groups_examined"] += 2
        target_analysis[str(seed)] = {}
        for update in (1, 128, 256):
            saved = {}
            for family in ("A", "N"):
                path = RUN / f"{family}-native-{seed}/checkpoint-{update}.npz"
                saved[family] = arrays(path, ["training_batch_s", "training_batch_labels", "training_batch_indices"])
            np.testing.assert_array_equal(saved["A"]["training_batch_indices"], saved["N"]["training_batch_indices"])
            target_analysis[str(seed)][str(update)] = {
                f: logit_components(saved[f]["training_batch_s"], saved[f]["training_batch_labels"], reward)
                for f in ("A", "N")}

    budget = {}
    for family in FAMILIES:
        rows = [s for s in build["slot_results"] if s["family"] == family]
        train_CPU = sum(s["training_CPU"] for s in rows)
        init_CPU = sum(s["initialization_CPU"] for s in rows)
        training_units = sum(s["training_units_including_checkpoints"] for s in rows)
        core_nontraining_CPU = build["costs"][family]["active_CPU"] - train_CPU
        budget[family] = dict(training_with_checkpoints_CPU=train_CPU, initialization_CPU=init_CPU,
            core_export_observation_service_residual_CPU=core_nontraining_CPU - init_CPU,
            core_all_nontraining_with_scheduler_outer_CPU=core_nontraining_CPU
                + build["costs"][family]["scheduler_CPU"] + execution["final_administration_and_saved_output_analysis_CPU"],
            training_with_checkpoints_units=training_units,
            core_tail_units=build["ledgers"][family]["consumed_units"] - build["shared_ledger"]["consumed_units"] - training_units,
            fixed_checkpoint_units=build["ledgers"][family]["stages"]["fixed_checkpoint"]["consumed_units"],
            per_slot=[{key: s[key] for key in ("recipe", "seed", "updates", "training_CPU", "training_units_including_checkpoints", "per_step_kernel_units", "initialization_CPU", "initialization_units")}
                      for s in rows],
            stages=build["ledgers"][family]["stages"])
    max_tail = max(v["core_all_nontraining_with_scheduler_outer_CPU"] for v in budget.values())
    old_review = audit["complete_audit_CPU_before_receipt"] + final_costs["saved_description_CPU_before_receipt"]
    future = dict(status="proposal only; no new training or method execution",
        observed_worst_core_tail_CPU=max_tail, observed_old_promised_review_CPU=old_review,
        observed_old_whole_tail_CPU=max_tail + old_review,
        proposed_tail_reserve_CPU=2.5, proposed_global_guard_CPU=.5,
        proposed_tail_reserve_units=500_000_000,
        observed_worst_core_tail_units=max(v["core_tail_units"] for v in budget.values()),
        shared_CPU_reference=build["common_CPU"], shared_units_reference=build["shared_ledger"]["consumed_units"],
        plans={str(cap): dict(cap_CPU=cap, cap_units=12_000_000_000,
             slots_per_family=6, training_CPU_per_slot=(cap - .5 - build["common_CPU"] - 2.5) / 6,
             training_units_per_slot=(12_000_000_000 - build["shared_ledger"]["consumed_units"] - 500_000_000) // 6)
             for cap in (10., 11.)},
        old_slot_CPU=build["quota_CPU"], prospective_bound_not_a_CPU_guarantee=True,
        historical_failure_unchanged=True)
    result = dict(scope="independent saved-evidence research review, not an extension of old method ledger",
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), inputs=INPUTS,
        old_final_status=old_final, original_final_costs=final_costs,
        model_forward_calls=0, decoder_forward_calls=0, optimizer_updates=0,
        sampling_draws=0, images_rendered=0, formal_data_opened=False,
        initial_sharpness=initial_sharpness, coupling_gap_reversal=gap_reversal,
        matched_saved_update_comparisons=matched, fixed_probability_state_curves=curves,
        paired_native_A_N_training_traces=trace_analysis,
        derived_saved_batch_logit_components=target_analysis,
        actual_initial_parameter_gradients_and_deltas=first_parameter,
        budget_components=budget, future_budget_candidates=future,
        missing_information=["no zero-update fit probability capture", "no intermediate Adam moment snapshots",
            "no saved pre-update training hidden/Jacobian except probabilities", "no per-step or separate checkpoint CPU timings",
            "final export/observation/service CPU only aggregate residual", "no alternative initialization or equal-step final511/490 counterfactual"],
        review_counts=REVIEW_COUNTS)
    usage = resource.getrusage(resource.RUSAGE_SELF)
    result["separate_review_CPU_before_receipt"] = usage.ru_utime + usage.ru_stime
    (OUT / "diagnosis.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    fields = ("family", "seed", "recipe", "law", "stage", "update", "partition", "rows",
              "ce", "raw_reward", "joint_success", "both_wrong", "anchor_CE", "A_objective", "N_objective",
              "probability_entropy", "mean_max_probability", "mean_target_probability")
    with (OUT / "all_saved_curves.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(curves)
    print(json.dumps(dict(separate_review_CPU=result["separate_review_CPU_before_receipt"],
        matched_comparisons=len(matched), saved_state_rows=len(curves), future=future), indent=2))


if __name__ == "__main__":
    main()
