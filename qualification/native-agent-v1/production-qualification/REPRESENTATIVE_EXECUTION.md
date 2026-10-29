# Executable representative comparison

For observed results and outstanding evidence, see
[REPRESENTATIVE_STATUS_20261029.md](REPRESENTATIVE_STATUS_20261029.md).
The sections below describe the available implementations; they are not a list
of experiments that have all passed.

`representative_compare.py` executes edits, observed test-failure repair,
read/write/validation chains, and a real stdio MCP exchange through the existing
native qualification runner and runtime jobs owner. Each action has an original
admission and terminal result. The test file and other immutable inputs are
hashed and checked independently after execution.

The owner remains the qualification `SessionOwner`. These runs do not close the
registered `production_owner`, Agentd/QueueStore/FinalUse, whole-controller
recovery, or live third-party connector requirements in `corpus.json`.
They must not be fed to the older production checker as completed production
slots. The default suite contains four cases. Long output and controlled faults
have separate candidate entry points; their remote results are not established
in the status snapshot. PTY and a live third-party connector remain outside the
executed slice. The complete fourteen-case production verdict remains held.

## Replay

```sh
python3 qualification/native-agent-v1/production-qualification/representative_compare.py \
  --output /absolute/new/run-directory \
  --native /absolute/hepta-native-qualification \
  --codex /absolute/official-codex \
  --facade /absolute/official-in-process-facade \
  --mode replay --group behavior_matched --repeats 3
```

All lanes receive the same response sequence for each case. The gateway refuses
to emit the next replay response unless the real original tool feedback is
present and has the expected exit status. The repair starts with an actual
failing test. A replay success proves execution/feedback compatibility, not the
model's ability to discover a repair. Usage in replay is synthetic.

Each case starts a fresh resident executor. Startup and task wall time are kept
separate. No p95, total resource-efficiency conclusion, or performance ratio is
emitted. Every attempt is retained, and a failed case is not silently retried.
The old three read-only controls and their archived reports are unchanged.

## Live and separate configurations

Live uses the existing bounded Responses gateway and requires a nonsecret model
identity evidence file. It captures actual request bodies, Responses streams,
reported model identities and usage. An alias by itself is insufficient.

```json
{
  "schema": "hepta.model-identity.v1",
  "model": "qwen38-flash-next-uc",
  "response_model": "EXACT_REPORTED_MODEL",
  "provider_revision": "EXACT_PROVIDER_DEPLOYMENT_REVISION",
  "model_sha256": "64-lowercase-hex-from-the-frozen-model",
  "evidence_sha256": "64-lowercase-hex-of-the-deployment-evidence"
}
```

Use `--mode live --upstream http://AUTHORIZED-ENDPOINT/v1 --model-evidence PATH`.
This interface does not read credentials or manufacture model identity evidence.
The operator must independently verify the pinned deployment and preserve the
source evidence. The run cannot detect an upstream replacement hidden behind
unchanged metadata; this remains a deployment-observation limitation.

`--group individually_optimized` requires a `--profiles` JSON mapping for all
three lanes. Each lane has `budgets` with the same fields as `BUDGET` in the runner
and a nonempty `notes` description. These ceilings are actually passed to the
native loop, Codex tool dispatcher and common gateway. This does not claim to
expose every engine-specific optimization. Behavior-matched profiles require
identical ceilings, while actual request/context parity is retained for audit.
Use separate fresh output directories for each mode/group; do not pool them.

## Long output qualification slice

Use `--cases long_output --profiles qualification/native-agent-v1/production-qualification/long_output_profiles.json` in a fresh output directory. Local fixture tests observe the frozen generator's 1,179,648 stdout bytes. The separate runtime experiment is designed to execute that generator through its original runtime-owned process descriptors. Its equal profiles retain up to 4 MiB, while the case independently caps each model-facing tool item at 4,096 bytes. The excerpt explicitly names the original host, job, operation, idempotency key and runtime-intent digest and retains exact full-stream lengths and SHA-256. The audit requires the original job's retained files and compares every byte with a separately generated oracle. It rejects a changed reference, missing terminal record, extra runtime job, oversized item or incomplete stream. This implementation description does not establish that the remote long-output experiment has passed.

The native default presentation hook preserves the original complete-byte receipt check and is bounded by the existing tool deadline and cancellation. The qualification bridge overrides that hook; the production Agentd continuation fold still uses its default full JSON policy. Passing this slice therefore does not close the production long-output recovery gate.

The private qualification host uses the existing runtime's operator contract, which requires `allow_job_network=true`. This is an explicitly network-capable operator configuration, not proof of network isolation. All three lanes use the same capability. Frozen fixtures and MCP stdio contain no external-service operations.

## Controlled cancellation and process restoration

Run `representative_faults.py --output <fresh-dir> --native <runner> --codex <official-0165> --facade <hepta_facade> --lane <native|app-server|facade> --case <cancel|recover_process>`. These runs use fixed response replay and are separate from latency samples and live model-quality comparisons.

The watcher requires the original immutable admission, original runtime job, durable pending checkpoint, actual child metadata and retained `STARTED` bytes before acting. Cancellation sends the owner's existing cancel/session message, then re-enters the same immutable owner command only for observation until a complete durable original cancellation terminal appears. Codex lanes also require the original turn's interrupted notification. Restoration SIGKILLs only the waiting runner created by this experiment, verifies its injected EOF, starts exactly one replacement helper and re-enters the unchanged command. The runtime child remains untouched and creates the original `done` artifact. Both variants verify there is one original job and terminally consumed call, no live original child and no duplicate model request.

These fixtures exercise SessionOwner, not production Agentd ThreadStore, QueueStore or FinalUse. Production cancellation and controller restart gates remain separate. A tool/transport failure outside the explicitly verified injection point is retained as failure and never authorizes restart.
