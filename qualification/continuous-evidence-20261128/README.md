# Continuous engineering evidence, 2026-11-28 UTC

This evidence-only branch preserves completed observations while existing source
heads remain fixed for natural CI. The parent is the combined Draft #7243 at
`85ccf3305e34c90d3d10bdb1a6294d4e6adcf893`; no Rust, Python or workflow is changed.

## Qualified observations

- The fresh complete original-function proof at source `0195e00d2883db5208de6cab8119cb6304b231c9`
  with manifest `6a1fd9f44d75f01a4aea430102b29dc58b65723af2676ad9b60277a836289c7e`
  checked 6,265 actual Rust files, all 252 boundaries and all 230 protected rules.
  It returned zero rule errors in 548.775845666 static seconds. The original checker
  and lexer were unchanged; no historical lexical cache supplied passing evidence.
  This is a parallel run of original functions, not a pass of the original serial
  CLI. The earlier 900.021999451 s CLI timeout remains retained in #7238.
- Architecture job 140877796085, run 46112102168 attempt 1, executed the actual
  source head `3871fbb62d4c3f69d07ce8651d488309c5363be8`. Each of the original
  28 named terminal/factory/bridge controls passed exactly once, in four successful
  commands (19 + 3 + 4 + 2), with clean before/after source identity. The previously
  missing drain control has an actual PASS at 05:39:17.1806147Z. The base-merge
  native lane was skipped. The original local 0195 compile timeout is unchanged.
- Linux Bazel Clippy job 140882843389 passed at the actual prospective merge
  `6e0e1629fca59272af7f0060ad02da36b3a43b73`. Its tree is exactly the #7238 source
  tree `27b32baf059e480409c4073710824a276d9eb429`; this was not a source-head
  checkout. The build and clean-worktree check both completed successfully.

## Remaining CI finding

The complete 18,108,191-byte cargo-deny log for job 140878049321 is retained.
It checked merge `f5ff27d024eaaf9d878f1681805bcbf9aa1ff6e9`, whose tree equals
source `3871`. The actual failing diagnostic is `error[unmaintained]` for
`chrono 0.4.45`, RUSTSEC-2026-0543. Bans, licenses and sources passed. This is
an unmaintained-package advisory, not evidence of an observed exploitable bug.
The earlier RUSTSEC-2026-0370 text belongs to a passing negative policy test.
Official advisory: https://rustsec.org/advisories/RUSTSEC-2026-0543.html

The fixed source inventory identifies 172 files with 407 chrono references.
The lock has 23 workspace and eight third-party direct dependents. All eight
cached third-party crate archives match their exact Cargo.lock checksums, and
all inspected cached manifest/source files match those archives. Optional feature
removal is insufficient for the pinned unconditional oauth2/rmcp dependencies.
A real migration and fresh dependency/build qualification remain open; no ignore,
renaming workaround, dependency update or revised security policy was applied.

## Scope and original ceilings

These observations remain bound to their exact inputs. They do not qualify the
later combined tree, four new enrollment controls, genuine external capture,
Root current-trust recovery, human Train consent, adoption, useful work or model
quality. No manual CI rerun or dispatch was made to produce these observations.
The local native engineering pool remains 3,247.6470368430616 / 3,600 seconds;
352.3529631569384 seconds remain, with the single 220 + 66 second scoped-fix
reservation still unexecuted. Original E1–E6 ceilings and negatives are unchanged.

The source-proof archive includes all raw-source hashes and original rule outputs.
The separate 12,141,586-byte fresh lexical-code index is omitted from this Git
capsule and identified by SHA256
`341dc6094b76d0c7a87523d90b3ba7f1096a01b411be3cbac2f34fd5df72504d`.
It is reproducible from the fixed Git source and retained unchanged original lexer.
The chrono index V2 explicitly preserves the correction of V1's derived Git-blob
separator field; all V2 blob IDs were checked against original Git objects.
