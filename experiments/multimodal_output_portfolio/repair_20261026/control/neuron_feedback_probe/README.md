# Original sparse-neuron feedback probe

This new study executes the repository's real `sparse_tick`; it does not replay
or qualify the missing historical Agentd execution closure. The copied
`hepta-neuron`, `hepta-types`, and `hepta-infer-core` sources contain 83 files and
are byte-identical to the checkout. The original sparse source SHA256 is
`bc5a1f64ddfda4e603e590d62b0ed01fa5b0b3cd54f1d1d4407477af5bed2810`.
The isolated build uses only package name/version/source/checksum identities
present in the repository's Cargo lock. No other experiment's compiled rlib
was substituted. The current bridge is formatted after execution; the exact
compiled source and original crates are retained in the evidence archive.

## What the actual causal path contains

Each episode first writes and reopens four actual files: UTF8 text, PNG, tone
PCM WAV, and uncompressed AVI. A public delivery-consistency scalar is computed
from this readback and committed. It is a target-free proxy, not the private
task utility. A fixed two-channel encoder supplies that scalar to the first
original native tick. A second original native tick receives **zero drive**;
only its previous numerical checkpoint can carry the scalar forward. A trained
21-coefficient linear readout takes the second tick's ten activations and ten
eligibility values, plus an intercept, and selects stop or a real retransmission.
The final files and decision are persisted before the private target is used to
score the entire episode, including irreversible initial-delivery damage and
actual repair charges.

The head is fitted on 96 new paired, actually delivered examples; its labels
are positive observed repair gain. There are 600 gradient updates. The original
sparse configuration, kernel, deterministic media codecs, and inherited
categorical posterior remain fixed. This is **not training of the original
neuron kernel, an encoder/decoder, or the full NDU model**. Eligibility is an
observed state feature here, not a claim that it is a model-parameter gradient.

## Registered experiment and result

The single run uses 256 fresh synthetic cases and five paired arms. All arms
have the same public readback, same fitted head, two native calls, and a maximum
of two output bundles. Actual retransmissions and their utility cost differ;
there is no claim of equal realized wall time. Shuffle is formed only after
every first bundle has been delivered and read back, preserving the exact
empirical scalar marginal. The state-reset intervention executes the numeric
first tick, discards its checkpoint, then executes the zero-drive second tick
from `None`. This explicit research intervention grants no production reset.

| Arm | Mean net return | Empirical CE, gamma 1.5 | Repairs / 256 | Actions different from numeric |
| --- | ---: | ---: | ---: | ---: |
| Numeric state path | 0.30203125 | 0.18706384 | 92 | 0 |
| Zero scalar | 0.22515625 | 0.11927942 | 256 | 164 |
| Shuffled scalar | -0.28000000 | -2.89172560 | 92 | 122 |
| Same-information history | 0.30203125 | 0.18706384 | 92 | 0 |
| Checkpoint reset | 0.22515625 | 0.11927942 | 256 | 164 |

The two prespecified primary mean contrasts, numeric minus zero and numeric
minus reset, are both **+0.076875**, with paired 97.5% percentile-bootstrap
interval **[0.0684375, 0.0846152344]**. These intervals condition on the one fitted
head and synthetic case law; they do not estimate natural-source or training-
seed population uncertainty. Reset changes all 256 second-tick temporal state
digests and 164 continuation actions. Thus the original recurrent state is a
causal mediator in this constructed pipeline. Numeric and the strong history
control make identical decisions in all 256 cases: no unique benefit over an
equally informed non-neural rule is established.

The run produced 1,280 evaluation episodes, 2,752 original native calls
including training, and 9,040 actual media files. Independent post-run auditing
reopened all 8,272 evaluation media files, replayed the original native binary
for all 2,560 evaluation ticks, and recomputed all 1,280 terminal returns. The
768 training media files and their receipts are also archived; the independent
replay count applies to evaluation. All declared chronological checks pass.

## Boundaries

Every actual original-neuron receipt reports `requires_calibration=true` and
`authority=DENY_ALL`. `native_owner_integration=false` throughout. There is no
new owner qualification, candidate admission, host-private-state isolation,
natural speech/video learning, or proof of global portfolio optimality. The
simple scalar-to-state encoding deliberately creates a testable state pathway;
this result alone does not show that such a pathway is necessary or best for
large multimodal models. Direct history is a decisive counterexample to any
claimed exclusive advantage of numeric feedback in this task.

## Reproduce in a fresh destination

Run from the repository root with Python 3, numpy and Pillow installed. A local
Rust toolchain and an offline registry cache containing the pinned dependencies
are required. The prepare step only copies source into a new destination and
does not edit production crates or manifests.

```bash
python -m experiments.multimodal_output_portfolio.repair_20261026.control.neuron_feedback_probe.prepare \
  --repository "$PWD" --destination /tmp/ndu-neuron-build-new \
  --compiler /absolute/rust-toolchain/bin --cached-registry /absolute/cargo-cache/registry
python -m experiments.multimodal_output_portfolio.repair_20261026.control.neuron_feedback_probe.run \
  --output /tmp/ndu-neuron-run-new \
  --build-receipt /tmp/ndu-neuron-build-new/BUILD_RECEIPT.json
python -m experiments.multimodal_output_portfolio.repair_20261026.control.neuron_feedback_probe.audit \
  --output /tmp/ndu-neuron-run-new
```

The externally retained `ndu_neuron_feedback_evidence_20261026.tar.gz` contains
all media, exact executed sources,
the verified native binary, the reduced lock, raw requests and native
state receipts, committed decisions, private outcomes, and fitted parameters.
`POST_RUN_SOURCE_REVISIONS.json` records the subsequent packaging, audit-path,
and formatting fixes separately from the executed source. None changed the
experiment's protocol, learned parameters, policy, scores, or retained rows.
`evidence/ARCHIVE_RECEIPT.json` and `ARTIFACT_MANIFEST.json` retain its exact
9,852,793-byte identity and all member hashes in the repository. The archive
was moved without recompression. `DELIVERY_SOURCE_ADDENDUM.json` additionally
records a guard preventing a repeated invocation from creating a failure
marker inside a previously completed run directory.
