# Codex HIA native components

This directory contains the current HIA implementation and its native build,
contracts, Rust call boundaries and original-behavior tests. The combined patch
candidate contains **19 compiled modules covering seventeen algorithm groups**.
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
| `patch_application` | Parser/effects/summary order, diagnostic choice, writer-error priority and committed-delta result selection. | Rust retains original typed errors, individual writer calls and the existing asynchronous effects future. |
| `patch_standalone` | Standalone argument/stdin, diagnostic/exit, runtime/environment and application sequencing. | Rust performs the original OS, I/O, Tokio and process-exit callbacks; HIA selects their order and results. |
| `uuid_find` | Complete fixed UUID byte-pattern scanning, match selection, count and span plan. | Rust validates the plan and copies native-selected substrings into owned strings. |
| `template_parse` | Complete delimiter parsing, Unicode trim, ordered parse errors and literal/placeholder spans. | Rust validates the plan and owns the original template values; the opt-in renderer uses the separate HIA render entry. |
| `template_render` | Duplicate, missing and extra variable selection, segment lookup, checked output length and exact rendered bytes. | Rust preserves generic iteration, AsRef, original owned errors and destructor order while decoding the HIA result. |

The patch path composes the native parser, file-update planner, matcher,
SourceFile owner, effect state machine, unified formatter, summary selector and
application result routing, followed by standalone entry orchestration.
The feature-selected adapters use HIA for these decisions. PathUri, real
filesystem execution, symlink/sandbox enforcement, string allocation and the
public writer's formatting/I/O remain host boundaries. The original Rust owners
remain available to the default platform path and immutable parity tests.

Seventeen CLI-reachable native symbols are required in installed full Codex
checks, including eight in apply_patch and both template entries. The full
Codex path also reaches the unified formatter. `utf8_boundaries` remains a
separate qualification entry. UUID matching has library-positive coverage;
it is not a required CLI symbol. The default reference must contain none
of all eighteen native symbols, including UUID. These are configured
requirements; current nineteen-module installed execution remains pending.

## Native interfaces

The eleven complete buffer contracts are normative:

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
- [Patch application](patch_application_buffer_contract.json): 64-byte request and
  result, no workspace, two entries and 25 explicit result-routing transitions.
- [Patch standalone](patch_standalone_buffer_contract.json): 64-byte read-only
  continuation workspace and 64-byte result, with 17 selected host actions.

- [UUID matching](uuid_find_buffer_contract.json): 32-byte read-only request,
  64-byte result header and 16-byte byte-span rows; operation 0 queries capacity
  and operation 1 emits the complete table.

- [Template parsing](template_parse_buffer_contract.json): 32-byte read-only
  query/emit request, 64-byte result header and 24-byte span records.

- [Template rendering](template_render_buffer_contract.json): 32-byte read-only
  candidate-check/query/emit request and 80-byte result header.

All integer fields in these buffer interfaces are little-endian u64. Their
capacity, frame, range, UTF-8, error-priority and no-write rules are specified in
the contracts and exercised directly against machine code. Unaligned live,
disjoint buffers are supported. Native calls retain no host pointers.

### Patch semantics

The application continuation selects parse/effects/summary sequencing and the
result after each original writer call. A failed diagnostic takes precedence over
the parse or effects error; a failed summary preserves the already committed
delta. Effects diagnostics execute before an error downcast. The adapter awaits
the original effects future once and preserves its typed error ownership. The
raw continuation gate does not qualify controlled Pending/cancellation behavior;
that scope remains explicit in the verification record.

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

### Template parsing

`Template::parse` delegates the complete delimiter parser to HIA. Four-brace
escapes take priority over two-brace delimiters. Placeholder names retain the
original Unicode whitespace trimming, and malformed input keeps the original
first-error variant and byte offset. The native plan distinguishes a new
literal, an append to the preceding literal and a placeholder.

The Rust adapter validates the returned frame and each source span while
materializing independent owned strings, the existing segment vector and
sorted placeholder set. Malformed plans never return a partial Template.
The original Debug, Clone, equality and error interfaces remain available.
Rendering is still the original Rust algorithm in this increment.

Raw operations validate the entire input as UTF-8. Query writes the fixed
header; emit writes the selected spans after complete validation and capacity
checks. Transport failures write nothing. A semantic parse error returns an
error header without constructing a partial template. Exact rules are in the
template contract; owned public behavior is a separate complete-crate gate.

