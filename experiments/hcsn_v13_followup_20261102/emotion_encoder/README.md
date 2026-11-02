# Fixed emotion encoder in an independent execution environment

This source freezes a new actual-model campaign for
`audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim` at revision
`6eba34a2485ea31cb03600241787c3a5edab8626`. The original local Hugging Face
timeouts are not retried and proxy settings are not changed. A dedicated
GitHub Actions push-only branch runs the public official HTTPS acquisition.
At this source checkpoint the new emotion weights have **not been loaded
locally**, and no new emotion-model forward is claimed.

## Exact model and research license

The [fixed publisher card](https://huggingface.co/audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim/blob/6eba34a2485ea31cb03600241787c3a5edab8626/README.md)
specifies a Wav2Vec2-Large-Robust backbone pruned from24 to12 layers and fine-tuned
for dimensional emotion regression. The explicit architecture here is
`Wav2Vec2Model(config)` followed by mean pooling and a1024→1024 tanh/dropout
regression head with three outputs. Arousal/dominance/valence are audit outputs,
not CREMA-D class probabilities. Only the1024-dimensional pooled embedding
feeds the separately fitted six-emotion readout.

`acquire.py` downloads README/config/preprocessor and the official safetensors
from the immutable revision. The weight must have SHA256
`efa5ac1a13b2d2f42182738e44794b1eb4c0cdd221a8b4ae11304c3a5f5fae95`.
Architecture, prefix normalization, and the README's CC-BY-NC-SA-4.0 declaration
are checked; exact metadata bytes/SHA and a pre-inference asset seal are retained.
The license declaration and canonical legal-terms link travel with evidence.
This is research use with audEERING attribution; no commercial or production
license is claimed. Derived features and newly fitted readout artifacts retain
this upstream research-license notice.

There is one attempt per required official file, bounded socket/whole-file
time and bytes, no authentication, mirror or retries. HTTPS redirects are
allowed but only query-free/fragment-free host/path/status are persisted.
Signed URLs, authentication headers and cookies are not logged. Partial failures
retain status, consumed bytes/hash, timing and sanitized errors. The large
upstream weight remains outside the artifact and Git.

`model.py` uses no Auto model or remote code. It constructs the publisher's
explicit graph from sealed local configuration and completely loads local
safetensors. Only the old positional-convolution weight-g/v aliases may be
mapped to modern parametrization keys; collisions, missing/extra keys, shapes,
nonfinite or non-FP32 state all fail before any forward. The graph keeps the
publisher's training-augmentation parameters for checkpoint compatibility;
eval/inference mode disables training behavior after strict loading. Principal
packages are fixed, resolved dependency-wheel identities are retained, and
actual runtime-source identities are recorded. Original pretrained parameter
tensor bytes, including classifier slices, are never exported.

## Actual prepared physical prefixes

`prepare_waveforms.py` has already verified288 genuine historical TRAIN FLVs,
24actors,89,552,339bytes and decoded each physical accepted prefix using the
frozen original decoder. Native audio is cropped at the common audio/video
source origin before resampling. All288 actual waveforms exactly match their
prior frozen PCM identities. Actual source origins are287×0.027s and1×0.067s;
all actual windows have zero padding. Offline full-media preparation does not
establish a streaming decoder or give early source-length information to the
encoder.

The exact float32 (288,16000) NPZ is17,207,799bytes, SHA256
`2dc28d9ac49549f9b550787cbeaf2c8d7e1956942808a0da05443b57d6819709`.
Four bounded transport parts reconstruct that exact file into runner temporary
storage. **Do not add the ignored original `inputs/WAVEFORMS.npz` to Git**;
the parts and manifest already preserve every byte. All source-clock, raw-media,
clip/actor and waveform hashes are retained in `PCM_IDENTITY.json`.

The complete local preparation worker consumed50.540465CPU seconds, including
waited ffprobe/ffmpeg children. Local schema/identity contracts pass1,178 checks,
with no Torch/Transformers/safetensors import or genuine emotion-model forward.
Toy key/shape arrays and metadata are explicitly synthetic. Three separately
retained contract runs consume0.436948+0.481461+0.441233CPU seconds; repeated
checks are not extra coverage. The old fixture-location source and receipts
remain. Transport roundtrip and workflow actionlint/Prettier checks pass.

## Declared real CI campaign

The workflow runs only on a push to
`research/hcsn-v13-emotion-encoder-20261102`; no PR-open event can cancel it.
Exact event-head sparse checkout and Git-blob source/input snapshots precede
execution, including the hidden workflow file. Metadata acquisition and model
execution each have an enclosing waited-worker CPU receipt. Pip setup,
source capture and restoration have separate boundaries; missing complete
project costs, full-family RSS and physical energy are not filled with zero.

One fresh fixed-model worker actually encodes288 waveforms sequentially, one
recording at a time. The first prefix additionally tests two future suffixes
with bitwise equality and invalid accepted-window rejection. This gives290
declared forwards if all complete. Prefix NPZs and hashes/CPU progress are
flushed individually, so cancellation/failure preserves completed work without
pretending an incomplete campaign cost is zero.

A small forward reference preserves accepted/normalized waveform, last hidden
states, pooled embedding and three regression values. In CI, independent
NumPy FP64 mean/dense/tanh/head equations must match the actual Torch output
under the fixed numeric gate; only parameter shape/SHA identities and residuals
are retained. No original classifier tensor is included in the reference.

The unchanged ASR reference's ridge implementation is reused: fixed lambda10,
24leave-one-actor-out fits plus one all-TRAIN fit, six declared emotions, each
fold's normalization and coefficients fitted solely on the other23actors.
Softmax temperature1 remains uncalibrated. No validation/test is opened and no
hyperparameters are selected from this OOF. All new coefficients and predictions
are preserved. The original v6 task's equivalence remains unauthenticated;
semantic binding and genuinely independent new-cohort admission are incomplete.
Executing this pipeline, including a green CI job, cannot by itself qualify
the strong-audio reference or close the original four scientific gates.

The `always()` artifact includes success or failure source snapshots, official
metadata/license identity, dependency manifests, costs, small actual references,
features and new readout weights. Official safetensors stay in runner temporary
storage and are never uploaded. Root will separately download and audit the
actual artifact before updating any execution status.
