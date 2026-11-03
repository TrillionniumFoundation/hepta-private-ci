# AWS login dependency backport

This copy retains the published aws-config 1.12.0 archive and its Apache-2.0 license. The provenance file records every original file and each changed file.

The login DPoP path uses p256 0.14 and rand 0.10 so the workspace can resolve the fixed crypto-bigint implementation. The randomized ES256 signature, SEC1 key format, DPoP claims, provider features, and account selection remain the same. Random generator initialization now returns a provider error if operating-system entropy acquisition fails. Cargo.toml.orig is the unmodified upstream manifest.

The workspace lock and its original cargo-deny gate must qualify the resolved dependency graph. This source patch by itself is not runtime or live AWS account qualification.

The p256 0.14 adapter uses ToSec1Point::to_sec1_point(false), retaining the original uncompressed SEC1 public-key encoding and JWK coordinates.
