# E0 public-pretrained CPU → existing Q24 projection: shadow experiment

**Status: research-only; E0 acceptance remains BLOCKED.** This is a physically executed
partial numerical route, not a trained/selected Hepta Cell. It does not bypass or
modify Neuron V1's input maximum of 512 dimensions.

## What is reused (exact Git identities)

- Existing full **ModernBERT MLM** loader / HF mean Encoder:
  [research/shared-stem-hf-ci-conformance](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/be511bd63aaae8813c415a116d50f01fe54baba5)
  commit `be511bd63aaae8813c415a116d50f01fe54baba5`, tree
  `e2ae2b013e16f7aa3a0babe2869104b28a913132`.
- Existing **versioned low-rank Q24 projector** and Python/native parity Head:
  [audit/stem-cell-p0-freeze](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/d6f35c362289c90427bfbdffd4505d2e535c1b1b)
  commit `d6f35c362289c90427bfbdffd4505d2e535c1b1b`, tree
  `eff00c335408b3931e4316c2b0d4334d7620aee4`.
- Public immutable upstream **ModernBERT-base** revision
  `8949b909ec900327062f0ebf497f51aef5e6f0c8`, raw safetensors
  SHA-256 `340ac08b74eef0d7bdec2d7981a6a3d4249bf0e6aab60634b72ad02c2b8023a9`,
  whole clean snapshot digest
  `43138a5545ce4e7996d91735f2330519a8913304d3abf257f6cfdfbe0541283d`.

The hosted research branch has already executed the real pretrained CPU Encoder, but
not the Q24 cross-branch stitch. **Its historical receipt is not claimed as a pass
for this new executable/commit.**

## Physical read-only path

`public_e0_shadow.py` verifies the exact two source commits/trees and clean
working copies, downloads only the named checkpoint files at the immutable HF
revision, copies them to a clean local snapshot, checks all weight/snapshot
digests **before loading**, loads the real complete MLM model with the registered
Transformers 4.57.1 / Torch 2.10.0 CPU-eager profile and calculates three actual
mean-feature forwards. The frozen public test inputs are two distinct texts and
a repetition of the first.

It then calls **the existing** `LowRankProjectionQ24` numeric implementation on
the resulting 768-dimensional float32 features, producing a 256-dimensional Q24
vector; verifies tie-safe input/shape bounds, repeated-input parity and the
survival of a perturbation to original coordinate 767, so **silent slicing is
not permitted**. Its 2-rank weights are constructed deterministically in the
script as an explicit **synthetic, untrained diagnostic control**. A fixed
synthetic Q24 affine readout runs through the **existing**
`native_bridge.native_logits` mechanism to demonstrate arithmetic parity, but
is not a genuine trained Cell Head or a native Rust Worker call.

Actual source model bytes are rechecked after the computation. Create-only
`shadow.json` includes source and model SHA, numeric vector hashes, observed
forward timing and process-lifetime (not request-level) RSS, along with **false**
for every production/learning acceptance field. Failures are recorded in
`FAILED.json` where the output directory has been reserved. Test fixtures in
`public_e0_shadow_checks.py` are clearly separate from the real pretrained
execution; no test counts as model performance evidence.

Run the opt-in exact-source hosted workflow
[hepta-e0-public-projection-shadow.yml](../../.github/workflows/hepta-e0-public-projection-shadow.yml)
to produce a new artifact and inspect the **actual current SHA's** job conclusion
before any claim. Its access token is read-only and not persisted; it grants no
producer/consumer authority.

## Still blocking E0

1. The diagnostic projector is **not** a data-trained, independently selected,
   source/normalizer-compatible production projection. A task split and measured
   representation loss versus unprojected 768-D features are required.
2. The Q24 readout is **not** a selected trained Head; the native trusted
   `NeuronFeatureDriver` path and verified CAS model-load/final-use evidence
   remain missing. Calling the Python arithmetic helper does not invoke a Worker.
3. No actual `InferenceControlModelPort -> NeuronRuntime` production caller,
   durable Q24 Tick/checkpoint/AnchorWitnessStore CAS, or crash/revocation recovery
   is established by this study.
4. No independent task outcome, future-time NDU utility or budget-matched
   E1/E2 comparison was performed. Complete CPU/GPU FLOPs, true request p95/p99,
   real throughput, thermal power and complete process-tree RSS are unknown.

No automated Cell Split, product activation, selection, promotion or release.
