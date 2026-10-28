# Unified NDU multimodal research — 2026-10-28

This package implements a shared finite-horizon objective contract and three
bounded research executions: full-path text/image learning, the existing native
owner's continuation, and natural four-modality event reconstruction. Each study
has its own frozen task, observer, execution law, cost convention, and evidence.
The common schema makes those contracts comparable and auditable; it does not
make different tasks or continuations the same experiment.

## Completed results and disposition

All predefined capability/promotion decisions remain **not approved**. The
implementation and byte-level audits passed; they do not establish a gain over
the strong controls or a globally optimal multimodal policy.

| Frozen result | Outcome |
| --- | --- |
| Full-path learning | 6 matched runs, 1,920 updates, 92,160 actual output roundtrips; 1,005,524 trainable parameters at the final stage |
| Full-path qualification | 27,648 bundles; independent reopening of 55,296 files; maximum score discrepancy 0 |
| Risk minus strong prior | Mean fixed-seed CE difference -0.00557131, paired-source 95% interval [-0.01018463, -0.00109823] |
| Risk minus matched mean | Approximately zero; two seeds select the exact prior and one selects transition-only updates |
| Expanded natural qualification | 32 new videos, 93 events, 8 arms, 1,488 bundles; NDU64 minus uniform64 +0.00070077, source interval [-0.00001952, +0.00225515] |
| NDU64 minus strong natural interpolation | -0.08694486, source interval [-0.11683931, -0.06187751]; semantic gates also fail |

[Natural study details](natural_studies.md) preserve both the original and
expanded experiments. [Selected-policy critic diagnostic](natural_selected_critic.md)
corrects source weighting and fits the complete frozen actor's actual net moment;
it is post-study, never changes a decision, and issues no rigorous tail certificate.

## Architecture and scope

| Work package | Implementation | What the evidence can establish |
| --- | --- | --- |
| One objective contract | [profile.py](profile.py), [objective_oracle.py](objective_oracle.py) | Fixed-risk CE semantics, actual terminal/cost receipts, and finite-model dynamic consistency |
| Train the generation path | [generator.py](generator.py), [fullpath_train.py](fullpath_train.py), [gradient_oracle.py](gradient_oracle.py) | Actual-output gradients through transition, adapters, emissions, and encoder |
| Joint outcomes and tails | [tail.py](tail.py), [test_tail.py](test_tail.py) | Selected-policy moment bounds under declared support and independent-source assumptions |
| Low-overhead native control | [control.py](control.py), [native_check.py](native_check.py), [native_failure_check.py](native_failure_check.py) | Actual owner lifecycle, dispatch, readback, recovery, and complete execution receipts |
| Same-event natural modalities | [natural_model.py](natural_model.py), [natural_run.py](natural_run.py), [natural_expand_run.py](natural_expand_run.py) | Bounded neural text/audio/image/video reconstruction, source-held-out evaluation, and semantic controls |

The encoder initializes shared and modality states. Registered transitions update
those states, emissions produce actual media, and the bound observer scores the
reopened outputs. This is a finite stochastic control construction inspired by
portfolio allocation. The neural optimization and the natural task do not have a
global-optimality proof. Native kernel parameters remain fixed. Frozen natural four-media generation now
crosses the original owner in a separately bound transport diagnostic
([natural_native_check.py](natural_native_check.py)): 16 episodes, 20 neural
forwards, 536 kernels and 16 cold recoveries. All eight full/fast pairs preserve
actions, pre-codec tensors and final four-file hashes. This adds no semantic
qualification; joint training through that native continuation remains open.

## Objective and execution identity

For actual delivered gross utility `u`, debit each actual cost event once:

```text
R = u - sum(unique actual cost events)
CE_gamma(R | x) = -log E[exp(-gamma R) | x] / gamma
J_population = -log sum_x q_x E[exp(-gamma R) | x] / gamma
J_conditional = sum_x q_x CE_gamma(R | x)
```

At `gamma = 0`, both values use the expected return limit. Gamma is fixed across
the finite continuation and time discount is exactly one. Random cost, failure,
and continuation outcomes remain joint inside the expectation. `backup()` uses
one conditional CE of reward minus cost plus the bound continuation value.

`NduProfile` is immutable. Its canonical SHA-256 binds the objective definition,
observer, continuation semantics, risk scope, cost unit, gross utility support,
required modalities, terminal treatment, and absence of time discount. Changes
to those semantics require a new profile. Learned parameter snapshots, actor
parameters, policy routes, and concrete execution receipts have additional
identities. A hash alone does not authenticate an observer or prove readback.

`DeliveredOutcome` requires explicit context, sample, independent-source cluster,
artifact hashes, observer/objective/continuation identities, terminal status,
and cost events. Exact duplicate cost receipts are idempotent; conflicting
receipts with the same event ID are rejected. Repeated real work needs new IDs.
The declared utility interval bounds gross score, not the net return after cost.

Contexts identify fixed public inputs. Source clusters identify independent
evidence units. Neither is a training seed. `aggregate()` reports both risk
scopes, chooses only the declared one, and preserves explicit task weights when
different contexts have different numbers of draws. The finite oracle enumerates
complete contingent stopping policies and uses independent high-precision
Decimal valuation; its scope is a known finite model.

