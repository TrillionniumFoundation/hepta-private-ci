# Codex in HIA

This directory contains fifteen native HIA modules compiled with
[`TrillionniumFoundation/Hepta`](https://github.com/TrillionniumFoundation/Hepta)
at `0de5657a80f96b138525ac7ee9ce11712a83a10d`: fourteen borrowed-buffer
entries and one scalar count-admission entry. Their algorithms execute as
machine code compiled from the checked-in `.hepta` sources.

The opt-in `hia-native` Cargo feature connects the earlier eight components to
existing production paths on Linux x86-64 GNU: patch matching, four string
operations, and template parsing, rendering and ordered indexing. The prefix
matcher, scalar admission helper, pure RuleMatch reduction, ordered network-domain
reduction and allowed-prefix collection reach production callers through
`codex-execpolicy/hia-native`. Twelve production-path algorithms are configured;
the scalar helper belongs to the prefix algorithm. The allowed-prefix increment
has scoped local build, raw ABI and original-owner execution on exact final
bytes. Current full CLI, Protocol/Core consumers and prior component reruns need
new CI. Published fourteen-module push/PR native CI passed at
`b39a8ef9bd4256113874daf721ddf3f12b85dd4b`; those results remain historical.
Rust retains
allocation, owned strings and AST storage, generic iterator effects, public
formatting, and checked transport across the native interfaces. Static archives are
verified at build time and incorporated into the caller binary.

Two other components have narrower scopes. `utf8_boundaries` is a diagnostic
full-input UTF-8 validator; production prefix selection uses `utf8_prefix`.
`uuid_matches` implements the public `find_uuids` API behind the feature and
passes its original-source comparisons, but has no current repository
production caller. Neither was counted among the eight symbols retained by
the historical ten-module installed-full-CLI gate. That gate predates the
prefix matcher. The later published V2 full-CLI gate retained nine symbols;
neither historical gate qualifies the current compiler and scalar helper.

[`verification.json`](verification.json) records exact source, artifact and
report identities. [`migration.json`](migration.json) tracks the remaining
owners. Template, prefix-matcher, policy-summary, network-domain and allowed-prefix performance
equivalence, complete owner migration, default native releases and other
platforms remain open:

```json
{
  "production_dispatch_migrated": false,
  "whole_codex_rewritten": false,
  "legacy_source_retired": false
}
```

## Implemented components

| HIA module                                               | Original function or responsibility                                                 | Implemented behavior                                                                                                             |
| -------------------------------------------------------- | ----------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| [`seek_sequence.hepta`](seek_sequence.hepta)             | [`seek_sequence`](../codex-rs/apply-patch/src/seek_sequence.rs)                     | Four matching passes, Unicode whitespace/punctuation, first-match precedence, EOF/start semantics and both line-ending modes.    |
| [`utf8_boundaries.hepta`](utf8_boundaries.hepta)         | Diagnostic counterpart of `take_bytes_at_char_boundary`                             | Complete UTF-8 validation and the largest prefix within the byte budget.                                                         |
| [`utf8_prefix.hepta`](utf8_prefix.hepta)                 | [`take_bytes_at_char_boundary`](../codex-rs/utils/string/src/lib.rs)                | Constant-size boundary selection for a valid Rust string, preserving borrowing and allocation-free calls.                        |
| [`metric_tag.hepta`](metric_tag.hepta)                   | `sanitize_metric_tag_value`                                                         | Scalar replacement, trimming, whole-input default decision and the original 256-byte limit.                                      |
| [`markdown_location.hepta`](markdown_location.hepta)     | `normalize_markdown_hash_location_suffix`                                           | Location grammar, first range/column separators, empty/nonnumeric bodies and byte preservation.                                  |
| [`ascii_json_fragment.hepta`](ascii_json_fragment.hepta) | [`AsciiJsonFormatter::write_string_fragment`](../codex-rs/utils/string/src/json.rs) | ASCII preservation and lowercase Unicode escapes, including surrogate pairs. Serde still owns the surrounding JSON format.       |
| [`uuid_matches.hepta`](uuid_matches.hepta)               | `find_uuids` public API                                                             | Leftmost non-overlapping ASCII UUID matching, exact case and borrowed-window progress; no existing production caller is claimed. |
| [`template_parser.hepta`](template_parser.hepta)         | [`Template::parse`](../codex-rs/utils/template/src/lib.rs)                          | Four-brace escapes, delimiter/error precedence, UTF-8 byte offsets and Unicode trimming.                                         |
| [`template_render.hepta`](template_render.hepta)         | `Template::render`                                                                  | Duplicate/missing/extra validation precedence and literal/value segment decisions.                                               |
| [`template_index.hepta`](template_index.hepta)           | Template placeholder collection and render variable index                           | AVL byte ordering, duplicate detection, sorted iteration, lookup, usage marks and smallest-unused selection.                     |
| [`prefix_match.hepta`](prefix_match.hepta)               | [`PrefixPattern::matches_prefix`](../codex-rs/execpolicy/src/rule.rs)                  | Exact command-token prefix and alternative matching, complete frame validation and no-match distinction from native errors.     |
| [`prefix_admission.hepta`](prefix_admission.hepta)       | Count admission for the same prefix matcher                                          | HIA decides invalid, too-short or full-frame-required from two `u64` counts before Rust sizes or copies the pattern.               |
| [`policy_summary.hepta`](policy_summary.hepta) | `Evaluation::from_matches`, `Evaluation::is_match` and CLI summary | Complete pure reduction of current RuleMatch tags to presence, strictest decision and explicit-match flag. |
| [`network_domains.hepta`](network_domains.hepta) | `Policy::compiled_network_domains` | Non-Prompt selection, exact raw-host last-winner decisions and ordered Allow/Forbidden host vectors. |
| [`allowed_prefixes.hepta`](allowed_prefixes.hepta) | `Policy::get_allowed_prefixes` | Allow admission, exact Single/Alts rendering, vector ordering and deduplication of rendered prefixes. |

The template feature propagates through
`codex-cli/hia-native` → `codex-login/hia-native` →
`codex-utils-template/hia-native`. The template adapter does not substitute a
Rust ordered set, comparison or map lookup for the HIA index. The public
`Clone`, `Debug`, equality and ordered iterator behavior remains compatible.
These are component algorithm migrations, not complete Rust-owner retirement.

The prefix feature propagates from `codex-cli/hia-native` to
`codex-execpolicy/hia-native`. `PrefixRule::matches` and the existing `Policy`
callers reach the selected native matcher, including the standalone
`codex-execpolicy check` command. The Rust adapter calls the HIA scalar admission
entry before frame sizing, copying or allocation. The checked complete-frame
capacity selects a 512-byte stack buffer when it fits and the existing reserved
Vec otherwise. Both stores use one generic encoder and the same full-frame HIA
call. A small same-first/later-token mismatch needs no frame allocation; a
successful match still clones the selected command prefix into owned strings. HIA owns count
admission, token and alternative comparisons, and the prefix-match decision.
The separate policy-summary module owns aggregate decision precedence and the
explicit-match flag. Rule order, justifications, resolved-program metadata, parser behavior and
unmatched-command heuristics remain with their original owners. A native
error fails the call; it must not become `None` and activate those heuristics.

The full-input UTF-8 validator rejects overlong encodings, surrogates, values
above U+10FFFF, lone continuations and truncation, including invalid bytes
beyond the requested prefix. The production prefix and metric callers accept
already-valid Rust strings. JSON fragments and template parsing perform their
own incremental validation within their documented framing contracts.

### Native buffer interface

The fourteen borrowed-buffer modules expose this HIA signature:

```text
f0(source:readbuf, output:mutbuf, workspace:mutbuf) -> u32
```

The native borrowed-buffer interface passes each buffer as an address and a
64-bit byte length:

```c
uint64_t f0(const uint8_t *source, uint64_t source_length,
            uint8_t *output, uint64_t output_capacity,
            uint8_t *workspace, uint64_t workspace_length);
```

The direct seed build uses the high 32 bits for buffer-wrapper status and the
low 32 bits for the component result. The selfhost build zero-extends the
component's `u32` result and has no equivalent pointer/alias admission wrapper.
For both build modes a successful caller observes zero high bits and one of
these low-bit results:

| Component result                                      | Meaning                                                                               |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------- |
| `16` for `seek_sequence`, `8` for either UTF-8 module | Number of output bytes written.                                                       |
| `0` for a nonfinal `metric_tag` call                  | The input chunk was consumed; more chunks may follow.                                 |
| `1` through `256` for a final `metric_tag` call       | Number of final ASCII output bytes.                                                   |
| `0..4096` for `markdown_location`                     | Current-frame output length.                                                          |
| `8..12296` for `ascii_json_fragment`                  | Eight-byte consumed-length header plus escaped fragment.                              |
| Packed tag/consumed length for `uuid_matches`         | Match, exhausted input or additional-window progress.                                 |
| `24` for `template_parser`                            | One committed event and its source span.                                              |
| `32` for `template_render` and scalar index results   | One typed policy/index result.                                                        |
| `32 + 8 * n` for an index ordered page                | Up to 1,024 native-selected IDs.                                                      |
| `8` for `prefix_match`                               | One little-endian `u64`: matching pattern-token count, or zero for no match.           |
| `24` for `policy_summary` | Three little-endian `u64` values: presence, strictest decision and explicit-match flag. |
| `0xffffffff`                                          | Invalid frame/state; also invalid UTF-8 for the original matching/validation entries. |
| `0xfffffffe`                                          | Insufficient output or workspace capacity.                                            |
| `0xfffffffd`                                          | Invalid location format, or invalid UTF-8 in the JSON fragment encoder.               |

Caller allocations must stay live for the call and mutable ranges must be
disjoint. The direct seed wrapper and bootstrap compiler profile have a
1,048,576-byte capacity. The production B3 ELF entry receives the actual live
buffer extent; that compiler capacity is not a maximum file size. The patch
adapter checks all length arithmetic and uses fallible allocation. All modules
leave the source unchanged. The patch, UTF-8, prefix-matching and policy-summary modules leave
workspace unchanged, reserve it for future use and accept length zero. Their successful
calls preserve output bytes beyond the result length. The metric module uses
its workspace and output buffer as streaming state, as described below.
Returned errors leave the current call's output and workspace unchanged.
Earlier successful streaming calls and external writer effects remain committed.

`policy_summary` accepts a little-endian `u64` count followed by that many
pairs of little-endian `u64` kind and decision tags, consuming exactly
`8 + 16 * count` bytes. Kinds are prefix `0` and heuristics `1`; decisions are
allow `0`, prompt `1` and forbidden `2`. The 24-byte result contains presence,
maximum decision and whether any prefix record exists; empty input returns
three zero values. Output capacity is checked first. The entire frame and all
tags are validated before any write. Errors write nothing; workspace is never
written. Rust encodes tags in a 512-byte stack buffer through 31 records and
uses one reserved Vec for larger frames. It retains original RuleMatch objects,
metadata and order, and preserves the existing empty-Evaluation panic and
optional empty CLI decision. Every call sees current public-vector mutations.

`seek_sequence` accepts four little-endian `u64` fields: line count, pattern
count, start and flags. Bit 0 of flags enables EOF behavior; bit 1 selects
`PreserveLineEndings`; zero selects `NormalizeToLf`. These fields are followed
by `line_count + pattern_count + 1` little-endian offsets and concatenated UTF-8
strings, with the input lines before the pattern lines. The first offset is
zero and the last equals the payload length. Its 16-byte result contains
`found` (0 or 1) and the match index as two little-endian `u64` values. It checks
output capacity before validating the input frame.

`utf8_boundaries` accepts a little-endian `u64 max_bytes`, followed by UTF-8
text. Its eight-byte result is the little-endian byte offset at which to slice
the original text. It checks the eight-byte input header, output capacity and
then the UTF-8 payload, in that order.

`utf8_prefix` accepts three little-endian `u64` fields: original string length,
byte budget, and window start. They are followed by at most four bytes around
the requested cutoff. HIA validates the framing and chooses the final boundary;
the caller checks the returned offset before borrowing the original prefix.
This entry requires a valid original UTF-8 string. It does not claim full
validation of bytes outside its small window; the byte-oriented
`utf8_boundaries` entry supplies that separate contract.

`metric_tag` requires a 256-byte output buffer and a 32-byte workspace,
initially zeroed. The caller keeps both buffers between chunks, sends at most
1 MiB of source per call and sets workspace byte 24 to `1` for the final chunk.
Chunks may split a UTF-8 sequence, but their complete input must be a valid
UTF-8 string. Continuation bytes do not create additional replacement
characters; this entry does not validate arbitrary byte strings.

Workspace offsets 0, 8 and 16 hold little-endian `u64` values: the retained
character count saturated at 257, the last non-underscore position saturated
at 257, and whether any ASCII alphanumeric character has occurred. Byte 24 is
the final-chunk flag; byte 25 records finalization. Bytes 26 through 31 are
reserved and preserved. Invalid states, invalid flag values, calls after
finalization and short buffers are rejected before changing either buffer.
Successful calls may update bytes within the first 256 output bytes even when
the final result is shorter; output beyond byte 255 is preserved. The caller
uses only the returned final prefix.

The HIA implementation retains ASCII letters, digits and `._-/`, replaces each
other Unicode scalar with `_`, trims leading and trailing `_`, and emits
`unspecified` if the entire input contains no ASCII letter or digit. Otherwise
it returns the first 256 bytes of the trimmed result. The default decision
considers the entire string, including characters beyond the output limit.
The Rust adapter only frames chunks, checks native status/length and converts
the final ASCII bytes to a Rust string.

`markdown_location` borrows at most 4,096 bytes per frame and requires output
capacity at least that frame's length. Its two-byte workspace starts at zero:
byte 0 is the grammar phase (0 through 6, or 7 after finalization), and byte 1
is the final-frame flag. The return value is the current frame's output length,
which may be zero. The adapter concatenates only successful frame outputs.

The state machine requires `#L`, converts `#` to `:` and omits the initial `L`
of each endpoint. It accepts the original empty and nonnumeric bodies. The first hyphen
introduces an end point that must begin with `L`; the first `C` in each endpoint
becomes `:`. Later `C` and hyphen bytes are retained. Windows may split UTF-8
scalars because non-syntax bytes are copied unchanged. Invalid format returns
`0xfffffffd`; a frame is fully checked before either buffer changes.

`ascii_json_fragment` borrows at most 4,096 bytes and requires an output
buffer of `8 + 3 * frame_length` bytes. The first eight output bytes hold the
consumed input length as a little-endian `u64`; subsequent bytes are the escaped
fragment. Its two-byte workspace starts at zero: byte 0 records finalization
and byte 1 requests the final frame. Successful calls return at least eight.

ASCII bytes pass through the fragment encoder. Other Unicode scalars become
lowercase `\uXXXX` escapes or UTF-16 surrogate pairs. The HIA code validates
canonical UTF-8 before emitting. A nonfinal trailing partial scalar is left
unconsumed and borrowed again with more bytes; an invalid sequence or a final
partial scalar returns `0xfffffffd` without writing either buffer. The Rust
adapter writes successful fragments through the existing `io::Write` contract.
Serde retains surrounding JSON structure and control-character escaping;
already completed writer effects are not rolled back if a later write fails.

`uuid_matches` borrows at most 4,096 source bytes, requires a 36-byte output
and one workspace byte, and uses workspace byte 0 as the final-window flag.
The high 16 bits of the component return encode match (1), exhausted (2), or
more input (3); the low 16 bits encode consumed source bytes. HIA copies the
original 36 ASCII bytes only for a complete match. The caller re-presents an
incomplete candidate with the next window. Errors and non-matches leave output
and workspace unchanged. No word-boundary requirement or case conversion is
added to the original pattern.

The three template interfaces, their state layouts, atomic error behavior,
large-buffer borrowing and public-effect preservation are specified in
[`template_buffer_contract.md`](template_buffer_contract.md). Template-specific
syntax and semantic error codes are distinct from malformed-buffer errors.

`prefix_match` accepts little-endian `u64 command_count` and
`u64 pattern_count`, followed by `pattern_count` groups. Each group contains a
`u64 alternative_count` and that many strings, each encoded as `u64 byte_length`
followed by raw bytes. `pattern_count` must be at least one; the first group
must contain exactly one alternative. Later groups may have no alternatives,
which produces a non-match. After all groups, the frame contains exactly
`min(command_count, pattern_count)` length-prefixed command tokens. Extra
command tokens are irrelevant to prefix selection and are not copied.

The entire frame, including all counts, lengths and its exact end, is validated
before matching. An early mismatch or insufficient command count cannot hide
a malformed tail. Comparison is byte-exact, with no normalization or case
folding; public Rust strings are already valid UTF-8, and the raw ABI also
accepts arbitrary byte values. Output capacity is checked first. A successful
call returns `8` and writes only the first eight output bytes: the pattern
count for a match, or zero for a non-match. A malformed frame returns
`0xffffffff`; output capacity below eight returns `0xfffffffe`. All errors
leave output and workspace unchanged, and workspace is never read or written.
The current v9 implementation uses native little-endian word loads and stores
only after explicit bounds checks. Its eight-byte comparisons retain a
byte-exact tail; they do not change this packet ABI or error precedence.

### Network-domain selection and reduction

`network_domains` owns the complete pure `Policy::compiled_network_domains`
algorithm. The last non-Prompt rule for each exact host wins; a repeated rule
with the same decision still moves that host to its final position. Allow and
Forbidden hosts retain their respective final-rule order. Raw `from_parts`
strings, including empty hosts and Unicode, remain byte-exact; protocol and
justification are ignored as before. Rust owns checked transport and the final
owned `String` values, with no host comparison, sorting or deduplication.

The borrowed-buffer entry uses little-endian `u64` framing:

| Mode | Input | Successful output and workspace |
| ---- | ----- | ------------------------------- |
| SELECT (`0`) | Mode, count at most 64, then exactly count decision bytes: Allow `0`, Prompt `1`, Forbidden `2`. | Output capacity at least `8 + count`: selected count, then increasing `u8` batch positions. Workspace is unchanged. |
| REDUCE (`1`) | Mode, original count `M`, selected count `N`, then `N` records of original index, decision, host length and raw host bytes. | Output capacity at least `16 + 8*N`: Allow count, Forbidden count, then final original indices grouped by decision and increasing within each group. Workspace capacity at least `N`: flags `0` superseded, `1` Allow, `2` Forbidden. |

REDUCE requires `N <= M`, increasing indices below `M`, only decisions `0` or
`2`, bounded lengths and exact frame consumption. It validates the complete
frame before checking both capacities and writing. SELECT checks its exact
frame/capacity and validates every tag before writing. The entry checks the
global minimum eight output bytes first. Status `0` means success; `0xffffffff`
means malformed input, `0xfffffffe` short output and `0xfffffffd` short
workspace. Every error preserves output and workspace; source is always
unchanged, and success preserves unused capacity. Raw ABI hosts need not be UTF-8.

The adapter sends fixed stack batches of decisions to SELECT before inspecting
selected hosts. All-Prompt inputs never read host lengths or bytes and allocate
no heap storage. Selected indices, full frames, output and workspace use bounded
stack storage before checked heap spill. Invalid statuses or structural output
failures panic without a Rust algorithm or empty-list fallback. These guards
cannot establish the correctness of a structurally valid wrong answer; the
actual HIA/original-owner differential provides that semantic evidence.

### Allowed-prefix admission, rendering and collection

`allowed_prefixes` owns the complete pure `Policy::get_allowed_prefixes`
algorithm. It admits Allow prefix rules, renders Single tokens unchanged and
Alts as `[` plus alternatives joined by `|` plus `]`, then sorts and deduplicates
complete rendered `Vec<String>` values. Empty alternatives, empty strings and
literal delimiters can produce equal rendered vectors; they retain the original
comparison and deduplication semantics.

Rust preserves rule iteration and dynamic `as_any` callbacks/downcasts. Each
admitted pattern is encoded before the next callback; non-prefix, Prompt and
Forbidden patterns remain uninspected. Rust owns checked framing, structural
result/UTF-8 validation and final owned strings. It does not render, sort or
deduplicate the selected prefixes.

The borrowed-buffer entry uses little-endian `u64` words:

| Mode | Input | Successful output and workspace |
| ---- | ----- | ------------------------------- |
| ADMIT (`0`) | Exactly mode and decision: Allow `0`, Prompt `1`, Forbidden `2`. | Eight-byte output is one only for Allow; workspace unchanged. |
| PLAN (`1`) | Mode, prefix count `N`, then exact prefix frames. Each starts with token count at least one. Each token has kind (`0` Single, `1` Alts), alternative count and length-prefixed raw alternatives. The first token must be Single; Single has one alternative, Alts may have zero. | Three words: rendered serialized bytes `R`, workspace `24*N+8+R`, output capacity `8+8*N`. Workspace unchanged. |
| RUN (`2`) | Same complete selected-prefix frame, with mode two. | Workspace stores `N+1` rendered offsets, two `N` index arrays and `R` rendered bytes. Output capacity is `8+8*N`; successful output is unique count `U` followed by `U` original selected-frame indices. |

RUN renders all vectors, uses stable bottom-up merge sort with bytewise token
ordering followed by vector-length ordering, and emits the earliest index for
equal rendered vectors. It writes only the `8+8*U` result prefix. Empty input
still executes PLAN/RUN, with zero rendered bytes and eight-byte workspace and
output; the public owner allocates no heap storage for this case.

Status `0` means success, `0xffffffff` malformed frame, `0xfffffffe` short output,
`0xfffffffd` short workspace and `0xfffffffc` an unrepresentable derived layout.
Minimum output eight is checked first, followed by complete exact validation
and checked layout; RUN checks output capacity before workspace capacity.
Every error preserves output/workspace, source is always unchanged, and success
preserves unused capacity. Raw ABI bytes need not be UTF-8. Invalid statuses or
structural results panic without fallback; semantic correctness comes from the
actual HIA/original-owner differential, not structural checks alone.

### Scalar prefix admission

`prefix_admission` uses the separate `u64-pair-to-u64-v1` entry profile,
with a v8 `exports(f0)` source:

```text
f0(command_count:u64, pattern_count:u64) -> u64
```

| Condition, in priority order | Return | Public adapter action |
| --------------------------- | ------ | --------------------- |
| `pattern_count == 0` | `0xffffffff` | Fail the call. |
| `command_count < pattern_count` | `0` | Return no match before frame allocation or copying. |
| Otherwise | `1` | Construct and validate the complete matcher frame. |

The helper receives counts only; it cannot inspect strings or memory buffers.
Rust performs checked transport conversions and handles the returned status.
Every status other than zero or one is an error, so an invalid native result
cannot become a no-match or activate unmatched-command heuristics. No Rust or
C matcher substitutes for either HIA decision.

This precheck is an additional public-call stage, not a relaxation of the
raw `prefix_match` ABI. Every supplied raw matcher packet still receives
complete validation, even when its command count is insufficient. Admitted
public calls still copy the complete pattern, including alternatives after
a possible first-token mismatch.

## Build

Use Linux x86-64, Python, GNU `ld`, `objcopy`, `ar`, and a clean checkout of the Hepta revision
in [`toolchain.json`](toolchain.json). The build checks the checkout revision
and working tree before and after compilation. Its output directory must not
already exist and must be outside the source checkout.

From the Codex repository root:

```bash
set -eu
hepta_checkout=/absolute/path/to/Hepta
build_parent=$(mktemp -d "${TMPDIR:-/tmp}/codex-hia.XXXXXXXX")
native_output="$build_parent/native"

python hia/build.py \
  --hepta-root "$hepta_checkout" \
  --output "$native_output"
```

The default build executes this sequence:

1. Create B0 from the pinned HIA compiler source using the host seed builder.
2. Run B0 to compile B1, B1 to compile B2, and B2 to compile B3.
3. Require B1, B2 and B3 to reproduce identical compiler bytes.
4. Run B3 to compile each component to an ELF object.
5. Link diagnostic shared objects with GNU `ld` and create namespaced static
   archives with GNU `objcopy` and deterministic `ar crsD`.
6. Verify that symbol renaming leaves `.text` unchanged, there are no imports,
   each entry is unique, and each archive contains exactly its HIA object.

The Python driver orchestrates this build and creates the initial B0 seed.
B1–B3 and the final component compilation execute native HIA compiler images.
The linker links the emitted object; it does not generate C or Rust source.

The build driver is the exact version from Codex revision
`7fe65ae990187e6ff1130c791f902728b4e50197`. Borrowed buffers remain the
default closed profile; only `prefix_admission` selects the scalar profile.
Scalar admission verifies the exact exported signature and 59-byte entry
wrapper, rejects imports or unexpected relocations, and normalizes the
compiler's empty relocation section without changing emitted `.text`.
The existing Cargo receipt helper is unchanged. The scalar artifact gate is
separate from raw scalar ABI and public-owner behavior tests.

`build.json` records the compiler generation identities, source/Core hashes,
object inventory, static archives and shared-library hashes. Each module also
receives a strict `.link` receipt. The shared Cargo build helper verifies the
current source, lock, driver, helper, build report, three compiler images,
ELF export, machine-code digest and exact archive member. It copies the
captured archive into Cargo's output directory before static linking.
A built component still needs its
behavioral tests. Compiler generation equality covers this bootstrap path;
the full compiler/runtime and Codex capability requirements are tracked in the
migration file.

For development, the explicit seed path directly uses Hepta's host machine
emitter and omits the B1–B3 rebuild:

```bash
python hia/build.py \
  --hepta-root "$hepta_checkout" \
  --output "$build_parent/seed-development" \
  --seed-only
```

The resulting report identifies this as `seed-only`. Keep generated objects,
libraries, compiler stages and logs in the external build directory.

## Verify against the original Rust

The component checks require a working Rust compiler. A missing Rust
oracle is a test failure. The matching test includes the actual Rust source
file; the UTF-8 test extracts the actual original public function and compiles
it unchanged. Rust supplies the expected original behavior.

After the native build, run both suites from the Codex repository root:

```bash
set -eu
rustc_binary=$(command -v rustc)
"$rustc_binary" --version

python hia/tests/test_seek_sequence.py \
  --library "$native_output/seek_sequence.so" \
  --rustc "$rustc_binary" \
  --report "$native_output/seek-sequence-tests.json"

HEPTA_SOURCE="$hepta_checkout" \
RUSTC="$rustc_binary" \
CODEX_HIA_UTF8_SHARED="$native_output/utf8_boundaries.so" \
python hia/tests/test_utf8_boundaries.py
```

`CODEX_HIA_UTF8_SHARED` selects the artifact produced by the native build.
Without it, the UTF-8 test creates a development shared object through the host
machine emitter. The source oracle and test coverage remain the same.

The search suite also supports exporting its framed corpus and importing the
original oracle output from another machine. The imported output must echo
every exact input frame, so results cannot silently be joined to a different
corpus. See `python hia/tests/test_seek_sequence.py --help`.

### Allowed-prefix increment: current scoped qualification

The fourteen-file increment starts from `b39a8ef9bd4256113874daf721ddf3f12b85dd4b`. Its frozen source manifest is
`2f9b47f940b30c7e298d4cf771a027479f9212eb01553578b488fc28389d254e` and qualification summary is
`a0c01523e4cd234caf4f7ac228262523c39c625b66057379b48ab2349f309e68`. All actual public source hashes
match the final files. Seven Rust files were formatted before execution; final
scoped fix/fmt changed zero bytes. No post-fmt tests ran. Independent frozen
source, capture, artifact and runtime-status review is bound by
`59d94f7945ebb4f19700a1f6e7b5f421776a193282d198e6febfdef4eaefd606`.

| Gate | Actual local observation |
| ---- | ------------------------ |
| Native build and receipts | Local B1/B2/B3 fixed point; 15 modules, 14 borrowed and one scalar; 70 receipt checks. Remote owner execution reused the exact 204-file transfer and did not rebuild HIA. |
| Raw allowed-prefix ABI | 6,118 calls: 3,810 successes and 2,308 errors preserving output/workspace; 256 concurrent calls included, maximum input 8,388,773 bytes, zero skips. |
| Original public owner | 11,270 comparisons including 512 concurrent comparisons, 16 entry observations and six callback/panic effect cases. Actual locked owner crates, captured rustc bindings and 47 source hashes are recorded. The 215-token extraction overlaps the unchanged 2,372-token policy oracle. |
| Allocations and injected errors | 31 allocation cases, 12 zero-allocation cases and a positive allocation/reallocation probe; 35 substituted-callee rejection cases plus five separate ignored-pattern transport cases. |
| Owning crate and standalone | 34 native and 34 default tests, zero skips; 30 installed cases and 60 processes retain three symbols. The standalone command does not exercise allowed-prefix collection. Both all-target Clippy modes passed `-D warnings`. |

The original owner wrapper remains failed: all four commands returned zero,
but its final guard found nextest's JUnit file inside the source tree. The exact
JUnit bytes were moved outside and source/protected roots reconciled without
rerunning tests. Maintenance v1 failed Cargo's source-only VCS guard; v2 used
the tool-required `--allow-no-vcs` for both scoped fixes, then formatted with
zero source delta. The first derived export summary omitted strict-command
labels; v2 corrected only that summary. Original failures and runtime terminal
records remain immutable; no failed report was rewritten as passed.

All fourteen diagnostic timing rows are slower than original Rust. Values are
total nanoseconds, from actual dev owner artifacts with an optimized external
harness; `performance_qualified` remains false.

| Allowed-prefix case | Calls | HIA total ns | Original Rust total ns |
| ------------------- | ----: | -----------: | ---------------------: |
| `empty` | 10,000 | 2,516,141 | 283,450 |
| `one_prompt` | 10,000 | 2,935,035 | 418,745 |
| `one_forbidden` | 10,000 | 2,940,526 | 417,815 |
| `many_prompt` | 1,000 | 2,213,841 | 547,731 |
| `ignored_large_pattern` | 1,000 | 299,260 | 41,878 |
| `ordinary_single` | 10,000 | 14,498,855 | 1,265,195 |
| `ordinary_alternatives` | 10,000 | 17,384,381 | 2,688,735 |
| `rendering_collisions` | 1,000 | 9,234,641 | 1,810,116 |
| `reverse_unique` | 100 | 13,678,354 | 1,545,125 |
| `sorted_unique` | 100 | 13,636,315 | 1,532,836 |
| `single_large` | 3 | 10,700,629 | 86,867 |
| `repeated_large` | 3 | 81,054,018 | 1,184,868 |
| `first_byte_difference` | 3 | 21,547,354 | 223,632 |
| `last_byte_difference` | 3 | 30,378,530 | 452,294 |

`single_large` takes about 123 times the Rust time. Its logical requested-live
peak is 6,291,603 versus 2,097,273 bytes, about three times as large. This metric
excludes RSS and allocator transient double buffers. All 31 allocation rows,
including selected-frame/render-copy costs and spill boundaries, remain in the
exact reports referenced by
[`allowed_prefixes_qualification`](verification.json#allowed_prefixes_qualification).

Current-source CI must execute the expected thirteen-symbol full CLI, exact
Protocol consumer `models::tests::format_allow_prefixes_limits_output` with
`codex-execpolicy/hia-native`, both existing Core consumer gates and all prior
components. No PASS count is prefilled for these pending gates. Whole Policy,
Core, workspace, required platforms, performance, default release and source
retirement remain open.

### Network-domain increment: recorded fourteen-module local checkpoint

The frozen fourteen-file increment starts from published thirteen-module
revision `7b51d6614e494ab62aa20f049c862ffef1808ce1`. Its source manifest is
`a918eb9a9ab6c3918e0dc0ff4f3c65fc99c7947d8d90c5044b9509977c5d3406`;
the qualification summary is
`97c656abb64e8ba21e7d843523d27bc5beeb514e112e789555030f90e8f22c6f`.
The final HIA source is `7ef166afa54278b0ec0957a9e210141cc58ca31652518a5d127ffff4a0eb9859`;
the production adapter is `bb23cad2692e0e4025c1d1a2a4c2843a9e73e73934a7eddc09ed3ca93c1e4902`.
Independent source, capture and evidence review is bound by
`c647451be7c181266c2b73d94a9db8579f523b5d13cac9f78c01ead69e2e84ff`.
That review did not run tests or download the compiled binaries; its precise
report/log coverage limits remain in the cited verification record.

| Gate | Actual local observation |
| ---- | ------------------------ |
| Native build and receipts | Fresh B1/B2/B3 fixed point; 14 modules, 13 borrowed and one scalar; 68 receipt checks. The earlier thirteen source/Core/static identities match their recorded build; identity equality does not transfer behavioral passes. |
| Raw network-domain ABI | 8,244 calls: 7,247 successes and 997 errors preserving output/workspace; 256 concurrent calls are included, maximum input 4,194,378 bytes, zero skips. |
| Original public owner | 67,976 comparisons total, including 66,430 exhaustive, 1,024 random, six explicit, four large and 512 concurrent comparisons; 18 entry observations. The 175-token reducer pin overlaps the unchanged 2,372-token whole-policy pin and is not an additional independent count. |
| Allocations and injected errors | 25 allocation cases, ten zero-allocation observations and positive alloc/realloc probes; 23 substituted-callee failure cases exercise the actual adapter's structural guards. |
| Owning crate and standalone | 34 native and 34 default owner tests with zero skips; 30 installed cases and 60 relocated processes with three symbols. The standalone command does not exercise network-domain compilation. |
| Owner checks and final source | Both all-target execpolicy Clippy modes passed `-D warnings`; nine owner/build/installed/fix/fmt/diff steps returned zero. Four Rust files were formatted before the tests; final fix/fmt changed zero bytes. No post-fmt tests ran, and executed/final source hashes are identical. |

The first assembler attempt rejected helper back edges to the entry block with
`E_HIA_CFG`. Separate loop headers corrected the source before the successful
native build. A later export-only freeze attempt misread the receipt's status
key; its corrected exporter did not change source or rerun tests. Both failure
reports remain immutable evidence outside the source tree.

All eleven timing rows below are slower than original Rust. These are total
nanoseconds from real dev crate artifacts and an opt-level-3 external harness;
they are diagnostic observations, with `performance_qualified: false`.

| Network-domain case | Calls | HIA total ns | Original Rust total ns |
| ------------------- | ----: | -----------: | ---------------------: |
| `empty` | 10,000 | 767,033 | 90,457 |
| `one_prompt` | 10,000 | 935,077 | 107,896 |
| `prompt_batch_boundary` | 1,000 | 1,006,324 | 143,985 |
| `large_prompt_hosts` | 1,000 | 131,216 | 13,529 |
| `three_unique` | 10,000 | 13,045,171 | 1,317,523 |
| `same_decision_moves_last` | 10,000 | 12,425,963 | 1,268,325 |
| `many_unique` | 100 | 8,825,969 | 2,878,959 |
| `single_large_host` | 3 | 201,833 | 105,166 |
| `repeated_large_host` | 3 | 9,989,578 | 743,974 |
| `first_byte_difference` | 3 | 475,273 | 254,431 |
| `last_byte_difference` | 3 | 3,249,126 | 323,339 |

The repeated-large-host case has an 8,388,732-byte frame. Logical requested-live
peak allocation is 10,485,909 bytes versus Rust's 2,097,249, about five times as
large; this metric is neither RSS nor transient realloc double-buffer memory.
All-Prompt cases, including 4,097 rules and large hosts/metadata, allocate zero.
The 511/512-byte frames use two native allocations and the 513-byte frame uses
three versus Rust's two; selected-index/output/workspace spill boundaries are
also recorded. Exact rows and report identities are retained in
[`network_domains_qualification`](verification.json#network_domains_qualification).

At this local checkpoint the full CLI twelfth-symbol gate and actual Core
network consumer were pending. The published fourteen-module CI below later
executed them on its exact source. Those passes do not qualify the current
fifteen-module candidate. Whole Policy/Core/workspace, required platforms,
performance, default release and source retirement remain open.

### Policy-summary increment: recorded thirteen-module local checkpoint

`policy_summary` owns the complete pure result reduction used by Evaluation
and the CLI. Rule traversal, user callbacks, iterator/as_ref/drop/panic effects,
strings and serialization remain in Rust. Whole Policy and Core are still open.
The immutable source manifest covers fifteen changed files over V4 `d7a5044a`.

| Gate | Actual local observation |
| ---- | ------------------------ |
| Native build and receipts | B1/B2/B3 fixed point; 13 modules, 12 borrowed and one scalar; 66 receipt checks. Previous twelve source/Core/static identities match V4, but rebuilt shared-library hashes differ. |
| Raw policy-summary ABI | 3,955 calls, including 875 no-write errors, every tested truncation, invalid tails, short-output precedence, buffer canaries, large frames and 512 concurrent calls; zero skips. |
| Original public owners | 10,356 complete-result comparisons, 23 mutable states and six complete effect traces against token-pinned original owners at `f75abe3e`; exact metadata, ordering, JSON and panic behavior are included. |
| Allocations and injected errors | 30 allocation cases, 20 zero-allocation observations and alloc/realloc positive probes; 18 injected callee failures rejected by the actual adapter. |
| Owning crate | 34 native-feature and 34 default-feature tests passed, zero skips. |
| Installed standalone | 30 cases and 60 relocated processes passed with three native symbols; exact output, exit and expected JSON were checked. |
| Owner checks | Both execpolicy all-target Clippy modes passed with `-D warnings`; scoped fix and workspace fmt returned zero. The aggregate final owner report remains **false** because its source-identity guard detected formatting. |

The public report executed harness SHA `0d74f5d82b59affa6b9d0668f93979af343be822479eb03aab97e9ad478cd4ab`.
Repository formatting only exchanged the two independent `serde_json` imports,
producing final SHA `323290da9790073f08e66871ba888ac9fa15a1dc24aad89490678437a22faf7b`.
Reversing that exact 336-byte diff reproduces the executed bytes. Production,
allocation and failure-harness sources are unchanged. No post-fmt tests ran,
as required by AGENTS.md; final harness execution was pending at that local
checkpoint. The published thirteen-module CI below subsequently executed its
final bytes. The immutable failed aggregate reports are preserved.

All five diagnostic timing rows were slower than original Rust. Each row below
contains totals for 10,000 calls using actual dev crate artifacts and an
opt-level-3 external harness; these observations do not establish equivalence.

| `Evaluation::is_match` case | HIA total ns | Original Rust total ns |
| -------------------------- | -----------: | ---------------------: |
| Empty | 1,195,881 | 71,767 |
| Mixed, three records | 2,687,282 | 52,579 |
| All heuristics, 31 records | 19,113,968 | 674,938 |
| First prefix, 31 records | 18,471,439 | 52,568 |
| Last prefix, 32 records | 16,603,769 | 722,147 |

Observed 32/33-record frames add one allocation versus Rust's zero; frames
through 31 records fit the stack. At that local checkpoint, full Codex CLI
(expected 11 symbols) and Core were pending; the subsequent thirteen-module CI
qualifies only the scoped suites recorded below. Whole workspace, required
platforms, performance, default release and retirement remain unqualified.
Exact artifacts, original-owner identities,
format reconciliation and report hashes are in
[`policy_summary_qualification`](verification.json#policy_summary_qualification).

### Published fourteen-module CI: immutable history

Published head `b39a8ef9bd4256113874daf721ddf3f12b85dd4b` and PR merge
`1e1f117e2119e3570134fb626fa40f09318c13ab` share tree `641cdf1111cc346da3ede2ee45bafc8a3fbdcd05`.
Both native runs passed all 46 actual steps. Independent review rehashed all
260 ZIP members across the two artifacts and 55 published source inputs.

| Event | Run | Artifact | ZIP SHA-256 |
| ----- | --- | -------- | ----------- |
| push | [43692321284](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43692321284) | 14153173708 | `ae3ff46d51d3785cf252b644ab8169669b6815762a417506e1285939fd30a30c` |
| pull_request | [43692332741](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43692332741) | 14153867855 | `b9906adecc2addb60cc60e2db889e6b956b681cb37510c42af4f47735602c56c` |

Each run executed 68 receipt and 121 scalar-artifact checks, 8,244 raw network
calls and 67,976 original public comparisons, 25 allocation cases with ten
zero-allocation cases, and 23 injected-callee cases. The actual Core network
consumer has one PASS with 3,880 excluded tests; the existing execpolicy filter
has 11 PASS with 3,870 excluded. These are scoped consumers, not a complete Core
suite. The full CLI has 34 cases, two startup probes and 12 retained symbols;
standalone has 30 cases, 60 processes and three symbols. Native/default owner
components passed 198/185; CLI/arg0/TUI passed 4,474 with six skips, not the
whole workspace. Prior raw/public/allocation gates also executed.

Module source/object/archive identities match between events, while the two full
CLI binary hashes differ. Standalone binary hashes match. Each run's 11 network,
five policy-summary and seven prefix timing rows are slower than Rust. Complete
raw timing rows, all 25 network allocation rows and nine identified resource
regressions per run remain in the immutable audit, without performance closure.
Native audit SHA: `c7a95ee20b7308e6302480b7bf557d9044ffde604536f9dfd5f27ac14856dc81`;
independent verification SHA: `288ddcafbd3e589cc3b196f4a62ff65d1f116fb8cd17c8fb434332a937ae47f1`.

Broader CI is terminal: blocking run 43692332760 has 37 jobs, 17 successful,
16 failed and four skipped. Architecture has three successful jobs; canary has
one successful metadata job and two skips. Thirteen of sixteen original failure
logs are available: twelve actual merge checkouts and one workflow-only
aggregation. GNU Clippy, GNU tests and MUSL tests original logs are unavailable;
compact Clippy records do not establish the linker missing symbol. Intel Mac
failed with 363 pass, one build failure, 38 local failures and 165 skipped;
Required rejected Bazel and SDK failures. No paired-base causal attribution was
performed. Audit SHA: `c5ad5593c363bffbf8586f3dc64bc3050da307712119626c24ce34f63241f85b`;
independent verification SHA: `660ecbf422647a010166a26fb90db3ec19deeb91a8ac94e546088cbba6f18a52`.
These source-specific outcomes do not transfer to the current candidate.

### Published thirteen-module native CI: immutable history

Push [43686447298](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43686447298)
checked out `7b51d6614e494ab62aa20f049c862ffef1808ce1`; PR
[43686504680](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43686504680)
checked out merge `1702fc6ec25cee6c5558c1db13ff0e51acdd2fbe` with the same
`97cc6a157085f01ece227bf8c2e6dc2b7a71934e` tree. Each passed all 43 steps.
Both artifact ZIPs were verified, with all 196 extracted members rehashed and
88 published source bindings independently checked. Artifact IDs are
`14151312247` and `14150734300`; exact ZIP digests and source identities are in
[`published_policy_summary13_ci_history`](verification.json#published_policy_summary13_ci_history).

Each run actually executed final public harness `323290...`: 10,356 complete
results, 23 mutable states, six effect traces, raw ABI 3,955/875 errors/512
concurrent, allocations 30/20 zero and 18 injected failures. Each ran 66 receipt
checks, 120 scalar artifact checks including `source-policy_summary`, 158,100
scalar calls, 49,938 prefix comparisons, 5,937 prefix raw calls and 20/9 zero
prefix allocation cases. Standalone passed 30 cases/60 processes with three
symbols; full CLI passed 34 cases plus two startups with eleven symbols.
Native/default components passed 198/185 tests; CLI/arg0/TUI passed 4,474 with
six skips; Core passed eleven explicitly filtered tests with 3,870 excluded.
Reported binary hashes remain report evidence, since the binaries themselves
are not in the downloaded report archives.

All five policy-summary and all seven prefix timing rows in each run remained
slower than Rust. The native summary SHA is
`4de6c4851c224052cf8910875f60cb700119e3194115f5a3eb9326928bb38eac`;
the independent root verification SHA is
`81145a674bbb45d45bac10f9ca3f2b26181e6961b4f4691177318b1f139b378f`.
The separate broader run `43686504803` finished with 37 jobs: 16 success,
16 failure, one cancelled and four skipped. Architecture passed three jobs;
the metadata-only canary had one success and two skips. The Intel Mac job is
cancelled, with earlier failures but no final Bazel test summary; its cancellation
initiator is unproven. Windows Clippy reported an explicitly requested
incompatible cognitive-product target, and the required gate rejected Bazel,
blob-size and SDK dependency failures. No base comparison establishes cause.
The final broader audit SHA is
`d6c39aabd7d85137cff5d87252377ba0ccae56d5a05a416c77e2447ac4377e2c`;
it preserves the old nonterminal snapshot and the three unavailable original
logs. These immutable thirteen-module outcomes do not qualify the current
fourteen-module candidate or whole workspace/platform/default/performance/retirement.

### Published V4 native CI: immutable history

V4 push [43679109773](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43679109773)
checked out `d7a5044a5be10dcd8f13ad9dab03e2bf9ba3d88f`; PR
[43679113356](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43679113356)
checked out merge `18acfc33830d81632ce2b72d87a6eb657d075021` with the same tree.
Each passed all 41 steps and retained 66 verified artifact members. Each ran
the installed full CLI's 34 cases plus two startups with ten symbols,
CLI/arg0/TUI's 4,474 tests with six skips, and 11 explicitly filtered Core tests
with 3,870 excluded. Component crates passed 198 native and 185 default tests.
These are scoped suites, not full workspace or complete Core qualification.
All seven prefix timing rows in each run remained slower than original Rust.

V4's separate broader blocking run finished with 37 terminal jobs: 17 success,
16 failure and four skipped. Architecture passed; the v8 canary was metadata-only
with no native build executed. [`published_v4_ci_history`](verification.json#published_v4_ci_history)
binds the exact source, runs, artifacts and immutable reports. No V4 pass is
assigned to the current fourteen-module increment.

### Prefix matcher: historical V4 local stack-frame qualification

The adapter increment starts from published V3 revision
`98429434a266d2165e9d3b4d6f1894bd77916917` and changes three transport/test
files. The twelve HIA programs, compiler/build sources, raw ABI and native
archives are unchanged and were reused without a new HIA build.

After HIA count admission, the adapter computes the exact complete-frame size.
Frames of at most 512 bytes use a stack buffer; larger frames retain the
reserved Vec and append path, without another full-frame copy or zero fill.
One generic `Write` encoder emits the original packet into either store and
passes only the encoded extent to the same raw HIA matcher. HIA still owns
traversal, byte comparison and the decision. There is no first-token probe or
cache. Public `first` and `rest` mutations remain visible on every call.

For the normal Policy path after first-token lookup, a small later-token
mismatch now has no frame allocation. Successful results retain their owned
`Vec<String>` allocations. These measured local gates are distinct:

| Gate | Observed result and execution scope |
| ---- | ----------------------------------- |
| Original Rust public matcher | 49,938 comparisons across seven tests actually ran in the minimal stack fixture; integration bound all nine source files byte-for-byte and did not rerun this gate. |
| Public allocation regression | 20 fixture cases, nine zero-allocation calls; positive probes observed alloc and realloc. Integration bound the same nine files without rerunning this gate. All five earlier count-rejection cases remain zero-allocation. |
| Stack/heap threshold | Complete frames of 511/512/513 bytes observed 0/0/1 allocations. Mutating the same rest back across the threshold observed 0 then 1. Successful 512/514-byte frames observed 3/4 allocations including required owned results. |
| Current complete execpolicy crate | 34 native-feature and 34 default-feature tests actually ran and passed; zero skips. |
| Current builds and installed standalone | Both binaries built; 30 cases and 60 relocated production processes passed exact output/exit/expected-JSON checks. |
| Current owner checks | Eleven actual steps including both all-target Clippy modes with `-D warnings`, scoped `just fix`, `just fmt` and diff checks. Fix/fmt preserved every frozen source byte. |
| Reused V3 HIA artifacts | The earlier 5,937 raw-prefix calls, 158,100 scalar calls, 119 artifact checks and 64 receipt checks remain bound to identical artifacts. They were not executed again for this adapter increment. |

Exact source/binary identities, original report paths and hashes are recorded in
[`stack_frame_qualification`](verification.json#stack_frame_qualification).
The V3 adapter's own allocation/standalone/performance records remain below
and in the recorded `current_qualification` block. This local checkpoint
predated V4 CI; the subsequently published d7 gates are recorded above. A V3
result retains its V3 scope, and V4 results do not qualify the new summary source.
Performance, default release, complete ownership and retirement remain false.

#### Stack-frame performance remains open

The first complete stack public differential recorded all seven original
performance rows. Values are total nanoseconds for the stated call count:

| Scenario | Iterations | Stack HIA total (ns) | Original Rust total (ns) |
| -------- | ---------- | -------------------- | ------------------------ |
| short_match | 10,000 | 3,272,203 | 251,334 |
| first_mismatch | 10,000 | 2,437,382 | 60,039 |
| many_alternatives | 1,000 | 2,887,142 | 92,568 |
| large_match | 3 | 3,509,897 | 179,506 |
| large_pattern_empty_command | 3 | 80 | 70 |
| large_pattern_short_command | 3 | 60 | 30 |
| first_mismatch_large_alternatives | 3 | 95,588 | 80 |

One additional bounded same-machine diagnostic ran V3 and then stack using
the same Rust toolchain, V3 archives and unchanged performance harness:

| Scenario | Iterations | V3 HIA (ns) | V3 Rust (ns) | Stack HIA (ns) | Stack Rust (ns) |
| -------- | ---------- | ----------- | ------------ | -------------- | --------------- |
| short_match | 10,000 | 3,446,504 | 244,913 | 2,747,453 | 243,973 |
| first_mismatch | 10,000 | 2,015,984 | 61,138 | 1,826,669 | 58,369 |
| many_alternatives | 1,000 | 2,792,662 | 104,487 | 2,793,513 | 121,886 |
| large_match | 3 | 3,601,200 | 164,105 | 3,436,795 | 180,325 |
| large_pattern_empty_command | 3 | 140 | 70 | 130 | 70 |
| large_pattern_short_command | 3 | 60 | 40 | 60 | 40 |
| first_mismatch_large_alternatives | 3 | 87,807 | 70 | 93,497 | 80 |

Both observations retain the large-alternative first-mismatch cost. The
ordered pair is a diagnostic, not a statistical performance qualification or
a replacement for the full differential. No timing threshold is marked
passed. Raw logs and both complete stack observations remain external.

### Recorded V3 compiler and adapter qualification

The following local adapter results are recorded at published revision
`98429434a266d2165e9d3b4d6f1894bd77916917`. Its HIA artifact evidence still
corresponds to the identical reused artifacts; its caller/allocation results
belong to the V3 adapter, not to the current stack-frame adapter.

The V3 twelve-module B1/B2/B3 build passed with Hepta
`0de5657a80f96b138525ac7ee9ce11712a83a10d`. All three compiler generations
have SHA-256
`76fe758bc49499046169a5b4798c31d57366344c23530b35bc489e4008639273`;
the build report has SHA-256
`1a9a4f4c8da2e8523a584c68ce6aa74bce2924a656d2f83980cbe15955bb393b`.
Executed Linux x86-64 GNU results with Rust 1.96.1 are:

| Gate | Observed result |
| ---- | --------------- |
| Raw prefix ABI | 5,937 calls, including 2,310 error/no-write cases and 512 concurrent calls; zero skips. |
| Raw scalar admission ABI | 158,100 returned and verified calls, including full-width count boundaries, 8,192 concurrent calls, and all three outcomes; zero skips. |
| Scalar artifact admission | 119 checks of profile, source, exact wrapper, object, archive, symbol and negative mutations; zero skips. |
| Original Rust public matcher | 49,938 comparisons across seven tests; zero skips. The complete original prefix types and methods remain token-pinned and compiled independently. |
| Complete original execpolicy crate | 34/34 native-feature tests and 34/34 default-feature tests passed. |
| Relocated standalone execpolicy | 30 cases, 60 actual native/reference processes; raw output, errors and exit status agree. Both prefix symbols are retained and no HIA shared dependency is required. |
| Public allocation regressions | 11 cases, five allocation-free early no-match calls, plus positive alloc/realloc counter probes; zero skips. |
| Build receipts | 64 checks, retaining all eleven existing borrowed modules and admitting the scalar module. |
| Existing component regression gates | All 15 non-Cargo component scripts passed; current ASCII JSON and UUID public differentials also passed with 27,075 and 26,808 comparisons. |
| Owner checks and formatting | Native/default execpolicy Clippy with `-D warnings`, `just fix`, `just fmt` and diff checks passed. |

These recorded results qualify the V3 local components and standalone caller.
That local run did not execute the complete V3 full Codex CLI, Core suite or
workspace. The allocation runner counts calling-thread Rust allocator effects;
it has no independent subprocess timeout, and artifact provenance is bound
by the preceding receipt and scalar-admission gates. The original failed
owner preflight, where `just` was missing before Cargo execution, and the
allocation report before the review fix are preserved outside the source
tree. Successful reruns are recorded with their own source and report hashes.

At that V3 local checkpoint, full CLI/Core/workspace, required platforms,
performance, default-release and complete owner gates remained open. Historical
ten-module workspace and published V2 CI results below could not substitute
for those source-specific gates. The current stack pending gates are stated above.
Active Rust implementations remain necessary until their replacements meet
the retirement requirements.

#### Published V3 native CI

At exact V3 head `98429434a266d2165e9d3b4d6f1894bd77916917`, push
[43675407031](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43675407031)
and PR
[43675410486](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43675410486)
both passed all 41 steps. The PR checkout
`f9d89a9575d1b2f9b171c24b994043183b49b83c` has the same Git tree. Actual
checkout identities, report bindings, both ZIP digests and all 132 extracted
report/log files were verified.

Each run passed scalar 158,100 calls, 119 artifact checks, 64 receipt checks,
49,938 original-public comparisons, 5,937 raw-prefix calls and 11 allocation
cases with five zero-allocation calls. Each installed standalone run passed
30 cases / 60 processes; each full installed Codex run passed 34 cases and
two startup cases with all 10 required symbols and no HIA shared dependency.
Native/default owner suites passed 198/185 tests with no skips. CLI/arg0/TUI
passed 4,474 tests with six reported skips. Core passed 11 selected exec-policy
tests, with 3,870 excluded by the explicit filter; this was not the full Core
suite.

The two CI runs agree on all 12 module identities and reported executable
hashes. Local and CI source/Core/object/text/archive hashes agree, but their
linked shared-library hashes differ and remain recorded separately. The ZIPs
contain reports and logs, not compiled binaries. Architecture passed within
its source and same-tree-reuse scopes; the V8 canary ran metadata only, with
build jobs skipped. Broader CI still has actual platform/linking/test failures.
All seven prefix timing rows were slower than Rust in both native CI runs.

Exact identities and limits are in
[`published_v3_ci_history`](verification.json#published_v3_ci_history). These
results belong to the V3 adapter and do not qualify the current stack-frame
adapter, complete Core/workspace, all platforms, performance or retirement.

#### Recorded V3 prefix performance remains open

Native word operations reduce the matcher overhead, and HIA scalar admission
removes full-pattern allocation and copying for empty or too-short commands.
The measured region still includes the real production adapter and result
construction. The following values are total nanoseconds for the stated
iteration count, compared in one process against the original Rust matcher:

| Scenario | Iterations | HIA native total (ns) | Original Rust total (ns) |
| -------- | ---------- | --------------------- | ------------------------ |
| Short match | 10,000 | 3,136,578 | 254,901 |
| First-token mismatch | 10,000 | 2,102,015 | 59,697 |
| Many alternatives | 1,000 | 3,233,395 | 85,417 |
| Large matching token | 3 | 4,152,731 | 174,804 |
| Large pattern, empty command | 3 | 300 | 90 |
| Large pattern, short command | 3 | 60 | 40 |
| First-token mismatch with large alternatives | 3 | 89,837 | 80 |

All seven native measurements remain slower than Rust. Three-call timings
are bounded observations, not a performance-equivalence result. Count-admitted
first-token mismatches still copy and validate the full pattern. Performance
qualification remains false.

#### Preserved V1 and V2 negative performance evidence

V2 used HIA-only eight-byte loop unrolling with the fixed `f33d8da`
compiler's byte-load instructions. Its recorded measurements remain:

| Scenario | Timing basis | HIA native | Original Rust |
| -------- | ------------ | ---------- | ------------- |
| Short match | Per-call average | 469 ns | 24 ns |
| First-token mismatch | Per-call average | 291 ns | 5.86 ns |
| Many alternatives | Per-call average | 5,623 ns | 78.7 ns |
| Large matching token | Three-call total | 11.46 ms | 0.204 ms |
| Large pattern, empty command | Three-call total | 82.4 us | 70 ns |
| Large pattern, short command | Three-call total | 85.0 us | 40 ns |
| First-token mismatch with large alternatives | Three-call total | 85.0 us | 100 ns |

The earlier V1 measurements, approximately 37–155 times the Rust cost, are
also retained in `verification.json`. V2 improved its four original scenarios
by approximately 2.1–2.4 times but still copied the complete pattern before
HIA could reject an empty or short command. Neither those improvements nor
the current measurements close performance, default dispatch or retirement.

### Historical published V2 CI

At published source `be38c8b47a4955f7c7e453a570a688b07b1ad540`, both
[native push CI](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43669031066)
and [native PR CI](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43669081862)
completed successfully, with 39 successful steps each. The PR checkout was
the same-tree prospective merge. The
[architecture run](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43669081861)
also passed. These runs used the `f33d8da` compiler and eleven modules.

Each native run recorded 34 installed full-CLI cases plus two startup cases
with nine required HIA symbols, 198 native and 185 default component tests,
4,474 CLI/arg0/TUI tests with six skips, and 11 Core exec-policy tests with
3,870 tests excluded by the explicit filter. The filtered Core result is not
the complete Core suite. Artifact ZIP and manifest digests and scope details are retained in
`verification.json`; its referenced evidence report records the 60 report/log
file hashes per run.

The separate [required CI run](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43669081867)
finished with 37 jobs: 17 successful, 16 failed and four skipped. Fourteen
substantive failures covered SDK/release linking, remote test execution,
macOS execution paths and actual tests, and Windows tests/analysis; the
remaining two failures were required aggregates. No independent base
comparison established that all these failures were pre-existing or caused
by the prefix changes. The published V2 record does not qualify the current
compiler, scalar helper, whole workspace or required platforms.

### Historical ten-module validation

The earlier ten-module B3 build and the listed integration gates passed on Linux
x86-64 GNU with Rust 1.96.1. Exact inputs, commands, artifact identities and
raw-report hashes are recorded in [`verification.json`](verification.json).

| Scope                       | Observed result                                                                                                                                                                                                          |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Patch matching              | 2,327 valid cases, 86 invalid cases and 135 buffer-boundary calls against the actual Rust source.                                                                                                                        |
| Full UTF-8 validation       | 75,109 native calls, 2,093 original Rust comparisons and 56 Core VM comparisons.                                                                                                                                         |
| Production string prefix    | 5 tests, 18,559 Rust comparisons and 2,048 allocation-free calls.                                                                                                                                                        |
| Metric tags                 | 6 tests, 40,992 Rust comparisons and 10,535 ABI calls.                                                                                                                                                                   |
| Markdown locations          | 7 tests, 164,791 comparisons and 1,289 ABI calls, including 523 error/no-write cases.                                                                                                                                    |
| ASCII JSON fragments        | 7 tests, 27,075 comparisons through the full string crate and 957 ABI calls, including 659 error/no-write cases.                                                                                                         |
| UUID public API             | 6 tests, 26,808 comparisons through the full string crate and 34,861 ABI calls, including 259 error/no-write cases. No repository production caller is claimed.                                                          |
| Template parser             | 7 tests, 2,334,492 parse comparisons and 78 render comparisons; 962 ABI calls, including 373 error/no-write cases.                                                                                                       |
| Template render policy      | 5 tests, 1,161,985 comparisons, including 120 iterator/AsRef/Drop/unwind cases; 457 ABI calls, including 390 error/no-write cases.                                                                                       |
| Template placeholders/index | 6 public API tests and 2,029 comparisons; 609,200 ABI calls, including 238 error/no-write cases, 21 checked AVL trees and real offsets above `u32::MAX`.                                                                 |
| Combined owner crates       | `apply-patch`, `utils/string` and `utils/template`: 164 native-feature tests and 151 default-feature tests passed, with zero skipped. Both modes passed strict Clippy.                                                   |
| Build receipts              | 60 admission/mutation checks passed across all ten modules.                                                                                                                                                              |
| Native product consumers    | CLI, arg0, TUI, Core and login: 8,540 executed tests passed; 15 existing skips are not counted as qualified. The listed consumer lint gate passed.                                                                       |
| Full CLI installation       | Native and default full binaries built; eight production-path symbols were retained only in the native binary, with no HIA dynamic dependencies. Two relocated startup checks and four 2 MiB patch parity checks passed. |
| Full default workspace      | 19,383/19,383 passed, 53 existing skips and 7 slow tests. One test passed after the existing retry policy; this is not a no-retry result. All workspace binaries also built.                                             |

The final source follow-up also passed 3,966 default TUI/Linux-sandbox tests
and 3,815 native TUI tests, with six existing skips in each gate, both strict
lint gates, the Cargo/Bazel lock checks, and rebuilt native/default CLI
installation checks. The test source snapshot is
`575813eb6545264769276bd69b8e7ac957ae6d1be0c9b86adebf4b744c0d1dd5`;
its 9,959 recorded paths stayed unchanged during those gates. The four HIA
documentation files and three later CI changes are identified separately in
`verification.json`; the workspace result does not claim to execute those CI
changes. Earlier disk-capacity and path-fixture failures are superseded by
this completed run, not counted as successful attempts.

B1, B2 and B3 reproduce identical compiler bytes. The six previously verified
components retain exactly the same source, Core, shared-library and static
archive identities. Their existing behavior reports keep their original
Rust/adapter inputs and report hashes; they are not represented as fresh
executions in this combined gate. Current owner tests, new component oracles
and the source reconciliation are recorded separately.

The installed CLI check establishes symbol retention, relocated startup and
patch behavior. It does not execute every linked algorithm. Product tests and
installation do not establish whole-product HIA ownership, default native
release dispatch or cross-platform qualification.

Windows work is recorded separately. On diagnostic revision
`b10e6d45d05083a5cdf2f017e514940ee55a7fe5`, the durable/signature owner passed
360/360 tests (one existing skip) and the private-filesystem owner passed
16/16. The sandbox owner remains open: 189 executed, 180 passed, nine failed
and two existing skips. Those branch-specific results are not counted as
qualification of this main source or of native HIA dispatch on Windows.

### Template performance remains open

The recorded ten-module template sources were compared in one process, timing only
`Template::render` after both templates had been parsed. Result equality passed
for every measurement. At 50,000 keys the native path remains substantially
slower:

| Input order | Original Rust | HIA native |
| ----------- | ------------- | ---------- |
| Ascending   | 0.018576 s    | 0.561493 s |
| Descending  | 0.014146 s    | 0.579106 s |
| Shuffled    | 0.020962 s    | 0.579079 s |

All measured sizes and their source/report identities are in
`verification.json` under `template_performance`. These timings do not close
performance equivalence, default dispatch or retirement requirements.

## Remaining implementation map

The fixed Codex baseline is
`732e934ba496d90fbe042b8d41d479ef901643e5`, whose root tree is
`75dc1c1f65375c97da259d947c465a04f030461d`. Its tree contains 8,665 tracked
file blobs, 4,404 Rust files under `codex-rs/`, 198 Cargo manifests under that
directory, and no `.hia` or `.hepta` files. The repository has 4,429 Rust files
in total.

These are structural inventory counts. They include tests, fixtures, examples
and supporting code. In particular, the 198 manifests include the workspace
manifest and nested fixture manifests; that number is not the number of
workspace member crates. `migration.json` lists all 198 paths and assigns each
of the 4,404 Rust files to its nearest ancestor manifest exactly once. The
pinned Git tree is the complete source-path inventory.

| Capability                  | Current owners                                                                         | Required next implementation                                                                                                                                                                                                                                              |
| --------------------------- | -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Model transport             | `codex-api`, `codex-client`, `http-client`, `websocket-client`, provider crates        | HTTP/TLS, SSE/WebSocket events, retry, cancellation and provider request behavior.                                                                                                                                                                                        |
| Authentication and identity | `login`, `keyring-store`, `secrets`, `aws-auth`, `workload-identity`, `agent-identity` | Login, refresh, storage, redaction and platform identity interfaces.                                                                                                                                                                                                      |
| Threads and turns           | `core`, `core-api`, `protocol`, `thread-store`                                         | Turn state, ordered events, incremental context and concurrent ownership.                                                                                                                                                                                                 |
| History and recovery        | `state`, `history`, `message-history`, `rollout`, `thread-store`                       | Existing session/database formats, atomic persistence, resume and crash recovery.                                                                                                                                                                                         |
| Tools, processes and files  | `tools`, `exec`, `exec-server`, `shell-command`, `file-system`, code-mode crates       | Tool execution, PTY/pipes, process groups, cancellation and owned file effects.                                                                                                                                                                                           |
| Permissions and sandboxing  | `execpolicy`, `sandboxing`, platform sandboxes, `network-proxy`, `bwrap` | Prefix matching/scalar admission, RuleMatch reduction, network-domain reduction and allowed-prefix rendering/order/dedup are opt-in HIA algorithms. Whole Policy/Core/platform sandbox ownership, current full CLI/Protocol/Core qualification and performance remain open. |
| MCP                         | `codex-mcp`, `rmcp-client`, `mcp-server`                                               | Initialization, catalogs, calls, notifications, cancellation and transports.                                                                                                                                                                                              |
| App Server v2               | `app-server`, protocol/transport/client/daemon crates                                  | Public JSON-RPC behavior, schemas, events and mixed app/exec host configurations.                                                                                                                                                                                         |
| CLI and TUI                 | `cli`, `tui`, `arg0`, terminal utilities                                               | Flags, exit status, terminal event/rendering paths and existing snapshots.                                                                                                                                                                                                |
| SDK and frontends           | `sdk/`, `codex-cli/`, `apps/`                                                          | Public client interfaces, frontend lifecycle and packaging.                                                                                                                                                                                                               |
| Patch application           | `apply-patch`, `file-search`                                                           | Matching is connected behind `hia-native`; parser and file-update owners still need migration.                                                                                                                                                                            |
| String utilities            | `utils/string`                                                                         | Prefix selection, metric tags, Markdown location suffixes and JSON string fragments are connected behind `hia-native`; UUID matching is verified as a public API without a production caller; middle truncation and complete owner/default/platform qualification remain. |
| Hepta cells and adapters    | `hepta-*` crates                                                                       | Existing cell, Agentd, Codex adapter, identity, recovery and learning/adoption boundaries.                                                                                                                                                                                |
| Platforms and release       | Linux/macOS/Windows integrations, build and release paths                              | Supported architectures, packages, clean installation and end-to-end platform tests.                                                                                                                                                                                      |
| HIA toolchain               | The pinned Hepta compiler and runtime                                                  | Required host interfaces, broader platform support and complete compiler/runtime ownership.                                                                                                                                                                               |

All 15 complete capability migrations remain pending. The earlier eight
connected components, the prefix matcher and its scalar helper, pure RuleMatch
reduction, ordered network-domain reduction and allowed-prefix collection advance individual algorithms;
the helper does not add another complete owner.
Their complete Rust owners and default release dispatch have not been migrated.
Login template algorithms are connected, while login and credential ownership
remain separate work.

The search implementation preserves the original four-pass search complexity.
Long repeated context can require quadratic work. Large-input compatibility
does not establish an execution deadline. A future cancellable matcher must
propagate interruption distinctly from a genuine no-match result.

## Retiring superseded files

Retire an old implementation after its HIA replacement owns the actual call
path and passes the original behavior tests, API/session compatibility checks,
required platform tests and clean-install end-to-end workflow. Then remove
unused source, dependency declarations, build rules and process artifacts in
the same verified change, retaining the tests, licensing and release assets
needed by the final version.

The native-feature production patch matcher excludes the original Rust search
function; tests and the default platform path still retain it. Global deletion
requires the remaining default-release and platform gates. The wider capability
map determines the rest of the repository cleanup.

## Build and test the production callers

After the native build above, select the verified static artifacts:

```bash
export CODEX_HIA_NATIVE_LIB_DIR="$native_output"

python3 -B hia/tests/test_build_receipt.py --artifacts "$native_output" --report "$build_parent/receipt-tests.json"
python3 -B hia/tests/test_native_string_caller.py --library-dir "$native_output" --rustc "$rustc_binary" --report "$build_parent/string-caller-tests.json"
python3 -B hia/tests/test_native_metric_caller.py --library-dir "$native_output" --rustc "$rustc_binary" --report "$build_parent/metric-caller-tests.json"
python3 -B hia/tests/test_metric_tag_abi.py --library-dir "$native_output" --report "$build_parent/metric-abi-tests.json"
python3 -B hia/tests/test_native_markdown_caller.py --library-dir "$native_output" --rustc "$rustc_binary" --report "$build_parent/markdown-caller-tests.json"
python3 -B hia/tests/test_markdown_location_abi.py --library-dir "$native_output" --report "$build_parent/markdown-abi-tests.json"
python3 -B hia/tests/test_native_ascii_json_caller.py --library-dir "$native_output" --rustc "$rustc_binary" --report "$build_parent/ascii-json-caller-tests.json"
python3 -B hia/tests/test_ascii_json_abi.py --library-dir "$native_output" --report "$build_parent/ascii-json-abi-tests.json"
python3 -B hia/tests/test_native_uuid_caller.py --library-dir "$native_output" --rustc "$rustc_binary" --report "$build_parent/uuid-caller-tests.json"
python3 -B hia/tests/test_uuid_abi.py --library-dir "$native_output" --report "$build_parent/uuid-abi-tests.json"
python3 -B hia/tests/test_native_template_parser.py --library-dir "$native_output" --rustc "$rustc_binary" --report "$build_parent/template-parser-tests.json"
python3 -B hia/tests/test_native_template_parser.py --library-dir "$native_output" --rustc "$rustc_binary" --harness hia/tests/native_template_render.rs --report "$build_parent/template-render-tests.json"
python3 -B hia/tests/test_native_template_parser.py --library-dir "$native_output" --rustc "$rustc_binary" --harness hia/tests/native_template_placeholders.rs --report "$build_parent/template-placeholder-tests.json"
python3 -B hia/tests/test_template_parser_abi.py --library "$native_output/libcodex_hia_template_parser.so" --report "$build_parent/template-parser-abi.json"
python3 -B hia/tests/test_template_render_abi.py --library "$native_output/libcodex_hia_template_render.so" --report "$build_parent/template-render-abi.json"
python3 -B hia/tests/test_template_index_abi.py --library "$native_output/libcodex_hia_template_index.so" --report "$build_parent/template-index-abi.json"
python3 -B hia/tests/test_prefix_match_abi.py --library "$native_output/prefix_match.so" --report "$build_parent/prefix-match-abi.json"
python3 -B hia/tests/test_prefix_admission_abi.py --library "$native_output/prefix_admission.so" --report "$build_parent/prefix-admission-abi.json"
python3 -B hia/tests/test_scalar_build_admission.py --artifacts "$native_output" --module prefix_admission --report "$build_parent/prefix-scalar-admission.json"
python3 -B hia/tests/test_native_execpolicy_caller.py --library-dir "$native_output" --rustc "$rustc_binary" --report "$build_parent/prefix-caller-tests.json"
python3 -B hia/tests/test_native_execpolicy_allocations.py --library-dir "$native_output" --rustc "$rustc_binary" --report "$build_parent/prefix-allocations.json"
python3 -B hia/tests/test_policy_summary_abi.py --library "$native_output/policy_summary.so" --report "$build_parent/policy-summary-abi.json"
python3 -B hia/tests/test_native_policy_summary.py --library-dir "$native_output" --rustc "$rustc_binary" --target-dir "$build_parent/policy-summary-target" --report "$build_parent/policy-summary-public.json"
python3 -B hia/tests/test_network_domains_abi.py --library "$native_output/network_domains.so" --report "$build_parent/network-domains-abi.json"
python3 -B hia/tests/test_native_network_domains.py --library-dir "$native_output" --rustc "$rustc_binary" --target-dir "$build_parent/network-domains-target" --report "$build_parent/network-domains-public.json"
python3 -B hia/tests/test_allowed_prefixes_abi.py --library "$native_output/allowed_prefixes.so" --report "$build_parent/allowed-prefixes-abi.json"
python3 -B hia/tests/test_native_allowed_prefixes.py --library-dir "$native_output" --rustc "$rustc_binary" --target-dir "$build_parent/allowed-prefixes-target" --report "$build_parent/allowed-prefixes-public.json"

"$rustc_binary" --edition=2024 --test --cfg 'feature="hia-native"' hia/tests/native_patch_caller.rs -L "native=$native_output" -l static=codex_hia_seek_sequence -o "$build_parent/patch-caller-tests"
"$build_parent/patch-caller-tests"

cd codex-rs
just test -p codex-apply-patch -p codex-utils-string -p codex-utils-template -p codex-execpolicy --features hia-native --locked

cargo build --locked -p codex-execpolicy --features hia-native --bin codex-execpolicy
cp "${CARGO_TARGET_DIR:-target}/debug/codex-execpolicy" "$build_parent/hia-execpolicy"
cargo build --locked -p codex-execpolicy --bin codex-execpolicy
python3 -B ../hia/tests/test_installed_execpolicy.py \
  --binary "$build_parent/hia-execpolicy" \
  --reference-binary "${CARGO_TARGET_DIR:-target}/debug/codex-execpolicy" \
  --report "$build_parent/installed-execpolicy.json"

cargo build --locked -p codex-apply-patch --features hia-native --bin apply_patch
cp "${CARGO_TARGET_DIR:-target}/debug/apply_patch" "$build_parent/hia-apply_patch"
cargo build --locked -p codex-apply-patch --bin apply_patch
python3 -B ../hia/tests/test_installed_patch.py \
  --binary "$build_parent/hia-apply_patch" \
  --reference-binary "${CARGO_TARGET_DIR:-target}/debug/apply_patch" \
  --report "$build_parent/installed-patch.json"

# Preserve both full binaries before changing the feature selection.
cargo build --locked -p codex-cli --features hia-native --bin codex
cp "${CARGO_TARGET_DIR:-target}/debug/codex" "$build_parent/hia-codex"
cargo build --locked -p codex-cli --bin codex
python3 -B ../hia/tests/test_installed_codex.py \
  --binary "$build_parent/hia-codex" \
  --reference-binary "${CARGO_TARGET_DIR:-target}/debug/codex" \
  --report "$build_parent/installed-codex.json"
```

The static callers need no HIA shared-library directory at runtime. Build-time
artifact mismatches are errors; selecting `hia-native` on an unsupported target
is also an error. With the feature disabled the build helper performs no HIA
source or artifact reads, so existing platform builds need no HIA toolchain.

The production gates cover exact source oracles, multi-megabyte files and
strings, large offset tables, both patch line-ending modes, EOF/start semantics,
allocation-free string calls, concurrent calls, and actual crate integration
tests. Receipt tests use real artifacts and reject changed sources, compiler
images, reports, symbols and archive members.

The installed-executable gate copies the HIA binary into a separate temporary
directory and runs it without the native build directory or dynamic-library
search override. It compares complete output files and CLI results with a
default-feature Rust executable. The normal line-ending mode preserves the
original behavior of untouched CRLF lines while writing LF replacement lines;
the preserving mode retains CRLF throughout. Sandbox settings are inherited.

The `Codex HIA native components` workflow runs these gates against the checked
out revision. Build products and logs stay outside the repository.