### String interfaces

`find_uuids` uses HIA to search the complete input for the fixed
8-4-4-4-12 ASCII hexadecimal pattern. It preserves case, duplicates and
encounter order, selecting non-overlapping matches without word boundaries,
version/variant checks or normalization. Raw calls accept arbitrary bytes;
the public Rust input is a valid string. The adapter validates the returned
spans and creates independent owned strings. Every error leaves the whole
output and request unchanged; successful queries write only the header.

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

### Current nineteen-module template-render candidate

The opt-in renderer delegates duplicate, missing and extra-variable selection,
segment lookup, checked output length and final rendered bytes to HIA. The Rust
boundary retains the original generic iteration, key/value `AsRef` calls, owned
errors and destructor order. The default implementation remains available.
Whole-product migration, default release, performance and retirement are open.

One fresh B1/B2/B3 bootstrap and all nineteen modules built successfully. All
54 inherited namespaced artifacts remain byte-identical; the three new renderer
artifacts match the frozen prototype. The initial qualification controller then
failed while reading the receipt format header. Its failure is retained. The
corrected continuation reused the same successful build, checked complete
canonical receipt bytes and ran the previously unexecuted component gates.
The formal renderer ABI passed 66,026 calls, including 54,262 whole-output
no-write transport failures, with zero skips. The receipt mutation gate passed
78 checks. These results do not qualify the current Cargo owner or product.

Historical direct-rustc observations against the complete four-file original
template crate remain separate: fourteen original tests, 13,206 public pairs,
21 constructed values and the exact ownership/iteration/error observations.
The current portable gate uses both actual native links and twenty-word traces,
retains the complete original crate and tests, and checks each Cargo-staged
archive against the admitted formal archive by complete bytes and digest.
Its actual Cargo linkage directory is the build script's `OUT_DIR`.

Both eighteen-module CI runs failed at the old public observer's incorrect
linkage-directory assertion. Their full logs and API responses are preserved;
the failed Cargo JSON row inside the undownloaded archive was not independently
read. This increment contains the observer repair, whose current Cargo execution
remains pending. The corrected seventeen-module UUID push and PR runs each
completed all 69 steps and their complete uploaded archives were audited. Those
historical results do not qualify this nineteen-module source; UUID scoped fix
also remains outside their qualified scope.

Current owner and six-consumer suites, default/native uncapped strict Clippy,
scoped string/template fix, installed Codex checks and final-source CI remain
pending. Installed checks require seventeen reachable CLI symbols and eighteen
default-reference absences, with UUID positive coverage at the library boundary.
Required platforms, release/LTO and scan-based renderer performance remain open.

### Published eighteen-module template-parse checkpoint

The formal B1/B2/B3 build reproduced the fixed point, retained all seventeen
prior module sources and 51 namespaced machine artifacts, and matched the
three frozen template-parse artifacts. The formal ABI gate ran 52,179 real
calls, including 9,255 transport error/no-write cases. Its matrix includes
16,383 brace cases, 5,888 byte-position mutations and 128 independent
interleavings on one worker. It used actual buffers up to 2,097,159 source
bytes and 1,572,952 output bytes. The 76-check template receipt gate admitted
all eighteen modules. These results do not claim simultaneous threads,
invented maximum-size pointers or public API equivalence by themselves.

The earlier direct-rustc comparison compiled the complete unchanged four-file
a201 template crate and complete candidate, using three genuine Cargo-produced
dependency libraries and all 54 locked registry source files. All 14 original
tests passed on each side with no omissions. Four uncapped strict Clippy
invocations applied the actual 37 workspace lint levels with warnings denied.
The public observers matched all 13,206 pairs and 21 constructed template
values, with 40,287 real parse calls: 32,184 queries and 8,103 emits.
Public payloads were compared byte for byte; native traces were checked
separately. Observations include source ownership after drop, iterator,
AsRef and destructor order, exact errors, Unicode, NUL and inputs over 1 MiB.
Both sides retained the original Rust rendering algorithm.