## Actual-output full-path learning

[fullpath_protocol.py](fullpath_protocol.py) pins the strong inherited checkpoint,
task distribution, tariffs, retention gate, and study budget. The original frozen
encoder and gate select the plan. The current generator is opened cumulatively:

1. Shared semantic and coupling transitions.
2. Modality initializers and transition adapters.
3. Pixel and autoregressive text emission modules.
4. Public-input encoders, embeddings, and command conditioning.

The image law samples Gaussian logits with fixed sigma `0.03`, then applies
sigmoid, 8-bit PNG serialization, and reopening. The text law samples categorical
tokens at temperature `0.7` for a fixed latent horizon. Tokens after rendered EOS
remain sampled and included in the full latent density. UTF-8 rendering is not
repaired to improve the score. Training rewards come from reopened PNG/UTF-8.

For the population objective, the sample cost is
`ell_gamma(R) = expm1(-gamma R) / gamma`, with `ell_0(R) = -R`. Under the same hard
constraints, minimizing its expectation has the CE optimum. The estimator uses
detached output actions and rewards and differentiates the sum of Gaussian and
categorical log probabilities. It includes every sampled autoregressive action.

K independent emissions may share the same fixed input and exogenous initial
noise. A per-context leave-one-out baseline is unbiased under that conditional
independence. It is invalid to reuse the same emission noise, include the sample
itself in that baseline, or ignore reward coupling across samples. The oracle
checks these failure modes, exact codec-bin probabilities, and actual generator
gradients against independent held-action density and finite differences.

The mean control has a separately declared `gamma = 0` training profile. Model
selection uses the primary evaluation objective and an external retention gate;
no retention regularizer is hidden in the claimed NDU loss. Deterministic prior
and fallback routes and sampled learned routes are declared explicitly. Shared
objective scoring does not imply that their output laws are identical. Reported
optimization seeds share the inherited base checkpoint. Per-episode work tariffs
and measured batch CPU/wall time are recorded separately.

## Selected-policy tails and native execution

`calibrate_selected()` consumes complete actual joint events, including the
selected and executed action, failure/refusal, cost, feedback, and artifact
receipt. It does not multiply separately estimated modality marginals. Sources
must be disjoint from training/reserved splits and from other calibration events;
duplicate source clusters cannot inflate the evidence count.

The caller must declare finite support for future **net** returns, including the
maximum allowed cost and failure branches. The bounded method uses a one-sided
Hoeffding bound; a predeclared two-point return law can use exact one-sided
Clopper–Pearson. Variable costs cannot be silently treated as a two-point law.
Family correction is declared before selection. It does not repair fitting a
policy on its calibration set. Near-zero risk uses `log1p`/`expm1`. A conditional
profile rejects pooled events from different public contexts; a weighted
conditional objective needs separately controlled context bounds.

The native host executes the existing `Open`, `Tick`, `Forecast`, `Close`, and
`Resume` operations and registered keep/swap dispatch. With cold recovery, fast
execution performs **17 actual kernels**: seven ticks plus ten journal/ledger
recovery steps. Full forecasting adds 33 kernels, for **50**. Live-owner counts
are 7 and 40. Receipts count all branches, recovery, generator work, refusals,
delivery, actor time, and measured CPU/wall time. These counts alone do not prove
a wall-clock speedup or superior policy quality.

The native scope's historical objective and `DENY_ALL` authority are unchanged;
the new profile is bound at the research host receipt. Actor/dispatch source and
parameters must be bound, and private target truth is not public feedback. An
unhandled exception aborts the trial; excluding such episodes and reporting
only successful outputs would invalidate evaluation. The tail guard added after
native execution does not rewrite the archived native evidence.

## Natural joint event reconstruction

The natural study generates text, waveform, image, and short video for one event
using shared neural states and four emissions. Scoring reopens UTF-8, PCM WAV,
PNG, and FFV1 video. Source manifests, independent-source partitions, a frozen
joint score, fixed comparators, mismatch controls, and separate semantic-observer
checks accompany the reconstruction metrics.

Pilot/warmstart losses are proxies. The subsequent score-function phase uses
actual delivered returns; a whole-batch score retains cross terms from shared
runtime costs, with a baseline from the preceding batch. Measured CPU is treated
as conditionally exogenous for fixed architecture; derivatives of platform timing
with respect to parameters are not estimated. Study-specific moment regression
and source bootstrap summaries do not automatically inherit `tail.py` guarantees.

The expanded study preserves the original result, uses fresh held-out sources,
and declares a new continuation for its enlarged candidate set. Inherited
checkpoints retain their original training identities through explicit migration.
Small media reconstruction and four valid output files do not establish
open-domain semantic generation or foundation-model capacity. Source-video
separation also does not establish participant/writer identity independence.

## Run the lightweight checks

Run from the repository root with Python 3.12. These checks need only the standard
library and do not download datasets, train models, or build the native binary:

