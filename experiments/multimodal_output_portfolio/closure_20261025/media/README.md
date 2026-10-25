# Learned multimodal media closure study

This directory contains executable training, inference, serialization and
independent audit code. It extends the recovered shared neural generator with
trained acoustic/video ingress and actual learned acoustic and temporal output
heads. All four outputs are emitted as real UTF-8, PNG, PCM WAV and lossless
audio/video MP4 files, then reopened and scored.

The primary final candidate is the **trained canonical-voice VAE with the
original two-second clock**. Its immutable selection is recorded in
`FINAL_PROTOCOL.json` (SHA-256
`66db720064d45fc2e38cc9f8123767f51bfb82029767a093062971e05aff3a34`). The original
failure stages and the separate pretrained Piper reference are retained. The
Piper reference is not the primary final candidate.

## What the executable model does

| Input route | Actual observed material | Learned path into the shared state |
| --- | --- | --- |
| `image` | PNG containing two real source images, reparsed from disk | Existing image encoder; public `keep` command and unknown textual hints |
| `text` | Reparsed UTF-8 task string in the declared digit grammar | Existing learned token embedding/fusion, with missing-image masks |
| `audio` | Two actual FSDD recordings, serialized and reparsed as PCM | STFT, label-free mel/voice-time normalization, trained CNN, posterior-weighted shared token embedding/fusion |
| `video` | Actual MP4 decoded to twenty ordered frames constructed from the real source images | Trained frame CNN and temporal GRU, then the same shared posterior-to-state bridge |
| `audio_video` | Both observed acoustic and temporal channels of the same task | Equal-weight average of the two learned posteriors, then shared state fusion |

Every route uses the same source-task order and evidence opportunities. Text
prompts and aligned speech/video views are deliberately constructed from digit
semantics; this is a bounded experiment, not a corpus of naturally aligned
unrestricted multimodal requests. Source labels are used by task construction,
training or offline scoring. `generate_state` accepts only observed tensors and
does not accept a Target or an evaluator.

The frozen NDU-trained core takes the fixed `refine_semantic`, `couple` action
prefix. Its neural decoders emit the caption and image. The acoustic VAE consumes
the current predicted semantic probabilities and a zero latent code that was
explicitly trained for inference. It predicts a spectrum; Griffin–Lim constructs
the waveform. No recording is retrieved during generation. The video head uses
a learned recurrent spatial displacement field and the *same emitted neural
image panels*, producing the twenty sampled frames. The motion is learned by
pixel reconstruction on real training images. It is a small image-to-video
model, not natural-video generation or repeated-frame playback.

Hard and soft conditions use the identical shared state. The primary hard
condition discretizes its **predicted** semantic code; it never uses the target
digit. In the primary final protocol the nominal population is 64 source pairs
(128 distinct image sources), reused by five input modes and two conditions:
640 output bundles do not constitute 640 independent samples.

## Sources, auditors and qualification

The FSDD archive is fixed to commit
`26eb9aaf76e81b692f806f9140c2d2777410d7a1` and SHA-256
`9a68686ad29274bd0affde81b244953e677c9d7048dfb8acaf1168d7758bafab`.
Recording indices 20–49 are generator training, 10–14 train the reward model,
15–19 train the independent acoustic auditor, 5–9 are development validation,
and 0–4 are final test. These roles are recording-disjoint; the same six speakers
occur across roles. The selected acoustic output model uses only the 300
`jackson` recordings in the original generator role. It does not establish
unseen-speaker generalization.

The independent mel auditor and input CNN are frozen before final access. The
auditor is absent from the acoustic trainer's gradient graph and checkpoint
loads. The new image and task sources are the allocator's reserved `media`
range, not recycled historical development data. The loader verifies the exact
allocation, model/source pins and qualified development run before releasing
the new role. Final outcomes are never used for further fitting or threshold
changes.

The original thresholds remain: real acoustic auditor and acoustic ingress
accuracy at least 85%; conditional generated audio 80%; conditional video frame
accuracy 90%; joint output success at least 75% separately for every input mode;
at least six distinct frames per event; complete physical codec readback.
An output's joint success requires a correct neural caption and relation, both
image panels, both audio events, and **every one of its twenty video frames**.
Valid timestamps alone cannot make an output successful.

Negative controls begin from a genuinely successful, unequal-digit bundle.
Physical silence, swapped audio events, swapped video events, repeated frames
and a missing modality are recreated and re-read. Event swaps retain legitimate
container timestamps but must fail semantic event alignment. Repeated frames
retain correct digit semantics but must fail the movement requirement.

