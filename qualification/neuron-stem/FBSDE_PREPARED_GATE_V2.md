# Prepare immutable outcome gates; preserve the policy and its checks

Parent: `7129bf1bea250ced028d9df04bece50546178ae9`, Draft PR #1550.
This is an execution optimization, not a new learned model or acceptance gate.
All existing study profiles, exact/cheap controls and CPU limits remain.

## Diagnosis and mechanism

The outcome router revalidated all 265 network scalars and serialized the entire
weight dictionary for the request bundle digest on every call. A local cProfile
run on 192 frozen test cases attributed 43ms to scalar_score and 37ms to digest
out of 295ms instrumented execution. These are profiler observations, not normal
latency measurements and not a reason to remove required current-context checks.

PreparedOutcomeGate validates and copies weights into immutable tuples once for
a frozen policy configuration. It computes exactly the same compensated sums,
sigmoid and threshold predicate. The canonical state/threshold byte suffix is
prepared once; each request still validates the model, calibration, scope,
generation and full source binding, and constructs the ORIGINAL bundle SHA256.
No request answer, pilot value, source revelation or decision is cached. Returned
scores and provenance match the original byte semantics, including exact ties.
Mutation of caller lists cannot rewrite the prepared object. This is application
ownership discipline, NOT attestation against arbitrary hostile Python mutation.

The optional execute(..., prepared=gate, context=current_context) uses this path.
The existing dict-bundle path remains the default. Confidence receives an explicit
zero-weight preparation control, while all fixed/exact methods remain unchanged.
There is no claim that preparing a trivial confidence rule helps; its extra
context checks may cost more than the original tiny expression.

Preparation, including validation/copy/hash work, is measured once per actual
configuration and added to the calls that actually occur. In this experiment six
prepared configurations share the same frozen inputs. No imagined future volume
is used. Per-call binding, pilot, features, arithmetic, deeper continuation and
workspace disposal remain inside the existing 100ms process-CPU check. Its
20,000-node allowance and two-verification limit are unchanged. No GC/thread
settings or threshold selection are changed. Encoder and training are not rerun.

## Frozen-output experiment

The original entry gains --profile prepared_gate_execution_v1. Its input is a
complete, independently audited outcome-depth study, not a PASS field. All model
parameters, selectors, source inputs and answers stay frozen. Five preregistered
seeded repetitions interleave 12 methods x 252 historical cases x two engines:
30,240 actual calls. Each engine executes its own pilot and verification sequence.
The first repetition preserves all 6,048 full traces; subsequent calls retain
semantic fingerprints and measured work. Every fingerprint matches the original
independently checked decision/score/verification/answer record. Repetitions add
no independent semantic samples. The 252 cases comprise 192 explored renderer
cases and 60 known-form replays, not new human or future-window observations.

First complete local benchmark, median CPU per 252-case repetition:

| Method | Existing path | Prepared path |
| --- | ---: | ---: |
| Outcome-trained / outcome-selected | 135.497ms | 91.626ms |
| Model-trained / model-selected | 173.020ms | 120.629ms |
| Cheap confidence | 82.531ms | 88.479ms |
| Fixed two-step | 118.312ms | 123.659ms |
| Exact reverse | 47.519ms | 47.739ms |

Summing all five repetitions and the actual preparation, the first two save
31.63% and 27.23% CPU respectively. Cheap confidence becomes 4.94% more costly
and remains faster than the prepared learned gate. Fixed/exact controls execute
the same code in both labelled engines; their timing differences are measurement
variability, not effects attributed to compilation. These are single-host
component measurements, not stable latency or complete lifecycle superiority.
Recording, audit and common belief preparation are separately included in the
study envelope, not falsely allocated as per-policy production expenses.

## Retained failure and numerical compatibility

An initial command was interrupted by the tool's 45-second limit before writing
complete results. A later implementation run failed when an inherited probability
was slightly greater than one from floating-point summation. An added strict
confidence range check was incompatible with the existing finite feature rule.
The fix preserves 1-p exactly, including its tiny negative result, without
clipping or changing thresholds. A nextafter boundary regression covers it. The
failed run and its exact source-hash-matched reconstruction are retained; neither
interruption nor partial result is counted as a successful trial.

The original source auditor is reused. A separate no-Torch/no-runtime-policy
pair auditor checks fixed source provenance, randomization order, complete call
inventory, traces, original bundle identities and preparation-inclusive costs.
Artifact mutations must reject changed semantic digests, removed/reordered calls,
changed gate identities and fabricated speedups. This remains arithmetic/byte
consistency rather than hardware execution or calibrated risk certification.

No native owner, main merge, current production no-change, general FBSDE theorem,
Riccati solver, semantic learning result or model promotion is introduced.
