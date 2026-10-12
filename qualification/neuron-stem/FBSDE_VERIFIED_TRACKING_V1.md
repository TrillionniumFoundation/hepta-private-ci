# Verified transition proposals: a restricted-language workspace, not a new FBSDE

Continues #1550 at `cc6fcb8e7171a4b985ebc76859b0940152c74f4b`, which already
contains the parallel continuation-bank implementation. Do not overwrite it with
the older offline continuation patch. All prior numerical, model, risk and native
owner paths stay unchanged. The sole study entry remains `fbsde_study.py`.

## What is learned, what is provided

A shared frozen Encoder maps candidate-normalized event sentences to features.
Entity-name normalization and the constrained English grammar are hand-coded.
A shared two-branch 8-wide gated Head predicts which two actors participate in
one swap. Its parameters are reused across every event and every logical state
slot; state is independent per request. With hashing features it has 2,073
parameters. Physical mmBERT uses the existing pinned loader and 384-wide features.
No Cell receives a separate pretrained model.

Train only on 720 separately generated simulator operation labels (240 three-person events),
160 fixed optimizer steps. This teaches local entity participation, NOT an
end-to-end reasoning algorithm. The forward state update, sequence execution and
checker are explicit code. Benchmark inputs and targets never enter fitting;
benchmark files are opened only after freezing the two Head copies. A publisher
example was inspected to develop the grammar and is a parser regression, not a
held-out efficacy example. Model pretraining contamination is unknown.

## Eight unchanged-information controls

Initial state, last-step-only, frozen recurrent, learned recurrent, verified
recurrent, exact forward, exact backward query tracing, and fault-injected verified
recurrent receive the same source story. Both cheap exact methods are retained.
The model proposes participants without access to the parsed correct pair or
benchmark target. Verification consults the original instruction, not the answer.
Wrong transitions are rejected and replaced by the cheap exact operation. The
fault arm intentionally proposes a wrong first pair; it is an adversarial check,
not an ordinary efficacy sample. A learned-only output is not certified.

Every accepted state has its predecessor, source event, scope/generation binding
and successor recorded. Unknown instructions, negations, ambiguous inventories
and invalid participants reject. A sequence budget exhausted before completing
required work returns no answer. An independent reverse-direction auditor checks
steps, corrections, bindings and the decoded option, without importing a model
or the forward executor. Its guarantee is only for the explicit grammar, not an
independent judgement of unrestricted natural language.

## Original benchmark and separate generated mechanism study

`--tracking-source bbh` downloads original files from the authors' repository:
https://github.com/suzgunmirac/BIG-Bench-Hard at
`9ee07bd481feebf959a6b59d61ea57bdcf30964d`, the three/five/seven-object tracking
JSON files (250 examples each). Complete immutable Git blob pins and the canary
are checked. All 750 original examples remain in the denominator; parser failures
are retained and fail the profile, not silently removed. Original target
inconsistency is reported and rejects rather than relabelling the benchmark.
This is a task-specific constrained parser, NOT a general BBH language-model score.
The BBH files are evaluation only and must not enter any training corpus.

`--tracking-source generated` is a different declared mechanism study with 192
newly generated 3/5/7-person stories. It is not a substitute for actual public
benchmark execution. Do not transfer its results to mmBERT or BBH. The two backends
are explicitly separate, with no silent substitution after a download failure.

## Resource scope and relation to NDU/Riccati

Canonical sentence features are cached in the study process. Encoding and fitting
costs, cache uses and per-proposal process CPU are measured; the 100ms proposal
budget records and rejects overruns. A denied proposal is not applied. Failed
runs retain prepared tiny weights, inputs and partial predictions but no completed
results. Per-arm CPU is NOT a full standalone lifecycle allocation, especially
when an encoding is shared; no equal-total-cost or superiority claim follows.

Riccati residuals certify a numerical model, not actor names or language facts.
The earlier numerical solver is therefore not artificially inserted as a semantic
checker. This stage supplies a concrete verified state-workspace contract for a
future learned NDU controller; no current NDU advantage, risk certificate or
continuous semantic FBSDE integration is claimed. Exact tracking is expected to
remain cheaper. Do not replace native final-use, evidence ownership or admission.

```sh
PYTHONPATH=qualification/neuron-stem python qualification/neuron-stem/fbsde_study.py \
  --profile verified_tracking_v1 --tracking-source generated \
  --backend hashing_reference_v1 --output /new/mechanism
```

Use `--tracking-source bbh` for actual original benchmark input, and `--backend
mmbert --model-dir /cache` for real pretrained features. Keep the PR Draft.
