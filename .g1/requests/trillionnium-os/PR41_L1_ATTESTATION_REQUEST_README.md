# PR #41 L1 detached-attestation request

Status: **UNSIGNED / NOT PROMOTABLE / NO TARGET OR RELEASE AUTHORITY**

This bundle contains a structurally complete L1 source-qualification package for
the reviewed PR head `7e1e611e7299391cf3d4edc1ded322da0d023cc6` and its deterministic synthetic merge
`906aa352f9b714940504c4071e8d15f7937f3411`. GitHub protected integration produced main commit
`968968046d69d000f1f9fe03683e92aa7903cf99` with the identical reviewed tree.

The package is not sufficient to close a gap. An independently administered
out-of-repository trust root must verify all declared artifact bytes and live
GitHub identities, create a strict `org.trillionnium.g1.evidence-attestation.v2`
receipt, and sign the exact receipt bytes using RSA-SHA256. Until that receipt,
signature, public key and pinned key digest pass the live verifier:

```text
promotion_authorized=false
public_release=false
automatic_redispatch=false
```

Package ID: `sha256:5969ce9801f672299a3e02dec41bdc23488d148598b0e3d688fcd7d3ca01caf9`
Package file SHA-256: `2e3fb115ec9494a1b907d4bdf6c536e2717fdb9f5b2ae233cc06029c7c0e62b3`
Request file SHA-256: `4dcaa9b9c3b44225dc3701b72eebbb661e04ba5ebb5cc1e71b26ff884370fc7f`
