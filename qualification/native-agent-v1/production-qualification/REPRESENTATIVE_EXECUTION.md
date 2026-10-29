# Executable representative comparison

`representative_compare.py` executes edits, observed test-failure repair,
read/write/validation chains, and a real stdio MCP exchange through the existing
native qualification runner and runtime jobs owner. Each action has an original
admission and terminal result. The test file and other immutable inputs are
hashed and checked independently after execution.

The owner remains the qualification `SessionOwner`. These runs do not close the
registered `production_owner`, Agentd/QueueStore/FinalUse, whole-controller
recovery, or live third-party connector requirements in `corpus.json`.
They must not be fed to the older production checker as completed production
slots. Long-output retention and PTY are still outside this initial executable
slice. The complete fourteen-case production verdict remains held.

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
