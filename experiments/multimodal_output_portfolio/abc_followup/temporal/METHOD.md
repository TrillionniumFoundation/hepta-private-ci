# Two-gate acoustic information acquisition

This follow-up addresses the unestablished learned-feedback increment in the
[previous real-speech experiment](../../abc_next/temporal/RESULTS.md). It uses
actual pretrained Piper speech synthesis, unrestricted Vosk acoustic input,
append-only text/PCM output and independent offline Whisper measurement. It
does not train the acoustic model or an open-ended neural text generator.

## Why the action family changed

The first bounded development pilot used eight new fact groups, three sentence
templates and three actual speech renditions. Its negative result is retained:

| Rendition | Vosk exact / 24 | Whisper exact / 24 | Mean TTS ms |
| --- | ---: | ---: | ---: |
| Compact | 20 | 24 | 178.95 |
| Explicit | 24 | 21 | 294.80 |
| Redundant | 22 | 20 | 470.14 |

Vosk preferred a slower rendition that the independent observer decoded less
accurately. This did not justify a frozen pronunciation-repair experiment.
The next bounded development run instead executed a real optional acoustic
observation. Four development facts, two templates, two noisy-cue futures and
four constant acquisition sequences produced 64 paths. The two-stage sequences
00/01/10/11 achieved Whisper success 50%/50%/93.75%/93.75%; the first acquisition
changed subsequent shared content, while a redundant second acquisition often
added cost. These are development observations, with only four underlying fact
groups, not confirmatory evidence. [DEVELOPMENT_SUMMARY.json](DEVELOPMENT_SUMMARY.json)
retains both pilots and their measured costs.

## Physical sequence and information boundary

1. A private environment owner constructs an initial noisy written cue and
   pre-samples three noisy factual cue records. The controller receives only the
   initial public cue. The owner is never passed to a policy.
2. A neutral text/audio prefix is actually synthesized, committed and fsynced.
3. The mandatory first cue is released, newly synthesized into a real WAV and
   decoded by unrestricted Vosk. Only the decoded public observation enters a
   shared posterior. The nominal sensor model is explicitly discounted for
   imperfect ASR; this is a declared fusion rule, not an exact Bayesian ASR
   posterior or a calibrated probability certificate.
4. Gate 0 chooses acquire or commit. Its detached decision is written and
   fsynced before an optional second cue can exist. Acquisition pays actual
   cue synthesis, WAV persistence and ASR; it does not return hidden truth.
   The shared three-fact state then determines the count/color output chunk,
   which is actually synthesized and irreversibly committed.
5. The full observer policy decodes that committed chunk before gate 1. The
   cue-only candidate physically omits that operation and has all corresponding
   features masked. Both policies retain the same actual input-cue history.
6. Gate 1 may acquire the third real spoken cue. It then emits and commits the
   direction continuation. The earlier count/color output cannot be rewritten.
   An acquisition at gate 0 can therefore improve later direction output as
   well as the next chunk through the shared state.
7. Final WAV serialization and exact committed-span readback close online
   timing. Both terminal scoring roles are outside that timer. Independent
   Whisper is not available during fitting, reference selection or decisions.

This is controlled delayed sensor evidence. The cue owner pre-samples factual
records; the experiment does not claim an external live sensor or a changing
real-world event. Input and output audio are nevertheless actual neural speech,
and every selected request synthesizes its own cues and output.

## Strong controls and public state

All four constant query sequences 00/01/10/11 have identical posterior fusion
and content-update rights. They can omit the unused committed-prefix probe.
The initial-only route ensemble chooses among all four sequences before the
first acoustic cue, and its chosen operators still fuse later observations.
The feedback ensemble chooses at both physical gates.

The public adapter contains 82 features: initial cue categories, the full
shared posterior, observed committed-prefix ASR categories, and uncertainty /
history summaries. It accepts a detached `Frame`, never a target, source ID,
unreleased cue, RNG state, outcome score or candidate future. For cue-only,
`previous_audio_fact` is replaced with missing before *all* feature extraction;
no category or derived equality/missing feature can retain the omitted probe.
Elapsed wall time is recorded for costing but is not a policy feature.

Each feedback seed has two 2,722-parameter heads, total 5,444. Each initial-only
seed has a 5,572-parameter route head. Both are three-seed ensembles. Nominal
parameter counts are similar, but feedback has additional source-fold fitting
and different conditional inputs/targets. This is not a claim of identical
training compute or pure single-factor information attribution.

## Conditional exponential values and clocks

The declared final target is

\[
\mathrm{CE}_{2,\lambda}(\pi)
=-\tfrac12\log E[\exp\{-2(U-\lambda T)\}],\qquad\lambda=0.05,
\]

where `T` is the complete measured online wall time of the **same actual output**
used to measure `U`. Utility is
`0.6*(text accuracy + audio accuracy)/2 + 0.2*nonmissing agreement + 0.2*joint exact success`.
The price is a predeclared research profile in utility units per second. It is
not a measured external willingness-to-pay or a universal economic valuation.