Two earlier harness failures remain recorded. The first omitted Rust's
`cfg(test)` declaration from standalone Clippy; a continuation added that
exact declaration without reducing the workspace lint levels. The second
hit a disk reserve guard after the complete original observer finished and
before the candidate observer started; its continuation ran the candidate.
Neither failed attempt is relabeled as a successful complete run.

These are historical source-bound direct-rustc results. The current parser
and adapter bytes match that candidate, but its Cargo manifest/build entry,
formatted portable harness and final workflow require separate qualification.
The fifteen-file portable public gate has been integrated and formatted.
It requires actual default/native ordinary-library and test-library Cargo
rows, complete fingerprints and dependencies, exact hashed peers and
publication aliases, and the full original crate. It has not executed on
the current producer.

The corrected UUID parent at `c468f632` has been adopted. Its initial push and
PR installation failures and exact scope correction remain recorded below.
All inherited default-reference absences remain required; adding the template
parser brings that control to seventeen symbols. The repaired parent's CI
status is not promoted by this increment.

The final owner workflow is integrated and its actual formatting completed
without source drift. It selects default/native `just test` for the template
owner and six direct consumers: `codex-login`, `codex-models-manager`,
`codex-prompts`, `codex-memories-write`, `codex-goal-extension` and
`codex-memories-extension`. Each native consumer feature is selected explicitly.
It also requires default/native uncapped all-target Clippy, actual scoped
string/template fix with compiler and unchanged-source evidence, final format,
and the installed full-Codex parser symbol alongside unchanged runtime checks.
Those Cargo, test, lint/fix, consumer, installed and final-source CI executions
remain pending. The actual 9,976-file source snapshot and all current input
hashes are bound in the verification record; only these three metadata files
are proposed after that snapshot. Source integration does not qualify runtime
gates. Performance, default dispatch, required platforms and retirement remain
unqualified. Exact evidence is recorded under
`verification.json#template_parse_increment`.

#### Inherited checkpoint scope

The following seventeen-module and earlier checkpoint text is preserved
verbatim. Its references to current or pending describe the producing source
for that checkpoint; they do not qualify this eighteen-module composition.

### Published seventeen-module UUID checkpoint

The formal B1/B2/B3 build reproduced the fixed point, retained all sixteen
prior module sources and 48 namespaced machine artifacts, and matched the
three frozen UUID artifacts. The portable ABI gate ran 19,232 real calls,
including 370 error/no-write cases and all 9,216 single-byte mutations.
Its 128 independent interleavings used one worker. The 74-check UUID
receipt gate admitted all seventeen modules. These results cover actual
buffers up to 2,359,332 source bytes and a 1,048,656-byte output table;
they do not claim simultaneous threads or invented maximum-size pointers.

The earlier direct-rustc comparison compiled the complete unmodified
a201 fifteen-file `utils/string` crate and complete 23-file locked
`regex-lite` 0.1.8 crate. It passed all 26 original and 38 candidate tests
with no omissions, plus actual workspace Clippy for the candidate library.
The 9,609 public pairs returned 78,778 strings with 14,060 real native calls;
owned results were observed after the source was overwritten and dropped.
A separate complete-regex comparison checked every query/emit span plan
in another 19,218 calls. These source-bound results remain historical
direct-rustc evidence. They are not a new Cargo or installed-product result.

Seventeen of the eighteen historical candidate crate files still match.
The current Cargo build script additionally links `uuid_find`; the earlier
direct-rustc commands linked it explicitly and did not execute that script.

The integrated public gate captures real default/native `--lib --tests`
Cargo graphs, binds the actual hashed artifacts and publication aliases,
and compares the complete original crate with the actual native owner.
That gate, current owner/consumer suites, strict lint/fix, installed binaries
and final-source CI remain pending. The parent is the published standalone
CLI repair `eb439d69`; neither that repair nor inherited results establish
successful sixteen- or seventeen-module CI. Performance, default dispatch
and retirement remain unqualified. Exact reports and input hashes are in
`verification.json#uuid_find_increment`.

Both initial `7c94ad70` native CI runs failed the installed full-Codex step.
The inspected PR and push artifact reports each record successful `nm`, one
definition of each of the fifteen required CLI symbols, and only
`codex_hia_uuid_find` missing. The scope correction removes that library-only
positive symbol requirement; it retains all sixteen default-binary absence
assertions and all other symbol, dynamic-library and runtime checks. The
initial failures remain recorded in
`verification.json#uuid_installed_scope_repair_history`. The selected artifact
members were CRC-checked; neither complete artifact ZIP was audited. This
correction does not claim a successful rerun or promote any qualification.

