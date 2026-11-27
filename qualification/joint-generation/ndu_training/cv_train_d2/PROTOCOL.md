# One fixed full-budget TRAIN 2×2: original Adam versus CE-anchor CV, A versus N

This is a single exploratory TRAIN run after e788524d6c, with parent-authorized
execution after source freeze, numerical tests and real-entry smoke. It opens
no formal/validation data and creates no confirmatory acceptance claim. Previous
r1 narrow/padding caveat, r2 non-superiority and consumed failed CORE c1 remain.
Selection history also includes d1's two samplers/three fixed seeds, aggregate
mechanism analysis, the fixed CE CV toy candidate and e788's common-panel32
minibatch measurements. CV helped A too; no NDU-exclusive variance claim exists.

## Four systems and immutable objective

Groups are A-plain, N-plain, A-CV, N-CV. EACH complete system contains the same
six useful candidates: seeds11/23/47 × IID/target-stratified. All start from the
same three original saved CE bases with fresh adaptation moments, h32, batch64,
learning rate.003, .5 full/.5 low, identical six minibatch streams
(model_seed+3000), and at least128 matched updates. Maximum1024 rounds is a bound,
not a requirement to waste work. Original dense/joint generation and fixed
12-code text/image decoder have identical opportunities. No utility/scorer,
shape penalty, rho=1.5, CE=.2, learning-rate, sampler or coefficient search.

N remains the original per-request entropic certainty equivalent of decoded
joint reward under p⊗q, averaged across requests. A uses expected identical
decoded reward and the identical CE anchor. Fixed rho can admit conditioned
entropic recursion, but this experiment does not implement time-recursive
conditional continuation values, path learning or a new controlled state.

CV is exclusively g'_B(theta)=g_B(theta)+.2[H_CE(base)−h_CE,B(base)], applied BEFORE
the original norm clip and unchanged NativeAdam. Reference is always the fixed
corresponding base; no refresh. Mean covers every3072 request and both views.
Whole-request importance weights apply to reference CE and objective equally.
The e788 reference means passed independent dense backward checks. Their
unbiasedness is pre-clip only; Adam updates and training outcomes need not be
unbiased or better. Cache staleness and the lower update count may defeat CV.

## Full historical/current cost, without billing vanilla for CV

Reuse immutable d1 bases/native binary and e788 TRAIN/cache to avoid repeating
expensive preparation. Every group receives the FULL original shared receipt:
4,546,132,125 units /4.025272465 CPU seconds. It is not a new physical execution
or a free pretrained base. The two CV groups alone additionally receive the
FULL e788 shared-reference receipt:1,437,213,192 units /0.895446775 CPU seconds,
derived from its final physical CPU minus measured A/N own phases. This
conservatively includes all original common reference construction/checking and
recording overhead, rather than pretending an exact isolated cache-build timer
existed. The reference is loaded once physically, its CURRENT loading CPU paid
in full only by the two CV groups. Plain groups pay neither historical reference
nor current reference loading, pullback, correction or refresh work.

Genuinely common CURRENT data loading, source hashing, six precomputed streams,
readout observers, scheduler and final summaries are fully charged to all four
groups; not divided by4. Candidate/objective/optimizer setup, all useful updates,
matched128 model/Adam exports, native service, row capture, readout, statistics
and final model/Adam exports are charged to their owning system. CV pullback,
mapping/correction/finite checks are charged per actual update. There is no
padding. Cheaper plain groups may and should train more actual steps.

Each COMPLETE group retains the original10 CPU seconds /12B declared-unit dual
cap. The four attributed caps total40 seconds/48B; this is four actual candidate
systems, not four times the cap for one N model. Historical/current CPU and
physical process CPU are reported separately. After historical attribution,
sum of all current group CPU can be at most22.108016590 seconds; physical current
CPU is no greater and an independent22.2-second guard reserves terminal evidence.
These are scientific-entry scopes including imports, I/O, observations, hashes
and receipt writing; source editing, software-only tests and git delivery are
reported separately, without an end-to-end development-cost claim.

`admission.json` is a read-only exact-geometry quote. The operator envelope counts
all-full/mixed possibilities and even a norm trace every update for reservation,
but actual ledgers charge only executed low/full masks and observed step1/64.
Each CV step additionally costs933064 weighted reference pullback +43728
correction +64 index mapping (IID pullback costs252 fewer units). Original
priced-operator inventories are not hardware FLOP/energy estimates. RNG/index
gather/copy/hash/PNG/serialization costs appear in actual CPU; unused quotation
envelopes are never recorded as executed work.

