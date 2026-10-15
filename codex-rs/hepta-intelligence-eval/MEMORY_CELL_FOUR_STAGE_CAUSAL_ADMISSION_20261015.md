# MemoryCell four-stage causal admission — 2026-10-15

**Research-only; no model success, production approval, or semantic reviewer
signature is created by this change.** This continuation is stacked on
PR #1452 at parent `d60c29b5377193b9ce36a76e02307a42582f3a01`; the parent, not main, is its integration base.

## Observed evidence already present on the parent

- The *original* 40 calibration / 72 evaluation Qwen calls from run
  [38423223376](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38423223376)
  were archived and independently replayed in successful verification
  [38590620658](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38590620658).
  The generating workflow remains **failure** (collector).
- All eight held-out-in-execution but **previously exposed authored development**
  scenarios: ordinary hybrid k=4 solved **3/8**, entity/time projection **8/8**,
  organized evidence **8/8**, no evidence **0/8**; correct answers with full
  *program-declared* public chain in the organized arm **4/8**.
  Organized-minus-entity/time solved **0 additional tasks**. This is not a
  blind independent-source statistical result or semantic entailment validation.
- The prior controlled event study saw Qwen solve **4/8** after a purportedly
  required premise was removed. A deleted premise therefore has **not** been
  demonstrated causally necessary. No independent human-certified sufficient
  evidence reviews are available for the present controlled cohort.
- A parameter-memory win over the strongest same-reader organized control,
  genuine program recovery in a prospective developer population, and deployed
  revocation/retention/TCO are **not established**.

## Added: bounded, original-answer-bound factorial read-only audit

`scripts/memory_cell/memory_trial_admission.py` augments the existing
`factorial_evidence_gate.py`; it does not replace its five-arm/four-condition/
two-reader matrix and does not import a pretrained model or an optimizer.
Required inputs are supplied **separately**:

1. A previously committed plan with `cutoff`, source roots, four task kinds,
   frozen reader identity revisions, prompt template digest, identical tools
   policy, per-case source-write snapshot/timestamps and five arm-specific
   parameter snapshot identities. Every learned state must have a source-only
   training recipe digest and nonzero train steps, frozen before task exposure.
2. A **complete original generation journal** including original answer bytes,
   distinct model call IDs, input evidence digests, source size, model identity,
   source snapshot, parameter state, token costs, failed attempts and program
   execution trace digest. Independently SHA-pin the original bytes externally.
3. Complete scored records, preserving each original answer digest and matching
   trace; no synthetic scored `verified` flag can substitute for original
   generation identity.

The admission checks the fixed matrix, SHA-256 on the raw plan and journal,
duplicate/missing original attempts and call identities, source/answer mutation,
reader/prompt/tool/snapshot drift, source-write-before-task chronology,
total input+output budget, identical evidence for reference reader comparisons,
and knowledge-only denial of raw evidence. For real program tasks, successful
scoring needs a completed tool trace and passing executable tests. The learned
knowledge arm must use the same evidence as deterministic organization for a
valid parameter-benefit contrast; mismatches become an **explicit confound**.

Outputs include matched per-root paired wins/losses/ties, Reader failure
attribution, missing source necessity, and conservative four-stage gates.
A strong reference model can identify a *reader-capacity* gap, never a MemoryCell
gain. A self-claimed `verified` boolean or timestamp is not externally
authenticated by this tool; the report always has
`verified_model_execution_by_independent_runner=false` and
`independent_human_oracle_certified=false`.

## Execution and mandatory exclusions

```sh
export PYTHONPATH=scripts/memory_cell
python3 -m unittest discover -s scripts/memory_cell -p test_factorial_evidence_gate.py -v
python3 -m unittest discover -s scripts/memory_cell -p test_memory_trial_admission.py -v
python3 scripts/memory_cell/memory_trial_admission.py \
  --plan PLAN.json --plan-sha256 EXTERNAL_PLAN_BYTES_SHA256 \
  --original ORIGINAL_MODEL_ANSWERS.json --original-sha256 EXTERNAL_RAW_BYTES_SHA256 \
  --scored SCORED.json --output NEW_REPORT.json
```

Synthetic regression fixtures exist **only** to prove the audit rejects
integrity violations; they are not real Reader experiments. A future generating
workflow must commit and freeze the plan before task exposure and produce a
raw-answer journal with independent reviewer adjudications to obtain a
qualified stage-1 reference ceiling and prospective stage-3 learned gains.

## Cost and production boundary

The inherited per-cell aggregated `cost` observations are **not** legitimate
total-lifecycle cost: extraction/index/model storage may be shared by many
arms, a model-load timer can overlap query timing, and artificial zero-filled
maintenance/revocation estimates are not measured. Full reuse costs must
include raw evidence retention, extraction, indexing, training, N actual
queries, maintenance, revocation, recovery and shared-work allocation;
missing terms are null, not zero. This audit sets `amortized_tco=null`,
`production_qualified=false` and never authorizes Cell scale-out.

Existing `blocking-ci`, Rust/architecture owners, evidence admission,
real-model source pins and production policies are unchanged. Exact current
HEAD checks must complete successfully before anyone proposes merge.
