#!/usr/bin/env python3
"""Fail-closed NDU-MGP P0–P4 acceptance gate; checks receipts, not scientific truth."""
import json, sys
from pathlib import Path

REQUIRED = {
 "P0": ["oracle_bvp_qp_agreement","nonlinear_error_bounds","encoder_flow_decoder_replay","exact_head_ci"],
 "P1": ["matched_six_arm_comparison","independent_heldout","semantic_quality","cvar","ambiguity","measured_total_cost","strong_baseline_superiority"],
 "P2": ["frozen_dllm_backbone","shared_vocab_logits","dynamic_unmask","stopping_policy","matched_tokens_and_compute","heldout_quality"],
 "P3": ["natural_image_speech_outputs","cross_modal_alignment","independent_factuality","streaming_safety","measured_latency","heldout_quality"],
 "P4": ["factorial_2x2_training_inference","same_capacity_free_controller","out_of_time_replication","external_utility_fixed","no_protected_task_regression","security_authority_review"]
}
def qualify(data):
    failures=[]
    if data.get("schema_version") != 1: failures.append("invalid schema_version")
    if set(data.get("phases",{})) != set(REQUIRED): failures.append("missing or unknown phase")
    for phase, names in REQUIRED.items():
        rows=data.get("phases",{}).get(phase,{})
        if not isinstance(rows,dict) or set(rows)!=set(names):
            failures.append(phase+": incomplete criteria");continue
        for name in names:
            item=rows[name]
            if not isinstance(item,dict) or item.get("status")!="PASS":
                failures.append(phase+"."+name+": not PASS");continue
            if item.get("attestation")!="independent-verified": failures.append(phase+"."+name+": missing independent verification")
            url=item.get("evidence_url")
            if not isinstance(url,str) or not url.startswith("https://"): failures.append(phase+"."+name+": missing evidence URL")
            sha=item.get("source_sha")
            if not isinstance(sha,str) or len(sha)!=40 or any(ch not in "0123456789abcdef" for ch in sha): failures.append(phase+"."+name+": missing exact source SHA")
            if item.get("study_status") not in ("pre_registered_holdout","prospective_replication","exact_head_ci"):
                failures.append(phase+"."+name+": no qualified evidence class")
    return failures
def main(path):
    try:
        data=json.loads(Path(path).read_text(encoding="utf-8"))
        problems=qualify(data)
    except (OSError,TypeError,ValueError) as exc:
        print("HOLD_NO_GO:",exc);return 2
    print("QUALIFIED" if not problems else "HOLD_NO_GO")
    for p in problems: print("BLOCKER",p)
    return 1 if problems else 0
if __name__=="__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv)==2 else "qualification.json"))
