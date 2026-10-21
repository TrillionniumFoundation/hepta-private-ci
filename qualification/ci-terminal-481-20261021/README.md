# Original 481 CI terminal evidence

This archive records completed original jobs for source
`48177153ad04605338c3a9a8dbd17defee9981bc`. Those workflows were created against
base `57636c7a17d4847eb5fd712409816fd040b4e90f`. The actual base branch was observed
at `f768d30dbd79d5d56923770ba3becb8018230e27` during this collection. These results
do not qualify that later base or either continuation head.

## Completed jobs and their scope

| Original job | Result and evidence |
| --- | --- |
| Architecture source `119168737606` | Success; 31 original command records and their complete logs in the original artifact ZIP. |
| Architecture base `119168737895` | Success; four repository/provenance command records. Its native work uses the existing identical-tree reuse rule and requires source-head success. |
| Architecture required `119185724444` | Success; original aggregate log records both applicable lanes succeeding. |
| UI source `119176036877` | Success; complete decoded job log and original summary artifact. |
| UI base `119176036978` | Success; complete decoded job log and original summary artifact. |
| V8 Windows x64 `119171686656` | Success; builds the ptrcomp sandbox release pair and compiles/links the POC using `--no-default-features --features sandbox --no-run`. This step does not execute the POC tests. |
| Full cargo-deny `119194391140` | Success in the original job-status response. The dedicated log connector returned `Transport closed` twice; the generic fetch endpoint is unsupported. A complete deny log is not present in this archive. |

The Architecture source and base trees both equal
`22e14fcd85f7a3f2c5dc8f3a1bdb17efc81b4d62`. The base job's actual locally created
commit is `4a6507e8ce71fd88bcfbd435647b7a0ac2b25f64`, with the recorded base and
source as parents. It is not the GitHub prospective-merge commit. All 35 command
records have exit zero, clean before/after source identities, and original log
byte counts and digests verified against their ZIP members. The base artifact
does not claim a second native execution.

The UI base job evaluates its own synthetic commit,
`97873c57ecff937b5f445dfa23b5b32a00595048`. Both UI lanes report six default browser
cases and nine fixture cases, with no skipped, unexpected or flaky cases. Their
pixel result files report success for 60 default and 78 fixture result records.
The 85-file UI source identity is identical in both builds. The summary archives
contain twelve selected members each; all twelve match the original evidence
inventory's byte counts and hashes. The complete inventory also identifies the
other browser artifacts, which are not duplicated here. Its `qualification:
false` field is preserved: the grouping manifest inventories evidence and does
not itself grant qualification.

## Artifact custody

The four ZIP files are unchanged original GitHub Actions downloads. Each archive
SHA-256 matches the corresponding original upload log, and each member has an
independent byte count and digest in the adjacent JSON receipt. The largest ZIP
is 308911 bytes, below the unchanged repository blob limit.

The six full job logs preserve the connector's decoded text, including its BOM
and line endings, as UTF-8. Their XZ archives round-trip byte for byte. Adjacent
JSON receipts give uncompressed and compressed sizes and digests. No temporary
download URLs or credentials are stored.

`artifact-verification.json` records the actual archive checks.
`architecture-command-verification.json` preserves the command identities and
observed test counts. `job-status-snapshot.json` records the observation time of
each run, current and queued jobs, and the log-retrieval limit. Remaining original
full-repository jobs, other V8 platforms, current-base qualification and all new
continuation gates remain separate requirements.
