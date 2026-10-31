# Completed-run paired evaluation through the existing owner

`paired_fixture.py` and the `generation_paired_evaluation` integration target
exercise the actual `ProductEvaluationRunnerV1::evaluate_paired_profile` and
the same `FencedFinalHoldoutOwnerV1` CAS/journal used by the existing OPE profile.
They import two policies' different, actually observed outcomes. They do not
invent a propensity, a cross-fit fold, a common chosen action, or a shared final
outcome to fit the OPE API.

## Fixed engineering comparison

The exporter always selects `terminal_entropic_ndu` training,
`risk_aware_recursive` as candidate, `fixed_dev_tuned` as baseline, all future
source pairs and all registered seeds, and the largest registered budget.
Selection uses completed protocol metadata. The same entry point supports the
current CI smoke or full run without depending on a historical private path.
The first local execution imports full-002: 60 source pairs × 3 fixed seeds × 2
arms, at budget 128, for 360 actual rows. These are previously observed data
replayed for engineering, not a prospectively frozen new evaluation.

Before export, retain the completed run's `rows.jsonl` SHA-256 in an independent
completion receipt. Its row self-hashes and summary alone cannot authenticate
the old log: the summary does not contain a whole-row-file digest. Pass the
retained hash to both exporter and native importer. An old summary pin can also
be required explicitly.

```sh
python -m experiments.multimodal_output_portfolio.v6.paired_fixture \
  "$COMPLETED_RUN" "$PAIRED_FIXTURE" --cache "$MNIST_CACHE" \
  --expected-rows-sha256 "$ORIGINAL_ROWS_SHA256" \
  --expected-summary "$ORIGINAL_CANONICAL_SUMMARY_SHA256"

export HEPTA_PAIRED_OWNER_FIXTURE="$PAIRED_FIXTURE"
export HEPTA_PAIRED_OWNER_FIXTURE_SHA256="$EXPORTED_FIXTURE_SHA256"
export HEPTA_PAIRED_SOURCE_ROWS_SHA256="$ORIGINAL_ROWS_SHA256"
# From codex-rs, using the repository's test wrapper:
just test --locked -p codex-hepta-agentd --test generation_paired_evaluation \
  --run-ignored all
```

The input recipe binds the original source archives, historical `data.py` and
`run.py` bytes, split/random seeds, pair offsets, corruptions, and runtime
environment. The exporter independently reconstructs source deduplication,
conflict exclusion and test split ordering, then checks each source-to-case
mapping. It does not materialize new Torch observations or compare learned
latents as though they were public inputs. Whole checkpoint and forecast files
bind model/configuration identity for each fixed seed.

The importer verifies the completed status→summary→protocol chain, full original
execution census, selected original row receipts, emitted UTF-8/PNG files,
source/context/version mapping, and distinct Audit-B and Reward-A artifact
identities. The metric arithmetic and binary64-to-Q32 rounding are recomputed.
No output is repaired and no model or observer is executed again.

## Actual owner order and recovery

Only manifest metadata reaches the evaluation runner before consumption. The
local data provider escrows the verified old rows and checks that the matching
consumption record exists in the actual locked CAS store before release. The
owner then enforces the full pair×seed×arm census and derives bounded loss and
factual-error differences. Existing Generator, Observer and Evaluator signature
verification is used with three explicitly local fixture roles/controllers.

The old run had a combined row receipt, not a separately signed original Audit
observation. This adapter creates a **posthoc Audit observation witness** over
that original row receipt and Audit-B file identity. It does not claim that
fixture keys authenticate an external evaluator or that scoring happened now.

A real file sink fsyncs a stable signed result. After dropping the first owner,
the test reopens the locked journal, takes a new fence, re-derives the same typed
evaluation and checks its stable signed bytes against the persisted file.
First-use/retry transport fields are excluded from this stable publication
encoding. The implementation does not deserialize or trust a Debug string as an
evaluation receipt. An altered real loss is rejected before evaluator signing;
successful recovery and retries leave exactly one consumption record.

## What the result means

For each source pair, the owner averages candidate-minus-baseline differences
over fixed seeds. The independent-case count is the number of original source
pairs. Its outward Q32 mean and conservative integer Hoeffding bounds require
independent source-case draws and condition on frozen models. This engineering
profile uses family size 64 for loss and factual-error comparisons; it is a
different reporting profile from the original run's registered family of 32.
Neither profile establishes coverage over training-seed variation or empirical
tail loss. Previously observed replay is not new confirmatory evidence.

The first actual full-002 replay had both required modalities in all 180
executions per arm. Candidate-minus-baseline mean loss was about +0.00544652 and
factual error about +0.01666667; both conservative intervals included zero and
the descriptive thresholds failed. The sealed plan and published receipt
always grant `DENY_ALL`, even if descriptive thresholds were favorable. This
application verifies owner execution and evidence custody. It does not make a
next-version qualification or promotion decision available.
