# Native agent / Codex execution qualification protocol

This protocol measures a finite, read-only tool loop. It does not establish
production replacement readiness, general coding capability, or an AGI claim.
The benchmark must retain failed runs and incomplete measurement coverage.

## Arms and fixed work

| Arm | Resident execution path | Tool backend |
| --- | --- | --- |
| `app-server` | Official Codex 0.165.0 App Server source, one persistent process | One persistent qualification helper using the pinned hepta-runtime code |
| `facade` | Pinned upstream 0.165.0 in-process client/server facade, one persistent wrapper process | The same helper executable and runtime code |
| `native` | Native model/tool loop, one persistent qualification process | The same runtime bridge and hepta-runtime code in that process |

Every arm has the same outer Python harness and model gateway. The facade still
has the shared outer JSON-lines measurement transport. Its internal typed
channels do not make this a zero-serialization benchmark. The native arm avoids
the separate tool-helper IPC because its runtime bridge is in-process; that is
an observed deployment difference, not work omitted from accounting.

Both Codex builds use upstream commit
`360319d8dee62d87e2d59fc0c21805d79519cfed`, the same recorded bootstrap
observability patch and a declared Rust 1.95.0 override of upstream's 1.99.1
toolchain. They are source qualification builds, not stock release binaries.
The 0.164 diagnostic runs remain separate from the formal comparison.

Each case gets a fresh session/thread on its resident executor. It invokes
`hepta_probe` exactly once with one of `sum`, `lines`, or `digest`, then returns
the tool's JSON result. All arms use the same script/data paths and SHA-256
values, compiled command arguments, fixture policy, localhost SSH host, and
runtime backend implementation. The host admits only the three read-only
fixture operations. The underlying runtime host uses operator mode; this is
not evidence of a general command sandbox.

### Planned sample counts

| Mode | Warmup | Measured cases per arm | Repeats |
| --- | --- | --- | --- |
| Fixed-response replay | One `sum` case | 9: `sum`, `lines`, `digest` repeated three times | `--repeats 3 --warmup` |
| Live provider | One `sum` case | 6: the three tasks repeated twice | `--repeats 2 --warmup` |

The CLI defaults to three repeats for replay and two for live. Warmup is explicit
via `--warmup`; the report records the actual complete plan, so a smoke run or a
run without warmup cannot be silently presented as this full protocol. Cases
use the declared task order. These small samples are exploratory; the reported
nearest-rank p95 is not a reliable population tail estimate. Record run order,
resource caps, host load, source revisions, build changes and executable hashes
alongside the reports. Repeated tasks can share OS/provider caches. A small
latency difference from one sequential pass is not a stable superiority claim.

## Two distinct comparisons

### Fixed-response replay

The gateway emits two predetermined model responses for the case: the original
`hepta_probe` call, followed by its final JSON answer. The final response is
released only when the second model request contains the original `call_id`
and the exact successful real tool result: integer exit code zero, expected
stdout including its newline, and empty stderr. A faulty backend cannot get a
correct canned answer. The tool is still executed by real hepta-runtime.

This measures request construction, event parsing, scheduling, communication,
state persistence, actual tool execution, and feedback handling. It does not
measure inference. The replay's token usage fields are synthetic fixtures and
must never be reported as actual token consumption or model efficiency.

### Same advertised model / task / budget ceilings

Live requests go through the same gateway to the same configured Responses
endpoint and advertised model ID, `qwen38-flash-next-uc`. The gateway forwards
actual requests and responses and captures their hashes and bytes. It does not
remove unwanted tools or rewrite outputs to force a match.

This establishes the same endpoint and advertised model, not a provider weight
hash or immutable inference deployment. External provider routing, model
version, compute, batching and caches are not pinned by this harness.

Both modes use these ceilings:

| Resource | Ceiling |
| --- | ---: |
| Serialized model request body | 65,536 bytes per request |
| Output tokens | At most 256 per model response |
| Model calls | At most 4 per case |
| Tool calls | At most 3 per case; success requires exactly 1 |
| Tool output | 32,768 bytes |
| Tool deadline | 60 seconds |
| Outer case deadline | 240 seconds by default |

