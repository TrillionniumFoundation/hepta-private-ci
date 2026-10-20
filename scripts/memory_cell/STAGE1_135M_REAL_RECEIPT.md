# Real Stage-1 SmolLM2-135M reader disposition (historical exact source)

This is a read-only inspection of **actual model output**, not a new generation
run on the latest source HEAD, a human review, a memory-learning success, a
production certificate, or a model-selection instruction.

- Generating source: `5c9acdb340975adc2d16927fdb744023bd973bd8`.
- Workflow: https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39007522955
- Uploaded artifact ID: `12093476084`, `memory-stage1-real-smol-135m`.
- Independently downloaded artifact ZIP SHA-256:
  `07bb823e3b54b175689c0c1440930164260a76bfd43a7451ef23eb6f07714197`.
- All **20** inner files validated against the included original SHA256SUMS.
- Unedited scored-answer JSON SHA-256:
  `e5b437f07da5abac6ee1ab70018b4621ebb0af9b82d4c91aa926b72cef6ed971`.
- Unedited 98-row raw-answer journal exactly agrees with all non-scoring fields
  in the 98-row scored census. No original answer was rewritten.
- Immutable research tier: HuggingFaceTB/SmolLM2-135M-Instruct at revision
  `12fd25f77366fa6b3b4b768ec3050bf629380bac`.
- The original 8 public, exposed OpenBookQA-style diagnostic questions are **not**
  four independent prospective tasks, and their eight declared source-family
  strings are not an independence certificate.

## Actual observation census

98 planned inference conditions, 92 successful original generations, 6
unavailable because the prerequisite external review was missing; no execution
errors. Training optimizer: zero. The complete original planned denominator is
preserved. Diagnostic token F1 is **not** semantic QA accuracy.

| Condition | Planned | Succeeded | Unavailable | All-planned diagnostic F1 lower bound |
|---|---:|---:|---:|---:|
| empty | 8 | 8 | 0 | 0.148958 |
| retrieved1 | 8 | 8 | 0 | 0.248958 |
| retrieved2 | 8 | 8 | 0 | 0.076495 |
| reviewed_minimal | 8 | 5 | 3 | 0.010870 |
| reviewed_reversed | 8 | 5 | 3 | 0.010870 |
| noise_before | 8 | 8 | 0 | 0.133333 |
| noise_after | 8 | 8 | 0 | 0.133333 |
| without_fact1 | 8 | 8 | 0 | 0.248958 |
| without_fact2 | 8 | 8 | 0 | 0.248958 |
| reviewed_without_premise1 | 5 | 5 | 0 | 0.293333 |
| reviewed_without_premise2 | 5 | 5 | 0 | 0.293333 |

The other two original arms (`publisher_pair`, `pair_reversed`) each had
8/8 successful generations with diagnostic mean 0.076495. The 11-row controls
are intentionally **not** normalized to an 8-row denominator.

Paired original outcomes on the eight questions:
- `retrieved1` versus `empty`: one better, zero worse, seven equal, with
  four literally identical answers.
- `retrieved2` versus `retrieved1`: zero better, **two worse**, six equal,
  with five literally identical answers.
- Among the **five** cases where an externally reviewed minimal context existed,
  deleting its first marked premise improved token-F1 twice, worsened it zero
  times, and tied three times. This does **not** prove those premises unnecessary;
  the review is not independent, the reader output can be unrelated to evidence,
  and the remaining three cases were unavailable.
- No literal `[E...]` citation markers were emitted in any of the
  92 successfully generated answers. Semantic citation precision is **null**,
  not 0% or 100%: there were no citations to assess.

## Research disposition

1. The 135M frozen Reader has **not** shown that it can reliably use even the
   published reviewed minimal evidence. Changing the model or its input
   representation must be evaluated as a Reader/prompt effect, not a MemoryCell
   parameter-learning gain.
2. More retrieved context can reduce diagnostic performance; selection,
   distractor sensitivity, truncation, event/time normalization and prompt
   rendering deserve controlled matched ablations.
3. Existing open source reviews are incomplete (3/8 unavailable). Neither this
   metadata nor a consistent transcript hash proves oracle sufficiency or
   premise necessity.
4. The 1.7B tier and its complete paired whole-census bounds must be finalized
   separately; the 135M outcome alone cannot measure a capacity delta.
5. Stage-2 organizational effects, parameter-only compression, future
   independent program-task executions, storage/revocation costs, citation
   entailment and production acceptance remain **unproven**.

Do not promote a candidate, invent data for missing reviews, count unavailable
cases as successful, or retrain on these already exposed eight questions to
claim independent gain.
