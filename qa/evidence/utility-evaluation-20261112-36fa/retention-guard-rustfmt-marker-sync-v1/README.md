# Exact retention guard markers after native rustfmt

This package prepares three non-Rust source changes against the fixed a8 preparation tree. It does not publish a source head.

The actual native rustfmt outputs are model-material blob 18f897c8053202c4d45c99e8504192f479fb67e3 and panel-binding blob 7c8eadbd9cb73446208bdc386121af656e390ce4. Both have multiline conditions where the previous CALLERS and QA markers required a single line.

## Change scope

CALLERS.toml keeps all 534 boundary rows byte-for-byte in the parsed structure and all 409 protected rows in their original positions. Exactly four leaf string values change: row 338 require_observed_panel sequence[21] and top_level[2], and row 389 material sequence[56] and top_level[10]. Each new marker contains the full original predicate text with the actual rustfmt whitespace. Every other parsed field is identical.

The original three QA methods keep their assertions, mutation cases, order and control flow. Four AST string constants change: PANEL_GUARD, MATERIAL_GUARD and the old/new strings for the primary-qualified inversion. Normalizing only these four strings makes the complete QA AST identical. The blob-size allowlist gains one exact SHA256 line for the new CALLERS bytes; no existing entry is removed.

## Actual scoped diagnostic

The same isolated partial projection contains the actual two formatted Rust files, original verifier and typed helper, full CALLERS, the original QA file, and the allowlist: seven files, not a full repository. The command is the original unittest discover entry point limited to this single three-method QA file. Each attempt has a 600-second ceiling, complete raw combined output and its own before/after input inventory.

With old markers, the actual command exited 1: three methods ran, two FAIL and one ERROR. The two failures are source.count(marker) == 0; the error is the original verifier rejecting its obsolete top-level marker before the mutation. With only the three prepared non-Rust files substituted, the same command exited 0: all three methods were explicitly ok. Both runs were not timed out and their inputs stayed unchanged within each execution. The two Rust inputs and verifier/helper also stayed unchanged across phases.

These are source-mutation QA results. They are not a full source-closure result, original full caller verification, Rust behavior coverage for signed positive-primary/negative-retention inputs, or real A/B/C qualification.

## Reconstruction

POSTIMAGES.json.gz.b64 contains all three complete proposed postimages. Decode base64, then gzip; PACKET_IDENTITY.json binds encoded and decoded bytes. Each JSON file entry supplies the exact preimage and postimage Git blob, SHA256 and size, plus complete base64 bytes. marker-sync.patch and STRUCTURAL_REVIEW.json provide the independently checked textual and parsed/AST differences. The original native maintenance patch is retained separately. All run raw files and JSON records remain unedited.
