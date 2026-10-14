# Frozen acoustic tower and a lightweight spoken-content Cell

This is the speech understanding increment in the existing six-experiment
research program. It reuses `media_execution.LocalTowers`, `FusionHead`, and
`calibrated_fusion`; no second execution owner, model service or NDU subject.
The text/image calibration profile remains unchanged. Standalone audio is now
accepted explicitly; audio+image/video fusion is NOT silently admitted.

## Locked development profile

FSDD v1.0.10, source commit `d6938f9bf1545aa66d8489fc9f1385a7abd64282`, contains
English spoken-digit recordings. The source is
https://github.com/Jakobovski/free-spoken-digit-dataset/tree/d6938f9bf1545aa66d8489fc9f1385a7abd64282
and is distributed under CC BY-SA 4.0; its exact README attribution is retained.
The derivative WAVs preserve attribution and share-alike licensing. Changes are
explicit: 8 kHz mono PCM16 -> 16 kHz, scipy polyphase FIR (Kaiser 5, zero padding),
rounded and clipped back to PCM16. No rescaling, silence trimming or implicit
resampling in the inference loader. Each receipt records clipping and PCM hashes.

Frozen model: `openai/whisper-tiny.en`, Hub revision
`60c8e2222f9c090f473c11c73926baf0a56ed3f9`. Reuse the existing complete-publisher-
file and actual-tensor checks, safetensors only, no remote code or pickle fallback.
The whole encoder-decoder is resident even though only its encoder runs. All
resident parameters count as model storage; this is NOT a tiny-Head-only cost.

Indices 5..8 of all ten digits from george/jackson/lucas/nicolas form 160 training
rows; theo contributes 40 calibration rows; yweweler contributes 40 holdout rows.
This deliberate SPEAKER-DISJOINT profile is NOT FSDD's conventional per-recording
split. Released filename labels define class balance, not answer-blind sampling.
Do not interpret speaker identities as learned attributes: only audio enters the
tower, and generated filenames are opaque hashes. Task is digit CONTENT only.

All 240 source Git blobs are checked against a reconstructed, pinned recordings
Git tree. Byte budgets, missing records, malformed PCM and duplicate decoded
audio fail without a replacement or reduced denominator. Source speaker groups
are checked by the existing cross-fold leakage gate. One held-out speaker is
not a population study; source/pretraining overlap and temporal independence
remain unverified. The metadata speaker split alone is not independent attestation.

## Shared learning and controls

The existing Whisper extractor supplies declared lossy 32-time-bin means.
Only the existing small connector/readout is trained, once for 80 AdamW steps.
Checkpoint choices are 0,1,2,5,10,20,80 under the OLD correct/NLL/earlier rule;
all 80 updates still run. Same-initialization frozen and final models remain.
Selection is sealed before holdout Head execution, predictions before scoring.
The existing media loader reads released labels in one process; it is not an
independent evaluator boundary. No holdout targets enter fitting/selection APIs.

Existing same-model mask and within-holdout feature-rotation probes remain;
they are NOT waveform edits or causal proofs. Exactly one acoustic tower is
shared and frozen. This supplies a new modality to the common feature/Cell
interface, not proof that the frozen text Stem itself learned audio or that
cross-modal reasoning, speech/video generation or all six goals are complete.

```sh
python -m unittest -v experiments.shared_stem_cell.test_public_audio
python -m experiments.shared_stem_cell.public_audio --output /new/public-audio
```

`hepta-shared-stem-audio.yml` executes actual public acquisition/model inference,
required stock-HF API tests and the relevant inherited regressions. It neither
weakens nor replaces the existing shared-Stem/full-repository jobs. Unavailable
network/weights/dependencies are failures, never synthetic fallbacks. Test fixture
waveforms/towers are explicitly synthetic and do not constitute model results.
Predictions, model-load/encoding/training costs and provenance are retained;
missing energy/FLOPs/peak-RSS remain null. No activation or production selection.


## Same-encoder native transcription control

Run the existing command with `--native-control` to evaluate the frozen original
Whisper decoder on EXACTLY the same 40 held-out recordings as the learned Cell.
The data/model pins, 80-step fitting, checkpoint rule and original controls do not
change. This control never supplies a training target, digit vocabulary, speaker
name, filename, prior transcript or task-specific prompt to generation.

`speech_control.py` wraps the original tower without changing its pooling or
forward arithmetic. On held-out rows only, a temporary forward hook retains the
actual complete encoder output; `generate(encoder_outputs=...)` consumes it once.
An encoder pre-hook rejects any attempt to re-encode; decoder invocations are
counted. The saved state is discarded after the utterance, with no cross-utterance
cache or context. The original full Whisper model remains resident (not a second
model). Native decoding is greedy, one beam, at most 16 new tokens, no sampling,
temperature fallback, timestamps or prior-text conditioning. A required stock-HF
random-model test compares tokens to ordinary full generate(), counting one
encoder invocation for each path. That is API parity, not speech quality.

All native utterance records and their aggregate prediction seal are written
before hold-out Head execution/scoring. Original raw text/tokens, per-record
started receipts, decoder calls, latent/landmark hashes and decoding costs are
retained. The native baseline cannot change the calibrated Cell selection.
The scores compare the SAME rows: exact whole digit/English digit word after
whitespace/case normalization, and a separate preregistered variant permitting
one terminal `.`, `!` or `?`. No substring extraction, synonyms, transcript repair
or successful-only filtering; empty/unparsed output counts wrong in the full
denominator. No acoustic synthesis or open-domain reasoning is claimed.

This is not automatically an equal-quality resource win. The end-to-end media
`encoding` span INCLUDES native decoding in this mode and is explicitly marked
as such; decoder-only time is reported separately. Common Encoder cost cannot
be subtracted or omitted to claim total speedup. Full resident model parameters,
small-Head fitting and native autoregressive work must be considered separately.
One held-out speaker and four recordings per digit remain a small development
profile, not independent population/retention evidence. Original mode without
the flag retains its exact training/prediction path.
