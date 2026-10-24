# Native / Codex finite execution-layer A/B — review draft

**Status: root review and registration freeze required. No model run is
authorized by this file's presence.** The task fixtures, hidden cases and
author-only preparation checks are ready for review. Executor identities,
provider settings and the actual isolation supervisor remain to be bound by
the experiment owner before any agent sees a task.

## 1. Question and claim boundary

Under the same model/provider/reasoning effort, initial user task, tool
capabilities, host allocation and hard budgets, can the native agent loop
complete these finite Python repairs with a different cost/reliability profile
from the pinned Codex agent loop?

This is a newly constructed, bounded execution-layer qualification set: eight
small Python library repositories in four construction families. Every initial
source, reference solution and hidden expected observation was authored for
this pack. It is not SWE-bench, a sampled production workload, a cell-training
experiment, a split/migration experiment, evidence of emergence, or evidence of
AGI. The reference solutions verify that the tasks are satisfiable; they are
never shown to an agent. All tasks use Python 3.12 standard library only.

With the same model but different built-in system prompts and orchestration,
the treatment is the **complete execution/agent-loop package**. The comparison
does not identify pure transport overhead. Record system-prompt/configuration
digests and disclose that distinction. If a pure transport benchmark is later
needed, register a separate fixed-trace replay with no model decisions.

## 2. Frozen task inventory and grouping

| Construction family | Tasks | Main behavior under test |
| --- | --- | --- |
| `authored.incremental-parsers.20261024` | `stream_frames`, `stream_lines` | Byte boundaries, zero-length data, UTF-8 state, line-ending semantics |
| `authored.temporal-state.20261024` | `state_schedule`, `state_window` | Stale state, ordering, admission, exact boundary handling |
| `authored.immutable-transforms.20261024` | `transform_overlay`, `transform_intervals` | Recursive values, aliases, normalization, nonmutation |
| `authored.local-durable-formats.20261024` | `durable_store`, `durable_journal` | Compare-and-swap, failed replacement, committed-prefix recovery |

The two tasks in a family share construction provenance. All four families
also share one authoring process. Neither the eight tasks nor the hidden cases
are eight or 65 independent samples from real-world agent work. Report task
and family results; do not turn individual assertions into sample size.

`operator/task-index.json` fixes the task IDs, source groups, source hashes,
task-text hashes, private reference hashes and hidden-case hashes. Each task ID
contains the first 12 hex characters of the canonical visible bundle digest.
Case IDs are deterministic from their task-local ordinal and input digest.
No training data or agent trajectory is used to construct or select a case.

Materialization copies exactly `repair_target.py` and `TASK.md`. The complete
pack, its parent directory, `private/`, `operator/`, hidden request files and
reference solutions must **not** be mounted into the agent environment.
`TASK.md` is supplied verbatim as the initial user task, with the same working
directory description in both arms. The source starts identical. Agent-created
checks are allowed within its workspace; only `repair_target.py` is submitted.
Changing `TASK.md`, exceeding the registered source size, or submitting a
symlink instead of a regular file is a protocol violation.

Every primary attempt has a fresh workspace, fresh session and fresh executor
process tree. No conversation, task output, memory file, user skill, hidden
score, model answer or edited file carries between attempts. If Codex requires
a Git repository, the common isolated setup initializes an empty local-only
repository with no remotes, credentials, hooks or inherited configuration for
both arms. Creating Git metadata is setup, not a model action.

## 3. Registration and freeze before execution

The root owner reviews and fills `operator/registration.template.json` and
commits the pack before any model invocation. Archive the committed source,
resolved registration, Python image digest, exact binaries and tool/supervisor
source hashes. Preserve the draft and every preparation defect separately.
After freeze, changing a task, hidden expected value, budget, selection rule or
executor requires a new study identity. Never silently replace a failed row.

The same common model contract must bind both arms:

- provider endpoint/deployment, provider model identifier and immutable model
  revision when available; unresolved aliases are reported as such;
- reasoning effort, decoding controls and provider output-token limit;
- account/service tier and region when these affect routing or cost;
- the exact initial user-task bytes and common additional instructions;
- supported provider token-accounting fields, including reasoning and cached
  token semantics. Unknown usage remains null, never zero.

