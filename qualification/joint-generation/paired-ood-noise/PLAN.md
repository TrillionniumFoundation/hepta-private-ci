# Fixed paired corruption-domain evaluation, not a training repair

SOURCE ONLY. Rebuild the exact completed raw/Haar × A/original-rowN study:
4 shared Source bases,16 adapted models, original decoder300/sourceCE500/adapt300,
old static grouped64 sampler, learning rate .003, rho1.5, ordinary aligned anchor.2.
Training/serving law mismatch remains unchanged. The oldID scientific gate remains
false permanently. No Haar timing extension, model adjustment or NDU objective change.

All16 model/four base digests and all32 old FIT-only calibrated heads must match
historical controls exactly. All weights then all calibrators freeze before any
new real evaluation images. Reproduce oldID3701/3702/3711/3712 complete datasets,
full metrics/profiles,108 contrasts and12 coordinate-objective interactions exactly
before generating fresh domains. No restored weights, original TEST or VAL endpoint.

## One fixed paired domain, no pressure/seed search
Only paired helper mode fixed-paired-heldout-corruption-035-v1 is admitted.
Fold0 seeds4701/4702; fold1 seeds4711/4712; six variants for the same130 heldout
content groups per fold. Each pair renders its source scene ONCE, draws sigma_ID
uniform(.03,.25) and one192-dimensional standard Gaussian Z, then constructs
freshID=clip(clean+sigma_ID*Z,0,1), OOD=clip(clean+.35*Z,0,1).
The exact same Z is used in both domains. Each produces the unchanged2x2-mean
thumbnail/uprepeat low view, command features, labels and row ordering. Sigma.35
and these four seeds are final predeclared choices, not the start of a .5/.7 or
other stress search if N fails. Separate fixed pseudorandom branches do not prove
statistical independence. Pairing controls noise direction while changing scale;
it does not establish globally blind data or previously unseen source groups.

The model still sees202 observed-pixel+instruction features (Source masks words),
never sigma, seed, scene/group ID or renderer/target metadata. The renderer is only
the synthetic data generator. Same known260 FIT catalog, permodel130 heldout groups:
new corruptions, NOT new-group generalization or natural-image capability. OOD
here means a corruption-regime distribution shift (sigma.35 outside the training
sigma interval), NOT disjoint input support: Gaussian noise has full support and
clipping leaves overlapping supports. No strict invariant-P(y|x) covariate-shift
assumption is made; only a fixed corruption shift is tested. Sigma.35
is a fixed synthetic stress, not guaranteed danger/catastrophe or guaranteed NDU
robustness. Clipping can make realized perturbation geometry nonlinear; paired
Gaussian directions do not imply all pixelwise changes are larger or harder.

## Frozen evaluation and primary gates
Every adapted model uses its own unchanged old FIT-calibrated serving profile in
both fresh domains. No new base/uncalibrated evaluation and no OOD calibration,
refitting, adaptation, selection or temperature change. Check model/profile digest
before each domain evaluation and after both. Old normalized/CDF guards unchanged.

Each domain separately reports five cross-arm claims: HN−HA, HN−rawA, HN−rawN,
rawN−rawA, HaarA−rawA; each4cells×(2noise+pooled)=60 contrasts. All11 metrics,
full-low-macro/all-partial retained. OOD primary requires all8 unpooled comparisons
for EACH first three claims (24 conjunction). FreshID has the SAME24 gates,
reported independently. Original gates: CE>=.005 gain; text mass/greedy/joint no
regression beyond1e-10; pixel MSE no increase beyond1e-10. No mixed-domain gate,
pooled rescue or claim that OOD success rescues the original failed objective.
Cross-domain paired difference-in-differences for all5claims×12records=60, defined
(left−right)_OOD − (left−right)_freshID, all metrics retained, gate=null. These
are descriptive interactions, not an additional success criterion or general
causal proof. Old108+12 records stay in their original schema; new fields separate.

## Source qualification and strict admission
Old48 tests/helper modules remain byte-exact. Three new literal tests run in the
same bounded child BEFORE FIT generation: hand clean/Z paired formula, exact low
view/range/no mutation; fixed small literal Gaussian branch determinism/different
seed/commonZ; wrong mode/fold/seed/image/nonfinite refusal. These tests do not call
paired_dataset or render actual780 rows. Real new data generation occurs only after
both freeze barriers AND complete oldID reproduction. No standalone science pilot.
Bytes-backed per-domain full/low arrays are readonly; original arrays unchanged.
No renderer/data imports at new helper module import, only lazy science endpoint.

## Exact incremental work and bounded actual costs
40CPU/120wall/512MiB/4MiB, CPU0/single thread/existing nonblocking shared lock,
complete wait4/no retry or extension. Source producer performs AST/hash only.
All51 literal tests, import/array/hash/renderer work count in whole child. Toy model
initializations/Adam updates counted; old4 manual SGD parameter steps retained.
Original training budget/oldID work unchanged; extra evaluation is explicitly NOT
free or equal to the prior study's total CPU. Historical24.903823CPU cost additional.

Four paired dataset calls yield3120 render calls,3120 uniform sigma draws,
599040 standard-normal scalars,6240 clipped images,6240 thumbnails,12480 full-low
view rows. Incremental SHA tracks sigma, Z and clean render sequences plus all6240
full-input hashes; manifests and complete whole-child SHA counts retained. Generator
CPU includes array construction/readonly copies and metadata validation. No latent
or image payload is published, only hashes/counts/saved scalars.
New evaluation:16models×2channels×2domains=64 forwards/99840rows and64 calibrated
serves/99840tables. Combined18576 forwards/1396000rows; total136 serves/212160tables.
32 extra transforms/49920rows per coordinate. No additional model training, decoder
calls, calibrated heads or NLL evaluations.384 metric summary reductions with all
row visits and unspecified-attribute visits counted;60 cross-domain scalar DID
records additionally computed and charged inside whole CPU. Each model/domain
actual evaluation CPU and serving CPU retained separately; generator cost and
failure-prefix progress recorded. Old base/adapt/calibration/serving costs remain.
The exact old and combined ledgers are in LEDGER. Budget feasibility is not a
runtime promise: exhaustion retains failure, no extension/retry.
