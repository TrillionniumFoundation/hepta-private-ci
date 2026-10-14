# Shared-encoder speech cascade

## Calibrated fast/slow speech execution

`--cascade-control` adds an opt-in research path, mutually exclusive with the
original `--native-control`. It reuses the same frozen Whisper, FusionHead,
80-step AdamW fitting and fixed speaker-disjoint cohort. Audio landmarks are
explicitly padded to 32 slots BEFORE fitting; test lengths do not define the
Head shape. Existing frozen/final/selected and feature-intervention controls
remain and are charged as diagnostic work. The original CLI modes are unchanged.

One shared encoder processes each waveform once in the cascade execution.
All 40 calibration waveforms are also decoded natively, with no labels in the
model API. After existing checkpoint selection, a fixed confidence threshold
is chosen from 0,.5,.6,.7,.8,.9,.95,2. The last value means always decode. A
threshold must match or exceed BOTH always-fast and always-native calibration
correct counts, then minimizes native requests (ties: correct count, grid order).
The same calibration is reused for checkpoints and routing: this is an empirical
rule, NOT independent risk certification, NDU, or a guaranteed quality floor.
The complete route/model binding is sealed before ANY holdout inference.

Each holdout waveform first takes the selected small Head path. Low-confidence
rows lazily call the original decoder with their existing full encoder states;
fast rows do not. The foreground prediction is written before shadow-only work.
To retain the strong all-native comparison, the diagnostic then decodes all
remaining rows. Foreground, shadow and calibration calls/decoder steps are
reported separately: the experiment as a whole does NOT skip those shadow
computations. Raw outputs and both original full-output/terminal-punctuation
scores remain; punctuation scoring never changes the selected threshold.
One transient full encoder state is retained at a time, not a new model/cache.
Foreground timing includes checks/encoding/Head/routing/selected decode but
excludes receipt writes; shadow work and all training are additional costs.

The existing workflow first runs the UNCHANGED native-control study, then runs
`python -m experiments.shared_stem_cell.speech_cascade --root /staged/audio-study`
on its already staged files. No second download occurs, but this is a separate
model load, 240 new encoder calls, another80 training steps and up to80 native
calls (40 calibration +40 holdout including shadow). Do not hide those costs,
claim reused encodings across studies, or treat rerun examples as new evidence.
This is content classification/routing, NOT waveform generation or a production
selector. Missing dependencies or outputs fail; there is no dummy-model fallback.
