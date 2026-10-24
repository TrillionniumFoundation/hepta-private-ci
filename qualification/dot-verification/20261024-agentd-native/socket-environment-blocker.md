# dot Unix socket verification blocker

Observed complete-library result: 188 run, 184 passed, 4 failed, 0 skipped; exit 100. The original per-test retry ran and failed again. No timeouts or ignores changed.

Four failing tests:
- control::socket_entry_tests::absent_socket_entry_can_be_prepared_and_bound
- control::socket_entry_tests::closed_socket_entry_is_removed_before_rebinding
- control::socket_entry_tests::live_socket_entry_is_never_replaced
- cognitive_ranker::tests::running_socket_uses_launch_bound_model_and_isolates_ranker_revocation

All report EPERM / PermissionDenied / Operation not permitted. The control tests use separate tempfile directories, /tmp/.tmp*/agent.ctl; the ranker uses /tmp/.tmp*/fleet/run/<fixture-agent-id>.ctl. Operations are local UnixListener bind and UnixStream connect probes, not external vendor access. Closed/live cases perform a fixture bind before prepare_socket; the live case fails there, while the closed-case log does not independently locate first bind versus rebound. Absent/ranker fail during the connect probe. This supports environment restrictions rather than shared-path collision or insufficient deadline. It does not independently attest all host policies or prove every possible source defect absent.

No source fix, skipped test, alternative socket path, security-setting change, or credential was introduced. The 23-case scoped success is separately retained, not used to claim full-library success. Prior cloud 188/188 is a different environment and not a dot result.

A single normal require_escalated attempt requested only these four tests with offline dependencies, --test-threads 1 and --retries 0 to diagnose without parallelism or additional retries. The execution wrapper failed before running the shell due to a protected runtime session-path read-only filesystem error. Thus the diagnostic did not execute; this is not a permission-expanded test pass. No wrapper/path/security workaround was attempted. Further socket verification needs a supported execution capability or explicit platform remediation; current source remains unchanged.
