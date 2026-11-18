# d5af612 complete net-addition review

## Decision

Accept the original tip `d5af612c3c04f9bd7f4555411edb94341fe4553a` for an ordinary true merge into the consolidation candidate, preserving all 39 added files byte for byte. The independently recomputed default merge against `770179d123b879355b53db1d75f8f9f301280d3e` is conflict free and adds only `qualification/learn-ordinary-ce434/unified-source-7832-20261112/`. It changes no existing source, policy, build, workflow, manifest, or verifier file. Root should retain its normal fresh-ref/HIA checks and final exact-head CI gate when publishing the combined candidate.

This decision is about admitting historical evidence and manual reproduction inputs. It does not turn their historical results into a current-source native pass. No archived driver or frozen request was executed during this review.

The larger `21df04700aa885aef72b70962f270b966a112de6` candidate is not admitted by this report. Its existing Prettier and Codespell inputs have actual failures and its content review is still separate.

## Exact scope and materialization

- Ordinary branch: `codex/learn-unified-source-7832-evidence-ce434-20261112-v1`.
- Tip: `d5af612c3c04f9bd7f4555411edb94341fe4553a`.
- New history relative to both the original a911 candidate and reviewed 770 candidate consists of `926bd241e3aa832678c3d5d513f84eb6d51e1eeb` and `d5af612c3c04f9bd7f4555411edb94341fe4553a`.
- 39 regular files, all Git mode `100644`, all UTF-8; 447,165 total bytes. Types: 22 JSON, 10 log, five Python, one XML, one Markdown. The maximum individual blob is 81,572 bytes; none exceeds 512,000 bytes. No symlinks, submodules, native binaries, compressed archives, or split archive parts are added.
- Every actual file was read and independently checked against its Git blob SHA-1 and SHA-256. `file-manifest.json` records all paths, modes, types, sizes and hashes. The branch's original `manifest.json` indexes 38 files; every indexed byte count and SHA-256 matches, and the only unindexed file is that manifest itself.
- All 22 JSON files parse. All five Python files parse without being imported or executed. The frozen JSON request's outer Python and its nested `NATIVE_RUNNER` string were decoded with JSON/AST literal parsing, retained separately and read in full; they were not evaluated. No other JSON string matched the code-bearing search used in `d5-embedded-code-search.json`.

## Executable content, including embedded content

Mode `100644` alone was not treated as a proof of inactivity. The five Python files have top-level effects if explicitly run or imported.

| Retained file                                   | Behavior on explicit invocation                                                                                                                                                                                                                                                                                                                           | Current automatic execution                                                   |
| ----------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| `qualify_7832_source_v1.py`                     | Requires the hardcoded old clean checkout and exact 7832 source/tree, creates a separate evidence directory, runs the original 310-source, 16-parser and caller-self-test commands, and hashes raw outputs.                                                                                                                                               | No matching workflow, import or test discovery entry.                         |
| `qualify_7832_full_caller_v1.py`                | Requires the same fixed old source and all protected/Rust files, then runs the original full caller proof with a 7,200-second bound and records exact before/after state.                                                                                                                                                                                 | No matching workflow, import or test discovery entry.                         |
| `root_guard_514_patch.py`                       | Writes selected marker spans in the old absolute checkout's CALLERS file after preserving normalized content, row counts and all unrelated fields. It is a historical repair script, not a read-only verifier.                                                                                                                                            | No matching automatic entry.                                                  |
| `root_guard_514_qa_sync.py`                     | Rewrites unambiguous Python string literals in four old source-closure test files, using the retained marker map and AST validation.                                                                                                                                                                                                                      | No matching automatic entry.                                                  |
| `verify_guard_merge.py`                         | Reads the caller/QA three-way merge, compares complete protected rows and test inventories, invokes `git write-tree`, and writes the caller-selected report.                                                                                                                                                                                              | No matching automatic entry.                                                  |
| `typed-requests/v13-isolated-exact-inputs.json` | Frozen historical Python request. Its outer script can fetch the old fixed commit, create an isolated worktree/branch, run formatting, add/commit and push that new historical branch with an empty-old-ref lease. The nested runner can obtain exact-hash V8 artifacts, write its own evidence, build/verify helpers and run exactly seven native cases. | Stored JSON text; no request loader or replay entry references this new path. |

The explicit fixed source/tree/path checks and diagnostic-only claims were read, but were not used as a substitute for checking reachability from current execution entry points.

## Current execution and quality input review

The source provenance table pins 17 relevant files to the reviewed 770 Git tree. The shared source snapshot had the older a911 `MODULE.bazel`; the exact 770 blob was separately obtained and checked. Its only difference is the already-reviewed `sha2` build optimization annotation. It adds no qualification loader or new path discovery.

The exact new prefix and all five Python basenames were searched in `.github`, `scripts`, `qa`, `codex-rs` and the root build/package files. The only broader `learn-ordinary-ce434` matches were four existing source-closure tests naming other explicit qualification fixtures. Their paths do not name the new directory. The decoded current CALLERS manifest has `source_roots = ["codex-rs"]` and no reference to this new prefix.

