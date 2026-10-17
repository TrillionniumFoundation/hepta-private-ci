# Stem V5 — pinned original V3-neural / V4-lexical paired evaluation

**DRAFT · RESEARCH_ONLY · DENY_ALL · HOLD_NO_GO · NO MAIN MERGE · NO FINALUSE · NO PHYSICAL CELL SPLIT.**

Parent: #2610 / `88aa3e6be99feee305bb308078240ed04820268e`. Original V3
#2590 `bc8e83331294d43daf122224941e967bd29af15d` and V1/V2 evidence
are immutable; V5 is an additive research-only exact-source reviewer.

## Real inputs verified (not model selection)

`ORIGINAL_PAIR_V5.json` pins *five actual original GitHub Actions complete ZIPs*
by artifact ID, run ID, full archive SHA-256 and inner JSON SHA-256: V3 publisher
source, V4 publisher source, and the independently executed original pretrained
Granite47, Granite97 and mmBERT140 CPU 32-case prediction receipts. Original V3
and V4 source JSONs are byte-identical; all three original 100-update Head
initializations are identical. Original model execution completed; the separate V3 late-label reviewer
remains pending as of V5 authoring. An independent V5 reviewer is not a
substitute for missing V3/V4 canonical review receipts.

The sixth exact original V4 cheap lexical prediction ZIP **completed while V5
was being authored**: Action #39007227909, artifact #12094477972. Its entire
ZIP SHA-256 and inner JSON SHA-256 are now frozen in the committed manifest.
Missing, altered or substituted ZIPs remain fail-closed. No operator/AI can
supply a self-declared unregistered digest to claim paired review completion.
The V5 paired review is physically executable after commit, but **success must
be established from its actual GitHub Actions run**; schema closure does not
constitute an independent original score receipt.

## Implementation and statistical controls

- `download_original_zip_v5.py` fetches only registered same-repo Actions
  artifacts. Checks artifact metadata run ID/expiry/digest, refuses ZIP redirects
  to unexpected domains and **does not forward GitHub credentials** to the
  external archive store. Exact outer ZIP SHA verified before writing.
- `paired_review_v5.py` verifies inner JSON bytes and checksum sidecars, source
  identity, all 32 paired prelabel cases, same initialized Head and model
  materials. Original no-gold disagreement is reported with no false accuracy.
- After the sixth immutable ZIP lock exists, a new hosted independent postseal
  reviewer acquires original publisher TRAIN/TEST CSV *with original byte hashes*;
  invokes existing independent V3 and V4 reviewers to reconstruct all labels
  and **numerically replay every cheap baseline probability**. No training
  producer is imported for scoring.
- The **predeclared primary comparisons** are each original pretrained learned
  6,914-scalar gated Head vs the fixed character 3–5-gram train-only centroid;
  report paired correct counts, candidate-only and cheap-only successes,
  two-sided exact McNemar and Holm adjustment over precisely three models.
  Also report the word baseline and own-Encoder centroid as descriptive
  controls, with original multi-class Brier and recorded process costs.
- The earlier V4 exploratory JavaScript baseline replay had **already opened
  the original publisher TEST labels** and reported lexical 25/32 and 27/32
  before V5 was authored. V5 froze its three cross-model contrasts before
  the separate V3 pretrained-model correctness replay, but this is **not
  preregistered label-blind confirmation**: the same-source 32-case cohort
  was already partly inspected. All p-values are exploratory/descriptive,
  irrespective of any nominal or Holm-corrected threshold. Independent new
  publisher families and genuinely future-heldout windows are still required.

`hepta-stem-original-paired-v5.yml` runs exact-head normal and `python -O`
source regression on pull requests. A separate same-repo push job checks all
five **original ZIPs without opening test labels**. The final fully paired job
activates on a V5 push/dispatch only because all six exact original ZIP locks
are now committed. A queued or skipped final job is not a successful physical
evaluation.

## Local/CI reproducibility

```sh
python -m unittest discover -s qualification/stem-optimal-v5 -p 'test_*.py' -v
python -O -m unittest discover -s qualification/stem-optimal-v5 -p 'test_*.py' -v
python -m py_compile qualification/stem-optimal-v5/*.py
```

Before a final label-bearing run, the independent V3 and V4 original reviewers
must have genuinely run; matching PIN/ZIP and sample IDs do not by themselves
prove real-world confidence, temporal retention, NDU utility, CPU/RSS parity,
p95/p99, energy or signed FinalUse. Remain **HOLD_NO_GO / DENY_ALL** until
independent source families, frozen no-change and legacy 421M full-lifecycle
comparison, future windows, negative transfer and target-host acceptance close.
