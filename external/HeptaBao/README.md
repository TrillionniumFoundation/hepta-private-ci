# HeptaBao external source binding

The authorized HTTPS consumer pins the integrated service on
[`TrillionniumFoundation/HeptaBao@eac9c608bfda77a8972e1e8a1343dfc21985d62b`](https://github.com/TrillionniumFoundation/HeptaBao/commit/eac9c608bfda77a8972e1e8a1343dfc21985d62b)
on `main`. The real issuer and consumer processes passed 20 synthetic TLS,
replay, signature, provider-denial and restart checks against that source tree.
The [source-bound receipt](../../codex-rs/hepta-bao-adapter/qa/evidence/real-consumer-20260912.json)
records the build and executable digests. This validates the bounded KV consumer
profile; complete OpenBao replacement and production rollout remain unqualified.

The current HeptaBao repository head observed on 2026-09-12 is
[`55f27e4258ea3f71ab7872cd7a44e8cbd4da1f18`](https://github.com/TrillionniumFoundation/HeptaBao/commit/55f27e4258ea3f71ab7872cd7a44e8cbd4da1f18).
It is retained as an observation head because its published runtime and the
consumer receipt remain bound to `eac9c608bfda77a8972e1e8a1343dfc21985d62b`.
The observed candidate has 46 workspace packages and a versioned OpenBao 2.6.2
denominator of 60 surfaces: 13 are implemented only in scoped fixtures and 47
remain defined but unimplemented; current exact-head independent observations
are zero. The related OpenBao closure branches are ancestors of that `main`
head, so no branch cherry-pick is required. These facts do not grant runtime,
compatibility, production, migration or release authority.

[Client integration](../../codex-rs/hepta-bao-adapter/README.md) and
[kernel authority design](../../codex-rs/hepta-contracts/FINAL_USE.md) describe
explicit host enrollment, CA validation, independent signing, durable replay
protection and consumer-only secret delivery. The old metadata projection API
still does not dispatch. Only metadata receipts cross its public result
boundary; this directory stores no credentials or secret payloads. The source
pin itself grants no runtime access and does not update automatically.
