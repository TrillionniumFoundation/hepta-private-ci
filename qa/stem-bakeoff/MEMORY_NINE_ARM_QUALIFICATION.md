# Hepta Memory A-I: prospective, source-first original-answer qualification

**Status:** RESEARCH / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO. This protocol
does not merge or activate any MemoryCell, replace Memory/CNS/FinalUse owners,
prove trained memory improvement, or authenticate externally supplied receipts.

## What is new

This is the strict common-result gate for **one and the same memory task cohort**
under one frozen Reader, tokenizer, prompt, shared Encoder identity,
source/forget frontier, evidence-slot ceiling and token ceilings. Every case
requires exactly nine *original* calls and nine separate blinded judgments.
A descriptive retrieval-support win is not a Reader answer-accuracy win.

| Arm | Fixed architecture | Required comparison |
| --- | --- | --- |
| A | lexical BM25 | lexical floor |
| B | dense + BM25 + real reranker | strong hybrid floor |
| C | independent Graph-RAG / HippoRAG-style source graph | graph retrieval floor |
| D | frozen typed memory organization | D-B |
| E | one actually trained shared-Encoder Head | E-D |
| F | two typed learned Heads with equal TOTAL Head parameters | F-E |
| G | F with physically learned pre-Head sparse Router | G-F |
| H | G plus physically learned evidence-bounded Meta-Graph | H-G |
| I | H with actual Split/Merge/Retire and matched static continuation | I-H |

Additional primary tests are I-B and I-C on **each** future window.
All eight fixed comparisons use the same complete case census; none can be
chosen after examining results. The gate requires the same trainable Head
capacity and total training allocator ceiling for E-I, and matched H/I Head
continuation steps. Router, graph, replay and evolution work MUST consume
that common budget and be independently metered. A typed or evolutionary
candidate cannot quietly receive a larger training allowance.

## Authoritative input boundary

The gate accepts three separate JSON inputs:

1. An externally pinned immutable **plan**, generated before source-index
   construction, development selection, training, Reader calls or opening
   evaluator labels. Exact top-level fields: schema, common, cases, arms, policy.
   Each case contains only an immutable query/snapshot digest, its disjoint
   source-ancestor roots, a complete eligible source-ID inventory, a cohort
   family/window. Task categories belong to the separate blind judgments;
   the worker-facing plan contains no answer,
   gold support IDs or reviewer output. Full raw source and source-root
   membership must be authenticated by a separate ledger owner.
2. The **observations** array: exactly one source-bound original Reader outcome
   for every (case, arm). It includes original answer bytes and their recomputed
   SHA256, source selection, ordered citations [E1] etc., model and artifact
   digests, source/forget frontiers, Head and Reader physical call counts,
   generated/context token counts and actual CPU/RSS/latency counters. The
   gate checks these claims but cannot attest that the model really ran.
3. The **judgments** array, produced only after the complete answers are sealed
   and with reviewer source/gold access separate from the original workers.
   Each answer digest is rebound to the raw original answer; independent
   correctness, grounding, citation entailment, proper abstention, safety and
   gold support are all typed. A forged Boolean 0/1 is rejected; unavailable,
   missing and unresolved cases remain in the denominator.

All source roots connected through any case form ONE effective component.
The gate rejects any training/calibration ancestor used for evaluation, any
source-root crossing windows, and any duplicate or missing attempt/judgment.
The two future windows must be genuinely prospective and timestamped/authenticated
by a separate evaluator, **not** historical test slices renamed "future".
That external witness is not created or verified by this Python module.

The plan must be pinned outside the evaluator invocation: pass the SHA256 of
the **canonical JSON serialization** (sorted keys, compact separators, UTF-8)
that has already been deposited with the independent plan owner. An
arbitrary plan with a freshly computed hash is not proof of preregistration.

### Run only with real sealed inputs

From the repository root:

    python3 -m unittest discover -s qa/stem-bakeoff -p 'test_memory_nine_arm_gate.py' -v

    python3 qa/stem-bakeoff/memory_nine_arm_gate.py \
      --plan EXTERNAL_FROZEN_PLAN.json \
      --observations ORIGINAL_NINE_ARM_CALLS.json \
      --judgments INDEPENDENT_BLIND_JUDGMENTS.json \
      --expected-plan-sha256 EXTERNALLY_PUBLISHED_PLAN_SHA256 \
      --report NEW_CREATE_ONLY_REVIEW.json

The report is create-only and fsynced. An incomplete/mismatched input exits
with an error without writing a success-shaped report. Never edit the sealed
original Reader answers to make a score pass.

### Statistical admission

The descriptive candidate gate requires at least 200 effectively independent
future source components in aggregate, at least the precommitted floor in
each of two future windows, all eight Bonferroni-adjusted approximate
family-cluster paired lower bounds above zero, and I-B and I-C above zero
separately in both windows. There must be zero unsafe, unavailable or
unscorable original rows. I must meet predeclared physical CPU and peak RSS
ratios relative to B. Any regression or incomplete case stays visible.

These approximate intervals are diagnostics, NOT definitive statistical
certification. Dataset lineage, sampling design, source independence, blind
human/semantic judging, physical memory usage and multiplicity assumptions
must be reviewed by independent evidence owners.

**Even if the descriptive gate passes, output remains HOLD_NO_GO.** To move
beyond it, separately authenticate original model and Reader execution,
training/replay/graph artifacts, plan chronology, independent source/judge
signatures, all-up lifecycle compute/energy/recovery cost, deletion and
unlearning evidence, production authority and independent multi-host tests.
Source digests and test names alone cannot supply these proofs.

## Reuse existing research honestly

- PR #3125: actual pinned LoCoMo text-only episodic retrieval shows a
  conversation-macro all-annotated-support improvement over turn+session BM25
  (+4.924 percentage points over six evaluation conversations). Multi-hop
  retrieval regresses; the abstention classifier accepts all 299 adversarial
  questions, and the run contains no Reader answer generations. This is only
  an A/D-*like retrieval subcomparison*, **not** A-I qualification.
- PR #3125: actual local Procedural Head trained, but lost at confidence
  coverage to nearest-neighbor/centroid; the learned news Router lost accuracy
  to pooled Head, and Split degraded on the August heldout.
- PR #2085: earlier nine-arm causal audit has other arms and a source-first
  Reader and reviewer framework. Preserve original evidence and reuse
  authenticated interfaces where appropriate. Never relabel the earlier
  nine arms as this A-I matrix or combine different task sources/readers.

## Remaining blockers (no false closure)

1. Physically produce B's full-corpus dense+BM25+reranker and C's independently
   checked Graph-RAG evidence on the SAME cases as A and D, preserving source
   and context budgets.
2. Physically execute original shared Encoder, trained E/F Heads and selected
   G/H/I routes with exact immutable model/head/router/graph/replay pins.
3. Run one common Reader over all nine identical case sets, collect original
   answers and independent blind citation/answer/procedure judgments.
4. Rebuild fresh, independent, genuinely future source cohorts; authenticate
   source lineage, withdrawals/deletions and complete ancestor closure.
5. Match training, graph and evolution workload; measure wall time, CPU,
   RSS/GPU, context and Reader tokens, index storage, refresh, recovery and
   total lifecycle costs.
6. Obtain terminal exact-head test results across required platforms and
   independently verify the evidence, no exemptions or synthetic uplift.
7. Qualify durable MemoryCell/Agentd execution, production authorities,
   topology CAS/rollback and actual multi-host trust. None is granted here.

The unit fixtures are **deliberately synthetic negative/contract tests**, not
a neural experiment. Do not count successful CI unit tests as memory quality.
