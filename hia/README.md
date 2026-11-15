# Codex HIA native components

This directory contains the current HIA implementation and its native build,
contracts, Rust call boundaries and original-behavior tests. The combined patch
candidate contains **14 compiled modules covering twelve algorithm groups**.
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
| `unified_diff` | Line splitting, Myers/Compact/Replace transitions, grouping, context arithmetic and unified-diff bytes. | Rust transports valid strings and materializes HIA-selected output; actual compiler receipts select the supported arithmetic mode. |
| `patch_summary` | Success header, A/M/D group order, path index and continuation selection. | Rust executes each original `writeln!` separately with the actual `Path::display` and `Write` implementation. |

The patch path composes the native parser, file-update planner, matcher,
SourceFile owner, effect state machine, unified formatter and summary selector.
The feature-selected adapters use HIA for these decisions. PathUri, real
filesystem execution, symlink/sandbox enforcement, string allocation and the
public writer's formatting/I/O remain host boundaries. The original Rust owners
remain available to the default platform path and immutable parity tests.

Thirteen native symbols are required in installed full Codex checks, including
six in apply_patch. Standalone apply_patch does not call the unified formatter;
the full Codex verification path does. `utf8_boundaries` has a separate
qualification entry. These are required checks, not claims that the new installed
combination has already passed.

## Native interfaces

The six complete buffer contracts are normative:

- [SourceFile](source_file_buffer_contract.json): strict operations 0–7 and
  trusted-string counterparts 8–15; 64-byte request header, 40-byte result header
  and 32-byte span records.
- [File update](file_update_buffer_contract.json): LF split, planner/resume,
  stable permutation and reverse-edit/render query/emit pairs.
- [Parser](parser_buffer_contract.json): 128-byte request, 160-byte result header,
  64-byte event records and explicit streaming state.
- [Patch effects](patch_effects_buffer_contract.json): 176-byte request, 128-byte
  result, no workspace and explicit callback continuations.
- [Unified diff](unified_diff_buffer_contract.json): strict and trusted query/emit
  operations, checked line/span storage, explicit arithmetic policy and semantic
  panic results.
- [Patch summary](patch_summary_buffer_contract.json): 64-byte request and result,
  no workspace, explicit group/index continuation and one selected write effect.

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

The unified formatter preserves Similar 2.7.0's complete line, edit and grouping
behavior, including LF/CRLF/bare CR, missing final newlines, duplicate lines,
nonmonotonic coordinates and arithmetic panics at extreme context radii. It does
not clamp those coordinates or replace the original edit sequence with a
different but visually similar diff. The source catalog, Apache-2.0 license and
attribution accompany the native implementation.

The pinned HIA assembly grammar has no comment form. The adjacent
[adaptation notice](ATTRIBUTION.unified_diff.md), referenced by the contract and
the repository NOTICE, identifies the translated module and its exact source.

Arithmetic mode is derived from the real pinned compiler/codegen invocation and
the admitted Similar artifact. Both owners checked and both owners wrapping are
qualified modes. Mixed policies, unknown compiler chains and LTO are rejected.
The workspace's default thin-LTO release path therefore remains open. Raw ABI
coverage of a mode does not qualify that mode for production selection.

The summary selector always requests the header, including for empty path lists,
then visits added, modified and deleted paths in their original vector order.
Each selected effect executes the same individual `writeln!` as the original.
Custom `Write::write_fmt`, partial writes, Interrupted, WriteZero and other writer
errors retain their original observations and accepted output prefix. The native
continuation is structural caller-owned state; it does not authenticate a prior
writer result.

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

Before the first native Cargo build, generate the compiler-policy configuration
for this exact checkout and build. Use absolute paths for the external outputs:

```bash
python3 -B hia/prepare_unified_diff_policy.py \
  --repo "$PWD" --rustc "$rustc_binary" \
  --config "$build_parent/unified-policy/config.json" \
  --receipt-root "$build_parent/unified-policy/receipts" \
  --bind-input "$native_output/build.json" \
  --report "$build_parent/unified-policy/configuration-report.json"
export RUSTC_WRAPPER="$PWD/hia/similar_policy.py"
export RUSTC="$rustc_binary"
export CODEX_HIA_SIMILAR_POLICY_CONFIG="$build_parent/unified-policy/config.json"
```

Keep this environment for native Cargo builds, `just test`, Clippy and scoped
`just fix`. Configuration creation qualifies no compiler artifact by itself.
The wrapper captures and validates the real compiler invocations; the policy
gate separately checks cached reuse and rejected arrangements. A cached native
artifact without its matching receipt is rejected. Bind additional effective
Cargo configuration files with repeated `--bind-input` options.

