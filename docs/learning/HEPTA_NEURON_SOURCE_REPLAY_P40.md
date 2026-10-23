# P40: physical Neuron source replay and runner correction

**Posture: DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO.**

Stacked on P39 PR #3421 at exact parent
81f2b4b69e70dfcf0d171fd10fd9539025a71b13.
No P39 ancestor or main mutation; no production admission or merge.

## Closed in source: fatal Bash array substitution

The P39 physical model matrix expanded its CLI argument array using
a bare dollar sign as the index. With Bash set -u this raises an arithmetic
subscript error before Python can run. P40 replaces that index with the
full-array @ index and adds a regression asserting the workflow shape.
The actual hosted CPU model execution remains unverified until the exact
P40 commit has terminal successful jobs and retained original output.

## Closed in source: five-arm source/row provenance seam

The existing P39 raw-output auditor checks self-reported row IDs across
five candidate models. Matching reported IDs/digests alone do not prove
they came from the independently pinned UCI News archive.

A second cross-job audit now:
1. Downloads the original pinned UCI archive and checks its fixed SHA256.
2. Replays the deterministic disjoint cohorts with the existing source owner.
3. Recomputes each ordered source-row fingerprint from original per-row SHA256.
4. Rejects per-model identity, label, story, OOD, language, cohort size,
   split, archive or input-row-fingerprint inconsistencies.
5. Retains a separate source-audit JSON artifact, even though no production
   authority is available.

Reproduce using the source scripts in the P40 commit:
- prepare_news_cohorts.py to create archive-verified cohorts;
- replacement_physical_audit.py to audit physical model rows and metrics;
- replacement_source_audit.py with the five raw output directory, pinned
  UCI archive and cohorts to independently bind each claimed source row.

The new contract test covers forged common fingerprints, wrong labels,
row ordering, false groups, altered source-row bytes, wrong publisher
archive, missing arms, malformed results and changed sample budget.
These tests run without external model weights.

## Important remaining blockers

A passing source audit means REVIEW_REQUIRED, not MODEL_VERIFIED.
The source auditor does not see internal model input tensors or attest
that a specific model forward produced the probabilities. The English
historical 2014 UCI title classification set is not an independent
prospective, multilingual, retrieval, or sufficiently powered result.

The original six production stages still require external observations:
- Original complete Laya policy and independently trained Encoder Heads
  on common heldout cohorts with equivalent relevant training budgets.
- Independently measured calibration/OOD/negative transfer on task data.
- Physical target-host 64/256/1024/4096 Cell fan-out, actual active
  counts, CPU/GPU/RSS/energy/load and raw p95/p99 latency.
- Exact signed Artifact CAS/migration/CNS route/fence/crash reconciliation,
  rollback, and old-generation Final-use denial at the real owner.
- Terminal exact-HEAD physical CPU, blocking-ci, architecture, security,
  and independent operator review before model/Cell Split promotion.

Synthetic success, self-supplied SHA256 and an old/queued/cancelled
workflow are not real production witnesses. All six production blockers
remain OPEN. This change grants no extra Cell capabilities, model
selection, memory writes or NDU decision authority.

## Arctic pinned GTE CPU compatibility profile

The pinned Snowflake Arctic m-v2.0 publisher config enables memory-efficient
attention and unpadding; the custom GTE source can require xFormers when those
flags are enabled. The physical worker uses a CPU-only PyTorch environment
without xFormers. P40 now loads the publisher config, explicitly checks both
fields are recognized booleans or true/false strings, disables both flags for
the CPU probe, verifies they remain disabled after AutoModel load, and reports
the original values in the measured output.

This is an explicit distinct runtime profile. It neither patches published
checkpoint/config bytes nor claims the resulting CPU profile has identical
numerics, throughput or production support. Transformers v5 compatibility
of the external pinned modeling source still requires real exact-HEAD
forward execution evidence and can fail closed. Do not credit synthetic
flag tests as original-weight CPU inference.
