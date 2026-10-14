"""Read-only, source-group-aware paired audit for sealed conditional Reader panels.

All comparisons use identical held-out questions. No training, retrials,
candidate selection, unverified independence or significance claim. Probability
movement after premise deletion is NOT accuracy: the missing answer is unknown.
"""
import math
from conditioned_panel_study import ARMS, score_panel, _probabilities
from next_round_matrix import _digest

def audit_reader_groups(observation, labels, *, expected_observation_id,
                        expected_labels_sha256, max_group_accuracy_drop=0.0,
                        max_group_brier_increase=0.0):
    for name, value in (("max_group_accuracy_drop", max_group_accuracy_drop),
                        ("max_group_brier_increase", max_group_brier_increase)):
        if type(value) not in (int,float) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("predeclared finite nonnegative subgroup allowance required: " + name)
    original=score_panel(observation,labels,
        expected_observation_id=expected_observation_id,
        expected_labels_sha256=expected_labels_sha256)
    rows=observation["predictions"]
    group_ids=sorted(observation["protocol"]["eval_source_groups"])
    reference=rows["conditioned"]
    groups={g:[] for g in group_ids}
    for i,row in enumerate(reference):
        groups[row["source_group"]].append(i)
    report={}
    for arm in ARMS:
        if arm=="conditioned":
            continue
        by_group=[]
        for group,indices in groups.items():
            recovered=lost=both_correct=both_wrong=0
            ref_brier=alt_brier=0.0
            for i in indices:
                label=labels[reference[i]["task_id"]]
                a=reference[i]["logits"]
                b=rows[arm][i]["logits"]
                aw=int(max(range(2),key=a.__getitem__)==label)
                bw=int(max(range(2),key=b.__getitem__)==label)
                recovered+=int(aw and not bw)
                lost+=int(bw and not aw)
                both_correct+=int(aw and bw)
                both_wrong+=int(not aw and not bw)
                for logits,key in ((a,0),(b,1)):
                    p=_probabilities(logits)
                    br=sum((p[k]-int(k==label))**2 for k in range(2))
                    if key==0:ref_brier+=br
                    else:alt_brier+=br
            n=len(indices)
            if n<1 or recovered+lost+both_correct+both_wrong!=n:
                raise ValueError("missing or duplicated paired subgroup denominator")
            diff=(recovered-lost)/n
            brier_diff=(ref_brier-alt_brier)/n
            by_group.append(dict(source_group=group,questions=n,
                conditioned_recovered=recovered,conditioned_lost=lost,
                both_correct=both_correct,both_wrong=both_wrong,
                conditioned_minus_control_accuracy=diff,
                conditioned_minus_control_brier=brier_diff,
                passed_descriptive_accuracy_allowance=diff>=-max_group_accuracy_drop,
                passed_descriptive_brier_allowance=brier_diff<=max_group_brier_increase))
        report[arm]=dict(groups=by_group,
            worst_accuracy_delta=min(v["conditioned_minus_control_accuracy"] for v in by_group),
            worst_brier_increase=max(v["conditioned_minus_control_brier"] for v in by_group),
            all_groups_within_descriptive_allowance=all(
                v["passed_descriptive_accuracy_allowance"] and v["passed_descriptive_brier_allowance"]
                for v in by_group))
    result=dict(schema="hepta.conditioned-reader-group-audit.v1",
        source_observation_id=expected_observation_id,
        external_labels_sha256=expected_labels_sha256,
        common_questions=len(reference),
        independent_group_count_not_attested=len(groups),
        allowances=dict(max_group_accuracy_drop=max_group_accuracy_drop,
                        max_group_brier_increase=max_group_brier_increase),
        comparisons=report,
        original_ablation_sensitivity=original["evidence_removal_sensitivity"],
        repeated_question_rows_not_independent_samples=True,
        independent_source_groups_verified=False,
        subgroup_uniform_generalization_established=False,
        statistical_superiority_established=False,
        feature_reuse_safety_for_different_principals_established=False,
        production_authorized=False)
    result["audit_id"]=_digest(result)
    return result
