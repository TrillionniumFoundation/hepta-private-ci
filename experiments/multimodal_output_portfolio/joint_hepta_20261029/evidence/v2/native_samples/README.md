# Original native development output samples

These are twelve **original delivered files**, copied byte for byte from the
completed [run 41055922354](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41055922354).
They were not regenerated, re-encoded, resized, denoised or selected for quality.

## Fixed selection

The sample uses the first preregistered training configuration (seed 17, width
32), then **source 0 / draw 0** from each of the teacher, student and ordinary
candidates, in that order. This preservation choice uses the registered order,
not observed outcomes. The native episodes reuse the existing
`controller-v2-development` source and RNG. They are engineering execution
evidence, **not independent quality confirmation** or a pure operator comparison.

| Candidate | Actual serving strategy | Image | Audio | Video | Text |
| --- | --- | --- | --- | --- | --- |
| Teacher, `hepta_dynamic_risk` | Bounded critic planner | [PNG](teacher/image.png) | [WAV](teacher/audio.wav) | [GIF](teacher/video.gif) | [UTF-8](teacher/text.txt) |
| Student, `distilled` | Greedy actor | [PNG](student/image.png) | [WAV](student/audio.wav) | [GIF](student/video.gif) | [UTF-8](student/text.txt) |
| Ordinary, `ordinary_dynamic_risk` | Sampled dynamic actor | [PNG](ordinary/image.png) | [WAV](ordinary/audio.wav) | [GIF](ordinary/video.gif) | [UTF-8](ordinary/text.txt) |

## Interpretation

This is a **tiny synthetic restoration** mechanism: 16 x 16 images, four GIF
frames, 1,024 mono 16-bit PCM samples at 2,048 Hz, and two categorical ontology
labels serialized as text. These are not natural semantic generation samples,
open-domain speech or language, or evidence of a full-scale multimodal model.
The generator executes in Python/Torch under the actual native owner guard;
the trained backbone has not been ported into the native diagnostic readout.
The source-0 episodes include owner reopen and same-Python-process tensor
restoration. No new episode, training update or confirmation source was used
for this collection. The development benefit and natural-observer gates remain
unpassed.

## Byte provenance

The full original ZIP artifact is `12976673914` (7,946,719 bytes), SHA-256
`c6c065c015668f6ca218cb7101c495b35ba223d2587394eb40fc50b4c90d9c9a`.
Its size and digest were independently verified before the selected members
were read. No bulk extraction, model copying or checkpoint copying was used.

[MANIFEST.json](MANIFEST.json) records every original archive path, byte count
and SHA-256; the matching raw trajectory output hash; source, input, model,
policy, profile and RNG identities; and the original native evidence. All
twelve media hashes agree with both the raw trajectory and the original
compact archive input inventory. The three trajectory byte strings also agree
with their already-preserved `TRAJECTORIES.tar.gz` members and native result
digests. The copied files were read back and compared byte for byte.

Only these twelve output files are retained in this sample directory. The
existing compact evidence retains the full trajectory/checkpoint records;
the other original output files remain in the separate full Actions artifact.
See [the complete v2 report](../RESULTS.md) for the full-panel outcomes and cost
boundaries. Displaying these samples does not change any acceptance result.
