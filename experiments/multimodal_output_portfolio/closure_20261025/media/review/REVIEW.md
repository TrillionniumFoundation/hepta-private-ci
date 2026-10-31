# Independent review of the final media experiment

This review found no blocking implementation or evidence-integrity issue in
`final-001`. The result supports a bounded, actual four-modal generation and
serialization experiment under the frozen point gates. It does not establish a
general optimal NDU controller or unrestricted audio/video capability.
In particular, supplementary independent Whisper scoring on the same 64 source
pairs recognizes only 22/64 generated digit pairs, versus 55/64 real input pairs.
The passing local MelSpeech gates must be reported alongside this negative
result; they do not establish natural speech intelligibility.

The review was read-only with respect to candidate code, protocols, models and
the completed experiment. It inspected existing files, independently rehashed
the final media, recomputed the sample census and success fractions, and decoded
existing development negative-control files. It did not train, generate another
sample, or reopen an unused source allocation. The two machine-readable records
are [AUDIT.json](AUDIT.json) and
[NEGATIVE_READBACK.json](NEGATIVE_READBACK.json).

## Frozen identity and completed output census

`FINAL_PROTOCOL.json` has SHA-256
`66db720064d45fc2e38cc9f8123767f51bfb82029767a093062971e05aff3a34`.
All 55 pinned files matched. The 30 runtime source files matched both their
registration hashes and the execution's frozen-source copies. All 12 selected
runtime assets matched the protocol. Registration followed protocol freeze by
12,383,951,723 ns. The completed summary has SHA-256
`45c84618834397ed4353c6b0618d0e0e052d27c8bc3037ee576b2d3969c838ae`.

The completed run contains exactly 64 allocated source pairs, 128 unique MNIST
images, five input routes and two conditioning choices: 640 emitted bundles.
The independently rehashed files comprise 256 input files and 2,560 output files,
all matching their recorded SHA-256 values. The exact source/mode/condition
census contains no missing or repeated cell. Each of the 320 hard/soft pairs
uses the same shared state and posterior, with identical base image and text
outputs. These are paired conditions; the independent source count is 64.

The reported joint-success fractions were recomputed from the output rows:

| Input route | Hard successes | Soft successes | Denominator per condition |
| --- | ---: | ---: | ---: |
| Image | 49 | 49 | 64 |
| Text | 64 | 64 | 64 |
| Audio | 62 | 62 | 64 |
| Video | 55 | 55 | 64 |
| Audio and video | 59 | 59 | 64 |

All original point gates pass. The image route's 49/64 is only one additional
successful source above the minimum of 48/64 for its frozen 75% point gate.
Passing this point gate is not a lower-confidence-bound or population guarantee.

## Public-state boundary and actual model paths

The reviewed `generate_state` interface receives public observations, decoded
waveforms, decoded video frames and frozen models. Private expected labels and
audit targets are not passed into the generation function or output decoders.
Benchmark construction does use source labels to assemble aligned public
text/audio/video; this is a declared property of the bounded digit task.

Image and text routes use their actual reparsed public inputs. The audio route
reads real FSDD waveform files, then computes STFT/mel features and uses the
trained audio-input network. The video route processes frames decoded from an
actual MP4 using its trained frame and recurrent encoder. The audiovisual route
combines those observed semantic posteriors before entering the shared state.
Input videos are constructed motion clips of MNIST images, not natural camera
recordings.

The original NDU-trained shared generator is frozen and takes the fixed
`refine_semantic`, `couple` action sequence. Its neural text decoder and image
decoder supply the original two output modalities. The selected acoustic head
uses the generated semantic posterior, a zero style latent, the trained
conditional spectral decoder and 24 Griffin–Lim iterations. It does not retrieve
target recordings for output synthesis. The video head uses a learned recurrent
displacement field to move the same generated neural image panels. This is a
bounded image-to-video model. The additional heads have genuine training
gradients, but this experiment does not perform four-modal end-to-end NDU
training or dynamically optimize the NDU action policy.

## Independent scoring roles and their limits

The saved recording manifests establish disjoint reward, audit, validation and
test recording hashes. Their recording-index bands are respectively 10–14,
15–19, 5–9 and 0–4. The acoustic generator uses 300 Jackson recordings from
20–49; the audio-input network uses 1,800 recordings across the six speakers in
20–49. The acoustic training recordings are intentionally a subset of the
audio-input training role. The repair trainer does not load the audit checkpoint
into its differentiable loss.

