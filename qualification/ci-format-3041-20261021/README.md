# Original continuation formatter failure

The original continuation 3041 repo-checks job
[119206184343](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39591475871/job/119206184343)
failed at formatting step 19 on source
`52293403ea1e06465c41d24d39b54959bad40936`.

Its original frozen command was
`uv run --frozen --project scripts ruff format --check scripts .github`.
Ruff reported that `.github/scripts/test_v8_cargo_smoke.py` would be reformatted
and that the other 182 Python files were already formatted. All earlier job
steps passed; Prettier was skipped after this failure.

The Python file was fetched from the exact source above and compared byte for
byte with the original 481 file already preserved in
`../ci-format-481-20261021/test-v8-cargo-smoke-before.py.raw`. Both contain
4,933 bytes with SHA-256
`33b7df0a9861c283dbd95b2d35e3588e90d5e27b40940b89498ec636a933b654`.

This is the same two-string quote normalization already fixed by
`d1c402e5b15addfbfe60a8473763750db0bd5f1e`. The original 481 receipt contains
the real local failure reproduction, existing wrapper tests before formatting,
the frozen formatter's exact output, equal Python ASTs, and the successful
full formatter check afterward. No new source change or weakened gate is
needed for this duplicate manifestation. The failed 3041 CI result remains
failed until a new source receives its own qualification.

The complete connector-decoded 3041 job log is preserved losslessly as XZ.
Its receipt records the original job and step statuses and both raw and
compressed byte sizes and SHA-256 digests. No original job was cancelled or
rerun during this investigation.
