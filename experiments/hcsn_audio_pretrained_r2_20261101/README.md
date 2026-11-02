# Frozen pretrained speech frontend, separate audio candidate

This additive candidate uses the official TorchAudio2.6.0 CPU
`WAV2VEC2_ASR_BASE_960H` model, followed by fixed C=1 logistic heads. The
94,393,245-parameter encoder remains frozen. The official bundle converts the
checkpoint auxiliary head to its29 CTC labels. Original model/software identity,
download bytes and SHA256 are recorded in `CHECKPOINT.json`; official source
blob identities and output equivalence are checked in `CHECKS_FINAL.json`.

The encoder input is exactly the accepted synchronized one-second PCM prefix.
Its native-rate crop occurs before resampling. Only that bounded signal reaches
the bidirectional speech encoder. Whole-recording normalization is absent.
The fixed1652-dimensional descriptor consists of final-layer hidden mean/std
and four temporal CTC-logit means. Filenames, actors, emotions and targets are
not encoder or classifier features. `DFA=0/IOM=1` is checked independently of
the original cohort's six-way emotion label.

Four sorted-actor folds fit means/scales and C=1 logistic weights on18 actors
and score the other6. The full head uses all288 train clips; neither pooled OOF
recalibration nor development selection occurs. New audio with unchanged R1
nested video/text probabilities trains separate clean3-feature AT and7-feature
AVT heads. Anew+Vpretrained+T is a different prospectively frozen component at
`experiments/hcsn_joint_pretrained_av_r2_20261101`, preserving the primary
V-only attribution that keeps R1 A/T fixed.

Source/protocol publication is locked in `SOURCE_PUBLICATION.json`; target
head publication is locked in `CANDIDATE_PUBLICATION.json`. Development is only
the original72 clips from6 previously exposed actors, after both locks. It is
not a new independent population, open-domain multimodal qualification or a
test of analytical-core advantage. Offline compressed-media decoding also
does not qualify live one-second packet availability.

## External model and portable execution

- [Official model documentation](https://docs.pytorch.org/audio/2.6.0/generated/torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H.html)
- [Pinned TorchAudio source](https://github.com/pytorch/audio/blob/d8831425203385077a03c1d92cfbbe3bf2106008/src/torchaudio/pipelines/_wav2vec2/impl.py)
- [Official weight URL](https://download.pytorch.org/torchaudio/models/wav2vec2_fairseq_base_ls960_asr_ls960.pth)
- [Model MIT notice](https://github.com/facebookresearch/fairseq/blob/ce6c9eeae163ac04b79539c78e74f292f29eaa18/LICENSE)

The model was pretrained on LibriSpeech960h audio and ASR-finetuned using its
transcripts. Official documentation explicitly identifies the redistributed
weights as MIT; TorchAudio software has a separate BSD license. Pretraining
cost and arbitrary actor overlap are not measured here. The377,664,473-byte
checkpoint is external, not included in this source artifact. Its required
SHA256 is `488fd4f16de84438ffc945334278c1b9fb9b7159a806c1080b16111a958c945d`.

The recorded checkpoint path describes the original execution. A portable
bootstrap can put the verified file at the sibling `../upstream_audio/` path
and pass it explicitly; no metadata rewriting is needed. The historical
`acquire.py` command refuses an existing checkpoint metadata record, so a
packaged rerun should use the package's bounded bootstrap downloader or another
bounded official download verified against the SHA above.

From the repository root, using Python3.12 and the recorded scientific runtime:

```sh
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
python -m experiments.hcsn_audio_pretrained_r2_20261101.encoder \
  --manifest experiments/hcsn_audio_pretrained_r2_20261101/TRAIN_COHORT.json \
  --media-root ../video_raw_r2_media --out NEW_TRAIN_FEATURES --split train \
  --checkpoint ../upstream_audio/wav2vec2_fairseq_base_ls960_asr_ls960.pth
```

Keep the original candidate and cached feature identities intact. Existing
feature caches suffice to recompute fixed-head outputs without loading the
external encoder. New extraction outputs must use a fresh directory. Every
source, checkpoint, raw clip and copied cache manifest is checked. Evaluation
refuses additional or missing development clips.

All failed preflight/output-collision receipts and original source copies are
retained. Body extraction CPU excludes ffmpeg children; use the outer wait4
receipt for measured totals. Do not add nested body/fit times a second time.
One second of observation, model inference, startup and media decoding are
separate costs. GPU, device joules and complete pretraining/lifecycle costs
remain unmeasured.
