# Agent-identity Chrono retirement on the joint candidate

The actual execution source is `4cf78192425b8c9478147915745694495879a6f4`, tree `14317874cf27e0b6b7478d3f8389688e0eaf6cce`, on exact predecessor `902a8ccdff0326877515683717fe6e5db4356df7`. Evidence commits do not replace this execution identity.

## Actual qualification

All three complete package suites ran through the original repository test entry point:

`just test --locked --offline -p codex-agent-identity -p codex-utils-time -p codex-cloud-config --retries 0 --test-threads 2 --no-tests fail --success-output final --failure-output final`

The result is **61 distinct passing cases**: 16 agent-identity, 10 codec and 35 cloud-config. There were no retries, skipped cases, failures or errors. Both the actual child wait and its persistent terminal owner exited 0. The command took 128.135532583 seconds including compilation; no performance qualification is inferred.

[Original JUnit](retained/original-junit.xml), [case index](retained/CASES.json), [native result](retained/NATIVE_RESULT.json) and [complete readout](retained/READOUT.json) retain the exact output. JUnit UUID: `758c4326-cbda-4b1b-aa5a-5397978287ec`. JUnit SHA-256: `26343398e9bc4694f9a2aa658f5b8adafff0c49044c05c2016bcd7ec763cc855`.

The actual generated-assertion test still verifies its Ed25519 signature and now also checks whole seconds and the UTC `Z` suffix. All prior JWT issuer/audience/trusted-key, URL and retry-status controls remain. The complete codec and cloud-config suites were rerun on this new source; predecessor results are not inherited.

## Change and source binding

The two current-clock timestamp calls now use the retained `codex-utils-time` formatter with `Precision::Seconds` and `UtcSuffix::Z`. The agent-identity direct Chrono dependency is replaced by the existing workspace `time` and helper crates. Signed payload serialization, signing keys, verification, HTTP requests, timeouts and authentication rejection behavior are unchanged.

All **11,871 materialized tracked files** were checked against their Git blobs. Source inventory SHA-256 before and after the native execution:

`b445e915c770fa62990bf70daee54d3fb02a1562f16c2a62e779886bee329804`

The complete inventory is in the originals archive; [SOURCE_FREEZE.json](retained/SOURCE_FREEZE.json) binds the exact source.

- Cargo lock: `d8273be4e092dad45eef9d70263659ec22bbbe9edc471be55b76133ee9213f6d`.
- Bazel lock: `d240b972292c4101a01eceb1281dd15cdc43c77979711281bcaa5d0c680580c1`.
- Original Bazel lock update and check both ran with exit 0; the regenerated Bazel lock remained byte-identical.
- Actual target-platform offline Cargo metadata, scoped `just fix -p codex-agent-identity --locked --offline` and repository formatter all exited 0 before freezing.
- The independent target was an APFS clone of this task's completed target, with 112,849 regular files checked for distinct inodes and one link. Targets were not shared for writes.

[ORIGIN.json](ORIGIN.json) records the limited change. [NATIVE_PROTOCOL.json](NATIVE_PROTOCOL.json) was published before the new native execution.

## Control-plane failures and recovery

The initial preparation launch acknowledgement and its exact same-key retry both timed out at MCP. Separate inventory reads reported a 10,000-entry capacity bound; the directory contained 14,021 job entries. The cause of the acknowledgement timeouts is not established by that observation alone.

A read-only use of the already supported persistent terminal capability filtered five time-bounded candidate directories and matched the **complete original args** to one original job, `1a1f055d023-ffbe-787`. Its original exit JSON and witness both bind exit 0, no timeout/cancellation, and complete durable output. The preparation was not rerun. No permissions or inventory limits were changed, no historical jobs were deleted and no process was killed during recovery.

The archive keeps both failed tool replies, original inventory errors, exact original request and exit/witness, read-only recovery output and subsequent source-freeze/native terminal receipts.

## Remaining graph

The unchanged #6624 scanners were executed on the new lock. Direct workspace roots decreased **27 → 26**, indirect-only roots increased **94 → 95**, and **121 of 194 source-less candidate roots still reach Chrono**. Total direct Chrono edges across local, registry and vendored packages remain 34.

The agent-identity path continues through protocol; the selected cloud-config witness continues through core. [The graph result](retained/CHRONO_GRAPH.json) retains the actual `require_zero_actual_exit: 2`. No Cargo-deny pass, complete Chrono retirement, all-platform metadata result or Windows qualification is claimed. No advisory ignore or policy relaxation was added.

## Complete originals

[AGENT_IDENTITY_ORIGINALS.tar.xz](retained/AGENT_IDENTITY_ORIGINALS.tar.xz) retains 120 original source artifacts and receipts, including actual metadata/locks, source inventory, all native outputs/JUnit, original preparation/runtime records and the three terminal request/start/exit/output bundles. Compiled targets and the terminal runtime implementation remain on the original host.

- Archive size: 2098968 bytes.
- Archive SHA-256: `734427cd6921da4cfb90768ede056ce93d1bfcafc3b4bb8d943f1b9ca80c464b`.
- [INDEX.json](retained/INDEX.json) SHA-256: `2d3a17da3b008ce94ed547185065de93b0a978a4693e6950ff1a8614da87523b`.

Every archived member was reread and matched to the index. The size-policy exception binds this exact archive SHA and path; the global 512000-byte limit remains unchanged.
