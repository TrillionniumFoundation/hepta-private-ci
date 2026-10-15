"""Fail-closed research audit for pinned 24-to-64 original Reader budget ladder.
Source-only: the original private inference journals require separate physical review.
"""
import json
import hashlib
from pathlib import Path

ORIGINAL_READER = "5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c"
PROFILE = "hepta.amcn.archived-reader-24-vs-64-eight-verbatim-capacity-denial.v1"
NEGATIVE = ("human_sufficient_evidence_verified", "official_HF_operator_parity_verified",
            "reader_capacity_proven", "memorycell_learning_gain_proven",
            "answer_based_selection_is_representative", "production_accepted",
            "superiority_claim")
SHA_KEYS = ("original_24_token_plan_sha256", "original_24_completion_seal_sha256",
            "original_24_postseal_score_sha256", "original_64_completion_seal_sha256",
            "original_64_postseal_score_sha256")

def check(value):
    if not isinstance(value, dict) or value.get("profile") != PROFILE:
        raise ValueError("original Reader cohort missing")
    if any(not isinstance(value.get(x), str) or len(value[x]) != 64
           or any(ch not in "0123456789abcdef" for ch in value[x]) for x in SHA_KEYS):
        raise ValueError("original receipt identities missing")
    if (value.get("real_original_reader_model_sha256") != ORIGINAL_READER
            or value.get("original_case_count") != 8
            or value.get("original_source_families") != 4
            or value.get("original_24_max_new_tokens") != 24
            or value.get("original_64_max_new_tokens") != 64
            or value.get("actual_original_64_reader_calls") != 16
            or value.get("failed_original_64_reader_calls") != 0
            or value.get("paired_original_24_64_greedy_prefix_equal_calls") != 16):
        raise ValueError("original paired numeric execution census changed")
    for x in NEGATIVE:
        if value.get(x) is not False:
            raise ValueError("unsupported Reader/MemoryCell promotion")
    if (value.get("original_publisher_answer_selection_uses_gold") is not True
            or value.get("independent_semantic_task_success") is not None
            or value.get("true_future_calendar_windows") != 0):
        raise ValueError("gold-selected cohort may not become independent qualification")
    plans = {"publisher_annotated_witness":(1425,161,336,4,5),
             "publisher_witness_lesion":(1266,178,293,0,0)}
    for key, (inp, g24, g64, h24, h64) in plans.items():
        a=value.get(key)
        if not isinstance(a, dict) or any(a.get(k)!=v for k,v in (
            ("input_tokens", inp),("generated_24",g24),("generated_64",g64),
            ("substring_hits_24",h24),("substring_hits_64",h64),
            ("exact_matches_24",0),("exact_matches_64",0))):
            raise ValueError("paired original Reader result/cost drift")
    return {"original_64_calls_claimed":16,"greedy_prefix_parity_claimed":16,
            "substring_witness_24":4,"substring_witness_64":5,
            "original_model_calls_independently_authenticated":False,
            "semantic_success_verified":False,"production_accepted":False}

if __name__ == "__main__":
    import sys
    if len(sys.argv)!=2: raise SystemExit("expected original aggregate file")
    data = Path(sys.argv[1]).read_bytes()
    print(json.dumps(check(json.loads(data)),sort_keys=True))
