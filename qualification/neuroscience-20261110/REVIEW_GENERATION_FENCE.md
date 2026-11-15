# HPCA seven-lineage review-generation fence — qualification only (HOLD)

## Parent and source identity

- Parent: PR #5999 HEAD `1c31c59394eb43658786bdf1c99f0978e6a93536` (unmerged, stacked on prior neuroscience convergence).
- Original `study.py` Git blob from exact parent: `634f5a7c5a7893d96d809d9747226e7845455032`.
- Source-under-test: modified `study.py` SHA-256 `40d8a084f22cf9b6a27f36dd6d71825ca383ef6b1518f8a6bb66f8c234c5d1b3`.
- New regression source SHA-256 `7452b070dc4753fd7bf2d2da5f44510a2e052581746c6e26924e45051d2714c0`.
- Runtime: HeptaRuntime `ai395`, native Python standard library, deterministic constructed clock events. No external model, GPU, training dataset, sampling seeds, independent evaluator or real StageOwner trace involved.

## Reproduced defect

With PERC gap 16 and candidate generation 5, events at sequences 1 and 17 both satisfied the clock and evidence gates. The old shadow `cadence_gate` returned **REVIEW_CANDIDATE twice for the same lineage/generation**. As a result, clock spacing alone could be mistaken for a new candidate review. A similar retry after a prior evidence-denied event becomes valid only if that generation has not already entered review.

## Fix and negative controls

Keep a per-lineage **last reviewed generation** separate from the already existing monotone observed-generation and observed-sequence frontiers. A candidate may be reviewed only once per lineage/generation. Repeated review is `NO_UPDATE` with `duplicate_reviewed_generation`; even a denied duplicate that satisfies the clock gap still consumes its normal clock slot. Previously evidence-denied candidates can receive their *first* review after a new independent evaluation, and different lineages remain independent.

Existing lineage clocks, retrograde-generation denial, sparse-feedback treatment and `DENY_ALL` are unchanged. No production Owner, model weights, deployment, promotion or adopt path was modified.

## Actual RED/GREEN evidence and scope

- Parent code, newly written 4 directed regression cases: **3 failures / 4 tests**, expected failure. See `REVIEW_GENERATION_RED.log`. Wall 0.04 sec; user CPU 0.03 sec; peak RSS 23,044 KiB.
- Patched code plus original 13 existing clock/sparse tests: **17/17 pass**. See `REVIEW_GENERATION_GREEN.log`. Wall 0.03 sec; user CPU 0.03 sec; peak RSS 23,836 KiB.
- Test source and exact parent originally obtained through GitHub connector. Git objects checked locally after shallow filtered fetch of exact parent. Hosted CI for this new candidate must be inspected separately; passing local tests cannot imply overall CI or science qualification.

**HOLD_NO_GO / DENY_ALL**. This is a constructed-input shadow-contract defect. It does not close model training, Q24 real owner attestation, frozen independent future B, Adopt/NoUpdate to different C, cold recovery, full-cost matched 2×2 Core×NDU or neuroscience efficacy gates.