#### Inherited checkpoint text

The following existing checkpoint sections are retained verbatim. Their
uses of current or pending describe their original producing sources;
they do not qualify this seventeen-module composition.

### Published sixteen-module standalone checkpoint

The B3 build contains all sixteen locked modules and preserves the preceding
45 namespaced machine artifacts. The standalone ABI gate executed 6,310 native
calls: 5,097 error/no-write cases and 1,213 successes, with 25 transition keys,
27 source-condition outcomes, 17 actions and 13 complete callback traces. Its
128 interleaved instances ran on one worker. The actual 72-check receipt gate
admits all sixteen modules.

The portable comparison has 994 independently materialized paired fixtures.
Its complete original and native programs have not yet executed. The required
gate observes all 1,988 process launches and terminals, exact argv/stdin/env/cwd,
stdout/stderr/status and filesystem bytes, with no missing or skipped pair.
Fresh complete effects360 and application1470 results from the same clean
producing source are prerequisites.

An independent H build reproduces all 48 namespaced machine artifacts. The
original setup wrapper failed after its 24 successful commands; a separate
read-only completion verified those artifacts and the empty target. A new
owner preflight then passed all 20 commands, including native/default Cargo,
101/99 actual `just test` cases with zero skips, both strict workspace Clippy
modes and their native compiler receipt checks. Each Cargo graph binds
666 units and 1,284 files. This prepublication scope is parent `cae5db67` plus
18 overlays; its 9,933-file source map remained unchanged. These three final
metadata documents were outside the tested source.

Clean-source public comparisons, final scoped fix/format and installed
executables remain pending. Runtime-initialization failure, isolated final-flush
failure, internal write traces, cancellation and destructor order remain open.
The earlier application records below describe their original published scope;
they do not qualify this sixteen-module source.

### Fifteen-module application parent history

The current build reproduces the B1/B2/B3 fixed point and preserves every prior
HIA source, namespaced object, archive and shared-library identity. A separate
remote build reproduced all 45 machine artifacts. The application gate executed
2,790 native calls, including 1,841 error/no-write cases, 512 concurrent calls and
all 25 legal transitions, with zero skips. Its source/archive admission passed
70 checks against the actual fifteen-module build.

The actual owner preflight passed all 21 commands: native/default Cargo,
101/99 tests through `just test` with zero skips, both strict all-target workspace
Clippy modes and actual compiler receipt admissions. Its complete 9,922-file
source snapshot and machine artifacts remained unchanged. After this
prepublication test, final preparation changed the three metadata documents and
formatted the order of two oracle imports; all production inputs remain identical.

The first clean published `08dfcb76` public run passed the effects gate with
121 complete original inputs, 13 unchanged root tests and 360 result pairs.
Application comparison then stopped at case 756 during original fixture
construction, before `apply_hunks`: the fixture used unsupported literal
`<<'PATCH' ... PATCH`. It had matched 756 pairs, with 1,512 successful process
observations and one failed original attempt; the native counterpart of the
failed case did not run. Source bytes were unchanged. This attempt did not reach
final fix or formatting and does not qualify the complete application matrix.

The six-file test repair changes 18 materialized heredoc patches from `PATCH`
to accepted `EOF` delimiters. The previous 1,468 serialized selectors remain an
identical prefix, but those 18 actual patch inputs change. Two added rejection
cases retain the exact old `PATCH` bytes through the string APIs with default
options, no context and normal writers; other option/context combinations are
not claimed for these two additions. Targeted real-library checks passed
20 pairs/40 processes and 7 delimiter pairs in 2 processes, with zero mismatches
or skips. These probes do not qualify the full repaired matrix.

The subsequent clean `1083727e` run passed the fresh complete effects gate,
then the application entrypoint rejected a stale `DRIVER_SHA256`. No application
observer was compiled or executed, and final fix/format did not run. This
follow-up changes that one constant to the already published driver SHA,
retains the strict check and corpus, and verifies both hardcoded harness pins
against their actual files. The earlier bounded probe did not exercise this
full entrypoint admission; both failed runs are retained.

