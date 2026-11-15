# HPCA matched-seed cohort / retention audit — 2026-11-11

**HOLD_NO_GO / DENY_ALL.** Stacked on #5942; shadow evidence-integrity
preflight only, with no model training, owner authentication or new task scores.

Two distinct audit failures existed: (1) each seed could supply all four arms
but sample a different family mix or episode count; sign-flip analysis would
then compare incomparable seed populations. (2) the primary routed/shuffled
retention readouts could be complete while scalar/no-eligibility retention was
missing, yet the aggregate displayed a non-null retention figure.

The new gate requires exactly the same family-by-episode-count roster per
seed (different prospectively sampled episode IDs are allowed) and masks the
retention contrast if **any** of the four arms lacks a retention measurement.
Red tests demonstrate both failures in the parent; the complete shadow suite
passes after the patch. Synthetic assertions do not prove exchangeability,
independent evaluation, actual old-task retention, full costs or scientific
superiority. In particular neither producer hashes nor CI certify real Owner
truth or eligibility. Owner-attested A→B→NoUpdate/Adopt→C→cold recovery,
seven-lineage costs, sparse/dense ACT/CTRL, MEM deletion, and Core×NDU 2×2
remain HOLD. No authority or deployment changes.