```bash
python -B -m unittest -v \
  experiments.multimodal_output_portfolio.unified_20261028.profile_tests \
  experiments.multimodal_output_portfolio.unified_20261028.test_tail
python -B -m experiments.multimodal_output_portfolio.unified_20261028.objective_oracle
python -B -m experiments.multimodal_output_portfolio.unified_20261028.gradient_oracle
```

The gradient oracle explicitly reports whether optional Torch and actual-generator
checks ran. To require the actual implementation check in a CPU Torch environment:

```bash
python -m pip install -r experiments/multimodal_output_portfolio/v6/requirements.txt
python -B -m experiments.multimodal_output_portfolio.unified_20261028.gradient_oracle \
  --require-torch \
  --actual-generator experiments.multimodal_output_portfolio.unified_20261028.generator \
  --output gradient-oracle.json
```

The optional [research workflow](../../../.github/workflows/ndu-unified-research.yml)
runs only the standard-library checks on a pinned Python runner and retains the
tested source identities and logs. It is manually runnable or reusable; existing
aggregate CI remains unchanged. Heavy training and GPU jobs are excluded.

## Study execution and evidence

Full studies require the pinned data/checkpoints and fresh output directories.
`--assets` points to the prepared study assets; `--baseline` is the exact inherited
checkpoint checked by the protocol. A smoke run checks execution only.

```bash
python -B -m experiments.multimodal_output_portfolio.unified_20261028.fullpath_train \
  --assets /path/to/assets --baseline /path/to/pinned.pt --output /path/to/development
python -B -m experiments.multimodal_output_portfolio.unified_20261028.fullpath_qualify \
  --assets /path/to/assets --baseline /path/to/pinned.pt \
  --development /path/to/development --output /path/to/qualification
python -B -m experiments.multimodal_output_portfolio.unified_20261028.natural_run \
  --assets /path/to/natural-assets --output /path/to/natural-study
python -B -m experiments.multimodal_output_portfolio.unified_20261028.natural_expand_run \
  --assets /path/to/expanded-assets --first-study /path/to/natural-study \
  --output /path/to/expanded-study
```

| Evidence | Authoritative record |
| --- | --- |
| Finite objective/stopping oracle | [OBJECTIVE_ORACLE.json](results/OBJECTIVE_ORACLE.json) |
| Delivered-output and actual-generator gradient oracle | [GRADIENT_ORACLE.json](results/GRADIENT_ORACLE.json) |
| Native cold recovery and forecast comparison | [NATIVE_INTEGRATION_SUMMARY.json](results/NATIVE_INTEGRATION_SUMMARY.json) |
| Native actual failure/refusal branch | [NATIVE_FAILURE_SUMMARY.json](results/NATIVE_FAILURE_SUMMARY.json) |
| Selected-action public continuation table | [NATIVE_PUBLIC_CONTINUATION_TABLE.json](results/NATIVE_PUBLIC_CONTINUATION_TABLE.json) |
| Native archive and immutable provenance | [NATIVE_EVIDENCE_PACKAGE.json](results/NATIVE_EVIDENCE_PACKAGE.json) |
| Full-path qualification and paired comparisons | [FULLPATH_RESULT.json](results/FULLPATH_RESULT.json) |
| Independent full-path artifact/target audit | [FULLPATH_INDEPENDENT_AUDIT.json](results/FULLPATH_INDEPENDENT_AUDIT.json) |
| Full-path training and gradient coverage | [FULLPATH_TRAINING_SUMMARY.json](results/FULLPATH_TRAINING_SUMMARY.json) |
| Preserved initial natural study | [NATURAL_INITIAL_RESULT.json](results/NATURAL_INITIAL_RESULT.json) |
| Expanded natural qualification | [NATURAL_EXPANDED_RESULT.json](results/NATURAL_EXPANDED_RESULT.json) |
| Attempt history, including retired runs | [ATTEMPTS.json](results/ATTEMPTS.json) |
| Complete evidence and source identities | [EVIDENCE_INDEX.json](results/EVIDENCE_INDEX.json) |

Full-path runs additionally write `PROFILE.json`, `PROTOCOL.json`, per-stage
training/checkpoint records, `SELECTIONS.json`, and `DEVELOPMENT_SEAL.json` before
qualification writes `RESULT.json`. Natural runs write `NDU_PROFILE.json`,
`QUALIFICATION_FREEZE.json`, `OUTCOME_LEDGER.json`, and `RESULTS.json`. Report the
qualification gates, source census, paired uncertainty, failures, cost, and
fallback choice from those records. Neither an oracle pass nor a completed run
is a positive qualification result by itself. Earlier experiments remain intact.

## Exact archived records and future cohorts

To recover the original JSON files from their space-saving gzip form, run
`python -m experiments.multimodal_output_portfolio.unified_20261028.restore_records RUN_DIRECTORY`
for the archived development and qualification directories before re-auditing.
`COMPRESSED_RECORDS.json` pins both original and compressed SHA-256 values.
The archive includes the exact executed sources; use those for historical replay.

The current 384 qualification/retention pixels are now consumed. Future source
allocation must exclude `results/FULLPATH_SOURCE_ALLOCATION.json` in addition to
all previous manifests. The runner is not a global source-consumption registry.