The frozen 128-round admission quotes are A-plain6,770,245,405 units,
N-plain6,775,602,973, A-CV8,968,783,909 and N-CV8,974,141,477. CPU forecasts
are7.820072465 seconds for each plain group and9.560319240 for each CV group.
These include the declared430M/2.4s tail and historical costs; they are not
promised final consumption or evidence that a noisy run cannot fail admission.

Before any trained forward/update, complete current preparation plus historical
cost must admit128 six-candidate rounds at forecast.0011s/plain-update or
.0022s/CV-update, .15s/group setup and2.4s/group complete tail. Forecasts use d1
updates and e788 charged gradients/service; noisy host conditions can invalidate
them. Runtime refuses before results if this no longer fits. After each useful
round, a frozen next-round forecast is max(1.5×last actual round, original update
forecast×6). A group stops before its next full round plus430M units/2.4s final
tail would exceed its caps. Cost-only stopping is independent of scores.
All four groups rotate through fixed Williams rows each round. No competing
job from this task during the run. A group failure seals the entire 2×2 attempt;
other independent research need not stop.

## Exact observations and storage

Each final model serves ALL3072 TRAIN rows once. Six models/group ×48 physical
four-source cohorts ×64 rows =18,432 actual requests/group. Four groups give
**73,728 actual native/PNG outputs**,1152 batches; every one is retained.
Each model gets48 batches and3072 observations. No base-service output or extra
prediction pass is hidden in the denominator. Current training-forward rows
are64×the sum of actual candidate updates and are reported separately.

Service per group is354,557,952 original priced units, including the same native
full generation and original PNG/hash/base64/JSON path. Final p/q come directly
from this service, never an extra score pass. All cohorts retained, group order
Williams[(seed_index+sampler_index+cohort_index)%4]; candidates indexed in fixed
plan order. Sampling RNG=844021+37cohort_index+model_seed is paired across groups
and samplers. One timing wave is a TRAIN cost observation, not evidence of a
stable CPU-net gain. Group complete adaptation/preparation/export/serving cost
is reported, without converting a noisy single wave into confirmation.

Save lossless float64 p/q, each head's truth probability/margins, per-request Z,
entropic value, raw reward components/negative-tail probability and expectation,
greedy reward/codes/joint correctness/attribute errors. Keep all192-source means,
all12 target classes implicitly in complete rows, and all negative changes.
Full source/input arrays and base caches remain hash-bound references to e788;
do not duplicate them. Persist all actual master minibatches/weights/views once,
four groups' consumed prefix hashes/step counts, initial source references,
all matched128/final parameters and Adam states, scalar traces and output payload
hashes/choices/bytes. Deduplicate identical payloads, never drop unfavorable rows.
Entire new output directory must fit64MiB; expected under48MiB. Storage and
observation CPU are part of each complete-system budget.

## Prespecified TRAIN comparisons and falsifiable decisions

Primary is mean over the three fixed seeds of U(N-CV,stratified) minus the
endpointwise strongest of SIX effective A alternatives: new plain/CV × IID/
stratified and retained original d1 A-IID/A-stratified. Existing original A
models remain available even if this experiment's fuller observations reduce
the new plain groups' adaptation steps. Do not silently replace a strong A with
a weaker alternate-content baseline. Other research's strong dense/joint A
must additionally be fixed by parent integration before any future confirmation.

The fixed interaction is mean_seed[(N-CV−A-CV)−(N-plain−A-plain)], stratified.
Report all individual cells, both sampler contrasts, CV−plain for A and N,
all source deltas, greedy and tails. Positive N CV−plain alone does not establish
an NDU-specific improvement. If the interaction is ≤0, do not claim NDU-exclusive
CV benefit. If the primary strongest-A raw difference is ≤0, the candidate fails
its TRAIN improvement screen. Retain the existing greedy maximum drop.02 versus
endpointwise strongest A for every seed. A positive TRAIN screen, if any, is
selection evidence only; three fixed seeds/shared TRAIN do not generalize to a
random training program or consume/reset formal alpha. No subset/seed removal,
new rho or new weights after inspection; no repeat until significant.

## Freeze, smoke and terminal policy

Commit all source/protocol/plan, freeze source and input hashes, then real-entry
smoke with content forward, Adam update and TRAIN array loader forbidden. The
separate numerical single-step tests use HAND arrays/new untrained models only,
and compare all six gradients/moments/parameters against dense correction plus
the original Adam; test atomic admission and CV-only cost recipients.
Record exact source/test identities and all failures. Run one TRAIN invocation
only after these checks. A pure zero-model-result launch defect may get a new
technical identity after retaining its evidence. Once model results start, any
numerical/resource/provenance failure seals this attempt and retains partial
weights/Adam, per-row arrays/payloads/traces; no retry/new directory or adaptive
repair to rescue the outcome. Formal/validation markers remain unopened.
