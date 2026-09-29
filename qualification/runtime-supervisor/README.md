# runtime.supervisor target-host qualification

This directory contains the executable admission boundary for the remaining
`runtime.supervisor` host evidence. It does not manufacture a passing receipt.

Build the daemon with both explicit features when production-authority cases
are exercised:

```text
cargo build -p codex-hepta-supervisor \
  --features "qualification production-authority" \
  --bin hepta-supervisord
```

Run the daemon with `--qualification-metrics-out ABSOLUTE_PATH`. The default
and ordinary production builds contain lock measurement but no environment
driven durability failpoint. The `qualification` feature alone recognizes
markers under `HEPTA_SUPERVISOR_QUALIFICATION_FAULT_DIR`:

- `<durable-file>.write.fail-once`;
- `<durable-file>.file_sync.fail-once`;
- `<durable-file>.rename.fail-once`;
- `<durable-file>.directory_sync.fail-once`;
- `<durable-file>.link.fail-once`;
- `<target>.<stage>.delay-ms`.

A marker is consumed by rename before the error is returned. Delay values are
bounded to 60 seconds. These deterministic cuts qualify error classification;
they do not replace real ENOSPC, SIGKILL, filesystem, or power-loss tests.

`run_target_host.py` consumes a reviewed JSON plan whose command arrays perform
all required cases. It records command outcome hashes and combines them with
the daemon's lock snapshot. `verify_receipt.py` rejects a receipt unless every
required 256-instance, HOL, crash-consistency, and authority-distribution case
is present and passed. The plan and resulting receipt must name the real host,
binary digest, source commit, injected cut, before/after durable files, and
operator-visible terminal outcome.
