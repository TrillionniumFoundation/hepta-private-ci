# Reproduction

Use the repository source at the R19 delivery commit and Rust 1.95.0. The four
imported R18 sources must retain their recorded Git blob identities. No external
Rust crates or network downloads are required. The test binds local IPv4 TCP and
uses real child processes, file locks, fsync and SIGKILL. It requires Linux.

```sh
rustc --edition=2024 -D warnings \
  tools/hcsn/native_owner_r18_20261101/main.rs -o /tmp/hcsn-r19-baseline-new
rustc --edition=2024 -D warnings \
  tools/hcsn/native_owner_r19_20261101/main.rs -o /tmp/hcsn-r19-candidate-new
python -B tools/hcsn/native_owner_r19_20261101/check_v2.py \
  --binary /tmp/hcsn-r19-candidate-new \
  --baseline /tmp/hcsn-r19-baseline-new \
  --output /tmp/hcsn-r19-new-run
```

Choose a new output directory. The checker refuses to overwrite a previous run.
`PROTOCOL_V2.json` records the six unchanged cases plus the separately frozen seventh allocator-death case;
`SOURCE_FREEZE_V2.json` records the final code/protocol identities before execution. The original `SOURCE_FREEZE.json` describes V1 at commit d9bfd93d86a985dc603cce8b0c4ade6102cb7696; its source/report bytes and original run are preserved in `source_v1/` and `results/run01/`. A baseline
exit 2 in the alias case and an owner exit 2 after lost TCP delivery are required
regression observations, not omitted failures. Services are stopped with SIGKILL
after checks, and all process exit records remain visible.

The prototype is trusted-loopback-only and unauthenticated. It does not establish
cross-host networking, hostile-writer resistance or a native numerical kernel.