The current requirement is 1,470 original/native pairs and 2,940 processes
across three public APIs. That complete repaired gate has not run. The three
metadata documents, earlier two-import ordering follow-up and these six test
files are outside the original prepublication preflight scope; all production
inputs and native artifacts remain identical. Final fix/format, installed
executables and complete current consumer CI remain pending. The direct parent
is `1083727e`; its consumer CI is audited separately from the H public run, and
no H result substitutes its actual CI outcome. The earlier nextest version failure and UNKNOWN durable launch retain
their original evidence and status. The machine-readable failure and targeted
repair records are linked under `patch_application_increment` in verification.

### Fourteen-module parent history

The first published fourteen-module source, `0339bd5f`, ran both native CI
attempts. Each had 56 successful steps, one failed cached arithmetic-policy
admission, and two skipped steps. The checked Cargo build succeeded; its
hashless publication alias still indexed a different real compiler unit.
Wrapping, the eight policy rejection commands, and the complete unified public
comparison did not execute. Both full failed-run archives remain retained.

The published parent repair selects that alias through the unique hashed peer in the
same actual Cargo row. Actual compiler output events, crate/features, output
paths, immutable receipt identity, source/probe/mode checks, and complete
alias/artifact byte hashes remain required. Seven real baseline commands
reproduced the failure; 31 repaired commands exercised nine successful
admissions, four linked policy observers and five genuine rejections. These
small compiler controls are separate from the full owner gates. The repaired
`e23bc0d7` parent subsequently passed both complete native CI runs on attempt 1,
each with all 60 steps successful. These runs executed checked/wrapping owner
admission, all eight rejection cases, 7,948 unified public pairs, inherited
comparisons, installed checks and strict/fix. Broader checks and whole-product
qualification remain separate; these parent results do not qualify this candidate.

The recorded fourteen-module build reproduced the B1/B2/B3 fixed point. All twelve
existing HIA sources and static archives match the qualified effect parent.
The summary archive matches its exercised prototype. The unified formatter's
raw and namespaced objects also match its exercised prototype; its canonical
archive differs only in the ar member name, `hia.o` instead of `unified_diff.o`.
Those receipt gates exercised that actual canonical archive.

| Recorded fourteen-module combination | Observed result |
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
the portable gates must separately qualify each final composition.

The canonical component gate has also run on the actual fourteen-module build,
binding that source, contract, objects and archives. It rebuilt the complete
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

UUID component and public commands, after the native build:

```bash
python3 -B hia/tests/test_uuid_find_abi.py \
  --producer "$PWD" --library-dir "$native_output" \
  --report "$build_parent/uuid-abi.json"
python3 -B hia/tests/test_build_receipt.py \
  --artifacts "$native_output" --mutation-module uuid_find \
  --rustc "$rustc_binary" --report "$build_parent/uuid-receipts.json"
python3 -B hia/tests/test_native_uuid_find_caller.py \
  --producer "$PWD" --original-repo "$original_a201_checkout" \
  --library-dir "$native_output" --rustc "$rustc_binary" \
  --work-dir "$build_parent/uuid-caller" \
  --report "$build_parent/uuid-caller.json"
```

The public command requires clean producer and complete original checkouts,
an external Cargo target, genuine locked dependencies and the existing
admitted policy environment. It performs actual owner Cargo builds itself.
Its reports do not become passing results merely by listing the command.

Template-specific component and complete-public commands, after the native
build, are:

```bash
python3 -B hia/tests/test_template_parse_abi.py \
  --producer "$PWD" --library-dir "$native_output" \
  --report "$build_parent/template-parse-abi.json"
python3 -B hia/tests/test_build_receipt.py \
  --artifacts "$native_output" --mutation-module template_parse \
  --rustc "$rustc_binary" --report "$build_parent/template-parse-receipts.json"
python3 -B hia/tests/test_native_template_parse_caller.py \
  --producer "$PWD" --original-repo "$original_a201_checkout" \
  --library-dir "$native_output" --rustc "$rustc_binary" \
  --work-dir "$build_parent/template-caller" \
  --report "$build_parent/template-caller.json"
```

The public command requires clean producer/original checkouts, the actual
pinned toolchain and dependencies, the native policy environment above and
an external work directory. Listing a command is not a record of execution.

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
