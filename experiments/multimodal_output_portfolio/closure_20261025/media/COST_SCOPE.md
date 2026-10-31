# Measured execution boundaries

The primary final run uses the trained canonical-voice VAE and the original
two-second media profile. It contains 64 source tasks, each reused by five input
routes and two conditions, for 640 emitted four-modal bundles. The independent
sample count is 64. Hard and soft conditions reuse the same encoded shared state.

## Per-output fields

| Field | Included | Excluded or qualification |
| --- | --- | --- |
| `execution_wall_ns` | Input-state neural forward, fixed `refine_semantic` and `couple` steps, shared text/image decoding, acoustic spectrum synthesis, 24-step Griffin–Lim, learned recurrent motion and spatial sampling, PNG/WAV/UTF-8 writing, actual MP4 encoding, and the first full codec/sample/PTS readback | Independent outcome scoring, the extra content-check readback, row JSON writing, each source pair's input-bundle serialization/readback, and one-time model/source loads |
| `audit_included_wall_ns` | All of the above plus the independent image/speech observer, full video frame scoring, and extra content-check readback | Row JSON persistence, each source pair's input-bundle serialization/readback, and one-time loads |
| `python_cpu_ns` in each row | Main-process CPU from the beginning of modality rendering through auditing/content checks | The preceding common-state encoding, child codec CPU, row persistence; this is not a complete per-request CPU measure |
| `output.codec_wall_ns` | Artifact serialization and the encoder subprocess | Neural generation, subsequent readback and independent scoring |
| `output.verification_wall_ns` | First actual ffprobe/ffmpeg reopening and byte/sample/PTS checks | Additional reopening during independent audit and content checks |

The shared encoder time is included in both hard and soft row wall measures
although the state is computed once for their paired comparison. Therefore
adding row times is not a measurement of actual process cost. The whole-run
receipts below are authoritative for incurred work.

## Whole-run fields

`summary.wall_ns` begins after creating the new output directory and includes
source/model identity checks, source loading, observer qualification, all input
bundle serializations, all output bundles, audits, negative controls and final
identity checks. Python imports and argument parsing before that timer, and the
final summary-file write after the time value is formed, are outside it.

`summary.python_cpu_ns` measures the corresponding main Python process.
`summary.codec_children_cpu_seconds` is the difference in user-plus-system CPU
from `resource.getrusage(RUSAGE_CHILDREN)` across this run. In the primary VAE run
these children are ffmpeg/ffprobe. Adding those child seconds to Python CPU
seconds gives the measured total process-tree CPU over the stated boundary.
Other concurrently running experiments are not included. The observed wall time
can nevertheless be affected by shared machine load.

The separately identified Piper reference uses a persistent neural TTS/ASR
worker as another child. Its `children_cpu_scope` explicitly says that the same
historically named child-CPU field includes codec, neural synthesis and offline
ASR. Its worker closes before the child CPU census, and its receipts report
actual ONNX synthesis calls and observer cache hits. Only repeated independent
observations of identical PCM bytes may be cached; generated waveforms are not.

PyTorch training and inference are restricted to one CPU thread. Neural Piper
and Whisper workers also use one thread. MP4 encoding requests one thread.
Historical codec readback commands do not override the decoder library's own
thread choice; all measured child CPU is charged. None of these engineering
timings constitutes a proof of an optimal NDU computation allocation.
