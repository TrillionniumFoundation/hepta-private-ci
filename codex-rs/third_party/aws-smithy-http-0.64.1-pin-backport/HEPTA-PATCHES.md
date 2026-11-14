# Hepta current-version pin-utils backport

This is the exact published aws-smithy-http 0.64.1 archive with its pin-utils dependency removed from both manifests. Existing pin_mut calls use std::pin::pin!; mutable Pin bindings remain mutable where next() or as_mut() requires them. The crate version, API, features and Smithy schema compatibility line are unchanged.

HEPTA-PATCH-PROVENANCE.json binds the official archive checksum, unchanged license, exact source import and minimal patch. The endpoint imports are also normalized to the repository's item-per-import style; their exact before/after hashes are recorded as a formatting-only follow-up. All upstream files outside the listed manifest and formatting edits remain byte-identical, including the historical Cargo.lock when published. The workspace Cargo.lock controls the actual dependency graph. No advisory is ignored or downgraded.
