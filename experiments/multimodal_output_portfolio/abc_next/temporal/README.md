# Real text/speech continuation after an irreversible prefix

This experiment replaces the earlier byte-transport recovery witness with actual
new neural speech synthesis. A fixed pretrained Piper acoustic model speaks a
template-generated text stream. A small learned positive conditional-value
critic chooses a shared semantic update and acoustic duration action. **It is
not end-to-end text/acoustic co-training, an unrestricted language model, or a
video experiment.** See `RESULTS.md` for the frozen evaluation outcome.

## Causal operation and strong controls

Each controlled source is one number/color/direction tuple. A private episode
owner samples an initial and a later noisy public cue, with declared quality
profiles. The controller never accepts the target, source identifier, scenario
identifier, noise seed, future output, or a terminal observer result as a feature.
Source targets are used only to construct the environment and score outcomes.
This is an auditable process boundary in Python, not an adversarial OS sandbox.
The owner pre-samples both semantic cues at episode construction. Their declared
release order is enforced by the initial-only feature adapter and the executor;
it is not acquisition of a later live sensor signal. The generated draft and its
Vosk observation are actual newly executed synthesis/recognition operations.

1. The initial-only action gate is computed using only initial features.
2. Piper generates a neutral prefix. Text and PCM are actually committed and
   `fsync`ed. The original prefix is never edited after commitment.
3. Piper generates an internal, uncommitted draft from the initial shared state.
   Unrestricted Vosk decodes the actual generated PCM without a target or grammar.
4. Fresh public evidence is released. The feedback gate sees this evidence and
   the actual draft observation. Every decision is written durably before future
   candidate audio is generated or any final quality score is available.
5. The bounded action family is keep/fuse × normal/slow. Fuse uses the same
   public posterior-MAP operator under every policy. Fixed and initial-only
   gates therefore retain lawful access to the later evidence through their
   selected operator. A fifth, explicitly labelled causal intervention requests
   fuse but clamps the shared semantic state at its initial value.
6. Each path forks the already committed prefix, then actually synthesizes and
   appends two new future chunks. Exact text/PCM spans and the final WAV are
   checked against a chained append-only journal. Candidate waveforms are never
   looked up in a speech corpus or copied from another source's output.
7. Independent Whisper measures the completed WAV offline. It is unavailable to
   controller features, policy fitting, best-fixed selection, or hyperparameters.

The delayed mechanism is precise: a shared-state revision has no task reward at
the neutral prefix. Its effects appear only in the subsequent text and newly
generated speech. The acoustic generator has zero sampling noise in this study;
observed uncertainty comes from noisy public cues and actual draft decoding
errors, not from fabricated confidence scores.

## What is trained

The critic has one tanh hidden layer of 24 units and four positive softplus value
outputs. It learns `E[exp(-2 * net_utility) | public state, action]` by regression
on all four actually executed fit actions. The selected action minimizes the
predicted positive value. Training uses 1,200 Adam steps, a fixed learning rate,
five registered seeds, and only Vosk-based terminal fit labels. No selection uses
Whisper fit performance, since Whisper is not run on the fit partition.

Initial-only, full-feedback, and draft-masked-feedback critics share the same
action family and fit labels. Additional comparisons are all four fixed actions,
the Vosk-fit-selected best fixed action, and a strong declared-prior reference
that exactly enumerates the eight correctness masks under the public posterior,
uses the same gamma-2 exponential risk objective, and assumes perfect acoustic intelligibility.
That reference is not claimed to be the causal optimum of the actual ASR or the
finite held-out distribution. An all-information realized oracle is computed
only after every candidate path has been executed; it is a diagnostic upper
bound and never feeds a decision.

## Source roles and measurement

`freeze-v1/sources.json` freezes 128 distinct combinations into 16 development,
32 fit, 16 qualification, and 64 evaluation groups. All four noise scenarios,
candidate paths, policy seeds, and timing repetitions stay grouped by fact tuple.
The vocabulary, template family and voice are fixed across roles. **There is one
template family and one voice, not 64 independent natural-source domains.**
Fact-level uncertainty intervals are conditional on that limited task family;
they do not establish cross-template, cross-voice, or open-domain generalization.

Qualification was registered before its 16 groups were synthesized. It requires
normal and slow Whisper fact accuracy ≥0.90 and exact success ≥0.75, online Vosk
fact accuracy ≥0.85 and exact success ≥0.65, plus rejection of intentionally wrong
numbers and actual silent/truncated PCM. Failures are retained and cannot trigger
silent parser, template, threshold or observer adjustment. Public digit-to-word
normalization was frozen before qualification and is target-independent.

The primary observer is frozen Whisper tiny.en; Vosk is a separately reported
secondary observer. They have different models and architectures, but possible
overlap between pretraining corpora is unknown. This is an independent
measurement role, not a human perceptual evaluation or a proof of statistically
independent recognition errors.

Utility is `.6 * (text accuracy + audio accuracy)/2 + .2 * nonmissing factual
agreement + .2 * joint exact task success`. Required semantic completion demands
all facts in both modalities and a physically complete output. Silence or a
partial file cannot pass merely because a file exists. Incorrect but complete
facts count as completion and fail task success. Net utility subtracts 0.02 for
fuse, including the clamp intervention, and 0.01 for slow synthesis. These are
declared proxy penalties, not measured milliseconds, CPU, money, or evidence that
a deployment's economic cost has been covered.

