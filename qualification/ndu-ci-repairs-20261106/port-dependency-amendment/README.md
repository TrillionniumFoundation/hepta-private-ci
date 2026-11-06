# Bind the reviewed dependency backport to the integrated port

The integrated port producer on PR #5013, run `42222000674`, failed before any
Cargo or Bazel command. Its original source record still names the earlier
workspace manifest and locks. Applying the existing formatting amendment leaves
exactly three mismatches among the 35 original bound files: `Cargo.toml`,
`Cargo.lock`, and `MODULE.bazel.lock`. The other 32 identities still match.

`DEPENDENCY_AMENDMENT.v7.2.json` records this specific reviewed transition. The
original integration record, recipe, formatting amendment, source patch, policy
inputs, and all other existing source identities remain byte-for-byte bound.
The new record itself has a fixed SHA-256 in the self-contained common guard.
Changing its file set, hashes, provenance, or claims requires an explicit code
review; an artifact cannot authorize itself by recalculating its own hashes.

The record binds the three existing files before and after the change, all 284
new source/license/provenance files in the five vendor directories, their Git
modes, and four unchanged proof documents from the actual native proposal and
its integration. Producer and consumers now bind all 319 source files, reject
extra vendor files or symlinks, and retain an exactly empty integrated patch.
The original current-source, Git-index, Git-mode, policy and artifact checks
still apply. Synapse retains the new amendment with its other producer records.

Actual locked metadata must select the five reviewed versions from their exact
vendor paths, contain no product `pin-utils` package, and preserve the existing
supervisor-to-cargo-bin dependency. The two independent registry fact strings
used by the pinned `rules_rs` `rrprd` hub remain unchanged and are checked by
their original hashes. The statement about removing `pin-utils` applies to the
product workspace Cargo graph, not every tool used by Bazel.

## Native provenance and current qualification

The successful proposal is PR #4998, source
`2f08789097d230f57464ac74d8ee897e345b61b3`, run `42219101717`, job
`127896383834`, artifact `13503570141`. Its original artifact SHA-256 is
`7327b21d16c61455cf49aee85cd98c0eadb81686c117c7d9f7d846509f7d6a18`.
All 15 actual commands passed, including repeated Cargo/Bazel lock generation
and the original cargo-deny command. The earlier two failed proposal runs remain
separate historical observations.

Product integration PR #5013 is source
`d8187cce5e8ed27025edfabb1cfd5c4ec3c95e4d`, tree
`77f9b42f11f0efc4c8a52740020d1aa25ab8872f`. The minimal integration preserves
the supervisor dependency added after the proposal base; overwriting its lock
with the whole older proposal lock fails the graph guard. The original
blocking-ci cargo-deny job `127907656308`, contract job `127907656454`, and
Linux GNU MODULE-lock step passed on that product run. Those observations do
not qualify a later source amendment or imply that all native jobs passed.

This unit changes no workflow, permissions, compiler pin, generation command,
security command, dependency policy, test filter, or original native assertion.
The common guard remains self-contained because the isolated Synapse loader
deliberately permits only verified source and standard-library imports.
The next ordinary PR must run the existing integrated producer, consumers,
and original full/native gates on its actual complete source head.

## Local verification

`VALIDATION.json` distinguishes executable local checks from hosted native
qualification. The retained logs include 69 port tests, 16 post-qualification
tests, and 7 source/restore boundary tests, all passing without skipped tests.
The new checks use actual reviewed bytes and real Git; metadata fixtures are
controlled test inputs and are not represented as Rust compilation.

The broader unchanged Linux boundary suite ran 32 test methods. Three subcases
of its socket cleanup test could not create an AF_UNIX socket in this executor
and raised `PermissionError`; that original failure log is retained. No test or
socket restriction was bypassed. The isolated source/restore checks passed.
The hosted workflow still runs the entire unchanged suite.

Two exact upstream filename lines in the new inventory are registered with
codespell. No word or file-wide ignore is added. The new files pass codespell,
while an ordinary typo and a near-matching inventory line still fail.

Sources: [original failed integrated producer](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42222000674),
[successful native proposal](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42219101717),
[published product](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5013).
