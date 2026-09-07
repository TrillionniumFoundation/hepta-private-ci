# PR #41 L1 detached-attestation request

Status: **UNSIGNED / NOT PROMOTABLE / NO TARGET OR RELEASE AUTHORITY**

This bundle contains a structurally complete L1 source-qualification package for
the reviewed PR head `7e1e611e7299391cf3d4edc1ded322da0d023cc6` and deterministic synthetic merge
`906aa352f9b714940504c4071e8d15f7937f3411`. GitHub protected integration produced main commit
`968968046d69d000f1f9fe03683e92aa7903cf99` with the identical reviewed tree.

## Corrected operational history

The retired topic-branch dispatcher ran once as workflow run `34018916537` and
created exactly two non-qualifying availability probes: desktop run
`34022297088` and fleet run `34022298108`. They proved runner allocation only.
They did not check out the Trillionnium OS candidate, execute a target harness,
contact an authorized device, consume a target authorization nonce, produce an
evidence package, or close a gap.

The candidate-controlled dispatcher has been deleted. Candidate-controlled
self-hosted inventory run `34022826520` was cancelled before any runner
allocation. The trusted probe definitions now pass `reason` through an
environment variable, enforce a closed grammar, and pre-bind the desktop probe
to runner group `trillionnium-android-gpu`.

`automatic_redispatch=false` refers to effectful semantic operations. The two
availability workflow dispatches are recorded separately and are explicitly
non-evidence.

The package remains insufficient to close a gap. An independently administered
out-of-repository trust root must verify all declared artifact bytes and live
GitHub identities, create a strict `org.trillionnium.g1.evidence-attestation.v2`
receipt, and sign the exact receipt bytes using RSA-SHA256.

```text
promotion_authorized=false
public_release=false
automatic_redispatch=false
target_evidence_capture_dispatch_count=0
target_authorization_nonce_consumed_count=0
```

Package ID: `sha256:03369d6115e587b0baf207c3d361689913853814465a8e881a2f617d98a62e39`
Package file SHA-256: `848ab4952ca49e7107cb758fc5d4fce4fde98471fcb13b54feeeb7b9b1a28193`
Request file SHA-256: `7248cbc9abb69499da3bbba919d28da7db460b0e4328c4b99a49f83651f74228`
