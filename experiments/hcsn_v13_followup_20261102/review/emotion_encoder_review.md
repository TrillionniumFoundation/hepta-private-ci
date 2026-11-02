# Independent emotion-encoder CI review

Status: **source review in progress; no pretrained emotion forward or quality
PASS is established by this document.** Earlier ASR evidence remains unchanged.

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

## Required remaining source and actual-CI checks

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
