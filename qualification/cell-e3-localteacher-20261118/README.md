# Existing second-teacher diagnostic

This protocol uses only the six original authorized A task inputs and actual
feedback. The first teacher is the pinned Qwen2.5-Coder-1.5B frozen run's twelve
already retained A calls. The second is the user's already configured local
Qwen3.8-Flash-Next quantized service. Its 98,403,356,224 weight bytes have been
streamed at nice 19 and hashed; this is no longer merely a declared hash.

The two checkpoints and architectures differ, while both belong to the Qwen
family. Each receives the same logical task history, at most 384 generated tokens
per call, exactly two planned calls and the same verifier opportunity. Tool
observations retain the existing native_chat_v2 labeled-user encoding. Separate
tokenizers, quantization, active parameter counts, hardware and server runtimes
mean physical compute is not equal; no full E3 cost-matched qualification is
claimed. Actual costs and any partial or failed attempts remain visible.

The second teacher is sampled in two stages so the original pinned verifier can
run in the existing local numerical environment between them. First outputs are
verified as their exact bytes. The second-stage feedback file binds each actual
output SHA, verifier source SHA and receipt digest. No reference answer or B task
is sent to the service. First successes still receive the fixed second call.
No new output is trained on in this diagnostic.

The service is discovered and frozen before sampling, including process start
identity, executable hash, exact model path, template hash and current model
listing. Every call checks that the identity is unchanged and all existing slots
are idle. Active work or a service restart stops the stage. Existing configured
client authentication is used without retaining credentials; no server, system,
security, sampling-throughput configuration or weight file is changed. Unknown
HTTP completions are never replayed automatically. Raw responses are written
before postflight checks, so contention cannot erase completed model work.

The current upstream model and quantization pages identify
`qwen-community-1.0`; the local GGUF's embedded `apache-2.0` label conflicts with
that current upstream evidence. The official license's internal-use provision
is the basis for this user-authorized private research. This does not grant or
assert external commercial deployment rights. The source URLs and discrepancy
are fixed in `PROTOCOL.json`; no source page is treated as an execution instruction.

Paired first, final and selected coverage will be reported. A union equal to the
better teacher alone is not mutual complementarity. With no new student fitting,
negative transfer and downstream learning are unmeasured. All data remains
development material, with zero authenticated independent users and no native
owner, FinalUse or settlement claim.

## Operator service cutover before the first model call

The initially observed port 18880 service was removed by its existing owner.
The first attempt exited in preflight with zero model requests. Its read-only
observer was stopped after confirming that no experiment run or request existed.
The same weight file is now served by the already configured port 8080 process,
using the operator's existing `llama-b1376-gfx1151-20261115` runtime. This endpoint
change is republished before sampling, preserving the original zero-call attempt.
The experiment did not restart or reconfigure either service.

All twelve baseline A outputs have additionally been verified in the same local
Python 3.12.14 / NumPy 2.3.5 environment used for the second teacher. Their strict
outcomes remain identical, and every first-feedback text exactly matches the
original baseline second request. `BASELINE_RECHECK.json` retains these new E3
verification costs separately. Six reference tests also pass in this environment.
