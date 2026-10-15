# R22 executed certificate scaling and retrospective model rescoring

The protocol was pushed BEFORE the six R22 proof efficacy runs at commit 4e6e1eaf418ce8a4717edde80bfb1cd6d0550c5d. All original R21 trained weights remain frozen and all original classifications retained. This is exploratory, not a blind external registration.

| Parameters | Lower bound | Splits (cap 4000) | Strict global regret upper | Qualified <=0.01? | CPU seconds | Peak RSS MB |
|---|---|---:|---:|---|---:|---:|
|2|original|2985|0.00999390815022509|YES|9.879457791|100.67|
|2|centered hybrid|525|0.00990815789711237|YES|10.315560842|99.23|
|3|original|4000|0.04560924840912149|NO|24.439338120|102.11|
|3|centered hybrid|4000|0.01561546004374158|NO|98.411399061|101.08|
|4|original|4000|0.13207665196851925|NO|14.185660706|101.72|
|4|centered hybrid|4000|0.13046634747346850|NO|122.094141882|101.98|

All bounds use the SAME original R21 literal rational candidates, exact known two-step positive-risk law, 0.01 threshold and fixed 4,000-node maximum. W3 and W4 pilot candidates still FAIL at the original 0.01 gate. Across the six proof runs, summed CPU=279.325558402 sec. The hybrid lower is never weaker at the same box, but per-box gradient work increases CPU; 2-param split count reduces 82.4% without CPU improvement, and W4 barely gains in bound at about 8.6x cost.

**Retrospective R21 exact binary64 readout (NO new fits):** all 120 prior sealed weights reconstructed from their immutable Git IEEE754 hex tensors and individually cross-checked against the original R21 run reports. Historical R21 accepted 20/120: W2 20/40, W3 0/40, W4 0/40. The stronger proof certifies 39/120: W2 20/40, W3 19/40, W4 0/40. All 19 new proof certifications are distinct W3 frozen fitted endpoints and are NOT changed historical R21 statuses, better trained models or new experimental runs. W3 19/40 by method: Adam 4/8, BFGS 4/8, L-BFGS-B 5/8, explicit trust-exact 3/8, standard-AD trust-exact 3/8. **81 of 120 remain unqualified.** W3's frozen pilot candidate (regret bound .01561546) still does not qualify.

Independent read-only audit checked all SIX complete partition trees, all 19,510 rational splits, all retained fronts/pruning predicates, complete SHA256-verified original R21 1,120-member content archive and all 120 original final weight/report hashes; exact record replay maximum difference 0.0. Audit CPU222.14777468 sec in addition to proof CPU. A second Git-only replay independently reconstructs all 120 tensors from inherited Git WEIGHTS_HEX.csv without requiring original ZIP.

**37 distinct tests pass, zero skips:** 12 new mathematical/75-digit independent derivative/continued fraction tests, 18 unchanged R21 mathematical regression tests and 7 real-file tamper tests in python -O. One first audit launch failed before verification due a pre-created output folder; failure log retained and clean execution rerun without changing any proof or model. No source-slice FLOP/GPU/energy/hardware attestation, project-cloud or production adoption claim. No main, CURRENT, native contract or selected-model changes. Hosted/global CI status remains separate from these local facts.

Full source and proof/frontier JSONL, machine-readable classifications, all negative runs and verified checksum manifests are in the companion conversation ZIP. R21's full original binary weight/checkpoint ZIP remains a separate previously delivered artifact; Git R21 parent stores each original IEEE754 final weight exactly.
