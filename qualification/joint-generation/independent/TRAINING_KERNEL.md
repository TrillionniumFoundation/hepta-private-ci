# Folded mixed adaptation kernel v1

Development proof only. No experiment data, TRAIN/validation split, qualification,
held-out evaluation, timing benchmark, or base-checkpoint rebuilding was executed
for this implementation.

The optional kernel is confined to continued candidate/refinement adaptation.
Shared 500-step content pretraining and 300-step decoder adaptation retain the
existing dense entry point. `CachedObjective.step(..., full_mask=None)` preserves
the dense expressions and work inventory. All-full explicit masks also retain
the original floating expressions, with the executed mask scans additionally
accounted for.

The parameter map remains encoder[202,h]. Low rows are the existing expanded
2x2 blocks, and exact replica validation rejects inconsistent rows. Each mixed
step folds the current encoder's four pixel weights into a 58-feature low-view
encoder, performs full/low GEMMs, and scatters hidden rows into their original
order. The common content heads, objectives, hidden pullback, and Adam run once.
Low encoder gradients are expanded to the original 202-feature parameter map,
then combined with full-view gradients. The decoder and RNG are untouched.

Mixed floating reduction order changes. This is equality over real arithmetic,
not a bitwise promise for mixed rows. Default dense/all-full paths are bitwise.
Predeclared hand-test tolerances are: preactivation/hidden/probabilities/loss
rtol 2e-12, atol 4e-12; six gradients rtol 2e-11, atol 2e-12; Adam moments rtol
2e-10, atol 2e-12; one-step parameters rtol/atol 2e-8; eight-step parameters
rtol/atol 2e-7. Parameter tolerances allow epsilon-sensitive near-zero Adam
updates while the gradient and moment checks remain stricter. Decoder, clocks,
logical calls, and geometry counts are exact. Tolerances were not changed after
test execution.

Public work API:

`mixed_step_work(dimensions, arm, n, low_rows=None)` returns a flat inventory.
An integer low_rows is actual work; None is a componentwise reservation envelope
only and must never be charged. Relative to dense work, actual work adds n mask
negations, 2n index-scan comparisons, 144*low_rows block comparisons, 144*h fold
additions if there are low rows, and 202*h gradient-merge additions if both views
occur. It subtracts 288*h*low_rows MACs, half forward and half backward. The
envelope keeps dense MACs plus maximal extra comparisons and scalar work. Any
positive operator prices therefore admit all masks without RNG-dependent draws.
Gather, scatter, repeat, and concatenation memory traffic remain in actual CPU
cost rather than being assigned invented arithmetic work.

The driver must reserve before drawing indices or masks and retain its original
idx draw, full-view mask draw, and np.where input construction. Candidate actual
objective_step_units are ledger deltas, and forecast must use those actual units
instead of updates multiplied by the envelope. Shared base training never opts
in. Geometry counters are encoder_full_rows, encoder_low_rows,
encoder_fold_builds, and encoder_gradient_merges; logical forward/backward each
remain one per update.

Validation: five new bounded hand-array tests passed with the fixed tolerances;
25 existing learning/accounting/lazy-Adam tests passed. Tests use n=1/5/64 and
h=1/4/32 for encoder proofs, all four objectives for one/eight updates, fresh
folds, exact all-full behavior, clipping at norms 0.25/5/20, work envelopes,
invalid masks/blocks, and atomic cap refusal. Driver owner separately reported
one four-row NDU dispatcher/ledger hand check passing. No claim is made about
actual content benefit, whole-run speed, readiness, or qualification.
