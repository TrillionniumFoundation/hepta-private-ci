# HPCA greedy execution contract repair — HOLD_NO_GO

This is a source and evidence-contract repair stacked on #6029, exact parent
87858f5a74a248344b99bb319d937487a13b4a8b. The original 24 public OOD tasks,
training archive, binary-score archive, prompts, eight LoRA checkpoints and
standalone-label rule are unchanged. The new execution schema is
HPCA-V2-REAL-CPU-GREEDY-GEN-2. This implementation must be committed before
running it; a prospective record does not retroactively change earlier results.

## Failure addressed

The previous caller specified greedy selection and eight tokens but inherited
other model generation settings. A forced token, suppression list, repetition
penalty, minimum length or alternate stopping rule could silently contradict the
unconstrained greedy protocol. Only model weights, config.json, tokenizer.json
and the adapter archive's declared files were checked; auxiliary tokenizer and
generation settings were not preserved as one complete execution identity.
Prompt/family/truth agreement was checked only after the respective generation.

The revised caller validates all frozen tasks before any model generation.
It records the complete resolved generation configuration, rejects non-neutral
hidden controls, requires tokenizer/model generation special-token agreement,
and passes use_model_defaults=False to prevent subsequent default merging.
The caller does not silently remove an unexpected constraint and continue.

## Evidence retained for a new execution

A fresh RESULT.json.evidence directory is exclusive to one attempt.
PREEXECUTION.json is written with exclusive creation and fsync before the first
model.generate. It includes all three frozen input digests, runner/helper
digests, model and eight-adapter file manifests, runtime versions, special
tokens and each prompt's exact input token IDs. Cache bookkeeping is excluded.
The assets, frozen inputs and all three executing source files are checked again
before the result is published. The original four-thread budget is enforced.

ROWS.jsonl records a unique run ID, monotone sequence, condition and task for
each start and every completed raw row. Completed rows include emitted token
IDs and original decoded text. Each record is flushed and fsynced. Interruption
leaves an incomplete journal; started attempts are not counted as completed
rows. Only all nine conditions and the final consistency checks can produce the
exclusive final result. Neither partial journal rows nor passing unit tests
constitute a completed model study. These local before/after file snapshots are
not an atomic asset store, an authenticated Owner, or independent custody.

The new measured_phase_cost starts before the first model load and ends after
the final asset check and journal close. It excludes imports, tokenizer loading,
initial hashing, acquisition and external lifecycle work. Peak RSS is the
process lifetime high-water mark, not an additive per-condition cost. A real
host run should additionally retain an outer /usr/bin/time -v record. Greedy
eight-token decoding and prior two-choice scoring have different work costs.

## Verification and execution state

The targeted workflow uses Python 3.12, read-only repository permissions,
checkout of the exact source head, a five-minute timeout and retained raw test
logs. It runs the eight inherited parser tests, five plan tests, fifteen
archived-forward/provenance tests and twelve runtime-contract tests in the
successor (eleven in the executed 0b75 source). The new
negative cases cover hidden decoding controls, special-token changes, auxiliary
asset changes, source changes, thread-budget changes, early task binding and
interrupted/non-overwritable evidence.
This suite does not install or execute the pretrained model.

At preparation time the managed executor became unavailable. The ai395
configuration read, a read-only shell inspection and a read of two model
configuration files returned MCP timeouts; no new native model run was
submitted. The old replay job's retained succeeded status was readable, which
does not establish live host access. At that preparation stage the new 216-generation experiment was NOT_STARTED.
Its later successful execution and complete retained originals are recorded below.

No independent calibration set, future source or old-task retention panel has
been supplied: all remain MISSING in PREEXECUTION. The exposed 60-prompt B2
negative result is unchanged. No label inversion, fitted threshold, model
selection, scientific gain, production adoption or native NoUpdate is claimed.

## Retained native observation and successor guard

Execution source `0b75caf446a18807e527f8e2ed9937ae3cae515d` completed 39 targeted tests and the frozen 216 native generation attempts on ai395. The retained preexecution record identifies Python 3.14.4, torch 2.9.1+cpu, transformers 4.57.3, peft 0.18.0, and the original model plus eight adapters. Its effective `is_assistant` value is false. The native archive summary reports every output as token `[2]` (native EOS) and empty decoded text, yielding 0/24 valid responses in each of nine conditions on 24 public tasks. The preexecution record, original test log, native wrapper stdout and summary are retained under `evidence/runtime-contract-20261112-e901`; the complete RESULT and 433-record journal are now also retained byte-for-byte in GitHub. A separate same-session reviewer checked every raw row, start/completion pair, terminal record and source/input binding. This is operator-evidence consistency review, not external custody or independent task sampling. TRANSFER_STATUS and RAW_REVIEW record the precise scope.

A subsequent review of Transformers 4.57.3 found that `is_assistant=True` can activate confidence stopping while the generation mode still reports greedy. This successor adds one fail-closed field check and one counterexample test. It does not change the recorded execution source, rerun the model, or imply that confidence stopping occurred in the retained run. The earlier native 39-test result does not certify the successor test; its test result is recorded separately by the targeted workflow.

`just fmt` was not executed: neither the native sparse worktree's `codex-rs/justfile` nor a `just` executable was available. Raw formatting status is retained. Independent calibration, future sources and old-task retention remain MISSING.