The repository `just fix` recipe uses the admitted compiler bridge for a
configured native checkout. Cargo's fix proxy invokes the workspace wrapper
directly, so the bridge runs the real pinned Clippy compiler through the policy
helper and validates the artifacts produced by that fix invocation. Every
compiler call has paired start/completion records; failures and incomplete calls
are rejected even if Cargo returns zero after reverting an attempted repair.
Compiler-log identities include the actual source and diagnostic bytes, since
a repair can change diagnostics while leaving metadata bytes identical.

To require the native owner during a scoped fix, from `codex-rs`:

```bash
CODEX_HIA_POLICY_FIX_REQUIRE_NATIVE=1 \
  just fix --locked -p codex-apply-patch --features hia-native
git diff --exit-code
```

The command prints the external evidence report path. CI also checks the actual
fix artifact's arithmetic mode and separately reruns strict all-target Clippy.
Without a policy configuration, the recipe forwards the original Cargo Clippy
fix command. The small compiler-chain controls described below do not replace
the complete Codex owner gates.

## Qualification

The first published fourteen-module source, `0339bd5f`, ran both native CI
attempts. Each had 56 successful steps, one failed cached arithmetic-policy
admission, and two skipped steps. The checked Cargo build succeeded; its
hashless publication alias still indexed a different real compiler unit.
Wrapping, the eight policy rejection commands, and the complete unified public
comparison did not execute. Both full failed-run archives remain retained.

The current repair selects that alias through the unique hashed peer in the
same actual Cargo row. Actual compiler output events, crate/features, output
paths, immutable receipt identity, source/probe/mode checks, and complete
alias/artifact byte hashes remain required. Seven real baseline commands
reproduced the failure; 31 repaired commands exercised nine successful
admissions, four linked policy observers and five genuine rejections. These
small compiler controls do not qualify the complete owner. Fresh full CI is
still required for this repaired source; HIA programs and Rust adapters are
unchanged by the repair.

The current fourteen-module build reproduces the B1/B2/B3 fixed point. All twelve
existing HIA sources and static archives match the qualified effect parent.
The summary archive matches its exercised prototype. The unified formatter's
raw and namespaced objects also match its exercised prototype; its canonical
archive differs only in the ar member name, `hia.o` instead of `unified_diff.o`.
The current receipt gates exercise that actual canonical archive.

| Current combination | Observed result |
| --- | --- |
| Native build | Fourteen B3 modules; three identical compiler generations; all twelve inherited static archives unchanged. |
| Summary raw ABI | 1,328 calls, 157 error/no-write cases, 128 concurrent calls and 125 complete small-count traces; zero skips. |
| Unified component ABI | 522,858 native calls against fresh complete Similar references, covering original corpora, raw contracts, frontend collisions and word boundaries; zero skips. |
| Summary and unified source/archive admission | 68 checks for each mutation module, including admission of all fourteen modules. |
| Shared scalar/build admission | 120 checks. |
| Fix compiler-chain controls | Actual checked/wrapping `just fix`, each with 17 paired compiler records, two native helper calls and a real fixture repair; nine extended positive controls and eight small-control refusals. |
| Complete public calls, Cargo, installed callers and CI | Separate gates on this final composition; prior component and parent results do not substitute for them. |

The summary prototype passed the 13 unchanged root-owner tests and actual
workspace lint/configuration with warnings denied. Its public writer matrix
compared 1,002 complete original/native observations in 2,004 processes, with
4,022 counted native calls and zero skips or mismatches. It covers the default
writer and custom `write_fmt`, exact write attempts, partial accepted prefixes,
all observed errors, duplicate/Unicode/invalid-UTF8 paths and large path values.
Those complete libraries were compiled by direct rustc against the admitted
666-unit, 1,284-file Cargo dependency graph; that is not a Cargo build of this
new combined source tree.

The frozen unified formatter separately passed actual checked and wrapping Cargo
owner builds, cached receipt reuse, policy rejection tests and strict owner
Clippy. Its complete immutable-original public comparison passed 3,974 fixtures
under each of the two supported policies: 7,948 pairs and 15,864 native calls.
The 1,417 outcomes that differ between checked and wrapping behavior are retained.
These frozen-prototype results bind their exact source/artifact identities;
the portable gates must separately qualify the final fourteen-module composition.

The canonical component gate has also run on the actual fourteen-module build,
binding the current source, contract, objects and archives. It rebuilt the complete
73-file Similar release into two reference libraries and four observers. Its
522,858 native calls comprise 109,152 original-corpus calls, 2,490 raw-contract
calls, 3,136 frontend calls and 408,080 word-boundary calls. This includes 1,082
error/no-write cases, real line-hash collisions, concurrent calls and the complete
65-by-65 half-length byte-scan matrix. These are component observations; actual
production Cargo policy selection and the final public file/chunk adapters remain
separate gates.

Final source cleanup removes only extra trailing line breaks from eight catalog
and test files, with identical parsed JSON and Python AST. The helper and CI
catalog digests are updated together to retain strict byte admission. Earlier
component and compiler-control reports preserve their original source identities;
the complete production CI separately qualifies the final source tree.

