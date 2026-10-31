# Initial STOP, paired values and actual native Hepta generation

This additive research implementation starts at parent commit
`7db3b8347080326ded0cba037fc770df76c94a6a` (draft PR #4225). It executes the
six requested development workstreams while keeping implementation results,
empirical benefit, semantic qualification and production adoption distinct.

**The complete registered matrix and all final diagnostic experiments ran.**
The current dynamic policy has no stable net-utility advantage. For the same
trained dual-core model, immediate delivery exceeds dynamic continuation at
all six registered seed/width endpoints. This is useful evidence about the
contribution of extra computation, not a proof that generation control cannot
work. The free-text path and full native content backend execute, but natural
audio/video and adoption by the existing Agentd owner remain unfinished.

## Read the results

- [Complete matrix and interpretation (Chinese)](RESULTS.zh-CN.md).
- [All 48 arm endpoints and four inference controls](evidence/MATRIX_READABLE.json).
- [Paired action values, verification and critic calibration](evidence/diagnostics_frozen_20261030/DIAGNOSTIC_FINDINGS.md).
- [Actual consumption of calibrated values by a first-action rule](evidence/critic_choice_frozen_20261030/FINDINGS.md).
- [Free-text generation and independent content failures](open_domain_notes.md).
- [Native content, prefixes and recovery](native_generation/README.md).
- [Existing owner integration boundary and exact call sites](native_generation/INTEGRATION.md).
- [Independent readback audit](audit/evidence/final_20261031/AUDIT.md) and
  [additional first-choice audit](audit/evidence/consumer_20261031/AUDIT.json).

## What was executed

| Workstream | Implemented and executed | Acceptance result |
|---|---|---|
| Initial STOP | Initial content supervision, legal sampled STOP, encoder-only / one-update / fixed-multistep / dynamic-multistep controls | STOP sampled 387 times during training; encoder-only exceeds the current dynamic policy at 6/6 matched-model endpoints |
| Action marginal value | Same frozen state/budget, paired future noise, eight actual continuations including repeated verify; independent-source proper-moment critic fitting | Calibration loss and aggregate scale improve; reliable action benefit is not established |
| Verification information | Actual public observation, feedback/content hashes, fixed-clock policy response and duplicate detection | First verification changes feedback but not content; repeated verification adds no observation; measured benefit does not recover cost |
| Content versus control | 3 seeds × 2 widths × 2 core operators × frozen/joint content × fixed/dynamic policy | All 48 arms retained; main dynamic-minus-fixed CE has mixed signs and no positive 95% lower bound across all endpoints |
| Open-domain output | Real frozen causal LM, trainable Hepta soft prefix, unrestricted vocabulary, separate public development sources, post-generation checks | 12 completions / 544 tokens; complete factual checks 0/4 in each of three arms; semantic audio/video not implemented |
| Native state | Complete trained small-model inference in Rust, versioned recurrent/decoder state, real media, immutable prefixes, CAS and new-process recovery | Numerical/media/recovery contracts pass; production owner adoption and learned streaming coherence not completed |

The final evidence contains 6,144 training trajectories, 2,304 primary-analysis
trajectories, 2,304 inference-control trajectories, 2,048 paired diagnostic
continuations and 256 first-choice continuations: **13,056 actual final
trajectories**, all independently audited. The interrupted pilot and free-text
pilot remain separately identified and preserved. No reserved confirmation
source was opened. Repeated draws are not counted as independent task sources.

## Objective and cost contract

The fixed research objective is the inherited population entropic certainty
equivalent, with gamma = 2 and delivered return R = observed utility − cost:

`CE = -0.5 * log E[exp(-2 * R)]`.

The training score covers the actual sampled action law, Gaussian dense media
emissions and categorical text emissions. Independent-episode leave-one-out
baselines reduce variance. The scalar loss is an unnormalized exponential
moment objective; finite-batch normalized CE gradients are not claimed.
Supervised prefix pretraining includes the initial encoding. During the
factorial joint-training phase the auxiliary supervised weight is exactly zero.
Critic fitting detaches content features and checks frozen content/actor hashes.

This is an entropic, finite-horizon specialization. It does not implement a
general endogenous-preference NDU, a neuronal task-value free boundary, an
exact Merton solution or globally optimal multimodal control. The core retains
the parent's first-passage moment approximation. Physical-time direct
derivatives with respect to weights are not modeled.

The mechanism task requires all four final modalities. Its portfolio control
allocates subsequent computation among shared/modality updates, verification
and stopping; it does not yet learn which arbitrary set of output modalities
to offer. The native decoder state is complete for these small dense heads,
including sampler and committed cursors, not an implementation of a large
autoregressive decoder's KV cache or a video diffusion scheduler state.

`encoder_only` still runs decoding, file encoding, readback and observation;
it means zero subsequent content transitions. The runtime continuously meters
CPU/wall intervals through encoding, identity checks, policy, transitions,
emission, codecs, observer and the return seal. A final sidecar cannot bill its
own completed write recursively; it and cold setup/optimizer/analysis/archiving
are reported by explicitly scoped outer ledgers. Timing is from a shared CPU
host and the tariff is abstract, not a monetary or production-latency claim.

The core dynamic policy uses the actor directly. The separate first-choice
experiment actually consumes original/calibrated critic values, charges its
planning work, executes its selected first action and then uses the original
actor for the suffix. It does not silently turn a value under one policy into
a claim about repeated replanning. Its calibrated-minus-original CE difference
is +0.000616 with a source-bootstrap 95% interval [-0.007074, +0.008870].

## Reproduction

The measured main runtime uses Python 3.12, Torch 2.8.0+cpu, NumPy 2.3.5 and
Pillow 12.3.0. The text run separately records Transformers 4.57.3 and Torch
2.9.1+cpu. Native qualification uses Rust 1.95.0. Exact source, parameter,
compiler, codec and environment identities are retained in each protocol.

Run the additive contracts from the repository root:

```bash
export HEPTA_NATIVE_RUSTC="$(rustup which --toolchain 1.95.0 rustc)"
python -m unittest experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.test_runtime experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.test_diagnostics experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.test_open_domain experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.test_native_bridge -v
python -m unittest experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.critic_choice.test_run -v
```

Run one registered full cell, then use the other registered seeds/widths from
`protocol.json`; the output directory must not exist:

```bash
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.study --seed 17 --width 32 --output runs/seed-17-width-32
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.diagnostics_study --checkpoint runs/seed-17-width-32/dual.joint.dynamic/MODEL.pt --output paired-diagnostics
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.critic_choice.run --original-checkpoint runs/seed-17-width-32/dual.joint.dynamic/MODEL.pt --calibrated-checkpoint paired-diagnostics/MODEL_CALIBRATED.pt --output first-choice
```

`open_domain.py --help`, `native_generation/README.md`, and `packaging/README.md`
describe the optional local language model, native execution and byte-exact
evidence restoration. Large raw evidence/checkpoints are retained in verified
384 KiB chunks rather than oversized Git blobs; no size allowlist was changed.

## Validation and remaining work

The 32 core V3 integration tests passed together. The two additional critic
consumer tests passed. Independent audits reopen every final image/audio/video/
text artifact, rebuild synthetic targets, reconcile seals and costs, verify
checkpoint/source identities, and recompute critic values, policy choices and
source-bootstrap comparisons. They also decode actual free-text token IDs and
freshly compile/replay the native content journal. Audit success establishes
evidence consistency, not semantic quality or a positive scientific effect.

All 51 materialized parent files match their original Git blob identities.
New native modules pass `rustfmt --check`. The repository-wide `just fmt` was
unavailable in the partial materialization: neither `just` nor the production
`codex-rs` workspace was present. This is recorded in `evidence/FORMAT_SCOPE.json`;
it is not presented as a passed full-workspace gate. A dedicated exact-commit
GitHub workflow exercises the new runtime and native contracts.

Next experiments should test whether the critic's compressed readout is
sufficient for reachable multimodal states before increasing fitting steps.
It currently sees shared state, mean modality slots, feedback and clocks;
it does not directly see every modality slot or all recurrent core tensors.
State aliasing is a plausible limitation, not a demonstrated cause of these
results. Natural audio/video requires actual trained conditioning adapters and
independent semantic evaluators. Production adoption requires one owner to
atomically commit generation state and output progress, as specified in the
native integration document. None of these open items is relabeled as closed.
