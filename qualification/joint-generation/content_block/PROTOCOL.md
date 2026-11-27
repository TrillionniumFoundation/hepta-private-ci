# Fixed content block updates: one TRAIN-only registration

This is a newly authorized R&D diagnostic on the isolated branch
`research/content-control-budget-20261023`, descending from verified source
`0aca16714390ca045a53cece9644992b7990fc9c`. No old/new formal test is read,
constructed, evaluated or rerun. CORE/r2 boundaries and the rejected refiner
remain unchanged. TRAIN search is exploratory, not a formal alpha spend.

## Prior evidence and one falsifiable change

The saved dense A-H difference is+.00264133 on selected TRAIN inner validation,
positive for all three seeds even with fewer updates. The rejected refiner
cannot recover dense A's advantage even with a free label oracle. Dense A has
CPU headroom but is near the12B operator ceiling. This supports testing actual
encoder-backprop savings in the original content model, not more refiner routing.
These observations do not prove that alternating updates will work.

Compare EXACTLY two recipes: all-joint, and fixed1:1 alternating joint/heads.
Four groups H_joint/A_joint/H_alt/A_alt use identical0.2 CE anchors; A alone adds
the unchanged fixed decoded expected utility. No rho/CE/schedule ratio/seed
search. No new model parameters, routing, halting, output codec or decoder.
The usual32-unit trainable encoder and two content heads remain the architecture.
All candidates start from the same saved base for their model seed.

Each recipe advances complete TWO-update rounds: joint/joint for standard,
joint/heads-only for alternate, starting with joint. Batch64 inputs are full
views. On heads-only steps, perform the encoder forward and head gradients but
omit head-to-hidden derivatives, tanh/encoder derivatives, encoder parameter
gradients and encoder/bias optimizer work. No zero-gradient padding. Both heads
update on every step; encoder/bias update only on joint steps. Encoder Adam
first/second moments and per-parameter clocks stay byte-identical on heads-only
steps. Active groups alone enter gradient-norm clipping and bias-correction
powers; active clocks increment once. Decoder parameters never update.

The native masked Adam retains the existing checked ownership/alias/binding
contract and original element expressions, with contraction disabled. All-joint
and alternating hand arrays must match the established NumPy reference bitwise;
heads-only finite-difference gradients, budget refusal and inactive state checks
must pass before a committed source freeze. Expected clocks after r rounds:
joint recipe all content groups2r; alternate encoder/bias r and all heads2r.
Save actual first/last gradients by update type, first parameter movements,
final movements, final per-parameter moments/clocks and first-head skip hashes.

## Data, opportunity and complete caps

Reuse immutable artifacts from `runs/content-control-train-r2-20261023`:
three freshly trained bases11/23/47 and the fit/inner input tensor artifact.
No dataset generator is called. Verify hashes against the previously retained
artifact manifest. Keep144 fit/48 inner physical sources,2304/768 rows and
all16 variants/instructions per source together. The new protocol's freeze binds
these prior files, old budget receipt and old raw TRAIN endpoints for strong
dense A/H comparisons. No current failed-refiner model is used or retrained.

Exactly three LRs0.001/.003/.01 and three seeds11/23/47: nine candidates/group,
36 total. All four groups receive the same candidate opportunities and two-round
admission rule. Rotate group order by seed/LR round and selected-service order
by seed. Same per-group total caps:10 CPU seconds AND12B declared units.

Every group is charged the FULL prior shared preparation cost
(2.075925876 CPU seconds/3,486,924,537 units), including the old base/data/compiler
work despite reuse. Add actual new artifact access/hash/import/observer work,
new masked-optimizer compilation, a pre-selection64-fit-row base11 service
calibration and all new shared setup. Nothing is credited back for reused bytes.
No duplicate data/base training is performed. New code/binaries are hash-bound.

Reserve2 CPU seconds/500M units for actual candidate setup, validation/search,
evidence/model export and selected-service/observation/reload tail. Divide the
remaining training allowance by NINE, not one allowance per candidate. Admit
complete two-update rounds before drawing their input batches; actual H/A
objective/active geometry determines charges. Stop at either candidate allowance;
cheaper steps spend saved units on additional real head updates. All candidates,
including losers, are kept and charged. Every group's single WorkLedger covers
inherited preparation and all new stages. Record active CPU per group; attribute
actual common scheduler/setup overhead fully to every group. An actual complete
cap violation stops the build, preserves partial state and exits nonzero.

Each candidate scores all768 inner rows once. Global LR selection per group
maximizes mean three-seed raw decoded task utility (fixed LR order breaks ties).
No residual updates/reselection. Selected models get full real PNG/hash/JSON
service on inner rows, corrupted-decoder observation and a label-free external
hand-input model reload check. Charge these to the group. Final JSON archival
and descriptive post-build statistics are reported separately, not budget
credits. Service price remains.02/H100000 per selected seed; charge the whole
group's nine-candidate build/3, with current pre-selection calibration denominator.
CPU conclusions are conditional on this one new execution wave.

## Analysis and terminal rule

Retain all seed/source raw endpoints and moments; report useful encoder/head
updates and actual complete costs. Primary TRAIN diagnostics are A_alt-H_alt,
A_alt-A_joint and H_alt-H_joint for raw utility and joint success, plus per-seed
greedy retention and complete CPU-net values. Compare A_alt/H_alt with the strong
previous saved dense A/H endpoints without re-evaluating those old models.
Old CPU costs come from another wave and cannot establish a cross-wave CPU win.
Paired48-source/three-seed bootstrap2000/seed77431 intervals are descriptive:
selection used these same inner rows, so positive bounds are not confirmation.

For continued TRAIN readiness, A_alt-H_alt and A_alt-A_joint must have positive
mean utility AND joint success, A_alt must beat old strong dense A on both raw
means, greedy drop must be<=.02 for the matched comparisons in every seed,
and all complete caps must hold. Current-wave A_alt-A_joint CPU-net improvement
is separately reported, with no repeated-wave confidence claim. Any failed
requirement is retained as a failed readiness result; no endpoint can replace it.

After protocol/source identity is committed, commit its freeze BEFORE executing
ONE build. No score-based retries, schedule sweeps, new seed draws, formal
evaluation or refiner/gate expansion. A true pre-score implementation failure
may be diagnosed with its costs/errors preserved, but no replacement run is
implicitly authorized by this registration. Return the actual status to parent.
All future confirmations remain for unified parent/NDU review, using genuinely
independent new synthetic physical sources and honest formal-look error control;
natural images are not an added requirement.
