# Hepta current-version pin-utils backport

This document retains the original import and dependency-patch record. The current
checkout also includes the repository formatting follow-up described below.


This is the exact published aws-smithy-http 0.64.1 archive with its pin-utils dependency removed from both manifests. Existing pin_mut calls use std::pin::pin!; mutable Pin bindings remain mutable where next() or as_mut() requires them. The crate version, API, features and Smithy schema compatibility line are unchanged.

HEPTA-PATCH-PROVENANCE.json binds the official archive checksum, unchanged license, exact source import and minimal patch. The endpoint imports are also normalized to the repository's item-per-import style; their exact before/after hashes are recorded as a formatting-only follow-up. All upstream files outside the listed manifest and formatting edits remain byte-identical, including the historical Cargo.lock when published. The workspace Cargo.lock controls the actual dependency graph. No advisory is ignored or downgraded.

## Repository formatting follow-up (2026-11-14)

The normal repository formatter changed 8 Rust files.
HEPTA-FORMATTING-PROVENANCE.json binds every affected path to its exact Git
object, mode, size and SHA256 before and after formatting. The comparison uses
c2130629037b342e6e48154867b65acc8fc82434 as the input identity.

Import targets, aliases, visibility and attached attributes are retained.
Comments and non-import literals are retained; the other reviewed changes are
layout, trailing punctuation, single-expression block layout and same-order
derive grouping. Existing minimal dependency patches, upstream README files
and license bytes are retained. This record does not claim a new runtime test
result or a successful full-repository formatting check.
