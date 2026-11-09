# CTRL stage 1: selected content through independent scoring

Base: PR #5450, `f6a7d5307f888d30faa8803d23487c78789b99fe`.
This change extends that branch only. It does not merge or qualify PR #5451.

## Problem

The published six WRITE_TEXT failures show that a reference-matching candidate
exists in every candidate set, but do not retain the selected candidate or the
full delivery chain in the V2 training projection. A zero quality score cannot
identify a failed execution. The host previously checked the evaluator source
digest without also checking its case, rubric and exact delivery-file digest.

## Change

The actor emits a bounded ordered candidate-set commitment and the chosen
candidate/index for WRITE_TEXT. The host checks this witness against the action
before applying it. After execution, a digest-only sidecar binds the actual actor
stdout bytes and host exchange to the persisted delivery and independent scorer
input. The episode result pins the sidecar digest. This work is recorded in the
existing codec/evaluation meters.

New actors advertise the selection profile and a missing witness is rejected.
Historical records without selection, raw wire or matching evaluation retain an
unknown `selected_used` label. Local semantic effect remains a separate unknown;
neither zero reward nor an absent receipt is relabelled as an execution failure.

These are consistency receipts. Native owner authentication, semantic correctness
and complete-cost policy improvement remain separate obligations. Candidate
selection, model weights, existing controller choice and V2 row schema are
unchanged.

## Validation and limits

Three behavior tests passed: real host callback/persistence/independent scoring,
changed-link rejection, and preservation of unknown historical labels. The first
test chooses both a correct and an incorrect candidate: both are delivered as
chosen, while their quality scores correctly differ. The tests include UTF-8.

```sh
PYTHONPATH=scripts:. python -m unittest ndu_real_runtime.test_content_identity -v
```

The original six episodes have not been read back in this stage. No specific
historical root cause or research gain is claimed. Qualification remains HOLD.
