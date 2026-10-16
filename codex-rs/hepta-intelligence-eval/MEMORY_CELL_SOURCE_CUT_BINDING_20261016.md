# MemoryCell — prospective source-cut ↔ Reader execution binding (2026-10-16)

**Research only — DENY_ALL.** This change connects the previously independent
source-family admission and twelve-arm Reader controls. It does **not** perform
new neural inference or certify independent source capture, unseen tasks,
human evidence sufficiency, semantic citation entailment, production recovery
or superior parameter memory.

## Original failure mode repaired

`prospective_family_gate.admission` could accept one source cut while
`four_stage_evidence.prospective_guard` independently accepted a different
evaluation ledger. Both would pass despite substituted question IDs,
source families, task kinds, candidate pools or parameter snapshots.

`scripts/memory_cell/paired_source_cut.py` now demands:
- All test-source IDs appear **exactly once** in the evaluation plan; no
  omitted/extra tasks, including failed/abstained attempts.
- Each case matches its registered family, task kind, SHA-256 of the question,
  frozen candidate-pool hash, frozen policy and knowledge snapshot hashes,
  source freeze timestamp and planned task reveal timestamp.
- The entire plan and each of its 12 arms per task bind to the same canonical
  source-cut SHA-256; every attempt also binds its task's original source
  SHA-256.
- The original gates still enforce distinct train/select/test source roots and
  source content digests, unchanged Reader/token/tool/template budgets,
  identical reference evidence, permitted program receipt checks, and
  all-planned correctness denominators.
- File-input execution checks externally provided original-byte SHA-256 pins,
  duplicate JSON keys, non-finite values, file sizes and symlinks; output
  cannot overwrite earlier receipts.

The source cut requires at least four distinct test-family roots and
new-fact, updated-fact, composition and program task strata. These are
**structural** constraints, not statistical independence, genuine future
observation or proof that a label-blind examiner actually held the data.

## Reproduction

From a complete repository checkout:

```sh
PYTHONPATH=scripts/memory_cell python3 -m unittest discover \
  -s scripts/memory_cell -p 'test_prospective_family_gate.py' -v
PYTHONPATH=scripts/memory_cell python3 -m unittest discover \
  -s scripts/memory_cell -p 'test_four_stage_evidence.py' -v
PYTHONPATH=scripts/memory_cell python3 -m unittest discover \
  -s scripts/memory_cell -p 'test_paired_source_cut.py' -v
```

For independently precommitted **original JSON files**, pass the actual
on-disk SHA-256 values as separate, externally retained pins:

```sh
python3 scripts/memory_cell/paired_source_cut.py \
  --source-cut CUT.json --source-cut-sha256 CUT_FILE_SHA256 \
  --plan PLAN.json --plan-sha256 PLAN_FILE_SHA256 \
  --attempts ATTEMPTS.json --attempts-sha256 ATTEMPTS_FILE_SHA256 \
  --output NEW_SOURCE_BOUND_AUDIT.json
```

The `plan.source_cut_sha256` field is the canonical deterministic JSON digest
computed by `paired_source_cut.canonical_sha`; this differs from the original
file-byte hash when JSON whitespace/key order differs. Do not pass a generated
hash as if it were an independent archival signature. Trust, time, consent and
true source-family independence must be reviewed by external owners.

In a restricted isolated container, 14 of the 15 targeted Python tests ran
and passed; the remaining full `four_stage_evidence` integration required
the full repository checkout. The dedicated GitHub Actions job now runs all
three suites, and missing integration imports **must fail on the hosted runner**.
Do not substitute a queued or canceled job for a completed exact-head check.

## Scientific go/no-go

This work makes it harder to attribute a changed Reader, hidden scope answer,
post-task model update or missing attempt to a learned Cell. It does not
demonstrate any model success. Actual prospective independent source families
and executed real-project repairs with equal tool rights to strong Hybrid RAG
must still precede parameter-memory claims. Missing independent human
semantic review, real future windows and full maintenance/revocation/recovery
cost remain **unknown**, not zero. No production MemoryCell promotion,
FinalUse or selected-model activation is authorized.
