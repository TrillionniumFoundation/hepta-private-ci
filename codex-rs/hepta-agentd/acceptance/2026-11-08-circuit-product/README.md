# Circuit ordinary-task integration boundary

This stage extends `1eb72a1131285f5de98beeb7c95a27eab72d647e` without replacing
the existing authority, model, evaluation, or adoption owners.

## Ordinary task path

An embedding explicitly selects `AgentdConfig::with_circuit_task_bootstrap` with
the original Cell state/inference owners, an input provider, and an invocation
provider that also publishes results. Ordinary signed `ObjectiveStart` then
uses the existing RunStart journal and the daemon's original AutomationStore.
The supervised bounded lane creates a Circuit, claims each original computation,
commits its Cell result, and settles the corresponding Circuit completion.

The invocation provider must derive stable requests from the admitted RunStart.
The input provider must retain complete original semantic inputs before returning
Prepare, and retrieve those exact inputs on Readback after owner restart. The
result consumer must durably publish idempotently by original run/result identity.
These are required deployment ports, not new authorities inferred from IPC data.

A terminal result contains verified Circuit history and original Cell decisions.
Result acknowledgement loss can republish that same result; it cannot repeat
inference. Startup reconciliation does not project a Circuit task as an unrelated
App Server run. Canonical intelligence and finite application execution profiles
are mutually exclusive with this explicit Circuit profile.

## Recovery and shutdown

Expired computation recovery can settle a retained original claim under a higher
current owner fence even after recovery lease-renewal capacity is exhausted.
Its settlement-only fence grants no execution lease and cannot schedule new work.
The same recovery fence can settle multiple retained results after reopen.

That low-level API does not manufacture a supervisor generation or automatically
reauthorize an old ObjectiveStart. Cross-generation product recovery still needs
an explicitly wired current supervisor and original input/model receipt owners.
The new journal event requires the new reader; old-binary downgrade compatibility
is not claimed. Existing histories omit the absent settlement field.

Shutdown closes admission irreversibly for this process, including late readiness
callbacks. A guard covers task construction through result publication; the worker
guard survives a cancelled caller. Drain checks active work before opening one
verified durable-history snapshot. Nonterminal runs and retained unresolved work
remain blockers after the in-memory lane is gone. Corrupt history fails closed.

## Cost measurement boundary

The clock-aware Cell entry measures the wait across durable inference admission,
checks its fresh deadline/queue bound before native contact, and retains that
original host wait alongside the native queue measurement. An unavailable
measurement remains unknown during readback; it is not replaced with zero or
elapsed recovery time. The host must preserve or fence the Cell clock epoch on
reboot or migration. Earlier task-queue wait is outside this local measurement.

This work does not establish a shared-weight load count, batching throughput,
adapter switching cost, memory savings, or a journal/fsync bottleneck. Those
require observations from the actual selected serving backend and workload.

## Qualification scope

The integration tests enter through signed `AgentdState::response(ObjectiveStart)`
with real AuthBus verification, durable RunStart, SQLite Circuit history, Cell
journal, and independent witness files. Their issuer, model, source, and readiness
are controlled fixtures. They prove wiring and recovery semantics, not production
model quality or learning benefit. Driver tests also cover delayed feedback,
Circuit deadline termination, exact result replay, and lost claim acknowledgements.

The following acceptance claims remain separate:

| Work | Status of this stage |
| --- | --- |
| Product lifecycle | Ordinary signed ingress is connected under an explicit host profile; production ports must be supplied. |
| Computation/effect boundary | Original computation claims, queue-cost observations, and durable recovery are connected; no effect authority is added. |
| Credit/training/adoption | Original results are available to the result consumer; causal credit, the complete production learning adapter, independent evaluation, and successor-task adoption remain unqualified. |
| State/memory lifecycle | Late-result settlement and durable drain improve recovery; complete production reboot, migration, revocation, and rollback are not established here. |
| Circuit plasticity | Bounded feedback remains supported. Dynamic topology admission and benefit stay gated pending lifecycle integration and a strong fixed-graph control including all costs. |
| Cell versions | The common-bundle registry is preserved. Arbitrary independent per-Cell releases and rolling switches are not introduced. |

Run the scoped native suites with the actual `hepta-joint-propose` helper pinned
from compiler metadata, followed by scoped `just fix` and `just fmt`. Preserve the
tested tree and post-maintenance tree separately; a green fixture suite does not
authorize any of the production qualification claims above.