The request-body ceiling is UTF-8 JSON bytes, not tokenizer context tokens. The
native loop also has its own context assembly bound. Different prompt wrapping
can consume different fractions of this same ceiling.

**Timeouts are not identical at every layer.** The native model client has a
120-second total call deadline. The gateway upstream socket has a 120-second
I/O timeout. Codex also has its own client semantics and the shared outer case
deadline. These normal-operation measurements cannot establish identical
slow-stream recovery behavior or make a timeout-path performance claim.

Codex is configured with `goals = false`, disabled shell/unified-exec/image and
multi-agent features, disabled web search, and disabled plan/request-user-input
tools. Its reasoning summary is set to `none`. The authoritative check is the
**actual captured tool inventory on every request**: exactly one function,
`hepta_probe`. Flags alone are insufficient. A request containing `get_goal`,
`create_goal`, `update_goal`, or any other additional tool fails the equal-tool
comparison gate, even if the task answer is correct.

The native and Codex requests need not be byte-identical. Differences in prompt
wrapping, function `strict`, `parallel_tool_calls`, reasoning options, `store`,
and history representation remain in raw evidence and the inventory summary.
Do not attribute live success or token differences solely to executor overhead
while these model-visible differences exist. Replay isolates more runtime work,
but its JSON sizes and serialization costs can still differ by implementation.

## Success must be bound to real tool evidence

A completed case is correct only if all of the following hold:

1. The executor reports `completed` and exactly one tool call.
2. The final answer, after removing surrounding whitespace, equals the frozen
   canonical stdout JSON object. No prose, Markdown or substituted value passes.
3. Captured model requests and completed SSE items identify exactly one original
   call, named `hepta_probe`, with exactly `{"task": "<this case's task>"}`.
4. Model feedback identifies that same call and contains exactly the successful
   runtime output: integer `exit_code: 0`, expected stdout plus its newline,
   and empty stderr. Changed or conflicting call/feedback copies fail.
5. All started model-request evidence files have finished writing; missing,
   malformed or incomplete evidence cannot be scored as success.

The runtime bridge separately validates original intent/host/generation,
terminal-publication evidence, output durability and exact output digests
before returning feedback. The benchmark audit binds that returned feedback
to this case and final answer; it does not replace the runtime owner.

Partial reports mark correctness pending until the final feedback audit.
`answer_matches_expected` alone is a diagnostic, not task success.
`qualification_passed` additionally requires the shared-tool inventory gate.
Task failures remain part of the result. `completed_lane` means the measurement
loop completed, not that all tasks succeeded.

## Operation identity and failure handling

`threadId`, `turnId`, original tool `call_id`, backend session, and runtime
operation/generation identities remain recorded. `Accepted` is not completion.

A pending tool, model failure, timeout, protocol mismatch, or uncorrelated reply
aborts that lane. The driver is poisoned, records `requires_process_reset`,
and attempts to interrupt the original turn. The harness closes its resident
processes and records planned-but-unrun cases. It never treats unread events as
the next case or resubmits an unknown operation under a new identity.

A later qualification run requires a new run directory and restarted processes.
That restart is a new benchmark run, not proof that the prior operation safely
resumed. Recovery correctness requires separate fault injection and observation
of the same original owner records. Normal replay/live success and unit tests
must not be described as a completed three-arm end-to-end recovery comparison.

## Timing, CPU, memory and missing work

| Measurement | Included window |
| --- | --- |
| `startup_ms` | Launch the persistent qualification backend, launch Codex when applicable, complete readiness/initialization |
| Per-case `wall_ms` | Send native `run`, or begin Codex `thread/start`, through case result/failure; includes fresh thread creation |
| Whole-lane CPU and memory | Before backend launch through resident-client and gateway shutdown; includes startup, warmup, all attempted cases, observer and shutdown |
| `shutdown_ms` | Close resident clients and gateway |

Gateway construction, configuration preparation and final evidence auditing
are outside the whole-lane resource window. Python import time is also outside.
**Whole-lane CPU totals are not per-case CPU.** Do not compare those totals with
steady-state case latency as though their windows matched, or divide them by
the measured count and call the result steady-state execution overhead. Warmup
is excluded only from the case latency summary, not from resource totals.

