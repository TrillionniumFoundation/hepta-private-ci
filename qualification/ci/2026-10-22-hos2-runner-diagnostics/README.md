# HOS2 hosted runner diagnostics

The original source `95f330bd9d81c33865078cd6e5b503bd40e6dfde` failed its
scoped native job twice in
[run 39587172171](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39587172171).
Jobs `119192768692` and `119246305956` both report that the hosted runner lost
communication. Their final command logs return `BlobNotFound`. The annotation
names several possible causes; it does not establish an out-of-memory event.
The scope job's retained output binds the three Agentd changes to base
`f27c14641753e0b03ceaa0e76031c6d19b1efbfb` and selects the original scoped lane.

## Change

The scoped job uses the existing development-lane Cargo settings:
`CARGO_BUILD_JOBS=2` and `CARGO_INCREMENTAL=0`. Package selection, reverse
consumers, assertions, the 3,600-second command deadline and the 75-minute job
budget retain their existing behavior.

The optional `hepta_ci_exec.py --observe-resources` flag writes a separate
JSONL file beside the raw command log. It records actual readable Linux memory,
load, pressure, child status, disk usage and cgroup v2 counters. Initial,
periodic and final observations are bounded to 256 samples and 2 MiB.
Unavailable values remain `unknown`; reaching a bound records the remaining
observation gap. Cgroup ancestry is explicitly marked incomplete if the visible
parent chain exceeds the observation limit. Counters and peaks can include
other processes or activity before this command; they do not identify its
resource consumption by themselves.

The executor keeps the command's raw output, parsed test counts, exit status
and process-group deadline behavior. Observation errors do not turn a failed
command into a pass or a successful command into a failure. The final receipt
binds the resource file's bytes and digest when recording succeeds.

The existing `always()` artifact step already captures `impact-test.json*`,
including the resource sidecar. Abrupt runner loss can still prevent that step
and leave no downloadable artifact. This change supplies observations when
the runner can retain them; it does not guarantee recovery after machine loss.

## Qualification boundary

Local Python process and resource regressions exercise this execution wrapper.
They do not qualify HOS2, a native device, or the new hosted runner job. A new
original scoped native result is still required. Changes to shared CI files
also retain the existing full-repository qualification rule; the scoped lane
can be checked after the qualified CI change reaches its target base.