Let `tau0` and `tau1` denote the actual first and second decision times from
request start. Q1 regresses positive realized targets
`exp[-2*(U - lambda*(T-tau1))]`. For each held-out source fold, the three Q1
heads' predicted action values are averaged **before** taking the minimum.
The Q2 target is

\[
e^{2\lambda(\tau_1-\tau_0)}\min_a\frac13\sum_{s=1}^3
\widehat Z^{(-\mathrm{fold})}_{1,s}(H_1,a).
\]

All Q2 seeds use this same ensemble-continuation target, matching the deployed
continuation rule. A mean of separate per-seed minima would be a different
policy. This was corrected before any critic fitting or selection. Past cost
before gate 0 is common to its actions and drops from their conditional argmin;
initial-only route training and final evaluation still use full request cost.

Vosk confidence varies slightly across identical-PCM replays. Consequently,
each actual history receives only its executed action's label; other action
entries are masked. Separate replays are not asserted to be identical public
histories. Source folds keep every route/template/future of a fact together.
OOF models and final refitted models are different estimators, and their errors
are not covered by a uniform Bellman or global-optimality certificate.

For cue-only training, the measured prefix-probe component is subtracted from
the inter-gate cost, and probe features are fully masked. This is a training
estimate. Selection and final deployment actually skip the operation and are
timed directly. [CUE_ONLY_PREFIT_AMENDMENT.json](CUE_ONLY_PREFIT_AMENDMENT.json)
was recorded before either feedback model was fitted or selected.

## Source roles, selection and final inference

There are 128 underlying count/color/direction combinations. Counts are nine
through sixteen; the previous experiment used one through eight. Roles are
8 development, 32 fit, 16 selection, 8 observer qualification and 64 evaluation
facts. The shared vocabulary, deterministic pretrained voice and template
families limit generalization. Outputs can share words or even identical WAV
bytes across underlying tasks; repeated bytes do not create new independent N.

Fit runs all four acquisition routes in two worker processes. Its wall times
are development component costs, not serial latency qualification. Selection
actually executes all four optimized constant routes, initial-only, full
feedback and cue-only feedback serially: 16×2×2×7 = 448 requests. The strongest
constant route and feedback variant are selected separately using only Vosk CE
at the declared primary price. The final role is never used to select them.

The frozen final plan executes 64×2×2×3 = 768 selected-policy requests serially,
counterbalancing policy order. Only after all generation closes does Whisper
observe the resulting WAVs. One target-free transcription may be reused for
exactly identical complete-WAV hashes; every request's output hash is validated
and its metrics are calculated against its own target. Generation is never
replaced by a cached waveform. Full scoring work and unique decoder calls are
reported separately.

Three primary gates are priced CE gain over selected fixed, priced CE gain over
initial-only, and strict success retention over selected fixed with zero margin.
Each uses a nominal 98.3333% two-sided percentile interval for a Bonferroni
family of three. Four thousand fact-group bootstrap draws preserve all
templates, scenarios and policy results. The fitted three-seed ensemble is one
policy, not three independent test populations. These finite-source percentile
intervals do not give exact finite-sample or project-wide coverage guarantees.

The predeclared price grid is 0/.025/.05/.1/.2. Its ten feedback/reference
contrasts use nominal 99.5% individual intervals. A 41-point scan over [0,.2]
describes empirical break-even behavior. References remain selected at .05;
they are not silently reselected at each price.

## Qualification, source provenance and reproduction

[freeze-v3](freeze-v3/qualification_protocol.json) is the active observer
qualification, published before qualification execution. Earlier v1/v2 plans
had no qualification executions; their prelaunch corrections are retained in
[QUALIFICATION_PREFLIGHT_CORRECTION.json](QUALIFICATION_PREFLIGHT_CORRECTION.json).
Wrong/silent/truncated audio controls judge the actual decoded audio alone,
so wrong intended text cannot make a rejection tautologically pass.

Exact old fit-generator `state.py`/`run.py` bytes and their AST scope are retained
under [provenance](provenance/DATA_GENERATION_SOURCE_IDENTITY.json). The later
feature adapter is applied to preserved public Frames; data-owner/fusion/text/
metric behavior did not change. The data-generation run does not call critic
features. [BELLMAN_PREFIT_REVIEW.json](BELLMAN_PREFIT_REVIEW.json) records the
time-origin and ensemble-continuation review.

CLI order is `parallel --role fit`, `value fit`, `run --role selection`,
`value select`, `qualification run`, `registration`, serial
`run --role evaluation --defer-external`, `score`, then `analysis`.
Qualification and final execution wait for their applicable published freezes.
All CLIs expose arguments with `--help`. Actual model manifests and old backend
sources are pinned; frozen command arguments and exact-PID process receipts
record full phase costs. Raw WAVs, per-request matrices and model weights remain
outside Git. Source, main reports, protocols, identities and aggregates are the
published deliverable.
