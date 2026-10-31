# Control follow-up: same-source quality and durable-request cost

This experiment addresses the previous mismatch between a positive 512-source
quality result and the small 16-source timing cohort whose quality increment was
not established. It uses the same new sources for actual serial generation,
quality, wall latency, CPU time, and price sensitivity. It does not reinterpret
the earlier null or unfavorable results.

## Implemented candidates

1. **Exact cached feedback.** Keep the original feedback weights and public
   feature definition. Cache the generator draft encoder and public reader's
   draft probabilities only while the actual draft pixels are identical.
   Rebuild latent, caption and budget features every decision. Semantic and
   text-only actions leave pixels unchanged, so repeated visual work can be
   avoided. The original and cached paths, output hashes and ledger identities
   must match in every paired final request. A mismatch blocks inference.
2. **Compact shared conditional value.** Use 384 public generator-state values,
   the 192 actual caption one-hot values, and remaining horizon. A single
   64-wide shared head predicts five positive exponential moments and five
   success probabilities, without any extra CNN. Source-fold H1 predictions
   create H2 targets; the realized best grandchild is never the target. Actions
   must be within .02 of the highest predicted feasible success probability.
   This is a prediction constraint, not a true success guarantee.

The compact candidate is selected per historical generator seed only if its
development proxy CE is within .002 and exact success within .005 of the old
feedback. Otherwise the exact cached candidate is selected. These are fixed
development selection rules. The original generator weights remain unchanged.
The 90-reader-feature contribution, head capacity, success supervision and
source fitting are not individually identified by this candidate comparison.

## Historical development and new final sources

Fit uses the previously accessed forecast_fit pairs [480,736); selection uses
the previously accessed forecast_calibration pairs [448,576). These are openly
reused historical development sources, not new validation. Both full candidate
trees are actually regenerated, saved, reopened and scored with the original
primary observer. The final independent secondary observer is not used to fit
or select the compact policy.

Final test uses registered test pairs [512,768): 256 source pairs / 512 distinct
original image identities, all eight views, two generation scenarios and five
existing NDU generator seeds. SOURCE_ALLOCATION.json binds the original source
manifest, ordered identity hashes, pixel-hash disjointness and historical
metadata access evidence. Original writer identities are unavailable.

Native new calibration [768,1568) and verification [1568,3000) are disjoint
reservations. The root agent's new generator-training experiment may use exactly
the same [512,768) final sources only after all candidates have been frozen.
Shared sources across these studies do not create additional independent N.

## Four actual policies and one frozen selection

Every source/view/scenario/seed runs four actual requests:

- The development-selected strongest of registered fixed, static and one-shot
  references. A one-shot reference receives the same exact feature cache.
- The original feedback with its original feature computation.
- The exact cached feedback.
- The compact feedback.

The preselected candidate aliases its actually executed row for that seed.
There is no new physical request or independent observation for this alias.
All policies retain the same shared-content action rights. The owner generation
stream depends on source case, view, scenario, seed and committed path, never on
policy name. Policy order rotates by matched request-group ordinal.

## Cost and inference

All 81,920 requests include actual chosen generation, online features/decision,
lossless NPZ serialization, media append, fsync, exact readback and hash checks.
The endpoint is durable local output. Resident model load, source preparation,
offline scoring and analysis are separately measured and included in the full
child process receipt. The original action commitment is in-process, not a
crash-durable decision journal. No network-delivery or isolated-host claim is made.

The two primary families use nominal two-sided 97.5% paired source-by-seed
bootstrap intervals (4,000 replicates), with intersection rules:

- Candidate vs strong reference: raw CE gain lower endpoint > 0 and exact
  success lower endpoint >= 0 (zero success margin).
- Candidate vs old feedback: raw CE and success lower endpoints >= -.005,
  and mean wall-cost upper endpoint < 0.

The second family is an explicitly bounded replacement question; it does not
prove exact equivalence for the compact policy. Exact cache equivalence instead
has per-request output/path checks. Five-seed bootstrap coverage is not guaranteed.

Price sensitivity uses the fixed grid 0, .0005, .001, .002, .005, .01, .02, .05
utility per actual millisecond, separately for wall and CPU. For each price,
compute CE(U - price * realized cost), preserving joint quality/cost randomness.
The declared nominal 95% max-deviation bootstrap band covers the finite grid,
not all continuous prices or all project comparisons. No price is asserted to
be the user's calibrated economic value. Entire added development wall/CPU is
reported separately; request-level curves are not full-lifetime economic claims.

Every attempt, failure and outlier is retained. Missing or failed quality blocks
the primary result rather than silently shrinking the census. Reports publish
source, protocol, aggregate evidence and scope; raw media and row data stay local.
