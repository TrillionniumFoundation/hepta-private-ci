# Supervisord fixture socket paths

## Problem and change

The five-agent daemon-restart fixture used the runner's default temporary root.
Its daemon and agent sockets have different path lengths, so the daemon can
be reachable while the longer agent control and App Server sockets exceed
Darwin's 103-byte pathname capacity. The existing FleetHarness and supervisor
product fixtures already create short temporary roots for this reason.

This change gives this fixture a private, automatically cleaned temporary
directory under `/tmp` on macOS. It retains the original canonicalization and
checks all three actual socket paths for each of its five agents before any
child launch. Other Unix platforms keep the original temporary-root selection.

The five agent identities, immutable release contents, permissions, resource
budgets, daemon restart and upgrade/rollback actions, control fences, peer
assertions, and original 120-second readiness and 15-second daemon deadlines
remain unchanged. No production source, runtime policy, or dependency changes.

## Evidence and qualification limit

The original Intel failure reported the first agent as Failed, generation 2,
with no current process or runtime identity after 120.77 seconds. It retained
neither that child's stderr nor the fixture's actual temporary-root path.
Therefore that failure does not establish socket length as its root cause.
This patch removes a source-proven path-length dependency and makes the actual
fixture geometry an explicit precondition. A passing normal macOS integration
test is still required; formatting and source checks are not a native pass.

The original failure is retained. No test rerun, extended deadline, retry,
disabled assertion, or weaker ownership boundary is part of this source cut.
