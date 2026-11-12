# V37: typed transport diagnostic compile failure

The fixed source is `3dbffb487de65a7c598a92510d081855d8b052dc`, tree `8ad6fd006dbe6b514e5f014e2a12bb50334c08c4`. The original full qualification entrance exited **1**. Its `fix-seven-crates` command exited **101** with six Rust E0599 diagnostics: `HostIssuerTransportError` has no `kind()` method. All six sites are diagnostic calls in `codex-rs/hepta-contracts/src/authority_root_frontier.rs` (248, 262, 272, 283, 303, 322).

## Observed result

The original idle preflight, isolated clone, exact source fetch, detached checkout, base ancestry, pinned operator toolchain and `fmt-before` all exited 0. The exact source fetch took 438.0954257850535 seconds within its original 600-second bound. Formatting left the source clean. The seven-package scoped fix stopped after 91.32105494802818 seconds; it did not time out and produced no source drift.

The original full caller checker, four QA entrances, ordinary native tests and exact17 actual UID0 Root tests were not reached. This attempt inherits no predecessor PASS. Its five reached cleanup checks passed: source/drift retention, original tool source verification, physical source equality, read-only donor verification and external tool equality. Later Root/helper setup and their cleanup steps were not reached.

## Original evidence

The complete 18,509-byte progress record, all 3,721 terminal bytes, all eight reached launch logs, all three execution JSON records, all three original command stdout files and the final source identity were fetched and independently byte-checked. The failing command stdout is 25,181 bytes, SHA256 `d446a47ff516fcb0b7282b44746dc2b08ac6efa3a34d23fa67fcc1929d880e3b`; the full terminal SHA256 is `cc1d55e8bf88b28600153782a3c0e7f258cc1f32fc38af4b7b3a0b5d68c24474`. PTY capture reports no lost prefix or capture error and equal bytes seen/stored, complete output and actual exited status1.

The first PTY start returned an MCP timeout. Root reconciled the byte-identical request with the same advertised idempotency key, preserving the original work path, attempt and deadlines. The acknowledged start reports automatic_retry=false and reused=false. Failed read-only progress/terminal/log acquisitions are retained separately; subsequent retrieval did not launch another native attempt. Native retries remain0.

## Repair and acceptance boundary

This directory preserves the failed source and its original evidence. A separate future source revision will replace the invalid diagnostic I/O-kind calls with the actual typed transport error, while preserving the first-refusal scope, debug-only output, original errors, deadline, closure and refusal behavior. That revision requires its own fixed-source qualification. This evidence does not certify the repair or the isolated future daemon/B/completion work.

Ordinary complete chains, positive adoption chains and ordinary NoUpdate/rollback chains remain **0 / 0 / 0**. Independent ordinary C and actual daemon+Root OS stop/restart remain unaccepted. Both workstreams remain Draft; main is not merged.