| Existing entry point                                        | Effect of these additions                                                                                                                                                                                                                                        |
| ----------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Rust Cargo workspace, root Bazel rules, and caller verifier | No `.rs`, Cargo manifest, Bazel package/rule, or source-root addition. No added compiled or privileged caller source.                                                                                                                                            |
| `.github/workflows/repo-checks.yml` Python discovery        | Explicit directories are `.github/scripts`, `scripts/tests`, `scripts/codex_package`, `scripts/install`, signing scripts, and four `qa` suites. None includes this new qualification directory. None of the new Python basenames matches `test_*.py`.            |
| Root `pnpm run format`                                      | Patterns are root JSON/Markdown, `docs/*.md`, workflow YML and recursive `**/*.js`. The 39 nested additions contain no JS and match none of these paths. No Prettier pass is claimed for out-of-scope files.                                                     |
| `just fmt-check` / `scripts/format.py`                      | Rust full formatting uses the Cargo workspace; Python full/scoped formatting uses `scripts`, `.github` and `sdk/python`; global Starlark selection finds no added matching filename. The added Python/JSON/log files are not formatter inputs.                   |
| Existing Codespell workflow                                 | It does read these 39 files. The exact existing config, dictionary ignore file, static skips and verified custody skip expansion were retained. Codespell 2.4.3 checked all 39 files and returned 0, with zero diagnostics; all input hashes remained unchanged. |

The Codespell version matches the original successful CI job `134742755550` for run `44287117820`. This review used Python 3.14.4 on ROG; the CI action image uses Python 3.13. The complete arguments/config hashes and untouched stdout/stderr are retained. This is an incremental check of these exact additions, not a claim that the complete final combined repository CI has run here.

## Historical claims checked against retained evidence

- Fixed old source `7832eef16022f1af233e2a48ef46fb1ac61dcd8f`, tree `bfccf4de95b9b0d68a84a344c9071171edd005b1`: the original source log reports 310 tests and OK; the parser log reports 16 tests and OK; caller self-test returns 0. Their full recorded bytes/hashes match the manifest.
- The earlier scoped guard run is retained as 25 tests with one error, followed by a separate 25/25 working-tree run. The README explicitly does not invent a fixed-655 execution from that working-tree result.
- The old dcf7 seven-case diagnostic is retained with seven JUnit cases, five passing and two failing. The execution exit is 100 and its wrapper terminal exit is 1. The failure records and original raw log are retained. The interpretation identifies a downstream original evidence timeout and a fixture expiration-boundary issue; neither is represented as a current-source pass.
- The earlier running observation remains alongside the later failed terminal result. The source-7832 full caller proof remains `running_at_last_confirmed_observation_executor_now_unavailable`, with no terminal result and no pass claim.
- Positive adoption, complete NoUpdate/fallback and daemon-plus-Root cold-restart acceptance counts remain zero. The stated future/native fixes are not claimed as verified.

The review parsed terminal counts and the failure diagnostics and checked the full raw byte inventory; it did not rerun those historical tests or treat their raw logs as executable instructions.

## True merge and protected HIA boundary

The private audit bare clone recomputed default `git merge-tree --write-tree` without a conflict preference, tree overwrite, checkout mutation or remote write:

- Base: `770179d123b879355b53db1d75f8f9f301280d3e`.
- Merged tree: `ed69766229cb29cb3d63e833ae9ad9b35c40016b`.
- Raw net-diff SHA-256: `8f14856d86431eb402b06a4c050f025ade755af66757a907850294525a13dee7`.
- The raw additions are byte-identical to the independently recorded merge against 342b. The earlier a911 proof also records the same 39 path/blob additions.

The complete 356-ref protected snapshot supplied by root is retained with SHA-256 `3c01927324e0f3f0c3891af43042ff15d44455eeb1bc70fb4da6d6d4cd137285`. Neither of the two new commits is a protected tip. Direct native ancestry checks return 1, with no error, for both actual HIA graph roots `f02bb9f3344cdff4e361cca4353540ca0193bd21` and `3aa1f85ba90c79d220a5cadf2261def176892867` as ancestors of d5af. The extra retained descendant anchor `8347769bab248a287efa2e4e82f667b55a0f29bc` was absent in this private partial object store and its probe returned 128; that result is retained, not relabeled as negative ancestry. Root's earlier complete graph proof already records the anchor exclusion and its relationship to the second HIA root. Excluding that root also excludes its descendants by ancestry transitivity.

This is a frozen snapshot proof, not a claim that live protected refs stopped changing. Root owns the fresh boundary refresh and compare-and-swap publication. No branch was moved or deleted during this audit.

## Evidence package

`evidence/` includes all 39 exact original files, every-file inventory, original manifest validation, parsed content/outcomes, decoded request scripts, exact entrypoint files and provenance, complete frozen HIA list/merge proof, original Codespell output and check arguments. `AUDIT_FILES.json` hashes every package file except itself. The package is also preserved as a compressed tar archive so reproduction inputs and raw logs remain byte-for-byte evidence.
