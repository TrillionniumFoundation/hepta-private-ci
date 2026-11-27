# Synchronize the final fleet snapshot boundary

The six-agent fixture checks two different observations: direct Agentd control
health and the supervisor's last-tick readiness snapshot. A successful direct
control request does not update that snapshot. The final release wait previously
required the target's release and direct readiness, then returned without
requiring the supervisor readiness that the final boundary asserts for all six
agents.

Only the final Agent 5 rollback wait now also requires each of those six agents'
supervisor snapshots to be active and healthy. It uses the same existing
`RELEASE_WAIT` timeout, supervisor tick and 25 ms polling loop. The other release
waits use an empty required set and retain their original target conditions.
No second timer, retry loop or process API is added. Existing ticks can continue
for more of the same budget and retain normal supervisor behavior and fault
checks. The production health logic and polling interval do not change.

The original final snapshot assertions remain unchanged. The original process
identity, spawn/runtime generation, peer control health, ingress, real automation
turn and explicit rollback assertions also remain. The final rollback still
requires the target's exact release and its direct ready response. A permanent
unhealthy snapshot cannot satisfy the added condition and cannot receive a new
90-second budget. Peer identity changes still fail the existing assertions.

The original Intel attempt had one passing and one failing Rust case. The
six-agent case reached its final Agent 0 snapshot assertion, whose healthy bit
was false; the immediately preceding direct peer checks had returned. The
background probe runs independently and the snapshot records its last tick, so
these checks were not a synchronization barrier for the asserted state. The
original log did not print the final snapshot or the failed probe's reason.
This source correction does not prove which probe event produced that false
value or that the original failure is fixed in a new native execution.

Preparation base: `c2326de0631f27aee7178dcdf549f34e73c9b9dc`.
No new native execution or production behavior qualification is claimed.
