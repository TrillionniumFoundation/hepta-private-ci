# Independent emotion-encoder CI review

Status: **reviewed for real CI execution; no remaining blocking source finding
in this scope. Actual pretrained emotion forward and quality remain pending.**
Earlier ASR evidence remains unchanged. Reviewed source hashes are recorded in
`EMOTION_SOURCE_REVIEW.json`; this is source review, not a completed CI receipt.

## Primary architecture and preprocessing

The review opened the publisher's fixed-revision
[model card](https://huggingface.co/audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim/blob/6eba34a2485ea31cb03600241787c3a5edab8626/README.md),
[config](https://huggingface.co/audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim/blob/6eba34a2485ea31cb03600241787c3a5edab8626/config.json),
[preprocessor](https://huggingface.co/audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim/blob/6eba34a2485ea31cb03600241787c3a5edab8626/preprocessor_config.json),
and [safetensors pointer](https://huggingface.co/audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim/blob/6eba34a2485ea31cb03600241787c3a5edab8626/model.safetensors).

The official model uses a 12-layer, 1024-wide Wav2Vec2 encoder and a custom
1024-to-1024 tanh regression head with three outputs. The final transformer
states are mean-pooled. The three outputs represent arousal, dominance and
valence; they are not CREMA-D's six emotion labels. Input is 16 kHz audio with
per-input normalization. Its source config includes stable layer normalization,
16 attention heads and convolution bias. The 661 MB safetensors SHA256 is
`efa5ac1a13b2d2f42182738e44794b1eb4c0cdd221a8b4ae11304c3a5f5fae95`.
These observations bind the intended architecture; they do not show that its
weights have yet been downloaded or executed in this campaign.

The generic web auto-loader snippet is not sufficient to define the custom
head. Actual loading must account for every parameter with exact shapes and a
strict complete state load, before any inference. Constructor initialization
is not an admissible fallback. Old weight-normalization `g/v` keys may require
the documented modern parametrization compatibility conversion; mappings must
be one-to-one and reject collisions or unconsumed keys. PyTorch documents this
[compatibility](https://docs.pytorch.org/docs/main/generated/torch.nn.utils.weight_norm.html).

## Actual waveform-preparation source inspected

`emotion_encoder/prepare_waveforms.py` uses the already frozen historical TRAIN
cohort, original decoder and executed waveform identities. It verifies all
288 unique records and 24 actors, checks original media bytes/SHA, re-decodes,
and requires each resulting waveform and complete clock dictionary to match
the prior executed identity. The model is not run during this preparation.

The inherited decoder computes the joint origin as the later of audio start
and first video timestamp, checks full video/native-audio window availability,
crops native PCM first, and then resamples the accepted window. Metadata is
kept outside the encoder input. This is offline preparation, not streaming
decoder qualification or an early-EOF inference input.

Read-only examination of the prior 288-record identity finds zero output padding
for all records, native crop length 44,099 at 44.1 kHz, origins 0.027 seconds for
287 records and 0.067 seconds for one record. The general decoder allows tiny
rounding-related boundary padding; its actual zero count must not be turned
into a universal guarantee that arbitrary shorter media can be admitted.

## Final source review findings and limits

One blocking publication-boundary issue was found and corrected before CI:
`campaign.py` initially persisted the official pretrained classifier tensors
in `HEAD_REFERENCE_WEIGHTS.npz`. An entire raw artifact ZIP later published to
Git would have carried those upstream parameter bytes despite excluding the
661 MB checkpoint. The final source instead recomputes mean pooling and the
dense/tanh/head equations in memory using NumPy FP64, checks the declared
numeric gate, and preserves only shape/SHA/error evidence. It does not export
any pretrained parameter slice. The new six-emotion ridge heads are separate
user-trained parameters and remain retained.

The self-written model matches the fixed publisher architecture. All actual
asset bytes are sealed before graph construction/inference; weight identity,
all keys, shapes, FP32 finiteness and strict load must succeed. Only the exact
legacy positional `g/v` aliases are canonicalized, with collision rejection.
The original augmentation config is retained for state compatibility; eval
mode disables its training behavior. Eager CPU attention is declared.

Prefix cropping precedes the local feature extractor. Actual future-suffix
and invalid-window controls are scheduled before readout. The first real
hidden sequence and regression outputs have an independent NumPy mean/head
check. At success, 288 recording forwards plus two future controls account
for the declared 290 calls; no synthetic local contract is counted as one.

The actor-OOF loop uses only the sealed TRAIN records and 1024 pooled features.
Its reused ridge function recomputes mean/scale/coefficients from each fold's
23 training actors. Targets and actor/clip metadata select supervision/folds
and are not model features. Fixed lambda 10 and temperature 1 do not provide
probability calibration or independent qualification.

The dedicated push-only workflow binds checkout to the actual event head,
uses pinned actions and a fresh pinned scientific environment, restores the
byte-exact waveform transport, and runs official acquisition and model/readout
in separate waited-worker cost envelopes. The model is offline after explicit
acquisition. Source/input Git blob snapshots include the hidden workflow;
failure progress and receipts are uploaded with `always()` and hidden files.
The official checkpoint stays in runner temporary storage outside the artifact.

No new local real-emotion forward was executed by this reviewer. The author's
1,178 local checks deliberately forbid model-runtime imports and validate
schema/identity/transport contracts, not downloaded emotion weights. Actual
runtime installation, acquisition, strict loading, numerical controls, all
prefixes, readout and complete artifact verification remain real CI gates.

The following conditions must remain true in the actual downloaded artifact:

- Fixed revision and actual downloaded SHA are required. Preserve original
  config/preprocessor/model-card/license bytes and hashes. Disable remote code,
  implicit secondary model downloads and random/missing-parameter fallbacks.
- Crop the accepted waveform before normalization. Normalize that prefix alone;
  append-future NaN/finite controls must leave accepted tensors invariant.
  Short/nonfinite accepted windows must reject before model forward.
- Use the declared official mean-pooled descriptor. Preserve per-prefix raw
  output identity and progress, including partial failures. Do not relabel three
  regression dimensions as a trained six-class reference.
- Fit only the fixed 288 historical TRAIN records with 24 actor-held-out folds,
  fixed lambda 10 and training-actor-only per-fold normalization. Metadata,
  filenames, actor IDs and labels must not be encoder or ridge input features.
  OOF is previously exposed development evidence; it is not new confirmation.
- Pin the actual runtime and checkout. Keep download redirect queries and signed
  URLs out of logs, receipts and public artifacts. Record status and safe host/path
  metadata instead of dumping headers or exception objects containing secrets.
- Use complete waited-worker CPU envelopes for preparation/encoding/readout,
  preserve failed attempts and identify excluded setup/network/history costs.
  Actual device energy and complete-family memory must not be imputed.
- Preserve exact used source/input snapshots, including the hidden workflow,
  in an `always()` artifact with `include-hidden-files: true`. Official large
  weights remain external pinned assets, not Git payloads.

The existing ASR three-forward CPU 11.846144 seconds and its 36.46% actor-OOF
result remain separate unchanged evidence. A new emotion-pretrained candidate
uses a new predeclared representation; success of a download or a source audit
cannot promote it to strong-reference or independent-cohort qualification.
