# Codex HIA native components

This directory contains the current HIA implementation and its native build,
contracts, Rust call boundaries and original-behavior tests. The combined patch
candidate contains **12 compiled modules covering ten algorithm groups**.
Production selection remains the opt-in `hia-native` feature on Linux x86-64 GNU.
The complete Codex rewrite, default release migration, required-platform
qualification, whole-product performance and legacy retirement remain open.

[`migration.json`](migration.json) records all 15 complete capabilities and the
198-crate baseline inventory. [`verification.json`](verification.json) binds the
current sources and observed results. Component results do not qualify the
complete workspace or a different source tree.

## Current implementation

| HIA module | Responsibility | Production boundary |
| --- | --- | --- |
| `seek_sequence` | Four ordered context-matching passes, EOF selection and first-match behavior. | The existing checked patch-search dispatcher selects native matching. |
| `utf8_boundaries` | Full-buffer UTF-8 validation and prefix-boundary reference entry. | Standalone qualification module; the production string API uses `utf8_prefix`. |
| `utf8_prefix` | Select a UTF-8 prefix boundary from the byte budget and a bounded window. | Rust borrows a valid `str` and returns the selected slice. |
| `metric_tag` | Streaming metric-tag sanitizing, trimming, fallback and truncation. | Rust transports chunks and owns the final string. |
| `markdown_location` | Streaming Markdown hash-location suffix normalization. | Rust owns the accumulated output. |
| `ascii_json_fragment` | Strict UTF-8 admission and ASCII JSON fragment encoding. | Serde retains surrounding JSON structure, control-character escaping and writer effects. |
| `truncate` | Middle truncation, scalar counting and marker plan selection. | Rust materializes the native-selected spans and marker. |
| `token_budget` | Saturating approximate token/byte conversion. | Three existing arithmetic APIs call a typed scalar native entry. |
| `source_file` | Parse logical lines, choose endings, apply replacements and select output spans. | Rust owns backing strings and checks returned indices. |
| `file_update` | LF splitting, chunk/resume planning, search decisions, stable replacement order and reverse overlapping edits. | Rust transports HIA-selected searches and owns storage; preserving updates compose HIA SourceFile. |
| `parser` | Batch normalization, patch grammar, streaming state, errors, events and affected/source path selection. | Rust materializes AST values; actual PathUri joins remain a host operation. |
| `patch_effects` | Filesystem operation order, missing-parent retry, committed delta transitions, exactness and removal-error comparison. | Rust performs selected real filesystem calls with the original path, context and options. |

The patch path composes the native parser, file-update planner, matcher,
SourceFile owner and effect state machine. The feature-selected adapters use HIA
for these decisions. PathUri and real filesystem execution, symlink/sandbox
enforcement, public summary formatting and `similar` unified-diff formatting
remain host boundaries. The original Rust owners remain available to the
default platform path and immutable parity tests.

Eleven native symbols are required in installed full Codex checks, including
five in apply_patch. The twelfth compiled module, `utf8_boundaries`, has a separate
qualification entry.

## Native interfaces

The four complete buffer contracts are normative:

- [SourceFile](source_file_buffer_contract.json): strict operations 0–7 and
  trusted-string counterparts 8–15; 64-byte request header, 40-byte result header
  and 32-byte span records.
- [File update](file_update_buffer_contract.json): LF split, planner/resume,
  stable permutation and reverse-edit/render query/emit pairs.
- [Parser](parser_buffer_contract.json): 128-byte request, 160-byte result header,
  64-byte event records and explicit streaming state.
- [Patch effects](patch_effects_buffer_contract.json): 176-byte request, 128-byte
  result, no workspace and explicit callback continuations.

All integer fields in these buffer interfaces are little-endian u64. Their
capacity, frame, range, UTF-8, error-priority and no-write rules are specified in
the contracts and exercised directly against machine code. Unaligned live,
disjoint buffers are supported. Native calls retain no host pointers.

### Patch semantics

