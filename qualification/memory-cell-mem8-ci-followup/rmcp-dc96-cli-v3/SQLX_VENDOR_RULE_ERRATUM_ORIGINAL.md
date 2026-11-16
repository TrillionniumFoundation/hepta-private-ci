# SQLx vendor provenance and repository-rule correction

This corrects an unsupported statement in the earlier dependency-review README. It does not alter that original archived evidence, the official crate archive, any candidate source, any lockfile, or any test result.

## Correction

The earlier README said the review did not waive an “existing exact-upstream-byte preservation condition.” That phrase was not tied to an identified repository instruction. The applicable instructions and formatter at the frozen common source do not establish such a condition. The phrase is withdrawn as a claim about repository requirements. It must not be used to invent an approval requirement or to block otherwise authorized work.

The actual limitation remains: the SQLx vendor is not an exact byte copy of the official crate with only two manifest edits. Normalized syntax comparison, formatter conformance, native consumer tests, and official-byte identity are distinct observations. None should be substituted for another.

## Frozen rule sources

All of the following were read at common commit `96038ccf0660154fac143ba6cbe4be81e00813e8`. The exact returned files and API readbacks are preserved under `rule-readback/`.

| Source | Git blob | Relevant rule or behavior |
| --- | --- | --- |
| `AGENTS.md` | `faa57cc0db48123e1011f1eb47692cd3bbbcfc3a` | Run `just fmt`, use scoped `just test`, run scoped `just fix` for large Rust changes, and run `just bazel-lock-update` when Rust dependencies change. No vendor/upstream-byte-preservation clause was found. |
| `justfile` | `a215a76cf407ace9715bca39c20497014e7dd4dc` | The `fmt` recipe invokes `../scripts/format.py`; `fmt-check` invokes it with `--all --check`. |
| `scripts/format.py` | `d4eabe70b68605933240e9129245f7f4cccbde5d` | `rust_configuration_scope` includes changed `.rs` paths, without a vendor exception. `rust_file_command` uses the owning crate edition and `--config imports_granularity=Item,skip_children=true`. |
| `codex-rs/rustfmt.toml` | `f9686f9732d3d48311c41c4fd06b40781928b8ec` | Edition 2024 and `imports_granularity = "Item"`. The per-file formatter separately resolves each owning manifest's edition. |

Exact-ref requests for `codex-rs/AGENTS.md` and `codex-rs/third_party/AGENTS.md` returned 404. The introduced SQLx package's complete 57-file inventory contains no AGENTS file. This establishes the applicable ancestor/package scope that was checked; it is not a claim to have searched every unrelated repository instruction.

Primary links: [AGENTS](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/96038ccf0660154fac143ba6cbe4be81e00813e8/AGENTS.md), [formatter](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/96038ccf0660154fac143ba6cbe4be81e00813e8/scripts/format.py), [justfile](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/96038ccf0660154fac143ba6cbe4be81e00813e8/justfile).

## Actual source mapping

The fresh byte comparison uses the complete local `candidate64-v2.json.xz` source capsule for native commit `dc96a441312e239c165c1642880084dfeccc2c71`, tree `7796279284170f0f2c92449c1185eecac1f4f1b6`. Its declared upstream candidate is `6ecfa504d2132f3682ffb01f8c9d65346b26cf5b`; the earlier detailed vendor review was pinned to `72251601928807febae580dbd7754edac20bda10`. The official `sqlx-sqlite-0.9.0.crate` is 93,440 bytes with SHA256 `488e99c397a62007e4229aec669a179816339afc6d2620ca6fa420dbee2e982c`.

`SQLX_DC96_BYTE_MAP.json` records all 57 official, reviewed-upstream, and dc96 postimage byte lengths and SHA256 values, plus the dc96 Git blobs. Every dc96 postimage was independently checked against its capsule hash and Git-blob identity.

| Category | Count | Actual difference from official crate |
| --- | ---: | --- |
| Rust source with different bytes | 44 | Includes import grouping/order and other formatting. These are not byte-identical official sources. |
| Rust source with identical bytes | 7 | Exact byte equality. |
| Manifests | 2 | The only manifest change is `libsqlite3-sys` range `>=0.30.1, <0.38.0` to `>=0.30.1, <0.40.0`, in both `Cargo.toml` and `Cargo.toml.orig`. |
| Other package files | 4 | Exact byte equality. |
| Total | 57 | Same complete file inventory; 46 files differ in bytes. |

Relative to the 722-reviewed SQLx vendor, dc96 changes exactly one source file: `src/connection/deserialize.rs`. It removes trailing whitespace from three Rustdoc comment lines. Two of those removals change Markdown hard-line-break layout. Runtime Rust tokens are unchanged by that additional edit, but the documentation bytes and layout are not claimed unchanged.

The dc96 root Cargo comment was also corrected to disclose SQLx formatting/import-order differences. The old claim that all upstream Rust/SQL bytes were unchanged is not retained. Matrix source-byte preservation and the two Matrix manifest compatibility edits are a separate part of the 64-file closure; the Matrix encryption dev-profile optimization is an explicit performance hunk.

## Evidence boundaries and remaining work

The earlier Tree-sitter review compared all 51 Rust sources, normalizing syntax and import groups while checking comment multisets and negative controls. It was pinned to the 722 source. It did not establish official byte identity, unrestricted semantic equivalence, or a reproduction of upstream-to-candidate changes by pinned Rustfmt. Candidate formatter conformance and later native execution do not retroactively turn it into such a reproduction.

The native dc96 result identities remain separate from any later f1fd source. The original RMCP run remains 265 PASS / 3 FAIL across 268 unique selected tests; the three original failures later passed with a true CLI built from the same dc96 source. This is not a single 268-PASS run and does not qualify every CI consumer. The original Matrix and Bazel failures remain preserved in their own records. Later passing results must be stated with their own exact source and attempt.

This correction ran only local byte/hash comparisons and read frozen GitHub rule files. It ran no native test, no new model call, no formatter replay, and made no change to any native checkout, target, production service, or original immutable evidence archive.
