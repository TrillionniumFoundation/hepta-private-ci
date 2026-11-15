# Codex in HIA

This directory contains twelve native HIA modules compiled with
[`TrillionniumFoundation/Hepta`](https://github.com/TrillionniumFoundation/Hepta)
at `0de5657a80f96b138525ac7ee9ce11712a83a10d`: eleven borrowed-buffer
entries and one scalar count-admission entry. Their algorithms execute as
machine code compiled from the checked-in `.hepta` sources.

The opt-in `hia-native` Cargo feature connects the earlier eight components to
existing production paths on Linux x86-64 GNU: patch matching, four string
operations, and template parsing, rendering and ordered indexing. The prefix
matcher and its scalar admission helper reach production callers through
`codex-execpolicy/hia-native`. The current compiler's complete execpolicy
crate and installed standalone caller are qualified locally; its full Codex
CLI, Core and workspace gates remain pending. Published V2 native CI passed
with the earlier compiler and is recorded separately below. Rust retains
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
owners. Template and prefix-matcher performance equivalence, complete owner
migration, default native releases and other platforms remain open:

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
entry before frame sizing, copying or allocation, then frames admitted objects
and clones the selected command prefix after a match. HIA owns count
admission, token and alternative comparisons, and the match decision. Existing decision precedence,
rule order, justifications, resolved-program metadata, parser behavior and
unmatched-command heuristics remain with their original owners. A native
error fails the call; it must not become `None` and activate those heuristics.

The full-input UTF-8 validator rejects overlong encodings, surrogates, values
above U+10FFFF, lone continuations and truncation, including invalid bytes
beyond the requested prefix. The production prefix and metric callers accept
already-valid Rust strings. JSON fragments and template parsing perform their
own incremental validation within their documented framing contracts.

### Native buffer interface

The eleven borrowed-buffer modules expose this HIA signature:

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
| `0xffffffff`                                          | Invalid frame/state; also invalid UTF-8 for the original matching/validation entries. |
| `0xfffffffe`                                          | Insufficient output or workspace capacity.                                            |
| `0xfffffffd`                                          | Invalid location format, or invalid UTF-8 in the JSON fragment encoder.               |

Caller allocations must stay live for the call and mutable ranges must be
disjoint. The direct seed wrapper and bootstrap compiler profile have a
1,048,576-byte capacity. The production B3 ELF entry receives the actual live
buffer extent; that compiler capacity is not a maximum file size. The patch
adapter checks all length arithmetic and uses fallible allocation. All modules
leave the source unchanged. The patch, UTF-8 and prefix-matching modules leave
workspace unchanged, reserve it for future use and accept length zero. Their successful
calls preserve output bytes beyond the result length. The metric module uses
its workspace and output buffer as streaming state, as described below.
Returned errors leave the current call's output and workspace unchanged.
Earlier successful streaming calls and external writer effects remain committed.

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

### Prefix matcher: current local qualification

The current twelve-module B1/B2/B3 build passed with Hepta
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

These results qualify the current local components and standalone caller.
They do not execute the complete new-compiler full Codex CLI, Core suite or
workspace. The allocation runner counts calling-thread Rust allocator effects;
it has no independent subprocess timeout, and artifact provenance is bound
by the preceding receipt and scalar-admission gates. The original failed
owner preflight, where `just` was missing before Cargo execution, and the
allocation report before the review fix are preserved outside the source
tree. Successful reruns are recorded with their own source and report hashes.

New-compiler full CLI/Core/workspace, required platforms, performance,
default-release and complete owner gates remain open. Historical ten-module
workspace and published V2 CI results below cannot substitute for them.
Active Rust implementations remain necessary until their replacements meet
the retirement requirements.

#### Current prefix performance remains open

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
| Permissions and sandboxing  | `execpolicy`, `sandboxing`, platform sandboxes, `network-proxy`, `bwrap`               | Prefix matching and scalar count admission have opt-in HIA owners with current local standalone qualification; new-compiler full CLI/Core/workspace, complete policy/default/platform integration and isolation remain.                                                                                                   |
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
connected components, the prefix matcher and its scalar helper advance
individual algorithms; the helper does not add another complete owner.
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
