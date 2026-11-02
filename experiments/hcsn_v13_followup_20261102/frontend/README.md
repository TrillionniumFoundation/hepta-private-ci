# V13: actual pretrained audio, followed by TRAIN-only emotion development

This round found a newly available genuine pretrained speech checkpoint in an
adjacent, already completed acquisition. It is **TorchAudio2.6.0+cpu
WAV2VEC2_ASR_BASE_960H**, not the unavailable audEERING emotion checkpoint and not
the missing original v6 head. Its actual 377,664,473 bytes have SHA256
`488fd4f16de84438ffc945334278c1b9fb9b7159a806c1080b16111a958c945d`, matching that
acquisition's retained CHECKPOINT record. This hash was first observed during
that acquisition; it is not represented as an independently signed upstream hash.

The [official TorchAudio2.6 documentation](https://docs.pytorch.org/audio/2.6.0/generated/torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H.html)
identifies a base Wav2Vec2 model pretrained on LibriSpeech960h and then ASR
fine-tuned on the corresponding transcripts. It explicitly permits redistributed
weights under MIT, distinct from TorchAudio's software license. Its ASR provenance
does not establish emotion or audiovisual binding accuracy.

`strong_audio.py` verifies size/SHA before loading. It calls the exact installed
official bundle factory with its loader replaced by a local-file-only function;
the factory's strict state_dict loading and auxiliary-axis conversion remain.
No remote code, network model fallback, or random-weight fallback is allowed.
Pinned Torch and TorchAudio are both2.6.0+cpu. Runtime sources and the accepted
waveform are sealed before actual execution in `FORWARD_PLAN.json`.

`forward001/` executes three real pretrained forwards on the retained V12
16kHz native-audio-origin one-second waveform. Appending NaNs or an adversarial
finite suffix outside the accepted16000 samples leaves hidden states, CTC logits
and the1536-dimensional descriptor bitwise identical. NaN inside the accepted
window, a short window and incorrect checkpoint bytes are rejected. Complete
waited-worker CPU is **3.314803 seconds** in `cost_forward001/`; its inner timer
is contained in that number and must not be added again.

## Verified reused TRAIN input

`reused_train001/` preserves exact copies of the adjacent encoder source,
acquisition/source-publication records and prepared TRAIN cache, approximately
3.7MB. The 377MB model is read in place, not duplicated. Source publication
`6c3eabfcab18dd9feda400a7b470f4c646230084` preceded that cache extraction.
`COPIES.json` identifies every copied file's original path, bytes and SHA.

The cache has288 recordings,24 historical TRAIN actors, both phrases and six
emotions for each actor. All288 genuine FLVs, totalling89,552,339 bytes, were
rechecked against the frozen TRAIN cohort. No validation or test records were
loaded. `cache_contract.py` checks every complete descriptor/CTC row hash and
all raw identities; it then actually decodes the lexicographically first TRAIN
FLV and re-executes the strict local encoder. Its shared audiovisual source
origin is0.027 seconds, so this replay's physical accepted window differs from
the native-audio-origin V12 smoke waveform. Native PCM is cropped before
resampling, exactly as the retained preparation source specifies.

That actual synchronized-prefix replay matches all1536 used descriptor values
bitwise, with maximum absolute difference0. All288 full-cache row hashes and
all288 first1536-coordinate descriptor hashes are unique. `cache_contract001/`
retains the actual waveform, hidden/logit/descriptor and provenance. Its complete
waited-worker CPU is **7.875889 seconds**, including decoder children. The two new
nonoverlapping execution envelopes therefore total **11.190692 CPU seconds**.
The original288-clip feature preparation has a separate retained107.396369 CPU
second receipt; it is reused setup, not zero cost or new inference here. Weight
pretraining, unmetered development, full-family RSS and device energy remain
unmeasured in this frontend stage.

## Frozen emotion-head protocol

`PROTOCOL.json` and `emotion_readout.py` declare one fixed lambda10 centered
dual-ridge readout. Only the first1536 cache coordinates—final hidden mean and
population standard deviation—are used. CTC coordinates, transcripts and the
original binary sentence targets are excluded. Emotion targets are checked
TRAIN metadata with fixed order ANG/DIS/FEA/HAP/NEU/SAD.

There are24 leave-one-actor-out folds. Each fold fits normalization and all
coefficients solely on the other23 actors; the held actor has12 recordings,
two per emotion. One final all-TRAIN head is saved separately, giving25 actual
fits. There is no hyperparameter search or fitted-training adoption score.
Softmax at temperature1 is explicitly uncalibrated; OOF accuracy, per-actor
support, NLL/Brier and confusion are development descriptions.

`SOURCE_FREEZE.json` binds code, protocol, successful real-forward proof and
exact input bytes. The run refuses to start without a corresponding remote
`SOURCE_PUBLICATION.json`. At this source-freeze stage formal OOF fits have
**not started**; later results must be reported separately rather than silently
changing this checkpoint. No old test or independent confirmation cohort is
opened, and no result can qualify the original v6 five-class/binding task.

The current original-v6 GitHub lookup still returns422 for its exact commit and
no matching hcsn-v6 branch. `ORIGINAL_ASSET_LOOKUP.json` records this limited
observation; it is not proof of global absence. The complete historical exclusion
ledger and genuine new independent recordings remain unavailable. This new
pretrained-encoder execution closes an availability/execution gap, while strong
audio-reference quality and original front-end admission remain HOLD.
