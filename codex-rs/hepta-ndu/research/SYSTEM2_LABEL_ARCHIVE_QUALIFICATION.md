# Completed frozen Reader label experiment: independent archive qualification

**Scope:** Read-only research on PR #1546. No new model inference, data, labels,
learned Cell, Reader, tokenizer, NDU, FBSDE or production-path change.

## Verified generating source and archives

- Parent single-hop cardinality search: hosted [run 38266329906](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38266329906), artifact **11756357532**, ZIP SHA256 **`9f4a4ed9429212b98befffca27a297780d61317eaed8be519b1cb6880037f121`**.
- Label vs unlabeled Reader: hosted [run 38273406637](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38273406637), artifact **11760345185**, ZIP SHA256 **`a278014bae564336fc4d63335154cadbf14febc73620d958f45648b17ca0622a`**. Generating commit `24a1175958870816e40c7c62bbe1421b83e55dbd` and tree `84689f6c75dc35b8e9ff515be32094182438fa05`.
- **25/25 internal manifest SHA256 members passed in each ZIP.** The label answers' immutable raw seal is `6f630a86d374658049377d4611f92fd6c0dd6626c267eef7c37d77f07f5aeaa2`; **140/140** completed executions, **20 distinct** synthetic questions.

The new module verifies source, original output, its starts and schema, and both
outer and inner hashes. It then invokes the existing repository `system2_onehop_label_pair_audit.audit` against the **original sealed responses**. This calls no Reader and checks the source/evidence/Reader identities, independent scoring, completeness and original immutable disposition. Unknown or missing work is never counted as an unsuccessful answer or free inference. A single failure prevents the qualification receipt from being written.

## Actual findings, not an online action policy

| Fixed evidence | Labeled exact answer | Unlabeled exact answer | Labeled label-only output | Unlabeled decoder hits cap 64 |
| --- | ---: | ---: | ---: | ---: |
| One target fact | 0/20 | 0/20 | 12/20 | 20/20 |
| Target plus competing token fact | 0/20 | 0/20 | 12/20 | 20/20 |
| One irrelevant token fact | 0/20 | 0/20 | 10/20 | 20/20 |
| No evidence (unlabeled only) | — | 0/20 correct refusals | — | separately accounted |

Across the 60 subject-matched nonempty conditions, unlabeled presentation
removed **all** label-only echoes but caused **60/60** runs to use all 64
decoder tokens. Every original strict exact-answer/refusal success remained
zero. The actual prompts are **5 tokens shorter** for the single fact and
irrelevant-source conditions, **10 tokens shorter** for the two-source
condition. Therefore this is NOT a pure causal lexical-label intervention or
compute-matched improvement. One correlated cohort cannot establish Reader
generalization. No answer was altered, pasted, repaired or postprocessed.

## Why the separate workflow is needed

The first attempt to qualify the paired audit in [run 38276396054](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38276396054) failed in the full suite because its tests referenced an absent developer-local ZIP path. The current test code in PR #1546 instead resolves a required archival path from an environment variable and skips only truly source-only local integration. Rather than rerunning another 140 paid model calls, the separate workflow downloads the **already completed exact two archives**, runs tests with both pinned files staged, performs the full inherited post-seal semantic/source check and captures the report. It does **not** evade or assert passing the repository's separate blocking CI.

**Disposition:** `reject_no_answer_or_refusal_gain`; the original registered
admission threshold fails. Do not spend additional cycles growing the binary
Cell decision Head or adding NDU/FBSDE search depth to compensate for this
Reader deficit. A stronger fixed Reader and independently reviewed, budget-
matched compositional tasks are the necessary next science controls.

## Reproduce (no new model calls)

With an exact source checkout and two externally verified ZIPs:

```bash
export PYTHONPATH=scripts/memory_cell
export HEPTA_SYSTEM2_CARDINALITY_ARCHIVE=/path/to/parent-cardinality.zip
export HEPTA_SYSTEM2_COMPLETED_LABEL_ARCHIVE=/path/to/completed-label140.zip
python3 -m unittest discover -s scripts/memory_cell -p 'test_system2_label_archive_qualification.py' -v
python3 scripts/memory_cell/system2_label_archive_qualification.py \
    "$HEPTA_SYSTEM2_CARDINALITY_ARCHIVE" \
    "$HEPTA_SYSTEM2_COMPLETED_LABEL_ARCHIVE" /new/independent-receipt.json
```

Production accepted: **false**. NDU learning gain, probability calibration,
independent semantic correctness and multimodal capability: **not established**.
