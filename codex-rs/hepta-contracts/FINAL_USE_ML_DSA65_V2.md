# FinalUse ML-DSA-65 V2 grant profile

This profile adds ML-DSA-65 grant verification to the original FinalUse owner.
It does not migrate model evaluation, qualification, selection, artifact
publication, or the existing Ed25519 approval/revocation-feed protocols.

## Explicit selection

An embedding trusted host opens `FinalUseAuthority::open_state_dir_with_ml_dsa65_v2`
with its original `AuthorityClock` and externally durable
`AuthorityFrontierStore<FinalUseFrontier>`. The constructor cannot attest the
independence or durability of those injected implementations.

The worker-host adapter exposes `UnixFinalUseAuthorizer::open_ml_dsa65_v2` for a
protected `FinalUseMlDsa65AuthorizerConfigV2` JSON file with `schema_version: 2`.
The host supplies the same clock/frontier interfaces, then attaches this
authorizer through the existing `with_turn_start_authorizer` constructor.
The Unix request and response must both select schema 2. Unknown schemas,
classical grants, and classical key encodings are rejected without fallback.
Existing CLI and SmolLM constructors continue to select V1; they do not
automatically enable V2 from a new configuration file.
This slice adds no V2 constructor for the separate Windows opaque owner API.

The protected configuration limit remains 64 KiB, including keys, identifiers,
paths and revocation data. The core key-ring bound of eight keys is a maximum
count, not a promise that every eight-key JSON configuration fits this limit.
The request/response limits remain 16 KiB/64 KiB; the signed-file courier limit
remains 16 KiB. Every ML-DSA-65 public key must contain exactly 1952 bytes.

## Signature domain and carrier

The grant retains the original outer JSON fields, with grant schema 2. Its
signing input is the byte string
`hepta.kernel.authority.final-use.ml-dsa-65.v2\0`, followed by the canonical
compact serialization of the grant, a big-endian u16 key-ID byte length, and
the ASCII key ID. `ml_dsa65_v2_signing_bytes` constructs this input. The pure
ML-DSA-65 signing context is `hepta.kernel.final-use.ml-dsa-65.v2`.

`encode_ml_dsa65_final_use_signature_v2` constructs the signature carrier:
`HFU2`, suite byte `0x65`, reserved byte zero, big-endian u16 key-ID length,
the ASCII key ID, and exactly 3309 signature bytes. Key IDs use the original
identifier grammar and are 1–128 bytes. Truncation, trailing bytes, reserved
bits, suite changes, key-ID substitution and context changes are rejected.
The receiver selects the verifier from its pinned owner configuration;
request metadata cannot choose another algorithm.

V1 `signing_bytes`, signature domain, JSON fields and Ed25519 verification
remain unchanged. That original signing API continues to reject schema 2.

## Persistent authority and recovery

`StoreTrust::MlDsa65IssuerKeyRingV2` is a distinct persistent trust namespace
inside the existing schema-3 owner store. It binds the exact key IDs, public
keys and inclusive authority-epoch windows. Existing `SingleKey` and
`IssuerKeyRing` variants do not match it. Old schema-1/schema-2 directories
are not migrated to this profile. A fresh V2 owner or an exact V2 reopen is
required; no API resets an existing directory to make it compatible.

Claims, nonce journals, epoch transitions, revocations, external CAS ordering,
dispatch fences, expiry checks and `VerifiedUseToken::enter` remain owned by
the original implementation. Pre-pinned key generations become usable only
in their configured epochs. A new trust list or classical-to-PQ conversion
requires a separate recovery/migration protocol, which this profile does not
implement.

## Validation scope

The added component tests use real ML-DSA signatures and the original
persistent owner. The Unix/file courier tests exercise the existing framed
I/O and protected-file boundary. The Agentd/AppServer test exercises the
original `claim` → `token.enter` → `turn_start` path with a mock model provider
and a test issuer task. These fixtures do not establish independent issuer
operation, a real model-training result, whole-chain post-quantum security,
or deployment of V2 by the paired ordinary SmolLM workflow.
