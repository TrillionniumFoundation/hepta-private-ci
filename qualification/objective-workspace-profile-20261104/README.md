# Exact Objective workspace profile capture

Run the unchanged original `cargo metadata --locked --no-deps --format-version 1` command against the composed workspace based on 5d19. Capture every real member name, version and repository-relative manifest path, with immutable manifest Git identities and full source snapshots. No count threshold or guessed replacement for 193 is accepted here; the produced complete profile remains subject to review before adoption in the original owner gate.

This job compiles no Rust target, executes no native test, and grants no product qualification. The only production delta from 5d19 is the already reviewed pinned Landlock API method rename, which does not change the Cargo graph. Its second checkout verifies the retained original formatter-failure log using the standard Python gzip decoder, without executing archived source.
