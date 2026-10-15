# B0: Execution Kernel decoupling-cost reference (research only)

**Status:** `RESEARCH_DENY_ALL`; no selected runtime, physical tool execution, final-use grant, structural promotion, release or proof of Codex speed.  This probe is **not** the proposed Hepta Execution Kernel. It measures the transport cost of an identical **pure Python fake decision** over three deployment boundaries and a cold-start anti-pattern. Do not infer actual Codex Exec Server or Hepta model latency from it.

## Exact sources and reason for separation

- Hepta baseline: `main@78fdb0cf8537e3a84fc6e0a849707559c80881e8` as observed 2026-10-14. The source has `codex-rs/hepta-codex-adapter`, `hepta-infer-worker-host`, `hepta-neuron`, `hepta-agentd`; `runtime.codex` is an App Server adapter, not an unqualified tool executor.
- Codex reference: `openai/codex@rust-v0.162.1` (released 2026-10-09). The separately implemented `codex-exec-server` provides a process/filesystem execution protocol; `codex-app-server-client` offers an in-process typed-channel model but keeps App Server semantics. **Neither implies a safe replacement for Hepta's signed Final-use/effect path.** Recheck upstream SHA and licenses before lifting code.
- Hepta `codex-rs/hepta-infer-worker-host/FINAL_USE_AUTHORITY_PORT.md` describes a **model-only** App Server route with no tool grant. Preserve this distinction. A model `turn/start` authority is not a shell/tool authority.
- Existing draft experiments #1903/#1918/#1928 cover encoder/head sharing, not Codex execution IPC. #1924 captures only Linux process observations and does not establish live serving or signed target-host evidence. #1929 identifies a CellSplit route-cutover bypass in a separate control path. Do **not** merge or promote this cost experiment to resolve those blockers.

## Repeatable B0 workload

```sh
python3 -m unittest discover -v -s qa/execution-boundary -p 'test_*.py'
python3 qa/execution-boundary/cost_probe.py \
  --logical-cells 64 --active-cells 8 --payload-bytes 256 --rounds 4
python3 qa/execution-boundary/cost_probe.py \
  --logical-cells 4096 --active-cells 256 --payload-bytes 1024 \
  --rounds 4 --modes direct,queue,persistent
```

`logical-cells` models installed logical IDs, not physical model weights; `active-cells` specifies **exactly** how many identical research intents are executed each round. A large idle logical graph is not expected to launch a worker per Cell. All modes receive identical canonical serialized intent bytes, validate scope/generation/fence, return exactly equal deterministic receipts and preserve one-to-one operation correlation. The pure fake operation only hashes bounded data. There is no model, tool, Codex connection, sandbox, WAL or external outcome. No real side effect is possible through this intent schema.

The modes are:

| Mode | Resource topology | Timing interpretation |
| --- | --- | --- |
| `direct` | One process, direct pure function | Serialization/compute baseline, no dispatch boundary |
| `queue` | One process, one bounded request queue and one worker thread | Python typed-queue synchronization; **not** Rust Tokio channels |
| `persistent` | One long-lived child process, socketpair and bounded binary length frames | Actual local IPC; startup separately measured, first request may contain runtime initialization |
| `cold` | One new child for **every active call** | Anti-pattern reference; exact operation count capped at 32, never subsampled |

`total_wall_ms` includes client bootstrap, measured dispatch, receipt verification and shutdown; per-operation `dispatch_latency` excludes most setup/verification but includes the first child's readiness delay. `worker_startup_ms_total` is just `Popen`/thread setup, **not** guaranteed readiness. Do not add these fields as if disjoint. The probe reports nearest-rank p95 only from at least 20 real operation samples, and p99 only from at least 100. One synthetic repeated intent is not one independent real-world success episode. The Python process and runtime environment are reported to expose non-portability. No GPU, RSS, Codex, physical effect or signed metrics are reported.

All requests include only the seven allowlisted fields and a SHA256 of the fake payload. Frame sizes, model-free scope IDs and task counts have hard bounds. Unknown/duplicate fields, forged receipt success and identity mismatch reject. A truncated response is indeterminate and is **not retried** with a new operation. Child subprocesses use `-I -S` and receive no model/provider credential environment. None of these checks constitutes independent Hepta authorization.

### Explicit non-claims

This test **cannot** determine whether forking Codex, embedding `codex-app-server-client`, or running real `codex-exec-server` is faster on the target host. It does not test kernel namespace/sandbox startup, App Server session/turn semantics, external tool grants, file-system authority, real cancellation, target signing keys, actual memory use or power-loss recovery. Local Python ratios must **not** be used as promised percentage improvements for Hepta. `RESEARCH_DENY_ALL` is included in every report, and the benchmark raises on incomplete or inconsistent results instead of manufacturing them.

## Subsequent strictly gated integration (not implemented here)

1. **P0 original baseline:** obtain deployed Worker PID identity, manifest/actual loaded model receipt, signed service identity, target-host RAM/CPU/GPU, actual turn/tool traces and p50/p95/p99. Existing #1924 alone is insufficient. Freeze objective and no-change baseline before comparing architecture.
2. **P1 typed ownership:** define additive versioned `ExecutionIntent`/`Receipt`/`Reconcile` *without* importing `codex-core` into Neuron or copying Codex's entire planner. Map existing App Server `turn/start` and Exec Server process operations through distinct adapters. Retain original thread, journal, cancellation, effect identity and no-replay semantics.
3. **P2 authority/physical boundary:** pass independently issued Final-use at the **specific executable effect**; verify exact payload/scope/deadline/epoch/revocation and write an owner-durable intent before any external execution. A tool provider cannot self-authorize. Unknown result is reconcile-only. No direct Cell -> `exec-server` bypass or implicit agent-to-tool grant.
4. **P3 real comparison:** pin an *actually compiled* Codex revision, run approved no-op tools under equivalent sandbox/authority profiles using existing Hepta owners. Compare in-process model-only, persistent local Exec Server, remote Exec Server, and process-per-task on the **same work and security policy**. Record cold/warm, CPU/RSS, process count, transport bytes, WAL/fsync, p95/p99, queue age, failure/restart uncertainty; vary installed 64/256/1024/4096 versus active concurrency independently.
5. **P4 structural learning:** only then compare frozen Head, MoE, Meta Network, split/merge/no-change at matched active inference and *total* training/evaluation/serving/migration costs, independent future task groups and negative-transfer floors. No prospective result can waive CNS/Control CellSplit cutover, independent Selector or Operator acceptance.

**Architecture choice for experimentation:** logical module/ABI separation is the default; physical isolation belongs at untrusted/effect boundaries; one compatible persistent execution pool serves many active Cells. Separate repository extraction is an optional *later* engineering decision after measured cost and upstream patch maintenance are understood.
