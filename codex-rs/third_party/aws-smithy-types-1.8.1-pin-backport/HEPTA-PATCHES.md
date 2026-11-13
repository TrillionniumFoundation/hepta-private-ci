# Hepta current-version pin-utils backport

This is the exact published aws-smithy-types 1.8.1 archive with its pin-utils dependency removed from both manifests. Existing pin_mut calls use std::pin::pin!; mutable Pin bindings remain mutable where next() or as_mut() requires them. The crate version, API, features and Smithy schema compatibility line are unchanged.

HEPTA-PATCH-PROVENANCE.json binds the official archive checksum, unchanged license, exact source import and minimal patch. All other upstream files remain byte-identical, including the historical Cargo.lock when published. The workspace Cargo.lock controls the actual dependency graph. No advisory is ignored or downgraded.
