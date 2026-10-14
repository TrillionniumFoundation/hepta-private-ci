# One-hop Reader label ablation: sealed paired-outcome audit

Research-only addition under PR #1546. **No new model inference or parameter updates.** This module scores the already registered 20-subject, 140-position frozen Reader experiment; it never modifies an original answer or promotes a decision based on p-value.

## Scientific question

The currently registered one-hop Reader trial changes **only the evidence JSON `label` field** (labeled vs unlabeled) while keeping the answer-only system prompt, source excerpt bytes and source order unchanged. Three evidence conditions have matched presentations (one correct fact, correct fact plus one competing Token, one irrelevant Token). The zero-evidence condition has one presentation, not a nonexistent labeled twin.

An apparent aggregate success increase could conceal different subjects succeeding, failing requests, or prompt-token length effects. Label omission also changes serialized input length; therefore the existing experiment **is not guaranteed token-compute matched** even if the two evidence byte excerpts are identical. This audit exposes the actual differences and retains the correct planned denominator.

## Exact source and seal checks before any comparison

1. Verify the original completed 140-call parent archive against its **external** GitHub SHA256 `9f4a4ed9429212b98befffca27a297780d61317eaed8be519b1cb6880037f121`, every internal hash, generating source/tree, 140 signed-off answer receipts and original scores. This uses `system2_onehop_label_ablation.load_previous` without a model call.
2. Verify the new trial's exact Git SHA, pinned parent identity, original 20 questions, complete 140-position plan, `starts.jsonl` with all unique attempted positions, original `raw-answers.jsonl` SHA256 and `raw-seal.json` asserting scoring had not started. Reject missing positions, duplicate JSON keys, unknown arms, wrong Reader provenance, changed source bytes, evidence bundle/delivery drift, unrecognized execution status, changed token digests or saved scoring/summary discrepancies.
3. Recompute the same original promotion gate: unlabeled competitor >=15/20 exact answers, unlabeled irrelevant-source >=18/20 exact refusals, no-evidence >=18/20. Reject a post hoc `candidate_disposition` rewrite. **The paired audit does not lower or replace the original gate.**

## Paired output, token cost, uncertainty

For each of the three paired source conditions and six prespecified descriptive metrics (`exact_answer_only`, `correct_token_mentioned`, `label_only_echo`, `prescribed_refusal`, `unsupported_token_output`, and `success`), report four cells: both presentations succeed, labeled only, unlabeled only, neither. Each metric is over the same **20 question identities**; this is not 40 independent questions.

Provide the difference in the original **planned 20-question denominator**. If `u` pairs have missing/failed results, report intervals `[(unlabeled_only-labeled_only-u)/20, (unlabeled_only-labeled_only+u)/20]`. Unknown execution never becomes zero-cost refusal or negative label. An exact conditional two-sided paired discordance p-value is reported **only when all 20 pairs completed**; this is descriptive, not a generalization guarantee or a replacement for independent benchmark confirmation.

For each paired question log the observed difference in full prompt input tokens and output tokens, including the number of token-equal pairs. A prompt length difference makes any positive result insufficient for a pure label-vocabulary causal claim. The unpaired zero-evidence baseline retains its full 20-subject denominator.

## Runtime and qualification boundary

The existing pinned offline workflow keeps the full MemoryCell suite, Ruff F/E9 quality checks, source archive integrity, the **same** original 140 frozen Reader calls and complete artifact upload. The new post-seal step runs **after** the Reader raw-answer seal is written; if the original model execution fails before a seal, an `audit-unavailable.json` receipt is saved and the main failure remains. If a seal exists but source/score provenance is invalid, the audit fails closed. There is **zero additional Reader compute** for this report.

The 20 previously exposed synthetic questions do not constitute unseen natural-language or independent human semantic evaluation. Success cannot establish pretrained Reader adequacy, NDU/FBSDE reasoning emergence, compute-matched inference, correct citations, or production readiness. Main and serving defaults remain unchanged.

Reproduce from an exact checkout after the original 140-position experiment has completed:

```bash
PYTHONPATH=scripts/memory_cell python scripts/memory_cell/system2_onehop_label_pair_audit.py \
  /path/to/pinned-cardinality-parent.zip /path/to/new-label-ablation-trial \
  /path/to/paired-audit.json --source-commit "$(git rev-parse HEAD)"
```

**Completed evidence (not a new model trial):** hosted source run
[38273406637](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38273406637)
successfully recorded 140/140 frozen Reader outputs, and sealed archive
qualification [38492538441](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38492538441)
succeeded. No labeled or unlabeled one-hop source condition produced an
exact single-token answer (0/20 each). Label-list echoes occurred in
12/20, 12/20 and 10/20 labeled conditions, versus zero in all three
unlabeled counterparts. All 60 unlabeled source presentations exhausted
64 decoder tokens; no-evidence correctly abstained 0/20. Paired
prompt lengths differ, and these are the same 20 previously exposed
synthetic questions, not independent evidence. The original admission
condition **failed** and is not amended by this retrospective report.
