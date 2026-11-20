# A current-policy correction materials

This readback uses unchanged originals from #6778, source `ef096991a2632d04758d5a577ea9fbdf54209d31`. It verifies both A archives and all 578 indexed members in memory, then binds each current-policy action to its actual model, request history, feedback, patched source, original tests and ordered JUnit cases. No archive member is executed or extracted by the script.

The 16 original own-policy A calls contain 12 native executions, four admission refusals, eight native failures and four successful executions. All successes are humanize. The eight failures retain five distinct source states. Four are first-attempt native failures:

| Arm | Project | Original first native result |
| --- | --- | --- |
| document_evidence | attrs | 2/5 cases fail |
| document_evidence | rich | 10/24 cases fail |
| native_feedback | attrs | 5/5 cases fail |
| native_feedback | platformdirs | 4/29 cases fail |

The two first-attempt admission refusals remain separate: document/platformdirs emits content outside the allowed function/constant; native/rich changes the permitted signature/decorators. They remain in the original denominator and have no native state snapshot. The report retains every failed second attempt as well; repeated states are not new independent sources.

Replacing only the permitted function/constant of each saved failed state with its existing A maintainer target reconstructs the exact previously verified AFTER hash in **8/8** cases. This is a structural byte comparison. **New native revalidations: 0.** The existing CPU-reference record supplies the prior target identity; this readback does not repeat that native verification or establish correction-training benefit.

The completed training used four original P first-failure contexts, not these current-student states. Original budgets remain spent: **56 evaluation generations and 32 optimizer updates per arm**. Training admission, correction learning gain, retention, independent confirmation and native adoption remain false. Original scores and NoUpdate are unchanged.

## Reproduce

Use a checkout or exact materialization containing the original #6778 input paths:

```bash
python scripts/cell_experiments/e2_current_state_readback.py --source-root . > /tmp/A_CURRENT_STATE_READBACK.json
cmp /tmp/A_CURRENT_STATE_READBACK.json qualification/cell-upstream-raw-function-learning-20261119/evaluation-20261120/current-state-readback/READBACK.json
```

The script pins the original A dataset, CPU reference controls, A archive manifest and aggregate evaluation readout by SHA256. The aggregate readout supplies only the already completed budget counters. No future-task or future-answer artifact is opened. The two original archive files are read at their existing paths; none is copied into this evidence slice.

`READBACK.json` maps the four first native failures and two first refusals explicitly, retains all eight failed-state reconstructions, and records zero new model loads, forwards, generations, updates and native revalidations. `VALIDATION.json` records the actual byte verification, deterministic readback, input-read scope and tamper-refusal checks performed before final formatting.
