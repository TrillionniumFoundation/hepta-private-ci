# Execution06 detached measuring parent

Execution05 stopped after the original supervisor kept its PID/start ticks/session but changed parent PID from its measuring launcher to PID 1. The registered parent guard correctly failed closed. Execution06 keeps that guard and fixes the launch lifecycle: the complete measuring parent is detached before it creates the supervisor.

## Sole production entry

Use the actual initialized configuration descriptor and the verified interpreter:

```text
VENV -B SOURCE/operational/parameter_field_recovery06/daemon_bootstrap.py
  --config ACTUAL_CONFIG_PATH --expected-config-sha256 ACTUAL_CONFIG_SHA --execute
```

Omit `--execute` for metadata-only preparation. Direct `wait4_launcher.py --execute` fails before configuration access or spawning. The pipeline must pin both `daemon_bootstrap` and `wait4_launcher`; both sources are also required in the CWD runtime source closure. The policy structure version remains `.5`, with execution06 identified by its episode field.

The bootstrap reserves `OPS/daemon_bootstrap` exclusively and holds the episode launch flock. Its bridge calls `setsid` and forks the final measuring process. That process closes inherited executor FDs, routes stdin to `/dev/null` and stdout/stderr to retained regular files, and waits for a stable final parent PID of 1. No supervisor is created before the actual bootstrap has validated the detached identity and published acceptance.

Handshake JSON uses an exclusive same-directory temporary file, complete write/fsync, atomic `os.link` publication without replacement and directory fsync. A successful publication removes its temporary link. An I/O failure retains the pending bytes for reconciliation. Readers compare inode/size/mtime and the actual SHA; unlinking the temporary publication hardlink can change ctime without changing contents. The existing scientific/source identity guards remain unchanged.

## Evidence and failure behavior

The immutable launch directory contains `INTENT.json`, `FORKED.json`, `BRIDGE_WAIT4.json`, `READY.json`, `ACCEPTED.json`, `TARGET_STARTED.json`, and eventually `DAEMON_RETURNED.json` or a failure receipt. READY and ACCEPTED describe startup only. BRIDGE_WAIT4 measures only the bridge and explicitly excludes detached work.

The real supervisor outcome remains `OPS/wait4_launcher/WAIT4_COMPLETE.json`, with the unchanged full supervisor wait4 fields and added `measuring_parent_identity` and `detached_start`. Its owner ledger still reaps each returned direct child once. The daemon return record is not a kernel wait4 for the daemon itself. Postseal must bind the matching startup lineage, final real supervisor wait4 and daemon returned record, and reject bootstrap/daemon failure markers.

An existing launch directory, failed handoff, missing response or unknown outcome is never retried automatically. Inspect the original immutable attempt. A final measuring-parent identity change still fails closed. The 300-second individual capacity waits, absolute 12-hour deadline, memory/disk/C/CPU/steps/OOM/source gates, scientific argv and all original scientific source bytes retain their registered semantics.

CWD failure receipts now include bounded exception causes/contexts, and supervisor-parent mismatches include exact expected/observed fields. This preserves the initial failure when a later gzip/text closing write also fails. No resource retry, additional computation or relaxed guard is introduced.

## Actual tiny-process validation

All evidence is under `/workspace/scratch/178ced6a501f/execution06_recovery_20261030/`; no production RAW/OPS was created by this work.

The final focused run passed 79 tests: nine daemon/atomic-publication cases, five measured-launcher cases, fourteen owned-child cases, eighteen CWD cases and thirty-three original resource/backpressure cases. Its original `external_step.py` WAIT4 records exit 0. The first seven-case run remains preserved: one fixture inherited an ignored SIGHUP and failed to terminate its caller; the fixture now explicitly restores SIGHUP's default action before the test. That failed run is not represented as a pass.

A separate cross-exec test completed its originating host exec normally at 14:14:28 UTC. A later host exec at 14:15:15 UTC verified that the same detached measuring PID 398758/start 2275952/PPID 1 and tiny supervisor PID 398759 were still alive, with no final supervisor wait4 yet. It then released only the synthetic child. The original detached parent produced a real exit-0 wait4, exact owner closure and matching returned record. The startup READY was never counted as final wait4.

The tests cover originating command exit, actual caller SIGHUP, inherited-pipe closure, duplicate refusal, readiness/acceptance failures, nonzero target exit, and atomic-reader/no-overwrite boundaries. They do not claim survival after destruction of the whole container/cgroup or exempt any process from the original resource limits. Test-wrapper wait4 excludes intentionally detached descendants; their actual target wait4 and daemon interval CPU receipts are retained separately and must not be double counted.