These splits separate recordings, not speakers. The final speech qualification
pool covers the same six known speakers. The 128 unique recordings actually
selected for the joint source tasks cover four speakers: George 50, Jackson 47,
Lucas 26 and Nicolas 5. Neither an unseen-speaker claim nor a balanced
six-speaker joint-task claim follows.

The MelSpeech audit's held-out recording qualification is useful for this digit
task, but is not a human perceptual certification. Retained independent Whisper
development results are 9/12 for real input pairs and 7/12 for repaired generated
pairs. The completed final supplementary Whisper audit selected all 64
text-input, hard-condition rows, giving 55/64 correct real input pairs and only
22/64 correct generated pairs. Under the declared strict two-token parser, the
corresponding digit counts are 110/128 and 47/128. This review independently
recomputed all parses and success counts and paired all 128 ASR input file
hashes to the existing generation records and actual WAV files. Expected labels
and prompts were not supplied to the recognizer. The supplementary score is
not a preregistered primary gate, and it adds no independent source samples.

The substantial disagreement between the local and external speech observers
on generated output is a substantive quality limitation, even though it does
not invalidate the frozen local point gates. The separate four-second Piper
reference failed its full independent ASR qualification and was not used in the
primary final run. These limitations must remain visible alongside the passing
primary gates.

## Actual media, clock and physical negative controls

Each output contains UTF-8 text, PNG image, PCM16 WAV audio and an MP4 carrying
video and muxed audio. The selected clock is two seconds, 8 kHz audio with 16,000
samples, and 20 video frames at 10 fps. Event boundaries are at audio samples
0/8,000 and video frames 0/10. The implementation inspects actual presentation
timestamps through ffprobe, decodes the containers with ffmpeg, and compares
decoded text/image/audio/video content against the emitted arrays. The successful
path is therefore backed by actual codec and byte checks.

The review additionally decoded the existing unequal-label development baseline
and its four mutations. Silence was exactly zero PCM; swapped audio consisted
of exactly reversed event halves; swapped video consisted of exactly reversed
event blocks; repeated video copied the first frame separately within each
event. Untargeted modalities remained unchanged and the legal presentation
clock was preserved. All 20 media-file hashes matched the frozen negative
summary. The recorded failures distinguish missing/silent audio, wrong event
order, and static video from generic container failure. The repeated-frame
control can preserve digit semantics while correctly failing the motion check.
The final run also records nonvacuous rejection of its required controls.

No new corrupted-timestamp test was performed in this review. These checks
support the stated event/content controls and the valid presentation clock;
they are not a universal codec or adversarial-timestamp certification.

## Measured cost boundaries

The completed run records 430.149982472 seconds of wall time, 30.040113377 seconds
of Python CPU and 392.863963 seconds of codec-child CPU. The measured process-tree
CPU total is therefore 422.904076377 seconds. The whole-run interval includes
model/source checks, qualification, actual input and output media construction
and readback, independent scoring, controls and final identity checks. Imports
before the timer and the final summary write are outside it.

Per-row execution time includes neural generation and output codec readback.
Per-row audit-inclusive time additionally includes independent scoring and the
extra content readback. Both omit the source pair's preceding input-media
construction and readback. Hard and soft rows each include the reused common
inference time, so summing their row times double-counts that work. Per-row
Python CPU also omits the preceding shared inference and child codec CPU.
[COST_SCOPE.md](../COST_SCOPE.md) documents these boundaries in detail. The
whole-run receipts are the appropriate measure of incurred work here.
The separate final Whisper audit adds 70.353566766 seconds of wall time and
70.261806928 seconds of CPU; neither is included in the primary run's
430.149982472-second wall receipt.

## Conclusion boundary

The evidence establishes a frozen path from real public input media to actual
four-modal output files that passes the local task's point gates, with held-out
source pairs, recording-separated speech scoring and physical content controls.
The independent final ASR result places a material limit on the generated
audio's quality claim. The experiment leaves
natural audio/video generalization, human-perceived quality, unseen speakers,
four-modal end-to-end NDU training, dynamic NDU superiority, a globally optimal
output portfolio and production qualification unestablished.
