# MemoryCell four-stage experimental outcome gate - 2026-10-14

**Research-only, fail-closed. Neither a new Memory OS nor deployment authority.**

This continuation reuses the existing event reader, frozen Reader models,
strong RAG controls, organized evidence graph, source-only memory write,
learned policy and lifecycle accounting. It adds one strict, **read-only
reconciliation** of their eventual original outcomes; it does not fabricate
40/72 generations, human sufficient-evidence review, independent signatures,
future observation windows, or production switch/recovery.

## 1. Reader before learning

For each preregistered task, keep the same prompt, context/output budgets,
source pool and available tools. The **baseline and reference** Readers each
receive: `none`, `retrieved` (tuned strong RAG), independently `reviewed`
(sufficient evidence *if externally verified*), and `ablated` (exactly one
preregistered critical source removed). Reference comparison may diagnose
Reader capacity, **never** MemoryCell learning gain. An absent independent
sufficiency review stays `unavailable` for both `reviewed` and `ablated`;
missing model executions are failures or missing paired outcomes, not zeros
renamed unavailable. Audited row digests are not independent human reviews.

Diagnostic hierarchy: a failed answer with sufficient evidence points to
Reader/prompt/task bottlenecks; sufficient succeeds while tuned retrieval
fails points to retrieval/packing; ablated still succeeds invalidates a
necessity claim; only the stronger Reader succeeds records capacity gain.
No historical answer-conditioned literal span is an admissible reviewer oracle.

## 2. Nonparametric organization before parametric memory

Within the **same baseline Reader and original candidate-pool/source frontier**
run the additional `single_hop`, `entity_time`, and `organized` controls.
Compare the organized graph both to preregistered tuned strong RAG and
full-path entity/time, not merely to an intentionally weak top-4 Reader.
Event projection/correction and evidence completion are retrieval benefits,
not learned-parameter benefits. Task success and program execution receipts
are primary; source hit rate and F1 remain diagnostics.

## 3. Frozen-source write, then newly exposed tasks

Task/source cuts must precede write freeze, and write freeze must precede
exposure. This metadata claim must be authenticated by the upstream original
source/artifact owner; a self-authored timestamp is **not** sufficient.
Evaluate the same newly frozen source pool through `learned_policy`,
`knowledge` on byte-identical organized evidence, and `module_only` with
**zero original evidence** and the *same learned knowledge snapshot*.
The strong RAG and organized controls have the same Reader/tools/budget.
The auditor rejects missing cases, changed source frontier, unequal reference
evidence, a post-task write, mid-task write drift, and a knowledge arm that
gets different evidence. A learned arm with a regression or no task win over
organized evidence is rejected. A development win only calls for new blinded
prospective evaluation, not promotion.

Precommit the new-fact, updated-fact, cross-experience and real program-task
strata. For program success, retain the original execution trace and verification
receipt; avoid treating prose F1, an unexecuted procedure, or fewer selected
sources as task success. Production-scoped side effects require the current
owners and explicit authorization; this experiment executes no such effects.

## 4. Full lifecycle before qualification

`extract + index + train + N * query + maintenance + revocation + recovery`
are separate nonoverlapping monetary envelopes per arm. Include original raw
sources and physical index retention; maintenance must explicitly include
storage charges. Unknown dollars, future workload N, third-party costs and
revocation/recovery are `null` (never zero). The existing inclusive-envelope
owner remains authoritative for avoiding nested training/write double count.
Repeated source families/shards do not count as independent new histories.

Actual three-generation predecessor/current/future windows, multi-node
withdrawal and disaster recovery, independent semantic QA/citation reviewer,
production rollbacks, sufficient independent groups and stronger-RAG advantage
remain external admission gates. The reconciler unconditionally emits
`allow_parametric_promotion=false` and `production_accepted=false`; this is
not a replacement for `blocking-ci` or HNMF/DecisionCell authority.

## Current pinned observational baseline (not regenerated here)

* Frozen Qwen/Smol event study: generating source `59f9eadd5cc919359079e04442f7343838a60057`, pinned historical comparison. Qwen eight authored tasks: hybrid 3/8, full entity/time 8/8, organized 8/8; organized answers with complete *formal* cited source chain 4/8. Smol: hybrid 1/8, organized 3/8, complete formal cited chains 0/8. Human semantic sufficiency/entailment not reviewed.
* LongMemEval original 500 tasks: RAG diagnostic token-F1 `0.09417161800440411`, RAG-LoRA `0.09200215599714094`; no model-learning superiority.
* New 2026-10-14 disjoint top-k shard record: 37/40 actual calibrated Reader calls authenticated, remaining three on case 6/part 0 blocked by CPU BF16 ISA gate. Its new 72 nine-arm test calls are unexecuted. Do not splice earlier runs into that identity.

These are existing read-only findings, not newly produced original answers.
For repeatable input admission, every CLI file must have an **externally fixed**
SHA256 digest; the runner never infers an expected pin from a file being checked.
Upstream must authenticate original model outputs and worker traces independently
before passing *metadata* into this reconciler. Neither source hashes nor user
provided success booleans are proof of semantic correctness by themselves.

```sh
PYTHONPATH=scripts/memory_cell python3 -m unittest \
  discover -s scripts/memory_cell -p test_four_stage_audit.py -v
python3 scripts/memory_cell/four_stage_audit.py \
  PLAN.json ATTEMPTS.json LEDGER.json \
  --plan-sha256 EXTERNAL_SHA256 \
  --attempts-sha256 EXTERNAL_SHA256 \
  --ledger-sha256 EXTERNAL_SHA256
```
