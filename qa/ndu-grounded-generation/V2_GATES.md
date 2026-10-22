# Hepta NDU: v2 evidence firewall and fail-closed readiness screen

**Scope:** This is a post-hoc, model-free engineering follow-up to the already
completed **negative** v1 grounded-generation pilot (research PR #3213). It
neither changes the frozen `protocol.json`, evaluation denominators or v1
scores, nor constitutes a second multimodal model experiment. The original
831-file archive and its score replay remain authoritative. This audit pins its
original report, protocol and 768-row journal SHA256 receipts; supplying a
mutated replacement fails closed.

## What is checked now

`capability_gate.py` consumes the **full raw 768-row journal**, original v1
protocol and aggregate report from the unchanged evidence ZIP. It first checks the original pinned SHA256 identities of those three files. It recomputes
and checks per-method episodes, original-source-group count, quality, severe
rate, coverage, wall time, and fractional-boundary CVaR. It rejects incomplete
method rosters, non-finite outcomes, incompatible source identities,
repeated method/seed/task records and any aggregate/journal mismatch.

It also audits distinct capability claims rather than trusting an aggregate
`engineering_pass` flag. Specifically, it inspects actual NDU action counts
from the recorded trajectory (not configured checkpoint capacity), the frozen
development risk weight, paired covariance-ablation outcomes, whether the
text/pixel generators are independent, NDU versus the real best-of-2 cost and
coverage measurements, source/seed count, and the original empirical frontier.
V1-independent text/pixel generation, per-Cell counterfactuals, a new holdout,
and continuous FBSDE **cannot be established** by editing v1 metadata. They
remain open on this audit by design.

The **descriptive, post-hoc** cost screen tests a 5% relative mean-wall band,
identical mean coverage, and at least 95% of per-source/seed paired attempts
having wall times within 5% and equal valid/invalid coverage. These thresholds
are not the frozen v1 protocol, not a cost-balanced randomized experiment,
and not a confidence interval or statistical equivalence test. Actual hardware
work, FLOPs, energy, and uncertainty remain unbalanced/unidentified.

With the **verified existing v1 archive**, the result is:

| Audit item | Computed result | Decision |
| --- | --- | --- |
| Full journal/aggregate reconciliation | 768 records, 64 task-seed groups, 7 aggregate fields reconciled | **PASS: engineering integrity only** |
| 8–16 actually exercised NDU controls | 2 sources with 0; 47 with 2; 15 with 3 | OPEN |
| Covariance causal effect | Dev selected `lambda=0`; 62 jointly completed covariance-ablation pairs, 0 changed outputs | OPEN |
| Learned independent text + pixels | V1 has a text template and overlaid original image | OPEN |
| Independent one-Cell-at-a-time counterfactuals | Not executed in v1 | OPEN |
| Matched realized cost and coverage | Mean NDU wall time +23.95% versus best-of-2; NDU coverage −3.125 pp; 18/64 paired sources within ±5% and equal coverage | OPEN |
| Multiple holdout seeds and power | One seed, 64 original test sources | OPEN |
| Confirmed quality-risk-cost frontier improvement | NDU is outside the descriptive nondominated set | OPEN |
| Untouched v2 evaluation cohort | No new v2 cohort has been executed | OPEN |
| Complete state / continuous FBSDE | Action-only discrete approximation, no convergence evidence | OPEN |

See `v1-retrospective-gates.json` alongside this document for **actual machine
results and the exact original evidence file hashes**. This receipt is a
supplemental audit, **not** a replacement for v1's frozen score report.

## Source-cohort firewall (for a future v2 study)

`cohort_firewall.py` requires a candidate four-split manifest and **both**
original historical source rosters: the 256-source v1 cohort in its original
128/32/32/64 split sizes and the 384-image exclusions wrapper. The CLI refuses
missing history and requires a raw SHA256 pin for each history file, supplied
from an independently controlled record. Computing a pin from untrusted data
at run time is **not independent authentication**; even a matching caller pin
cannot prove entity independence, pretraining decontamination, or signer custody. It accepts existing
`hepta.grounded-cohort.v1` manifests and the 384-image
`hepta.ndu.historical-exclusions.v1` wrapper. It fails closed if any candidate
source collides with another candidate or historical source by:

- full source ID;
- exact original-image SHA256;
- decoded RGB SHA256;
- 64-bit perceptual dHash with Hamming distance at most four.

Missing fields, unsupported schemas, inconsistent historical image/source IDs,
missing source groups, invalid counts, missing pins, altered pinned historical
bytes and incomplete historical rosters cause explicit nonzero exits. Manifest
bytes are capped at 16 MiB; candidate sources at 2,048, historical sources at
4,096, pairwise comparisons at 2,000,000 and recorded violations at 4,096.
Resource overruns yield a typed denial, never a partial PASS. Direct library
calls without `require_complete_history=True` are *diagnostics only*. It verifies
**observable image identities only**: real-world entity identity and
foundation-model pretraining overlap remain outside what hashes can prove.

A required negative control was run with the *v1 candidate manifest itself*
and both historical data sources. All **256/256** reused v1 sources were
caught, with no internal false assumption that test data could be recycled.
The 384-image exclusions were also read and checked. That negative-control
result is not a valid v2 candidate cohort.

## Reproduction

Run from a checkout of the stacked gate PR, after unpacking the original
`hepta-ndu-evidence-v1-20261022.zip` to `/path/to/v1`:

```bash
python -m unittest discover -s qa/ndu-grounded-generation -p 'test_cohort_firewall.py' -v
python -m unittest discover -s qa/ndu-grounded-generation -p 'test_capability_gate.py' -v
python qa/ndu-grounded-generation/capability_gate.py \
  --bundle-root /path/to/v1/hepta-ndu-evidence-v1-20261022 \
  --output /tmp/v1-audit.json
# EXPECT EXIT STATUS 2: nine capability blockers remain OPEN, not a test failure.
python qa/ndu-grounded-generation/cohort_firewall.py \
  --candidate /path/to/a/new/v2/cohort/manifest.json \
  --historical /path/to/v1/hepta-ndu-evidence-v1-20261022/cohort/manifest.json \
  --historical qa/ndu-grounded-generation/historical_exclusions.json \
  --historical-sha256 "$TRUSTED_V1_MANIFEST_SHA256" \
  --historical-sha256 "$TRUSTED_384_EXCLUSIONS_SHA256" \
  --output /tmp/v2-cohort-firewall.json
# EXPECT EXIT STATUS 0 only if identity overlap is absent.
```

These 20 standard-library tests require no model weights or downloading.
The trusted SHA256 variables must be populated by the independent evidence
owner, not taken from the candidate or a self-asserted receipt.

Independent integrity replay of the original immutable evidence remains a
separate prerequisite:

```bash
python /path/to/v1/hepta-ndu-evidence-v1-20261022/replay_evidence.py \
  --bundle-root /path/to/v1/hepta-ndu-evidence-v1-20261022 \
  --output /tmp/v1-portable-replay.json
```

A replay PASS does not automatically turn v2 scientific gates green.

## Actual work required for scientifically valid v2 closure

1. **Do not reuse v1 dev/calibration/test samples**. Freeze a newly selected
   train/dev/calibration/test roster and run the firewall before any model or
   policy output is inspected. Record the reference isolation, any historical
   exclusions and remaining entity/pretraining-contamination unknowns.
2. **Use an actual long generation task**, on which all completed eligible
   episodes execute 8–16 real, measured decision checkpoints. Add leave-one-Cell
   interventions and matched seeds. Do not count configured maximum capacity.
3. **Generate real language and real visual pixels independently** (possibly
   sharing an initial plan), with distinct traces/artifacts and independent
   semantic and visual scorers. A template plus original-image overlay does not
   close this gate. A model-free provenance flag is not proof of generation.
4. **Estimate terminal-output error covariance** using real independent
   validation outcomes and out-of-fold predictions. Demonstrate covariance's
   *causal* contribution against covariance-disabled controls with a nonzero
   development-selected penalty; avoid test-set hyperparameter selection.
5. **Pre-register a matched actual-compute and coverage experiment**, not just
   a shared cap. Charge failed/cancelled attempts, extra candidates and
   verifiers; measure concurrency and hard deadline compliance separately.
6. **Run multiple seeds and a powered independent confirmatory cohort**;
   predefine effect size, paired source-cluster uncertainty, multiple-comparison
   control, and a non-inferiority margin for cost and coverage. Test outcomes
   must not be used to rewrite this protocol.
7. **Keep continuous FBSDE and Merton claims separate**. They require an
   explicit state process, filtration, noise model, admissible controls,
   well-posed terminal condition and convergence/optimality evidence. A
   discrete action-basis BSDE fit is not sufficient.

**Important:** Only the evidence-integrity blocker addressed by this
additional script is closed. The nine scientific blockers remain open. No
claim is made that a configured cloud project was used for a new model run;
these offline files were checked locally and can be executed in CI. The
original v1 results and the subsequent overlay-geometry audit remain
untouched.
