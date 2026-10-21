# Original V8 canary: complete terminal matrix

At 12:37:55 UTC on 2026-10-21, original run
[39583122999](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39583122999)
was complete with original conclusion `cancelled`. The fifteen jobs comprise
two successes (metadata and the Windows x64 source build) and thirteen
cancelled builds. The final Linux musl x64 release job ended at 12:36:35 UTC.
The V8 matrix is not qualified.

The original source is `48177153ad04605338c3a9a8dbd17defee9981bc`, with original
base `57636c7a17d4847eb5fd712409816fd040b4e90f`. All thirteen complete cancelled
logs contain checkout `3c32bedb07239b0cbdb38d100836258165cae633`, whose tree is
`22e14fcd85f7a3f2c5dc8f3a1bdb17efc81b4d62`. None of these results qualify the
later actual base, continuation head or local durability source.

`README.md`, `intermediate-status.json` and `terminal-log-analysis.json` retain
the earlier nine-cancellation checkpoint unchanged. The remaining four original
build logs are now archived alongside those nine:

| Job | Variant and target | Last recorded Bazel progress |
| --- | --- | --- |
| 119171686801 | sandbox Linux musl x64 | 14,142 / 15,709 actions |
| 119171686907 | release Linux GNU x64 | 13,717 / 14,383 actions |
| 119171686975 | sandbox Linux GNU x64 | 13,191 / 14,383 actions |
| 119171687082 | release Linux musl x64 | 14,910 / 15,709 actions |

`final-status.json` records every original job and step. `final-log-analysis.json`
verifies all thirteen complete raw logs against their archived SHA-256 and byte
counts, checks their actual checkout, and records their sole emitted error:
`The operation was canceled.` Each stopped in the original build step; every
associated artifact smoke was skipped. Progress is not a measure of remaining
wall time or successful artifact qualification.

The original workflow has a 90-minute job limit. These cancellations occurred
near that limit, but the decoded logs do not explicitly identify the initiator.
The original `cancelled` conclusion is preserved. No agent requested a
cancellation or rerun, and no timeout, cache permission, credential, matrix,
build flag or qualification assertion was changed.

Each XZ log preserves the connector-decoded UTF-8 bytes, including BOM and line
endings. Companion JSON files record raw and compressed hashes and sizes. The
successful Windows x64 source job is preserved in
`../ci-terminal-481-20261021/`; its POC command used a link-only `--no-run`
smoke, and does not establish runtime POC execution.