Two frozen primary contrasts use nominal 97.5% crossed fact/seed bootstrap
intervals: fuse versus its state clamp, and feedback versus fit-selected fixed.
Each trained seed's CE is computed first, then averaged across seeds. Replays
never expand independent N. Other contrasts and tails are descriptive. Few-seed
percentile coverage is not guaranteed. `abc_recovery/statistics.py` is reused
without modification and its content identity is pinned in the final protocol.

## Cost accounting

The candidate matrix executes every future path. Its complete wall/CPU cost,
TTS API request count, terminal Vosk cost and independent Whisper cost are retained.
The low-level `tts_model_calls: 1` receipt field counts one synthesis API request;
Piper can perform multiple sentence-level acoustic forwards within that request.
Reports therefore do not label that field as an acoustic forward-pass count.
Evaluation cases run in two independent processes, one CPU per process, with
single-thread ONNX/Whisper and OMP/BLAS settings. Vosk's library-default threading
is additionally bounded by that process affinity. Frozen source-index parity
assigns a case and all of its scenarios to one logical worker. Global elapsed
wall time and parent-plus-child CPU include worker startup; summed per-case wall
time is worker occupancy, not globally elapsed time.
A policy's matrix cost is a labelled sum of measured common and selected-branch
components; it is not asserted to be a sequential latency measurement. The
oracle is charged the complete executed matrix when reporting measured costs.

A separate registered timing run generates only the selected output, for the
first 16 evaluation groups, all four scenarios, both best-fixed and feedback seed
17, and two counterbalanced rounds. The timer encloses prefix and draft TTS,
online Vosk, the policy, both future TTS calls, immutable writes, final WAV
serialization and exact readback. Offline final scoring is separate. Model load,
fit data generation and critic training costs are reported separately. Both
policies pay the matched common probe in this measured pipeline; an optimized
fixed policy could omit unused probing and be cheaper. No such counterfactual
cost saving is claimed to have been measured. Shared-host load is retained;
there is no isolated-hardware latency guarantee.

## Public software and model identities

- [Official Piper Python API](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/API_PYTHON.md).
- [Selected LJ Speech voice card](https://huggingface.co/rhasspy/piper-voices/blob/5041a7a49ae5b3a0f30e6837769eb03fdbb231bd/en/en_US/ljspeech/medium/MODEL_CARD):
  public-domain LJ Speech source, one speaker, 22,050 Hz. Fixed model ONNX SHA-256:
  `6f52a751e2349abe7a76735eb09dc1875298c77ea2342ffd2fef79ff81b87f22`.
- [Official Vosk model list](https://alphacephei.com/vosk/models):
  `vosk-model-small-en-us-0.15`, Apache-2.0 model license, unrestricted decoding.
- [Official faster-whisper implementation](https://github.com/SYSTRAN/faster-whisper).
- [Pinned converted Whisper tiny.en card](https://huggingface.co/Systran/faster-whisper-tiny.en/blob/0d3d19a32d3338f10357c0889762bd8d64bbdeba/README.md):
  MIT model, CPU int8, one thread, beam 5, temperature 0, no target prompt,
  grammar or hotwords. Model SHA-256:
  `1a5afae06a4db91c975c9a9d78be5cc110ee4ea022ad57d55492e4550e936b2a`.

Runtime/model manifests also include actual downloaded byte hashes, versions and
licenses. Public asset download uses bounded byte counts and pinned LFS identity
checks. Vosk archive extraction checks file count, total size and path safety.
Generated waves, downloaded weights, fit-path rows and other large raw artifacts
stay outside Git. Published artifacts are source, frozen small protocols, the
main detailed report and compact aggregate evidence.

## Reproduction sequence

Use an isolated Python 3.12 environment with `requirements.txt`, CPU execution,
and `OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1`. Entry points are
modules under `experiments.multimodal_output_portfolio.abc_next.temporal`.

1. `fetch_assets --output <public-assets>` and
   `fetch_external --output <offline-asr-assets>` download only public models.
2. `qualification register` freezes source roles, code and observer gates;
   `qualification run` executes only qualification groups. Existing frozen files
   and output directories are never overwritten.
3. `episodes --role fit` executes all 32 fit groups and four candidate actions.
4. `policy --fit-run <fit-run> --output <policy.json>` trains and freezes all
   critics and best-fixed selection using only the online observer's labels.
5. `registration` writes the complete final evaluation protocol, policy identity,
   code identities, source identities, primary contrasts and timing plan.
6. Only after this freeze, `parallel_matrix` executes the 64 evaluation
   groups and the fifth clamp intervention with external offline scoring.
7. `timing` executes sequential selected-policy runs. `analysis` checks the full
   census, decisions, model identities, actual WAV observer inputs and immutable
   byte spans, then emits compact aggregate evidence.

All CLIs provide explicit arguments through `--help`. Paths refer to actual local
artifacts; a missing raw run prevents replay verification rather than being
silently replaced with generated scores.