The pinned native and Codex source commit/binary digests, runtime version,
system-prompt digest, resolved configuration and model-visible tool schemas
are separate treatment records. Disable external MCP tools, browsing, network
tools, remembered context, repository hooks, skills and user configuration.
API keys remain in the external provider broker and are absent from tool
process environment/files. Do not copy real user home directories into a run.

Both arms must use their actual qualified model/tool-loop owner. An echo,
scripted provider, config-bootstrap binary, or Core-linked qualification
executable is not the real native agent treatment. In particular, a small RSS
measurement of a **Core-linked config-bootstrap qualification executable**
cannot establish a Core-free agent RSS benefit. Bind an audited dependency
inventory and actual process role to each measured binary; use a real Core-free
owner before making that specific claim. Compilation, linking and fixture
success do not substitute for an admitted provider-backed agent run.

## 4. Enforced permission equivalence is an admission gate

**A prompt is not a permission boundary. A matching permission label or an
executor's own claim is not proof of equivalent enforcement.** Before either
arm runs, an independently controlled supervisor must demonstrate that the
actual reachable tool effects have the same restrictions. Map tool operations
to capabilities, not just names. Exposed schemas can differ as part of the
treatment, but one arm cannot have extra capabilities.

The common capability profile must enforce:

- a fresh bounded workspace as the only persistent writable task area;
- no host/home/config/credential/private-evidence mounts, no host process
  inspection, and no escape through symlinks or path traversal;
- read-only pinned interpreter/runtime files and a bounded ephemeral scratch
  mount; no package install, downloads or external code retrieval;
- no tool-side network, external sockets, messaging or provider credentials;
- process creation only inside the supervised sandbox subtree, with no access
  to other jobs or users and no inherited host file descriptors;
- the same read/list/write/patch/execute effects, tool-output caps and process
  limits for both executors;
- hard CPU, memory, PID, wall-time, tool-call and observable provider-budget
  limits, enforced outside the model and executor.

An acceptable implementation can use an audited container/bwrap/namespace
supervisor with the same immutable image, UID policy, mounts, namespace and
cgroup configuration. Record the actual enforcement artifact and independent
preflight receipts. Preflight probes use only operator-created sentinel files
and local fixtures; they never probe real secrets or external sites. Validate
both denied access and permitted workspace operations. A policy hash is useful
for identity, but does not by itself establish enforcement.

If Codex has an unmediated built-in shell/file tool, or native has a broader
process API, either route both through the same enforcement boundary or mark
the corresponding comparison **`not_comparable`**. Do not run an unrestricted
arm just to obtain a number. Missing sandbox evidence is **`not_admitted`**.
Unknown permission equivalence cannot be reinterpreted as equal permissions.

## 5. Proposed primary budgets, frozen on registration

These concrete values are the draft defaults; root may revise them only before
registration and before model exposure:

| Limit | Common per-attempt value |
| --- | ---: |
| Agent decision wall time | 180 seconds |
| Agent decision rounds | 12 |
| Model request count | 12 |
| Completed or failed logical tool requests | 24 |
| Provider-declared generated tokens, including reasoning where counted | 8,192 |
| Aggregate provider-reported input tokens | 65,536 |
| Tool result body | 32 KiB each / 256 KiB aggregate |
| Submitted Python source | 64 KiB |
| Workspace writes | 16 MiB |
| Tool/executor CPU allocation | 2 logical CPU equivalents |
| Dedicated full process-tree memory | 2 GiB |
| Dedicated full process-tree PID count | 32 |
| Automated retry count | 0 |

The supervisor must be able to enforce the same semantics. Reserve the remaining
generated-token budget before each provider request and set its output limit
to no more than that remaining budget. Include all charged reasoning output
in the ledger; if either backend cannot expose or cap a needed quantity, do
not describe this as a token-budget-matched comparison. Input limits require
pre-call tokenizer/usage accounting with a bounded reservation; discovering a
large overrun after a call is a violation, not successful enforcement.
One decision round is one model-request lifecycle that can emit tool requests
or a final answer; streaming chunks are not extra rounds. A fresh continuation
request consumes another round and another request. Provider retries also
consume request/budget ledger entries; this study allows zero automatic retry.

The agent wall timer starts at isolated executor launch, includes model/tool
latency and executor startup, and stops when the turn terminates or the hard
limit kills its whole process tree. Fresh workspace preparation and independent
grading are timed separately. Remote model-server CPU/RAM/energy are unknown
unless the provider supplies them; local RSS does not include them.

