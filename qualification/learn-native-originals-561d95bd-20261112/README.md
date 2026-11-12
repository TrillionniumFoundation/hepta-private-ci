# Frozen 561d95bd original native evidence

This directory preserves the completed original seven-package scoped fix and the original ordinary A run at source `561d95bdf192b2631f6a762d2915d27a120d87bb`, tree `387feebbb3bc51f6d0a187137128e100ba63dea1`. The evidence operation ran only the explicitly authorized read-only UID0 Python collector; it did not launch Rust or tests or change source.

## Original results

- Scoped `just fix`: exit `0`, 188.43195889797062 seconds, clean source unchanged, empty fix patch.
- Ordinary A: **0 passed / 1 failed / 0 skipped**, one testcase, 2.693 seconds. The complete native driver interval was 2026-11-12T23:27:30.102150+00:00 through 2026-11-12T23:36:17.364844+00:00 and includes preparation and collection work. Source remained unchanged.
- Original JUnit: 4,345 bytes, SHA-256 `4dd49372bfa0b96eab209e9d58d562888eb02502625bdeafbb93c286744deabf`.

The Root child `ordinary-q24-original-process-CyoZj4` recorded the Initial exchange returning after 57,908 microseconds. It recorded 442,132 microseconds of the original frame budget remaining when the response was encoded. Its full 2,326-byte stderr is preserved. The daemon child `ordinary-q24-original-process-cWI616` then returned:

```text
Error: agentd protocol error: prompt pipeline durable owners failed to open: RuntimeOpen(Unavailable)
```

The original daemon stderr is 102 bytes. These observations establish the new failure location; they do not identify which durable owner's internal condition caused `Unavailable`. Compilation and source gates do not convert this native failure into a pass. There is no Adopt, evaluated post-B NoUpdate, or whole-cold success claim here.

## Actual Cargo profile records

The complete original helper JSONL remains in the archive at `public/hepta-native-561d95bd-ff41-v1/helpers/codex-hepta-infer-worker-host.jsonl`. Its original compiler-artifact lines 668 and 735 respectively report `curve25519-dalek 4.1.3` and `ed25519-dalek 2.2.0` with `profile.opt_level` equal to the string `3` and `fresh=false`. Both corresponding product-build records report the same optimization level and `fresh=true`.

`crypto-profile-observations.json` includes the member SHA-256 and original line SHA-256, full reported profile fields, and target identity. `crypto-compiler-artifacts.original.jsonl` contains the four original matching lines. These establish the reported build profiles, not isolated runtime causality or an end-to-end success.

## Integrity and collection provenance

The archive contains 41 original files / 2,362,651 input bytes. It is 95,452 bytes with SHA-256 `14ad1216433b466da41e5ad6cbb73edd0fa34b722b59babf3b72de632c206e0f` and Git blob `6c81c93f123963cc5a5fb5d2d083eeb9b1a4820b`. The manifest SHA-256 is `9832f5617432f8c07a0e1e35d46fb66a027cef17b5b66076e53e3a7b59525ba5`.

Every downloaded chunk was pinned to one H file version and written locally before the next chunk. The archive and all member sizes, SHA-256 hashes and Git blob hashes were verified. The collector also reread every original file after packing and confirmed unchanged bytes.

The first create-only script upload returned an MCP timeout. A subsequent read of that exact path explicitly returned FileNotFoundError. Only after that observation was the same create-only upload repeated and verified by size/hash. The collector itself was started **once**, using key `ci-evidence-collect-561d95bd-20261112-v1-ff41`, job `1a1d225b81e-2564-1ca4`. Its authoritative state is `succeeded`, exit `0`, complete/durable output and confirmed terminal publication, with no automatic retry or timeout. That result belongs to collection, not native testing.

The collection receipt archive preserves both upload outcomes, the intervening absence observation, the exact launch, process status/read records, pinned download responses, and local verification/extraction code.