SourceFile retains LF, CRLF and bare CR, the first preferred ending, and the
absence of a terminal empty sentinel. Inserted strings containing internal
line-ending bytes remain one logical line across subsequent replacements.
Preferred style survives complete deletion and later insertion. Even an empty
replacement list repairs missing endings on surviving lines. Trusted entries
skip only redundant validation of text already guaranteed valid by Rust;
structural, span, capacity and arithmetic checks remain.

The file-update planner selects each context search, old-pattern search and
trailing-empty retry. The Rust adapter sends that request through the existing
checked dispatcher to the actual HIA matcher, then resumes the native state
machine. Stable ordering uses discovery order for equal starts. NormalizeToLf
applies edits in reverse, retaining the original overlapping-EOF behavior and
the distinction between an empty old pattern and a pattern containing one empty
line. Preserve mode uses the actual HIA SourceFile implementation.

A file-update continuation is explicit caller-owned state, not a proof of text
equality. Its structural checks do not authenticate an arbitrary caller's claimed
match. Production requests bind lengths and search results to actual strings
and the native matcher. Public-output parity does not expose every private
planner trace; raw continuation tests are a separate contract gate.

Parser semantic errors and transport errors have different effects. A streaming
semantic error commits the accepted prefix, consumes the failing line, advances
its line number, discards the remaining failed delta and permits later calls to
resume. A nonzero transport status writes nothing. The adapters preserve the
original AST/error variants and path behavior without repeatedly copying a long
pending line prefix.

The effect state machine selects real host operations one at a time. Add and
move writes retry exactly once after an initial NotFound, with optional recursive
parent creation. In-place writes do not retry. A move commits a destination Add
before attempting source removal, then replaces that same delta entry on success.
Removal errors with known old text trigger an actual reread and native byte
comparison, even when exactness is already false. A failed later operation never
rolls back an earlier committed effect.

The adapter forwards the same sandbox reference and symlink options. Its private
transport/framing errors conservatively mark the known delta prefix inexact;
ordinary host errors retain the state machine's original exactness decision.
Continuation validation checks structure and does not authenticate a caller's
claimed filesystem observations.

### String interfaces

`utf8_prefix` borrows at most four boundary bytes plus its fixed descriptor from
a valid Rust string. `metric_tag` transports chunks of at most 1 MiB, uses a
32-byte state and emits at most 256 bytes. Its default decision examines the
whole string, including alphanumeric characters beyond the output limit.

`markdown_location` and `ascii_json_fragment` use windows of at most 4,096 bytes.
The former preserves the original permissive endpoint grammar. The latter
validates UTF-8, leaves an incomplete nonfinal scalar unconsumed, and produces
lowercase Unicode escapes or surrogate pairs. Previously completed writer
effects remain committed if a later write fails.

`truncate` returns a 40-byte plan with prefix end, suffix start, removed units,
original token count and result kind. Its strict entries validate UTF-8; trusted
entries require a valid Rust string. It preserves odd-budget allocation,
saturating arithmetic, marker collisions and Unicode scalar counts.

`token_budget` uses `codex_hia_token_budget(value: u64, operation: u64) -> u64`.
Operation 0 computes saturating multiplication by four. Operation 1 computes
saturating addition of three followed by division by four. Other operation
values trap. All u64 input and result values remain valid, including `u64::MAX`.

The 1 MiB bootstrap buffer setting is not a product input-size limit. The patch,
SourceFile, parser and truncation owners admit larger inputs according to their
checked buffer contracts. A successful large-input test does not establish a
latency deadline or qualify performance.

## Build

The locked Hepta revision is
`0de5657a80f96b138525ac7ee9ce11712a83a10d`. Use a clean checkout at that revision,
Python 3, GNU `ld`, `objcopy`, `ar` and `nm`, and the repository's Rust 1.96.1
toolchain. Native output must be outside both source checkouts.

From the Codex repository root:

```bash
python3 -B hia/build.py \
  --hepta-root "$hepta_checkout" \
  --output "$native_output"
export CODEX_HIA_NATIVE_LIB_DIR="$native_output"
```