## Retained development evidence

| Attempt | Independent real-speech auditor | Acoustic ingress | Conditional audio | Conditional video | Main outcome |
| --- | ---: | ---: | ---: | ---: | --- |
| Original training / development-001 | 65.33% | 77.33% | 60% | 93% | Unqualified auditor; all four original routes had zero strict joint success |
| Robust CNN / development-002 | 80.00% | 88.00% | 100% under that unqualified auditor | 96% | Video `3`/`8` ambiguity; joint 50% in four routes and 33.33% in audio |
| Mel auditor and coupled motion / development-003 | 94.67% | 98.67% | **20%** | 100% | Stronger independent audit invalidated the earlier apparent acoustic success |
| Canonical-voice prior repair / development-004 | 94.67% | 98.67% | 100% | 100% | All unchanged primary gates pass; joint image 75%, video 91.67%, text/audio/audio-video 100% |

The acoustic failure was investigated, not discarded. Thirty actual training
recordings, their Griffin–Lim reconstructions and voice-time-aligned
reconstructions each scored 30/30. The failed VAE scored 2/10 both before and
after waveform reconstruction. On sixty training-source examples its posterior
mean reconstructions reached 71.67%, versus 20% for its zero-latent inference
prior; posterior standard deviation averaged 0.0271. These observations are
consistent with a substantial posterior/prior mismatch and poor prior content.
They do not isolate every causal contribution of the subsequent repair.

The prospective repair uses a single declared voice, a label-free time
alignment, explicit zero-prior reconstruction loss, a ten-times larger KL
coefficient, and a separately trained reward model applied after differentiable
waveform reconstruction. Its real loss is `0.5 posterior L1 + 0.5 zero-prior L1 +
0.005 KL + 0.05 reward CE`; the independent auditor is not optimized.

Frozen Whisper is a supplementary measurement, not a replacement primary gate.
On the same twelve development source pairs, its strict pair parsing scored
9/12 on real input speech, 0/12 on the failed VAE and 7/12 on the repaired VAE.
This supports retaining a perceptual-quality limitation, even when the
qualified in-domain mel criterion passes.

## Separately identified pretrained neural reference

The available Piper model is `en_US-ljspeech-medium` at pinned revision
`5041a7a49ae5b3a0f30e6837769eb03fdbb231bd`; it is not the unavailable
`libritts-high` asset named by a different old adapter. Every reference call
runs actual ONNX neural synthesis from the predicted shared semantic code.
No recorded waveform or expected target is supplied to the synthesizer.

The original two-second bare-word reference failed strict Vosk/Whisper consensus
on four of ten pairs. A separate, explicitly four-second profile uses the
uniform carrier `The digit is {predicted word}.` and twenty learned video frames
at five fps. Its initial dual-ASR profile also failed. A new independently
registered Whisper-primary profile passed all-class carrier controls and the
five waveform anti-hallucination controls, but its full independent ASR
qualification failed: over all 300 old validation recordings, word-event
accuracy was 31.33% for Whisper and 23.33% for Vosk. On the canonical carrier it
was 100% and 50%, respectively. These domain-specific results are reported
separately. The final runner prevents this reference from opening new sources
without the complete ASR qualification. It is retained as a mechanism study,
not as a substitute for the canonical VAE's final conclusion.

## Execution, publication and limits

`train.py`, `repair.py`, `refine.py` and `acoustic_repair.py` are the successive
actual training stages. `evaluate.py` performs the guarded development/final
generation and physical audits. `network.py`, `repaired.py` and `coherent.py`
contain the learned heads; `negatives.py` applies physical controls.
`wave_reference.py`, `wave_worker.py` and `carrier_media.py` implement the
separate pretrained reference; `qualification/asr.py` measures its independent
observer eligibility. `external.py` is the supplementary target-free Whisper
audit of closed generation outputs.

The checked-in code and prospective protocols are the executable source.
Historical `frozen-source` directories inside the run evidence preserve the
exact bytes used by earlier attempts; they are historical snapshots, not current
entry points. `ASSET_INVENTORY.json` identifies existing runtime weights, corpora
and codec binaries by hash. No large Python environment needs to be copied.
`COST_SCOPE.md` describes the precise wall/CPU accounting boundaries.

This work does not establish a general all-modal foundation model, natural
video, human perceptual quality, unseen-speaker generation, a globally optimal
output portfolio or end-to-end NDU training of every codec. It makes the bounded
multimodal forward process concrete, measurable and falsifiable. The control
and training comparisons elsewhere in the closure study must establish their
own NDU benefit; this media study does not imply such a benefit.
