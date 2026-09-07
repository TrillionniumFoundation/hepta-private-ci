# HeptaBao external source binding

The authorized HTTPS consumer targets reviewed service candidate
[`TrillionniumFoundation/HeptaBao@b798e88c98a7a9ab93a50abc1502c0a869233fda`](https://github.com/TrillionniumFoundation/HeptaBao/commit/b798e88c98a7a9ab93a50abc1502c0a869233fda),
proposed in [HeptaBao PR #78](https://github.com/TrillionniumFoundation/HeptaBao/pull/78).
This replaces the earlier bootstrap-only source pin with the actual single-node
HTTPS implementation. It is a reviewed candidate, not a complete OpenBao
replacement or a production rollout.

[Client integration](../../codex-rs/hepta-bao-adapter/README.md) and
[kernel authority design](../../codex-rs/hepta-contracts/FINAL_USE.md) describe
explicit host enrollment, CA validation, independent signing, durable replay
protection and consumer-only secret delivery. The old metadata projection API
still does not dispatch. Only metadata receipts cross its public result
boundary; this directory stores no credentials or secret payloads. The source
pin itself grants no runtime access and does not update automatically.
