# Combined native, UI and V8 smoke repair evidence

This report records the actual scopes executed during the continuation on
2026-10-21. It does not claim that the combined current head has passed its
original hosted matrix. Raw output, including failures before tests, is retained
losslessly under `fourth-wave/`; `artifact-receipts.json` binds every uncompressed
file and its compressed representation.

## Source integration

The published source `9decee38ff74bf52f3bbe03fba0386789ec5d92c`, tree
`c36f1b00c42ad30b02a896b0b5c51be2523ffb68`, retained the current owner base
`57636c7a17d4847eb5fd712409816fd040b4e90f`. Every remotely constructed commit
tree was compared with its local reviewed tree before a normal leased branch
update. Source identity, admission ownership, security policy and platform
requirements were preserved. Later commits in this PR repair the explicit V8
smoke feature selection and the evidence files' compression format.

## Executed scopes

| Scope | Observed result and limit |
| --- | --- |
| UI baseline Node 24 execution | 155 passed and 1 failed. The failure was retained before integrating the owner repairs. |
| Integrated UI Node 24 execution | 167 passed, zero failed or skipped. This is the direct JavaScript suite, not the hosted Node 22 or native browser matrix. |
| Native runtime, V8 POC and Git execution before the final Cargo feature repair | 114 tests ran: 113 passed, 1 failed, zero skipped. The failing POC feature assertion detected that Cargo's local sandbox feature did not match the sandbox-enabled linked V8. |
| Cold V8 process integration in that native run | The separate test executable successfully initialized 32 sessions on eight threads. Its process started without another test warming V8. |
| Git process-lifetime integration in that native run | Both real child-process cleanup cases passed on Linux. Windows qualification remains separate. |
| Broader combined native execution | Compilation ended naturally with exit 101 and ENOSPC after 591.529 seconds, before any tests ran. It was not killed and is not counted as successful validation. |
| V8 smoke workflow negative control | The same argument-execution regression failed in all eight subcases against the old workflow commands. These tests capture the real Bash step's Cargo arguments and artifact paths; they do not build V8. |
| Original `just test-github-scripts` after the smoke repair | 88 tests passed on the combined local source, including native release/sandbox and both Windows target argument cases. |
| Original blob size policy after lossless log re-encoding | Passed against current owner base `57636c7a17d4847eb5fd712409816fd040b4e90f`, with the existing 512000-byte limit and unchanged allowlist. |

The broad native command, original head, dirty source description, complete
Rust source hashes, start/end times, PID and exit status are in the preserved
`root-native-small-combined.json.gz`. It began at local head
`58a32221a488191e0a08966a269fe31a9208b87e`, with only a recorded queue-test
formatting diff, and finished at 09:48:50 UTC. Later owner and priority changes
are not covered by that compile attempt.

Earlier native failures due to missing development libraries and the default
upstream V8 download URL are retained separately. The successful artifact setup
used the repository's original setup action and the pinned OpenAI release. The
downloaded Linux archive and binding were verified against the release's
checksum manifest:

- Archive SHA-256: `a35c75d1f26e6a983885a45b33490a4ebe54f05050568b32b89cfb421b30b583`.
- Binding SHA-256: `7727826ae479bdb645e807239fb12d1f8e2e23de7a6cf16f5ee592690d1d8506`.

The final product POC defaults to sandbox, matching its linked runtime. Both
official canary and release smoke workflows now use `--no-default-features`
and explicitly add `sandbox` only for a sandbox archive. Ordinary and sandbox
variants remain in the matrix. Windows smoke retains both targets and its
existing link-only `--no-run` boundary. Real native builds and tests are still
required; argument tests cannot substitute for them.

## AuthBus global capacity fixture

Independent review found that the prior allocation filled the target issuer to
its own 512-row limit, so the expected capacity error could occur before the
global guard. The updated fixture retains one real target row and distributes
4095 synthetic rows over eight other issuers (seven groups of 512 and one of
511). It asserts both the global count and that the target issuer remains below
its limit, and retires all synthetic groups through normal quarantine. The exact
fixture SQL was executed against SQLite before and after the change; its count
receipt is archived. This validates allocation, not execution of the Rust owner
integration test. The original native CI must still execute that test.

The authenticated main-branch response also exposed the protected branch's
actual required contexts: `CI required` and `Architecture required`, both bound
to app 15368. The reduced receipt is retained. The separate protection endpoint
returned 403; this observation does not imply permission to alter protection or
complete visibility into organization runner configuration.

## Related qualified evidence

`../dependency-closure-20261021/` contains the actual dependency resolver,
security gates, repeated Bazel lock generation and GNOME/D-Bus interoperability
evidence. The two large cargo-deny logs were re-encoded from gzip to XZ without
changing their 12,790,661 uncompressed bytes. Original raw SHA-256 values remain
unchanged; `log-compression-receipt.json` also records both compressed forms.
No blob allowlist entry or policy limit was changed.

`../idle-priority-20261021/` contains the exact scheduler's four passing tests,
the old single-tail failure, source hashes and the independent harness. The
added real Queue/Core integration test still requires the original native CI.

## Remaining qualification

Only the original checks for the current source head and actual base can close
the platform and integration blockers. Previous-head greens, skipped builds,
these scoped Linux results and compilation without test execution are not
interchangeable. The shared host gave the actual Qwen research run an exclusive
large-memory window after the failed compilation; it is not a physical desktop
or mobile-device qualification. Research remains SHADOW_ONLY / DENY_ALL / NO_GO.