The primary treatment is **fresh-process cold start**, not an OS page-cache
flush or a cold remote-model server. One-time building, dependency installation,
provider authentication setup and workspace materialization are recorded as
separate setup components. Both binaries and the common runtime image are
already built and staged before the first pair. Do not drop host caches or
alter unrelated jobs. Record provider cache-hit usage and task order; remote
server warmth and OS caching are not assumed equal or measurable. No warm
reused-process quality/RSS trial is registered here. Do not mix a warm native
daemon observation with a cold Codex CLI observation and label the difference
a cold-start or complete-memory benefit. A warm trial would need a new frozen
phase with fresh task exposure and equivalent retained state.

The same provider model request needs only the common model-input contract;
native and Codex may assemble different full contexts. Actual prompt tokens
are measured and charged, so a larger scaffold consumes the same fixed budget.
Do not remove its overhead from one arm's accounting.

## 6. Assignment and analysis units

There are 16 primary attempts: one native and one Codex attempt for each of
the eight tasks. No task-specific prompt improvement or repair between arms.
Use `hepta-native-codex-ab-20261024-v1` as the order seed. Hash-sort the four
family IDs, then hash-sort the two task IDs within each family. Run all
attempts sequentially, with no concurrent arm. The first pair of each family
runs native then Codex; the second runs Codex then native. Thus pair order
alternates N→C / C→N through all eight pairs, with one of each order per family.
The next pair starts only after the previous pair's full process trees settle.
`operator/assignment.py` computes this exact schedule. Save actual start order
and any deviation; no scheduling choice depends on model output or score.

Primary outcome is all hidden checks passing on the frozen submitted file,
joined with a valid execution/permission/budget receipt. A task passing six
of seven checks is not a solved task. Preserve the assertion breakdown for
diagnostics but do not choose a new primary metric after seeing outcomes.

Report the eight paired task outcomes, four family outcomes, native-only and
Codex-only successes, and the paired success-rate difference. With eight tasks
from four authored families, this is descriptive qualification; no population
superiority/AGI claim or significance promotion is registered. Do not treat
65 checks as independent trials.

Report wall/CPU/RSS/tokens on all attempts together with status. To avoid
calling a fast crash efficient, also report capped time-to-verified-success:
successful tasks use actual agent wall time, all other admitted attempts use
the 180-second cap. Give cost among jointly solved pairs separately, retaining
its selected-sample limitation. No missing measurement becomes zero. No retry,
outage, timeout or failed grading row is silently removed.

## 7. Independent grading and information separation

After each attempt ends, the supervisor seals a regular-file copy of
`repair_target.py`, its digest, the unchanged task digest, workspace manifest,
model transcript and process/tool ledger. No grading feedback goes back to any
agent, including later tasks. Prefer collecting all primary submissions before
opening any model-run hidden grade. Grades cannot affect task order or prompts.

The trusted process reads `private/<task>/cases.json`. It does not import the
candidate. `operator/pack.py requests` emits input-only JSONL; no reference,
expected output or pass/fail value crosses into the candidate sandbox. The
public `candidate_runner.py` imports the sealed candidate **inside a separate
admitted sandbox**, receives inputs on stdin and returns observations. Mount
only that candidate, the public adapter and pinned runtime read-only, plus an
empty bounded temporary directory. Never mount the task pack/private grader.

The trusted `pack.py judge` validates every case/order/input identity and
compares canonical JSON observations. It preserves type distinctions such as
false versus zero. Extra/missing output, invalid JSON and candidate crashes
are visible grading failures. A reply's reported source hash is not trusted
attestation: independently bind the sealed candidate and immutable mounts in
the supervisor receipt. The adapter is not a sandbox or a security boundary.

Use a separate common grading budget (5 seconds CPU, 10 seconds wall, 256 MiB,
8 PIDs per candidate), collect all descendants, and preserve the raw stdout,
stderr and termination reason. Grading errors caused by the trusted harness
are classified separately from incorrect candidate behavior. Do not fix a
harness defect and rescore selectively: freeze a new harness identity and
rescore every sealed candidate from both arms, retaining original receipts.

## 8. Separate controller-fault qualification

The Python application tasks `durable_store` and `durable_journal` test repaired
library behavior only. Passing them says nothing about the executor's own
crash recovery, effect ledger, idempotency or exactly-once semantics.

