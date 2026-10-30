# Final-serving-law alignment: fixed paired RGB A/N training study

Prior support conditioning regressed keep axes. Semantic probability transport
fixed that as a serving invariant and improved actual finite RGB pixel MSE. None
of those zero-update studies established training benefit. This NEW experiment
tests a distinct mismatch: raw latent-outcome training versus the final served
semantic law. Do not revisit failed encoder splitting or frozen-text families.

For fixed observed semantic maps f,g and original reward R, use
R'(i,j)=R(f(i),g(j)). The original expectation and entropic certainty equivalent
under p*q and R' exactly equal those under transported marginals and R. Reuse
the unchanged original A/N gradient routine; no STE, custom clip or new utility.
The aligned supervised anchor is minus half the sum of log FINAL probabilities
of the true decoded text/image semantics. Its pullback sums all source candidates
that map to that target; no epsilon for an unreachable/zero-mass target.
All-keep makes the utility pullback identity for any decoded semantic map.
The aligned anchor also equals the raw latent-label anchor only when observed
text/image semantic maps are identity; with a decoder permutation it correctly
supervises observed semantics instead. Fully specified commands have zero aligned
gradient because serving is already fixed. This latter reduction is structural,
not model competence or an uncharged optimizer shortcut.

## Frozen useful work, controls and accounting

Two same supervised inference bases,seeds11/23; four profiles per seed:
raw/additive,raw/NDU,aligned/additive,aligned/NDU. Same shared encoder and heads,
learned decoder frozen, fresh sparse Adam moments via the original clone routine.
Exactly300 updates/profile,batch64,lr.003,anchor.2,rho1.5. These are the earlier
RGB recipe's fixed values, not tuned on this study. Use seed+9000's original
row draw then full/low coin, precompute all300 batches before training, reuse
identical batches across four arms. The same read-only extra base forward and
both raw/aligned anchors plus all four A/N utility branches run in every arm.
No branch is dropped from measured work just because its result is not selected.

Raw/additive and raw/NDU MUST exactly reproduce the four previously frozen
joint-control final tensor digests. Mismatch is terminal failure, not a reason
to change rounding, tolerance, batch order or select another checkpoint. Every
model gets300 updates; all8 finals are frozen BEFORE validation generation.
No new model checkpoint is saved, no TEST split requested, no original digit data.

Generate original synthetic train260groups/1560rows and reused validation
86groups/516rows, both full/low channels. This is exploratory reused validation,
not new held-out confirmation. Every model is evaluated under the SAME semantic
transport serving operator; compare training objectives, not differing services.
Report baseline bases and all8 finals, full/partial command populations and both
channels. Partial population is fixed312 rows with1/2 set words; full commands'
structural success cannot rescue the primary training claim.

## Prespecified primary gate

On macro-average full/low PARTIAL-command metrics, BOTH seeds must pass BOTH:
aligned/NDU minus raw/NDU (serving-alignment contribution), and aligned/NDU
minus aligned/additive (NDU increment). Each contrast needs:
- conditional CE at fixed rho1.5 gain >=.005;
- text correct mass,greedy text accuracy and decoded joint success no lower
  than comparator minus1e-10;
- actual learned-pixel MSE no higher than comparator plus1e-10.
This retains the prior RGB five-component rule with an explicit numerical
tolerance; no pooling, seed/model selection or threshold relaxation. Report raw
NDU−additive and aligned−raw additive as descriptive controls, not rescue gates.

Seven literal qualification tests precede any model loading: exact transported
value equality for A/N; centered full-objective logit derivatives; exact all-keep
raw parity under identity semantics; fully specified zero gradient; no-target-mass rejection; schema/map
rejection; input immutability. Training raw digest parity is an additional check.

One completely waited child,20CPU/90wall/512MiB/4MiB per file,CPU0/one thread,
same NEW synthetic-only shared EX lock. Includes tests/imports/two restores,
two frozen decoder observations,eight clones,2400 updates,7220 forward batches,
471120 forward rows,20 scalar/vector serving parity checks,all metrics and exit.
No automatic retry,limits expansion or repair-and-rerun. Complete child cost is
reported; per-arm prefixes are diagnostic, not a substitute for whole cost.
Prior base-preparation costs, source/review and supervisor final tail remain
additional/not zero. Equal useful updates and caps are NOT equal actual total
spend; no original digit recovery, old-budget reacceptance or deployment claim.
