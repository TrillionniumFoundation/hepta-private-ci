# Measured-clock execution contract

This POSIX adapter executes JSON controller, tool and verifier workers under
one monotonic physical service clock. It is an execution contract and a tested
foundation for a frozen-LLM experiment. **No frozen LLM was run in this session.**
The executed workers are explicit scripted validation fixtures. They are never
reported as learned agents, real-model evidence, or a net-benefit benchmark.

## What is actually enforced

The controller can issue a registered tool action or explicit `STOP`. Only a
valid verifier result completed by the delivery deadline can earn quality.
An expired, cancelled, malformed, failed, or never-stopped episode earns zero
delivered quality. Every attempted worker call retains its launch fee.

The service objective is frozen as

`delivered_quality - sum(attempt_fees) - time_price * envelope_wall_seconds`.

The envelope includes per-episode validation/hashing, controller calls, tool
processes, waiting, process-group cleanup, verification and dispatch overhead.
Each invocation's duration is a subtotal, not an extra time charge. Final report
serialization and one-time provisioning/training are outside this service
envelope and must be separately budgeted before a lifecycle-benefit claim.
Prices are declared utility tariffs, not measured provider currency costs.

`delivery_at_seconds` is the acceptance timestamp; the full bookkeeping envelope
can finish slightly later. `deadline_missed` uses the delivery time when there
is a delivery; `service_envelope_exceeded_deadline` records the separate envelope.
Cancellation is checked at call boundaries. An active call is bounded by its
own timeout and remaining service time; this is not instantaneous cancellation.

Each worker starts in its own POSIX process group, which is cleaned up after
exit or timeout. Workers must not detach or escape that group. Group supervision
does not establish cancellation of work already admitted by a remote provider.
Commands run with their operator's permissions; this is not a security sandbox.
Output length is checked before interpreting captured output, not enforced as
a streaming memory bound.

## Executed verification and defects fixed

[qualification-final.json](evidence/qualification-final.json) is the current
source-bound receipt: **14 behavioral tests passed**. It contains actual waited
process events, prices, measured timestamps, exit/parse statuses, and hashes.
The worker identity is `validation_fixture`; all episodes say `NOT_LLM_EVIDENCE`.

Independent internal review exposed three additional failures beyond the first
ten checks. Overflowing JSON numbers and deeply nested JSON could throw after
an attempt had already been paid, losing its receipt. Direct-child timeout could
leave a child worker running. The final code rejects recursively nonfinite JSON,
contains decoding/recursion failures in a paid failed event, and supervises the
worker process group. A non-UTF8 result is covered too. The three original
counterexamples were rerun independently against the corrected code.

The current receipt is the accepted qualification artifact. Earlier local
development receipts are superseded and are not scientific experiment results.
Ordinary fixture tests do not replace independent task evaluation.

## Run and connect a model

```bash
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.ndu_walltime.test_runtime \
  --output /tmp/ndu-walltime-new.json
```

`Worker(argv, attempt_fee)` accepts a command without a shell. It reads a JSON
object on stdin and returns one JSON object on stdout. The controller returns
exactly `{"action": "STOP-or-registered-tool", "payload": ...}`. Tools return a
JSON observation object. The verifier returns exactly `{"quality": number}` in
[0,1]. Model identity includes `kind`, `model_id`, and an explicit revision;
these declarations do not prove a hosted provider served immutable weights.

A scientific run must additionally save the complete frozen protocol, task
bank/split, worker sources, model revision evidence, decoding, action authority,
prices and all baseline policies. Hashes alone cannot reconstruct an arbitrary
external worker or task. [LLM_READINESS.json](LLM_READINESS.json) records current
unmet inputs. No claim of real-LLM success, independent-task net utility, or
large-scale training qualification follows from this adapter.
