# runtime.supervisor crash-consistency qualification matrix

This is the execution gate for the durability/process boundaries owned by `runtime.supervisor`. Source unit tests are necessary but are not a substitute for this target-host evidence.

## Evidence rule

Each case must record: source commit, built binary digest, host identity/profile, filesystem and mount options, supervisor epoch, agent id, source/target release ids, lifecycle/release generations before and after, signed-intent digest/status when applicable, process and Matrix lease digests, injected fault point, reboot/restart action, observed recovery result, and independent reviewer acceptance.

A case passes only when recovery is deterministic and no stale process identity, stale generation callback, ambiguous signed mutation, or unauthorized release becomes active. An unresolved outcome must remain fail-closed and must be recoverable through the documented signed-intent ceremony rather than by deleting state.

## Required crash points

| ID | Injected boundary | Required result |
| --- | --- | --- |
| RC-01 | immediately after durable `Prepared` signed-intent publication | restart fails closed with the exact unresolved grant; recovery tool can inspect/fence it |
| RC-02 | after control-revision advancement, before release transition side effect | client outcome is indeterminate; restart remains fail-closed |
| RC-03 | after lifecycle `Starting` CAS, before process spawn | recovery does not claim readiness; lifecycle converges to a non-running state |
| RC-04 | after process spawn, before main process lease publication | child is not silently adopted as trusted; orphan handling is explicit |
| RC-05 | after main process lease publication, before readiness commit | exact lease adoption/generation fencing prevents PID-reuse acceptance |
| RC-06 | before and after release-state CAS/persistence | source/target/predecessor facts never split into an unauthorized mixed state |
| RC-07 | after target becomes healthy, before signed intent is marked `Committed` | restart remains fail-closed; explicit recovery can commit only with exact target/current witnesses |
| RC-08 | during drain deadline and stop grace expiry | escalation is bounded and only the exact leased process is signalled |
| RC-09 | between Matrix spawn and Matrix lease publication | companion cannot survive as an unowned accepted process |
| RC-10 | main or Matrix PID reuse with mismatched incarnation/identity | adoption is rejected; lease is retained for incident analysis |
| RC-11 | corrupt/truncated main lease, Matrix lease, or signed intent | daemon/recovery tool refuses state; no destructive auto-repair |
| RC-12 | disk-full/write failure during intent, lease, or release-state publication | no partially published JSON is accepted; caller observes rejection or indeterminate outcome according to whether mutation began |
| RC-13 | fsync/rename/replace failure | previous durable object remains valid or recovery fails closed; no torn terminal acknowledgement |
| RC-14 | `SIGKILL` supervisord while main and Matrix children are live | exact identities are adopted/fenced according to lifecycle and signed-intent state |
| RC-15 | repeated crash loop | main and Matrix automatic restart attempts do not exceed the configured budget (`<=3`) inside one recovery window |

## 256-instance HOL/load gate

Provision 256 registered instances. At steady state and while injecting one deliberately slow/failing process driver/filesystem path, record p50/p95/p99/max for: full fleet tick, single-agent tick critical section, health-to-state propagation, snapshot RPC, lifecycle mutation RPC, and drain/stop escalation. The qualification must demonstrate that the per-agent ticker lock segmentation prevents a full-fleet critical section and must separately document the remaining worst-case blocking caused by one synchronous per-agent driver/filesystem operation.

This gate does not prescribe a universal latency number: the accepted thresholds belong to the target host profile. Missing measurements keep deployment qualification and independent acceptance false.
