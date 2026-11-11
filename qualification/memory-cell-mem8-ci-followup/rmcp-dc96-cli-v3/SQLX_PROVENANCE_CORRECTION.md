# SQLx provenance correction

This is a new correction recorded after the original review. It preserves the original archived report and does not change source, locks, tests, scores or acceptance thresholds.

The earlier dependency-review README referred to an “existing exact-upstream-byte preservation condition” without identifying a repository instruction. That wording is withdrawn as a repository-rule claim. The inspected frozen AGENTS and formatter require scoped formatting; they do not establish that quoted condition or an extra approval gate.

Frozen references at common source 96038ccf0660154fac143ba6cbe4be81e00813e8:

| File | Exact blob | Relevance |
| --- | --- | --- |
| AGENTS.md | faa57cc0db48123e1011f1eb47692cd3bbbcfc3a | just fmt, scoped just test/just fix, dependency lock update requirements. |
| scripts/format.py | d4eabe70b68605933240e9129245f7f4cccbde5d | Changed Rust paths are formatted with imports_granularity=Item,skip_children=true and each owning manifest's edition; no vendor exemption in the inspected scope. |
| justfile | a215a76cf407ace9715bca39c20497014e7dd4dc | fmt invokes the repository formatter. |

## Actual vendor bytes

The official sqlx-sqlite 0.9.0 crate is 93,440 bytes with SHA256 488e99c397a62007e4229aec669a179816339afc6d2620ca6fa420dbee2e982c. The dc96 candidate retains a complete 57-file inventory: 44 Rust files differ in bytes from the official crate, seven Rust files are identical, two manifests change the libsqlite3-sys upper bound from <0.38.0 to <0.40.0, and four other files are identical.

Relative to the previously reviewed 722/6ec vendor, dc96 additionally removes trailing whitespace from three Rustdoc lines in src/connection/deserialize.rs. Two removals change Markdown hard-line-break layout. It is not an unchanged-byte claim. The root Cargo comment was corrected to disclose SQLx formatting/import-order differences separately from Matrix source-byte preservation.

The earlier normalized Rust syntax/import/comment comparison is bounded evidence for its pinned candidate. It is not unrestricted semantic equivalence, a pinned formatter replay from the official crate, or official byte identity. Formatter conformance and native consumer passes do not turn these different observations into each other.

The complete dc96 source capsule is in the retained RMCP archive. Root independently compared its 64 postimages with all 65 f1fd postimages: the only changed existing path is codex-rs/Cargo.toml, and the only additional path is MODULE.bazel. All 57 SQLx postimages are consequently identical between those two candidates. The f1fd optimization still needs its own consumer qualification; the old 265/3 plus later 3/0 results are not one full 268-pass run.

No source or original evidence was rewritten for this correction. The original standalone local erratum could not be re-opened after the workspace went unavailable, so this file is a newly authored correction, not a claim to reproduce that local file's exact bytes.