The builder reproduces three compiler generations, requires the B1/B2/B3 fixed
point, compiles the locked HIA sources with B3, validates the object format and
exports, and constructs namespaced static archives. The shared Cargo helper
rejects source, compiler, report, object, symbol or archive drift. Only
`token_budget` uses the locked `u64-pair-to-u64-v1` scalar profile.

Installed production callers use the static archives and need no HIA shared
library directory at runtime. Shared libraries are separate direct-ABI test
artifacts. Their complete byte identity must not be inferred from matching
static objects or archives across build hosts.

Selecting `hia-native` on an unsupported target is an error. With the feature
disabled, the build helper does not read HIA sources or native artifacts.

## Qualification

The current twelve-module build reproduces the B1/B2/B3 fixed point. All eleven
existing HIA sources and static archives match the qualified parent combination.
The new effect archive also matches the archive exercised by the complete-crate
prototype. The repository candidate passed `just fmt` without source changes.

| Current effect qualification | Observed result |
| --- | --- |
| Complete original and native prototype libraries | Thirteen unchanged root-owner tests on each side; native workspace lint/configuration with warnings denied. |
| Real public API observations | 360 exact original/native pairs, 720 processes, zero skips or mismatches. |
| Observation scope | Thirty fixed natural filesystem cases, two line-ending modes, two symlink options and three context states; exact output/errors/delta/order plus an independent final tree. |
| Native transport-error regression | Fourteen public API cases; 95 planner attempts and 88 calls forwarded to the real HIA entry. |
| Current namespaced raw ABI | 455 calls, 218 error/no-write cases and 128 concurrent calls using unaligned disjoint buffers. |
| Current source/archive admission | 64 checks for the new module, including every locked module. |
| Current shared scalar/build admission | 118 checks. |
| Actual production owner Cargo | Both native and default builds; 101 native and 99 default `just test` cases, zero skips. |
| Actual production owner lint/fix | Both all-target Clippy modes with warnings denied; scoped `just fix` changed no source. |

The prototype public gate uses the complete immutable original library and the
complete candidate library with the actual 666-unit Cargo dependency graph; it is
a direct-rustc qualification. The current production owner separately passed
native/default Cargo builds, tests, strict lint and scoped fix; all 9,853 producing
source paths stayed unchanged. Each actual graph contains 666 library units and
1,284 admitted artifact files. The portable public gate captures native/default
Cargo artifacts before compiling observers. That public gate, installed
executables, wider consumers and the complete CI composition qualify separately.

The three context states are None, a present disabled context and a present
restricted context without configured sandbox runtime paths. The last observes
the actual existing runtime-path error; it does not qualify an OS sandbox backend.
The observer forwards filesystem return values unchanged and injects no filesystem
or writer errors. Its only transcript normalization replaces exact temporary
fixture paths, including their recorded hexadecimal encodings.

The immutable parent `2ff44b608a202c25e7551edca67a7a5362f34d36` passed both native
CI runs: 47/47 steps, 5,375 Cargo tests with six existing skips per run, complete
original owner comparisons, installed callers, native/default strict lint and
scoped fixes without source drift. Both uploaded artifact sets and the tested PR
merge tree were audited. Those results qualify the parent; they do not qualify
this candidate's newly added filesystem-effect dispatch.

[`codex-hia-native.yml`](../.github/workflows/codex-hia-native.yml) is the complete
executable gate inventory. It preserves existing sandbox checks and exercises
the listed original callers, raw ABIs, artifact admission, native/default crate and
consumer suites, installed apply_patch and full Codex, strict lint and scoped
fix/clean-diff. Its upload list includes the original snapshot's tracked hidden
fixture. Uploaded reports and logs do not imply that unuploaded executable or
rlib bytes were independently rehashed elsewhere.

Useful local commands, after the native build:

```bash
python3 -B hia/tests/test_build_receipt.py \
  --artifacts "$native_output" --mutation-module file_update \
  --rustc "$rustc_binary" --report "$build_parent/file-update-receipts.json"
python3 -B hia/tests/test_native_source_file_caller.py \
  --library-dir "$native_output" --rustc "$rustc_binary" \
  --report "$build_parent/source-file-original.json"
python3 -B hia/tests/test_native_parser_caller.py \
  --library-dir "$native_output" --rustc "$rustc_binary" \
  --report "$build_parent/parser-original.json"
python3 -B hia/tests/test_file_update_abi.py \
  --library-dir "$native_output" --report "$build_parent/file-update-abi.json"
python3 -B hia/tests/test_patch_effects_abi.py \
  --library-dir "$native_output" --report "$build_parent/patch-effects-abi.json"

cd codex-rs
just test -p codex-apply-patch -p codex-utils-string --features hia-native --locked
just test -p codex-utils-string -p codex-utils-output-truncation \
  -p codex-protocol -p codex-context-fragments \
  --features codex-utils-string/hia-native --locked
env -u CODEX_HIA_NATIVE_LIB_DIR just test -p codex-apply-patch -p codex-utils-string \
  -p codex-utils-output-truncation -p codex-protocol -p codex-context-fragments --locked
```

The complete file-update and patch-effect oracles require an independent checkout at
`a2014bc6bfa1c1c9957edb3f14f8ae7d9ddcc095` and an external `CARGO_TARGET_DIR`
containing the real dependency graph built by the native/default owner gates.
Both producing checkouts must be clean. From the current repository root:

```bash
python3 -B hia/tests/test_native_file_update_caller.py \
  --original-root "$original_checkout" --library-dir "$native_output" \
  --rustc "$rustc_binary" --output-dir "$build_parent/file-update-caller" \
  --report "$build_parent/file-update-caller.json"
python3 -B hia/tests/test_native_patch_effects_caller.py \
  --producer "$PWD" --original-root "$original_checkout" \
  --library-dir "$native_output" --rustc "$rustc_binary" \
  --work-dir "$build_parent/patch-effects-caller" \
  --report "$build_parent/patch-effects-caller.json"
```

The output directory must be new and outside both source checkouts. The oracle
compiles the complete pinned original library with actual dependencies and uses
the actual filesystem API. It retains raw process observations and applies only
the explicitly defined fixture-path/Debug normalization. Panic-precondition
observations do not claim post-panic recovery equivalence.

The patch-effect oracle also verifies the actual Cargo fingerprint dependency
chain shared by `serde_json` and the filesystem context type, runs the 13 unchanged
original root tests, compares 360 complete public result pairs, and exercises
the 14 native transport regression scenarios. Its output paths use ASCII letters,
digits, underscores, dots and hyphens so temporary path normalization stays exact;
this is a test-output precondition, not a production patch-path restriction.

Run `just fmt` after source changes and the scoped `just fix` gate before
finalizing a large Rust change. Keep build products, logs, dependency snapshots,
test corpora and publication manifests outside the repository.

## Remaining work and retirement

All 15 complete capability migrations remain open. In particular, native patch
computation does not migrate model transport, authentication, turns, persisted
history, tools/process effects, permissions and sandboxing, MCP, App Server v2,
CLI/TUI ownership, SDK/frontends, platform release paths or the entire HIA runtime.
Unified-diff formatting, actual host filesystem execution and filesystem search
remain outside the current HIA owners. The new state machine moves patch-effect
decisions into HIA; it does not replace OS operations or sandbox enforcement.

Retire an implementation only after its replacement owns the intended production
path and passes original behavior, API/session compatibility, required-platform,
clean-install and end-to-end tests. Then remove superseded source, dependencies
and build rules together, while retaining required regression fixtures, licenses
and release assets. The current candidate does not authorize deleting active
Rust implementations or enabling native dispatch by default.

The parser's 2,480-line, file-update's 1,953-line and patch-effect's 1,365-line
HIA programs are cohesive compiler inputs. Their documented review exceptions do not turn component
qualification into whole-product completion. Earlier detailed process records
remain bound to their published commits and external evidence; this directory's
canonical documents describe the current candidate.
