# Question-conditioned shared evidence Reader — execution handoff

Parent: `a301a9f4b8185509868a5538dfe39e1e3fce784e` (PR #1903).
Exact tested Python code commit: `50efbdb26f442f06e0941ef793a3d14ffa8823bd` (PR #1925).
The eight changed files' Git blob SHAs match their tested local byte sequences. Research only: no main merge or production deployment.

## What actually executes

The exact-query-only fanout of #1903 cannot answer *different* questions by reusing a question-conditioned pooled feature. This increment keeps **token-level evidence** from a single frozen Encoder forward and performs a fresh, independently charged question embedding + lightweight cross-attention Reader for each different question. A physical separate-Encoder control actually recomputes the document for each question. Evidence identity binds principal scope, document text/ID, availability time and exact checkpoint digest; different questions are allowed but cross-principal or changed evidence is not.

Readers must have independent parameter storage, finite CPU FP32 weights, distinct task IDs, bounded options/questions and legal temporal scope. Frozen evidence state and query buffers are bounded by actual backing storage. Inputs cannot include outcome labels. An observation compares each question's logits and keeps unknown operator work as null, never as zero. No persistent feature cache, native install or selection authority exists.

The CPU V4 Reader arithmetic profile adds an *exact* `aten.select_backward.default` gradient scatter rule (zero floating arithmetic; nonzero memory traffic) without changing V3 history or default accounting. Actual training can optionally run under that strict, counted profile; initialization, material approval and independent assessment remain separately scoped.

## Actual local observations

- **526 distinct tests, executed twice**, matching planned IDs and test file hashes; zero failures, errors, skips or discovery errors. Both processes exited 0. 507 predecessor tests plus 19 new source tests. Python compileall and updated workflow YAML parse passed.
- A 42-parameter trainable Reader handled two independently varying synthetic facts under separate question vectors. It answered **80 of 80** test-only held-out synthetic judgments. Two opposite assignments collapse under simple mean pooling. Manipulating a needed evidence token changed some predictions. This is not public text QA, contamination-free future evaluation or learned long-horizon reasoning.
- Tiny physical two-question comparison: Encoder calls **1** (shared) versus **2** (separate); formula work **378** versus **450** (16% less); identical logits. Query and Reader work are charged twice in both arms. No measured latency or energy speedup.
- Former public family split **did not trigger** because training residual 0.00174058 was below the pre-registered 0.05 threshold. Do not lower it after observing results.

## Hosted plan without duplicate weight downloads

The existing `hepta-shared-fanout-research.yml` now includes conditional Reader and V4 formula source tests, a real stock miniature ModernBERT test, and a **three-different-question public-pretrained** comparison reusing the canary's existing pinned snapshot. The public canary's question-specific Readers are **untrained**. Changed-evidence ablation is separately charged. Until an exact-SHA hosted job reports success, neither stock nor pretrained results are claimed.

## Required further independent qualification

Train on real, independently annotated multi-question evidence; evaluate held-out source groups and key-premise removal. Compare against full joint question-conditioned Encoder, pooled Reader, question-only Reader and evidence-absent controls at measured, same total resource budgets; include real p95/p99/energy/memory and longer-term old-task retention. Study NDU/System2 and multimodal generators separately. No general evidence sufficiency, independent multitask gains, native 1024/4096-Cell service or 10T/100T-equivalence claim is authorized.