Controller faults are a separate four-run qualification: two predeclared fault
cases through each actual controller owner, using a deterministic one-request
fixture, not a repair task or an LLM quality run. The fixture is supplied in
`controller/effect_fixture.py`. It intentionally appends one effect record on
**every invocation**; it does not hide duplicate replay behind its own
idempotency. The controller must supply the same original logical run, request
and effect identities across recovery. Physical process generation and attempt
IDs may change and are recorded separately.

| Fault case | Injection boundary | Expected disposition |
| --- | --- | --- |
| `acknowledged_effect` | Effect exists and the owner has durably committed its terminal tool receipt; kill owner before consuming that receipt in the next transition | Resume the original run, reuse the exact original settled request/effect result, perform no duplicate effect, and complete the deterministic continuation |
| `indeterminate_effect` | Fixture has fsynced the effect but is paused before terminal output/ack; kill owner and its full process tree | Preserve original identity and report the unresolved effect as indeterminate; do not automatically re-execute it or fabricate success |

The public fixture signals `effect_written`; for the second case it waits for
an operator-only release file before any terminal acknowledgement. The
supervisor independently observes the fsynced append and the owner's durable
receipt boundary. A tool-start hook alone does not prove the requested fault
point. Codex must expose the **same fault point and semantic contract** before
comparing it with native. A different restart stage or a manual reconstructed
prompt is not an equivalent control.

Use fresh controller workspaces, explicit original `run_id`, `request_id` and
`effect_id`, and a fixed 2-second restart delay. Each case has one injection,
30 seconds total controller wall budget, 2 CPUs, 256 MiB dedicated tree memory,
8 PIDs and zero automatic replay of indeterminate effects. The original logical
IDs and budget are never reset. `invocation_id` identifies physical tool
attempts, and every append retains all four identities. The controller
transport adapter and provider stub, if used to submit that one deterministic
request, are pinned and labeled fixture-only; they do not qualify real-model
agent behavior. These four runs are separate from the 16 model attempts.

Report injection-boundary attainment, actual receipt and effect IDs before and
after restart, process generations, observed append count, resume latency,
duplicate effects, terminal disposition and unsupported owner APIs. An
**indeterminate** result in its registered case is a valid safety outcome,
but **not task success** and not proven rollback/exactly-once completion.
In the acknowledged case, inability to resume is a recorded recovery failure.
If the two owners cannot implement the same boundary/contract, keep these
cases `not_comparable` or `not_admitted` and do not launch an approximation.

## 9. Required raw metrics and status ledger

Record immutable task/model/executor/policy/supervisor identities; UTC start
and end plus monotonic durations; final source digest; initial/final manifests;
all provider request IDs and nonsecret input/config digests; complete model
usage with cache/reasoning units; logical tool and actual process counts; retry
counts; and the exact reason for termination.

For each process record its sandbox PID, parent PID, launch/exit event,
executable digest, role, exit status/signal and resource attribution. Track
short-lived descendants, not just the currently live process list. Obtain
aggregate CPU and peak memory from the dedicated cgroup/job object covering
the whole tree. Report root-process RSS separately; do not sum asynchronously
sampled peaks and call it simultaneous tree peak. Reused broker/shared service
cost is a separate component with its own attribution. If unavailable, mark
the full-tree metric incomplete and do not claim a complete memory advantage.

Terminal execution status is one of `completed`, `tool_error`, `provider_error`,
`timeout`, `budget_exhausted`, `crashed`, `cancelled`, `not_admitted` or
`not_comparable`. Functional grade is separately `pass`, `fail`, `grading_error`
or `not_graded`. Preserve cancellation and infrastructure errors, rather than
turning them into a convenient missing observation. Unperformed recovery has
an explicit reason. Energy remains unmeasured unless an actual meter is bound.

## 10. Stop and extension rule

No model call occurs until root approves the concrete source/task/protocol and
the registration is frozen with real common capabilities. If a gate cannot
be met, publish the pack and exact blocker; do not launch a weaker experiment
and reuse the intended claim. After the registered attempts, report the full
result, failures and costs. A larger corpus, different model, extra attempts,
new budget or task repair needs a new preregistered study and fresh model
exposure accounting. These results cannot be relabeled cell learning gains.
