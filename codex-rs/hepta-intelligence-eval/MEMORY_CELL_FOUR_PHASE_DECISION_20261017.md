# MemoryCell — four-stage paired decision and capability boundaries (2026-10-17)

This update *extends the existing* `scripts/memory_cell/factorial_evidence_gate.py`.
It does not construct another Memory OS, retune trained weights, replace the
baseline, or turn prior development artifacts into new evidence.

## Experimental order (stop rather than escalating without a demonstrated effect)

1. **Reader solvability.** Compare frozen and stronger research readers on
   no evidence, ordinary hybrid evidence, human-reviewed sufficient evidence,
   and a necessary-premise ablation, with unchanged template and budgets.
   If a supposedly removed premise still permits correct answers, count that
   as a potential redundant-source/shortcut path, **not** proof of necessity.
   Inspect these cases before optimizing yet another retrieval objective.
   Record every paired task, including abstentions and errors. The existing
   schema's `oracle` is **not independently human verified**; its observed
   success may diagnose a bottleneck but does not qualify the experiment.
   Stronger-reader-only wins are always assigned to reader capacity.
2. **Nonparametric organization.** On the same frozen reader and identical
   tool permissions, compare strong Hybrid with entity/time projections and
   conflict-aware event organization. Record paired wins/losses by task type
   and stated root, not just aggregate accuracy, source-count savings or F1.
3. **Isolated parameter gain.** Compare a learned read policy and an
   experience-knowledge module against **both** organized memory and strong
   Hybrid, while holding reader, prompts and delivered evidence constant
   for parameter-only effects. Knowledge-only/no-raw-text results are a
   compression boundary, not a replacement baseline; the reported hashes do
   not authenticate the absence of raw evidence unless independently reviewed. Source-before-task
   frozen training and genuinely unexposed tasks must be certified separately.
4. **Lifecycle acceptance.** Keep extraction, indexing, writing/training,
   query/diagnosis/recovery, maintenance, revocation and retained raw-source
   storage in scope. A sum of per-observation receipts cannot be silently
   reinterpreted as once-only writing or reused-query TCO. Missing terms are
   unknown, not zero. Real future windows and cross-host recovery still
   require operational observations.

## Changes and validation

`paired_task_diagnostics` now reports ten frozen comparisons with per-task
and per-declared-root paired denominators, task wins/losses, diagnostic counts,
recovery differences, token deltas and evidence identity. This exposes an
unobserved task gain even when two aggregate means tie. `four_stage_disposition`
provides a causal next-priority indication and explicit nonqualification flags.
An apparent learned improvement does **not** gain statistical or production
acceptance through this audit; asserted `verified=true` is not an independently
authenticated semantic judgment.

The regression fixture is artificial and asserts only audit logic. New tests
verify that a stronger reference-reader gain cannot become a MemoryCell gain,
a saturated strong baseline rejects an ineffective learned candidate, result
denominators remain paired, and unknown lifecycle costs never become zero.

```sh
PYTHONPATH=scripts/memory_cell python3 -m unittest discover \
  -s scripts/memory_cell -p 'test_factorial_*.py' -v
PYTHONPATH=scripts/memory_cell python3 -m unittest discover \
  -s scripts/memory_cell -p 'test_matched_structured_rag_gate.py' -v
```

The archived-only matched-RAG suite is explicitly skipped in generic test
discovery without its pinned GitHub artifact; the dedicated CI job provides
the archive and must still fail if it is missing or changed. Existing
`blocking-ci`, reference-reader execution, independent review and HNMF
production admission rules remain unchanged.

**Current result:** protocol hardening only. No fresh pretrained inference,
new externally sourced benchmark gold, independent human evidence-sufficiency
certificate, learned parameter-memory advantage, long-run economic superiority
or production rollout is claimed by this patch.

## Full resource and cost scenario: no double-counting across reuse

`lifecycle_accounting.complete_lifecycle_scenario` computes a genuinely
reusable numerical scenario, not an execution result. It requires the same
price unit (USD), specified retention days and raw physical evidence bytes for
**both** alternatives. Extraction, indexing and training are charged once;
retrieval, reader, tools and diagnoses are multiplied by N; maintenance,
revocation and recovery are charged once for the stated retention window;
raw evidence plus derived snapshots/index bytes incur an explicit
USD-per-GiB-day storage charge:

```text
C(N,D) = C_extract + C_index + C_train
       + N * (C_retrieve + C_reader + C_tools + C_diagnose)
       + C_maintain(D) + C_revoke(D) + C_recover(D)
       + (raw_bytes + derived_bytes) / GiB * D * storage_rate
```

Missing price or costs yield a partial nonnegative lower bound and a `null`
complete total/difference; they are not replaced with zero. The calculation
takes a prospective workload N and a user-supplied retention horizon D,
which are **assumptions**, not observations. Input SHA-256 pins do not certify
real billing, disjoint time/cost allocation, matched quality or source
authorization. Even a numerically cheaper candidate is unqualified until
the independently matched task-success, tools, hardware and operating costs
are observed. Synthetic regression tests check conditional crossover,
double-count avoidance, source retention, explicit unknowns and invalid costs.
