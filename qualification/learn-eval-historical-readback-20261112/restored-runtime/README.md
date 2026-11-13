# Restored executor: actual compilation and scoped evidence

Recorded on 2026-11-12. This is a new verification record on the replacement
executor, not recovery of the original executor's missing files. The original
missing archive and interrupted scans keep their previously recorded status.

## Sources and observed results

| Source | Check | Actual result |
| --- | --- | --- |
| `6e4842b5ed28ab6f948646c051651a6c75085085`, tree `f1eb1c883bc4751aec415409ec23102912022dc9` | `just fmt --base d95…` | Exit 0, no tracked source changes. The empty format log is not a native-test receipt. |
| Same `6e` source | Caller checker self-test | Exit 0; original log and execution metadata retained. |
| Same `6e` source | Root historical Source closure QA | 21 tests passed; source unchanged before and after. |
| Same `6e` source | Complete caller inventory scan | Exit 1 after 1858.989 seconds: stale `q24_root_current_connect` definition marker. No full caller PASS. |
| Same `6e` source | First Linux native build | Exit 101 before tests: bindgen could not find the compiler builtin `stddef.h`. |
| Same `6e` source, existing GCC builtin header directory supplied | Second Linux native build | Exit 101 before tests: actual `AgentId` assigned to `CellScopeV1.agent_id`, which requires `StableId`. |
| `723a2d763339a55833519417a5f99f4defa9f8e2`, tree `63b36ed30394d135b481813b1020548d8cf628c5` | Root Source closure QA | 21 tests passed; unchanged source. |
| Same `723` source | All declared definition/caller markers and protected files | 504 boundary marker sets and 369 protected rows passed. This is not the complete call-site inventory scan. |
| Same `723` source | Third Linux native build | Exit 101 before tests: Source pin test fixture supplied non-serializable `StableId` values to JSON. |

The production fix in `723a2d7` converts the existing original `AgentId` string
through `StableId::new`; it preserves the original `AgentId` in `TaskFlowFence`.
The scope marker and its mutation test follow the real conversion. The CURRENT
guard marker now names the existing UFCS call,
`OriginalDecision::require_current(&self.original).await?`; both actual pre/post
checks remain in the function. The exact CALLERS digest was updated, with no
boundary or forbidden-marker deletion.

The subsequent test-only fix `f2bd9e335e08a24252e5dd2972fb8f58d29875f0` encodes
the three fixture identities with their existing `as_str()` values. It adds no
serialization implementation or production authority. Its native run was not
complete when this evidence set was assembled; it receives no PASS here.

## Windows result belongs to its actual scope

[Run 43147798456](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43147798456),
job `130949603928`, completed successfully on exact `6e4842b5…`. Its original
decoded job log is preserved losslessly: 263,502 UTF-8 bytes, SHA256
`356ab1fef0846cbeafb0c276f7788da310c4b21da2661520358e55e19cfe1a3d`.

The five native invocations report respectively 15, 2, 3, 2 and 12 passed tests,
with explicit `--retries 0`: 34 executed passes across private path state,
Prompt Registry, FinalUse, AuthorityLease and Agentd Prompt Runtime. Their
filtered-out test counts overlap and are not combined. The formatting,
acquisition attack checks and final clean-source check also completed.

This workflow version did **not** run the separate 36-case LEARN matrix. The
36/36 Windows observation on the different `6b8044a…` development-profile
candidate remains a separate record. Neither result covers the Linux-only
Root Source code or the outstanding GNU/shared 18 failures. Pending or queued
daemon, shared, architecture and blocking workflows are not successful checks.

## Runtime and evidence limits

Native commands use the repository's `just test` entry and the verified V8
helper. Actual local tools were Rust 1.96.0, nextest 0.9.103 and just 1.59.0;
the latter differs from CI's 1.51.0. The original missing-header failure is kept.
The second and third builds retain exit 101 and no JUnit, rather than being
classified as timeouts or test failures. All local invocations ran as UID 1000;
none exercised the ignored cases requiring actual Root custody.

`manifest.json` binds every original log/metadata file and its lossless XZ
archive. Every archive was decompressed and compared byte for byte before this
commit. The Windows file is the connector's original decoded log, not an
independently downloaded Actions ZIP. No source result is silently transferred
to later code, a different platform, or a different CI attempt.

Ordinary full-chain acceptance remains **Adopt 0 / NoUpdate 0 / daemon plus Root
cold restart 0**. This record supplies neither independent Observer/Evaluator
authority nor a completed ordinary learning entry point.