The three context states are None, a present disabled context and a present
restricted context without configured sandbox runtime paths. The last observes
the actual existing runtime-path error; it does not qualify an OS sandbox backend.
The observer forwards filesystem return values unchanged and injects no filesystem
or writer errors. Its only transcript normalization replaces exact temporary
fixture paths, including their recorded hexadecimal encodings.

The immutable effect parent `aeb88f596b83186456caac577080bcb2f253ad32` passed both
native CI runs: 50/50 steps and 5,375 Cargo tests with six existing skips per run.
Each run includes 360 complete original/native filesystem-effect pairs, the 13
unchanged root tests, installed apply_patch/full Codex, native/default strict lint
and scoped fixes without source drift. Both uploaded artifact sets, their
complete original snapshots and the tested PR merge tree were audited. Those
results qualify that parent; the new summary/formatter composition requires its
own Cargo, public-call, policy, installed and CI results.

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
python3 -B hia/tests/test_patch_summary_abi.py \
  --library-dir "$native_output" --report "$build_parent/patch-summary-abi.json"

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
python3 -B hia/tests/test_native_patch_summary_caller.py \
  --producer "$PWD" --library-dir "$native_output" \
  --effects-report "$build_parent/patch-effects-caller.json" \
  --rustc "$rustc_binary" --work-dir "$build_parent/patch-summary-caller" \
  --report "$build_parent/patch-summary-caller.json"
```

The output directory must be new and outside both source checkouts. The oracle
compiles the complete pinned original library with actual dependencies and uses
the actual filesystem API. It retains raw process observations and applies only
the explicitly defined fixture-path/Debug normalization. Panic-precondition
observations do not claim post-panic recovery equivalence.

The unified formatter's complete original checkout contains the fixed effect
parent `aeb88f596b83186456caac577080bcb2f253ad32`. Its public gate extracts all 109
original crate files from that immutable Git tree. Run its policy and public gates
serially against an exclusively owned external Cargo target:

```bash
python3 -B hia/tests/test_unified_diff_policy.py \
  --library-dir "$native_output" --rustc "$rustc_binary" \
  --target-dir "$CARGO_TARGET_DIR" \
  --output-dir "$build_parent/unified-policy-gate" \
  --report "$build_parent/unified-policy-report.json"
python3 -B hia/tests/test_native_unified_diff_caller.py \
  --library-dir "$native_output" --rustc "$rustc_binary" \
  --original-root "$unified_original_checkout" \
  --policy-report "$build_parent/unified-policy-report.json" \
  --target-dir "$CARGO_TARGET_DIR" \
  --output-dir "$build_parent/unified-public-gate" \
  --report "$build_parent/unified-public-report.json"
```

Both supported policies use actual original/native owner libraries. The eight
policy refusals execute real compiler or Cargo commands. Selected receipt indices
and one selected metadata artifact are restored after their rejection tests;
the target must have no concurrent Cargo user during this gate.

The patch-effect oracle also verifies the actual Cargo fingerprint dependency
chain shared by `serde_json` and the filesystem context type, runs the 13 unchanged
original root tests, compares 360 complete public result pairs, and exercises
the 14 native transport regression scenarios. Its output paths use ASCII letters,
digits, underscores, dots and hyphens so temporary path normalization stays exact;
this is a test-output precondition, not a production patch-path restriction.

Run `just fmt` after source changes and the scoped `just fix` gate before
finalizing a large Rust change. Keep build products, logs, generated test corpora,
runtime observations and publication manifests outside the repository. Retain the
checksum-pinned original regression inputs and licenses required by the portable
gates.

## Remaining work and retirement

All 15 complete capability migrations remain open. In particular, native patch
computation does not migrate model transport, authentication, turns, persisted
history, tools/process effects, permissions and sandboxing, MCP, App Server v2,
CLI/TUI ownership, SDK/frontends, platform release paths or the entire HIA runtime.
Actual host filesystem execution, writer formatting/I/O and filesystem search
remain outside the current HIA owners. Native unified formatting also retains an
explicit compiler-policy boundary; release/LTO and other platforms remain open.

Retire an implementation only after its replacement owns the intended production
path and passes original behavior, API/session compatibility, required-platform,
clean-install and end-to-end tests. Then remove superseded source, dependencies
and build rules together, while retaining required regression fixtures, licenses
and release assets. The current candidate does not authorize deleting active
Rust implementations or enabling native dispatch by default.

The parser's 2,480-line, file-update's 1,953-line, patch-effect's 1,365-line and
unified formatter's 4,378-line HIA programs are cohesive compiler inputs. Their
documented review exceptions do not turn component qualification into
whole-product completion. Earlier detailed process records
remain bound to their published commits and external evidence; this directory's
canonical documents describe the current candidate.
