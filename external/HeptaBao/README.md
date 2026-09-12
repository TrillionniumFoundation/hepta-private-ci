# HeptaBao external source binding

The authorized HTTPS consumer pins the integrated service on
[`TrillionniumFoundation/HeptaBao@eac9c608bfda77a8972e1e8a1343dfc21985d62b`](https://github.com/TrillionniumFoundation/HeptaBao/commit/eac9c608bfda77a8972e1e8a1343dfc21985d62b)
on `main`. The real issuer and consumer processes passed 20 synthetic TLS,
replay, signature, provider-denial and restart checks against that source tree.
The [source-bound receipt](../../codex-rs/hepta-bao-adapter/qa/evidence/real-consumer-20260912.json)
records the build and executable digests. This validates the bounded KV consumer
profile; complete OpenBao replacement and production rollout remain unqualified.

[Client integration](../../codex-rs/hepta-bao-adapter/README.md) and
[kernel authority design](../../codex-rs/hepta-contracts/FINAL_USE.md) describe
explicit host enrollment, CA validation, independent signing, durable replay
protection and consumer-only secret delivery. The old metadata projection API
still does not dispatch. Only metadata receipts cross its public result
boundary; this directory stores no credentials or secret payloads. The source
pin itself grants no runtime access and does not update automatically.
