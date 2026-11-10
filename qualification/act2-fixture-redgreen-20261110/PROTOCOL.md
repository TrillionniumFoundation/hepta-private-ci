# ACT-2 strict-store fixture path qualification

This workflow compares frozen baseline `8b1c1789916514471c6cacdf0f6c45467255fef9` with the seven-file fixture repair `8bebf0a3c207a49bfd0a99367fd6e06f52a6cb98` from #5618. Its own driver source is recorded separately. Production strict-path checks and all existing test assertions remain unchanged.

On a real macOS Intel runner, the same twelve existing Automation tests run in three stages: baseline with canonical TMPDIR must pass; baseline with an explicitly symlinked TMPDIR must produce exactly the twelve named `Invalid` setup failures and zero passes; repaired candidate with that same alias must pass. A timeout, incomplete log, missing test, different failure, source mutation or incorrect candidate diff fails qualification.

The workflow retains actual source/tree identities, command records, complete log SHA-256 values and canonical/alias paths. Scoped fix and official formatting run after the contrast; no tests rerun after them. Their source changes, if any, are retained and fail the final clean-tree check. Passing results do not exist until the exact-source workflow completes.

This qualifies only the twelve Automation fixture cases. It does not establish the two Agentd fixture roots, Windows semantics, every historical Bazel failure, cargo-deny, model-facing handler transport, Notes cancellation or scientific skill-learning benefit. The old runner ENOSPC annotations remain separate evidence and are not erased by a fresh pass.