The collector follows the benchmark process tree and recursively includes
members of explicitly selected cgroups. Detached runtime jobs are discovered
from this run's new controller registry. Newly created job evidence can justify
a zero CPU baseline; otherwise the first observation is the baseline. PID start
ticks protect against PID reuse. The report includes the parent cgroup's CPU,
memory and affinity limits and starting load average.

Limitations are explicit:

- Short-lived processes or cgroups can disappear between samples; missing exit
  counters and discovery failures remain coverage gaps, never zero cost.
- Local loopback `sshd` and control-plane processes can be outside the descendant
  tree and detached-job cgroups. Their omitted work is declared.
- Live inference and upstream model-service memory/CPU are not measured. A local
  proxy does not account for external inference work.
- Summed RSS double-counts shared pages. PSS is reported where available; unread
  PSS stays missing. Sampled peaks are lower bounds and can miss brief peaks.
- Per-process CPU and cgroup CPU overlap; **never add the two totals**. Cgroup
  aggregation excludes nested overlapping scopes. Retained cumulative counters
  can improve CPU coverage but do not restore an unobserved memory peak.
- The sampler itself runs in the measured process tree. Its cost is reported.
  `sample_interval` is a target, not a guarantee; inspect actual sampling gaps.

Consequently `global_total_memory_or_cpu_claim_supported` remains false. Use
these results as scoped runtime evidence, with the declared omitted work. A
lower main-process RSS or an apparent transfer of work to helpers, detached
jobs, SSH services or the model service is not proof of lower system cost.

## Frozen V2 measurement revision

The final run uses `benchmark_v2.py` and `process_metrics_v2.py`, with identities
and lane order frozen in [FORMAL_PLAN_V2.json](FORMAL_PLAN_V2.json). The model,
executors, tasks, budgets, helper and scoring remain the first round's inputs.
The V1 files and original reports remain immutable evidence.

V1's whole-host `/proc` scan used about 87% to 88% of one core during formal
measurement. V2 enumerates explicit cgroups and all selected task children.
It retains fresh PSS reads and both PID/start-tick identity checks; it does not
cache PSS or substitute RSS. The 100 ms candidate failed the unchanged 5% idle
tree observer-CPU gate. A 500 ms candidate was declared before calibration and
formal execution, then passed two controlled-tree calibrations at 2.43% and
2.53%. Failed calibration and summary attempts remain archived.

The interval is a **wait after each sample**, not an exact 2 Hz schedule.
Observer CPU is sampling-call thread CPU divided by actual whole-lane elapsed
time; active sampling wall time excludes waits and is not that denominator.
All six final lanes pass the same 5% observation threshold individually.
This does not establish negligible observer perturbation.

Lower cadence can miss more short-lived processes, cgroup CPU counters and
short memory peaks. The report must show missing counters next to the scoped
CPU values and complete/incomplete PSS samples next to memory. Complete PSS
means readable selected identities in that sample, not full temporal or global
coverage. Do not compare V1/V2 peak differences as implementation savings.
Do not subtract observer CPU to reconstruct an uninstrumented execution cost.

The fixed order is replay native / app-server / facade, then live facade /
app-server / native, in six separate fresh jobs requesting CPUQuota 400%, MemoryMax
8 GiB and nice 10. Reports verify CPU and memory limits; effective cpuset and
nice are not independently observed. This is not a randomized or
counterbalanced experiment.
The [final report](REPORT.md) records outcomes and limitations; the
[independent audit](evidence/V2_AUDIT.md) verifies actual requests, fingerprints,
observer ratios, incomplete counters and source-file preservation.

## Fault-target distinction

The latest fault qualification kills the entire native runner, but only the
runtime helper in the Codex arms while the Codex core remains alive. Each
declared scope preserves the original runtime operation; these are not matched
whole-agent failures. Unverified cold Codex pending-call recovery is not scored
as a Codex failure. See [CODEX_RECOVERY_BOUNDARY.md](CODEX_RECOVERY_BOUNDARY.md).
