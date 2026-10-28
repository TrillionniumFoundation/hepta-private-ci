# SmolLM pair publication metadata — 2026-10-27

This directory records source publication and the pinned Chain pair. It is not a hosted CI or model-owner acceptance receipt. No local Hepta Rust, Cargo, Bazel or model-owner test was executed for this pin change. Product authority and adoption remain false/no-update until their original gates succeed.

`publication-metadata.tar.gz` preserves the exact four original commit payloads, four original-to-remote mapping records, four GET readbacks and their original summary. `manifest.json` binds every member and the bounded archive by SHA256. Source IDs, parent arrays, observed readback paths and prior observations are preserved byte-for-byte. A changed commit identity in the mapping is not rewritten into an earlier execution receipt.

The archived original head is `c23a2c90a2d0cfd6c09f2bd492a84c6758faafc6`, whose same-tree remote head is `ba7276e2c5b0dfb11e2eb45abe6ac36467881e66`. The original Hepta base remains `3e9efb15faa261a4dc3ffc3205cd259aaee41a3f` (#3293).

**The future commit containing this directory and the final Chain pins is not one of those four archived commits.** Its publication/mapping and any hosted execution require separate receipts. This avoids claiming an archive contains its own future source identity.

The existing workflow now pins [Chain draft PR #506](https://github.com/TrillionniumFoundation/Trillionnium-Chain/pull/506):

| Identity | SHA |
|---|---|
| Chain source | `0c804e9f5bcf6e972bbb4524c744d4b3c8801c34` |
| Chain base | `57c1ed545d067937cbd7aaa7570d5f22123265e6` |
| Actual GitHub prospective merge | `e22045b22fcda846d826243210c998a97d4559a3` |
| Verified merge tree | `ebd3545aac5815260ec1f94a2b9a2f383e8dd051` |

`chain506-native-pair.json` is the original root verification receipt. The actual merge parents are ordered `[base, source]`; native canonical merge-tree equality was checked. The original failed verification attempt remains recorded. The isolated blocked M06 branch is excluded. These identity checks do not assert CI acceptance or production activation.

All original workflow budgets, lanes, test selectors, zero-retry policy and admission requirements remain unchanged by this pin-only workflow edit.
