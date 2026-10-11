# Transitive Agentd Clippy Convergence (Draft, no production promotion)

This PR is stacked on Signed Stem Final-use PR #1517. The exact pinned
Rust 1.95 CI failure in Worker Bridge runs 38115573584 and 38115731982
was **18 Clippy errors in the transitive codex-hepta-agentd library**,
not a Jina weight performance result or a bypass of signed Final-use.

The remediation intentionally preserves startup readiness, exact Scope and
generation fences, independent signature verification and owner-only
plasticity admission:

- Five redundant fields in an `AuthorizedTaskflowEffectInvocation` have
  identical values but now use Rust shorthand, without changing signed bytes.
- Browser Servo still compares and advances every strictly sequential inbound
  frame sequence. Its unused *duplicate* `DecodedFrame.sequence` field was
  removed only **after** validation. This does not disable replay protection.
- Four large enum payload variants use `Box` to reduce enum stack footprint,
  with corresponding construction and consumption changes in Agentd control
  and intelligence run owners. Serialized/wire receipt schemas and signing
  domains are not changed by the change in local Rust memory representation.
- Two unused convenience Retrieval sink methods which silently selected an
  implicit delivery policy were removed. The production path continues using
  the explicit `append_with_delivery_policy` receipt and governed
  propensity/learning trace.
- Cognitive read and revalidation now carry named, scoped policy and
  snapshot inputs instead of 9/10 positional parameters. The same owner,
  generation, ranker, retrieval context, learner and snapshot are passed.
- Agentd Plasticity admission now groups exactly the previously provided
  artifact registry, durable ledger, owner evidence resolver and evidence
  policy into a typed struct. No new admission policy is invented.
- The remaining internally staged Plasticity producer calls have real
  test-only call sites but **no product route**; targeted
  `#[cfg_attr(not(test), expect(dead_code, reason = "..."))]` annotations
  document this gap without opening the calls as `pub`, disabling Clippy
  globally, or issuing a grant. These are outstanding production integration
  work, not an implementation-complete claim.

## Native exact-source gates

```sh
cd codex-rs
cargo +1.95.0 fmt --all -- --check
cargo +1.95.0 clippy --locked -p codex-hepta-agentd --lib -- -D warnings
cargo +1.95.0 clippy --locked -p codex-hepta-infer-core -p codex-hepta-infer-worker-host --all-targets -- -D warnings
cargo +1.95.0 test --locked -p codex-hepta-agentd --lib
```

No suppression of the CI's `-D warnings` option or of security advisories
is permitted. Passing these focused source gates does **not** establish full
Cargo-deny/global CI, real Jina weights, target host 4096 Cell resources,
hardware crash/ack-loss recovery or independent NDU. All three stacked
PRs remain Draft and every shared Stem result stays `DENY_ALL` until
independent product authority signs and verifies an actual final-use grant.
