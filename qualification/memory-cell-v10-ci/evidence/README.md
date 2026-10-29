# Retained native CI evidence

The [total report](../../memory-cell-v10-results/REPORT.md) records the current
validation status. This directory preserves original attempts, including
failures. A later repair does not rewrite a failed attempt's receipt or logs.

| Attempt | Original run | Observed boundary |
| --- | --- | --- |
| 01 | [40900187124](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40900187124) | Ordinary tests failed to compile: extracted release wrapper field path |
| 02 | [40902864222](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40902864222) | Ordinary tests failed to compile: undeclared assertion import |
| 03 | [40906652698](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40906652698) | 969 ordinary tests passed, 31 skipped; driver then failed to find JUnit; actual test did not start |
| 04 | [40909855139](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40909855139) | Successful verify: 11 driver checks, 969 ordinary tests and the exact actual lifecycle parent; all 343 archive members verified |

Each attempt has a `GITHUB_ORIGIN.json` with stable run, job, artifact and ZIP
identity, the original transport index and receipt, decoded complete job log,
and local archive-member verification. Temporary signed download URLs are not
retained. Original timestamps and paths in the receipts remain unchanged.

Small ZIPs are stored directly as `artifact.zip`. Larger ZIPs can be retained
as canonical base64 chunks with `ZIP_PARTS.json`; reconstruction must produce
the exact original GitHub ZIP, including its size and SHA-256. The ZIP contains
the original tar, index and receipt. The tar retains original Unix names.

From this directory, verify the complete transport without extracting:

```sh
python restore.py --attempt native-attempt-03 --verify-only
```

To restore every verified regular file into a new directory:

```sh
python restore.py --attempt native-attempt-03 --output /tmp/hepta-v10-restored
```

Restoration verifies every indexed member before copying the staged output.
Recorded sockets, links and other nonregular entries are not recreated. This
is offline validation against retained origin metadata, not a new live GitHub
authentication request and not a rerun of tests, training or inference.

`tests_executed: true` in an original driver receipt means the verification
path invoked tests; it does not imply test compilation, all cases, JUnit
collection or the actual lifecycle succeeded. Read the phase exit codes and
the final `passed` field. The finalization gate additionally authenticates a
successful GitHub run/job/artifact and both exact test commands; it cannot use
these failed attempts as its verification proof.
