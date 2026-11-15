# Codex in HIA

This directory contains HIA implementations of Codex's patch-line matching,
UTF-8 prefix selection, metric-tag sanitizing, Markdown location suffix
normalization, ASCII JSON string-fragment encoding, middle truncation and token
arithmetic, and the complete SourceFile text-state owner. The compiler is
pinned to [`TrillionniumFoundation/Hepta`](https://github.com/TrillionniumFoundation/Hepta)
at `0de5657a80f96b138525ac7ee9ce11712a83a10d`. These algorithms execute as
native machine code compiled from `.hepta` source.

The current build contains 9 HIA modules for 7 production algorithm groups.
Token arithmetic uses a separate typed scalar entry, and character counting
uses checked unaligned 64-bit reads. These changes optimize the existing five
truncation APIs. SourceFile adds the complete `parse`, `line_texts`,
`apply_replacements` and `into_contents` owner behind the existing preserving-mode
patch-update caller.
The `hia-native` Cargo feature connects these routines to HIA machine code on
Linux x86-64 GNU. Rust adapters frame borrowed inputs, check native results
and preserve the surrounding public interfaces. Static
archives are verified at build time and incorporated into the caller binary.
The full-input UTF-8 validation module is a separately tested diagnostic
component; the production prefix caller uses the constant-size entry.

The feature remains opt-in. Other owners listed in
[`migration.json`](migration.json), other platforms, and the default release
dispatch still need migration. The whole-product state is therefore:

```json
{
  "production_dispatch_migrated": false,
  "whole_codex_rewritten": false,
  "retirement": { "ready": false }
}
```

## Implemented components

| HIA module                                               | Original source/function                                                            | Behavior implemented                                                                                                                                                                                                |
| -------------------------------------------------------- | ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [`seek_sequence.hepta`](seek_sequence.hepta)             | [`seek_sequence`](../codex-rs/apply-patch/src/seek_sequence.rs)                     | Exact, trailing-whitespace, trimmed and Unicode punctuation matching; original pass precedence, first match, empty patterns, start bounds, EOF behavior and both line-ending modes.                                 |
| [`utf8_boundaries.hepta`](utf8_boundaries.hepta)         | [`take_bytes_at_char_boundary`](../codex-rs/utils/string/src/lib.rs)                | The largest complete UTF-8 prefix within a byte budget, plus complete validation of the incoming UTF-8 bytes.                                                                                                       |
| [`utf8_prefix.hepta`](utf8_prefix.hepta)                 | The public string-prefix caller                                                     | Constant-size boundary selection for an already-valid Rust `&str`, preserving borrowing and allocation-free calls for arbitrarily large strings.                                                                    |
| [`metric_tag.hepta`](metric_tag.hepta)                   | [`sanitize_metric_tag_value`](../codex-rs/utils/string/src/lib.rs)                  | ASCII character filtering, one replacement per disallowed Unicode scalar, trimming, the original empty/default decision and 256-byte output limit; bounded streaming state accepts arbitrarily large valid strings. |
| [`markdown_location.hepta`](markdown_location.hepta)     | [`normalize_markdown_hash_location_suffix`](../codex-rs/utils/string/src/lib.rs)    | Streaming location grammar, the first range separator and first column separator per endpoint; original empty/nonnumeric acceptance and byte preservation.                                                          |
| [`ascii_json_fragment.hepta`](ascii_json_fragment.hepta) | [`AsciiJsonFormatter::write_string_fragment`](../codex-rs/utils/string/src/json.rs) | ASCII preservation and lowercase Unicode escapes, including surrogate pairs, with canonical UTF-8 validation and bounded borrowed windows. Serde still owns the surrounding JSON format.                            |
| [`truncate.hepta`](truncate.hepta) | [`truncate.rs`](../codex-rs/utils/string/src/truncate.rs) | UTF-8 middle truncation, removed Unicode-scalar counts and token markers; strict byte and trusted string entries. |
| [`token_budget.hepta`](token_budget.hepta) | The three public token/byte arithmetic helpers | Full-width saturating arithmetic through a typed `u64, u64 -> u64` native entry, without buffer framing. |
| [`source_file.hepta`](source_file.hepta) | [`SourceFile`](../codex-rs/apply-patch/src/text_file.rs) | Parse, line-text projection, ordered replacements and final contents; mixed endings, persistent preferred style, repeated edits and logical inserted lines. |

The truncation APIs are `truncate_middle_chars`,
`truncate_middle_with_token_budget`, `approx_token_count`,
`approx_bytes_for_tokens` and `approx_tokens_from_byte_count`.

The UTF-8 input checks reject overlong encodings, surrogate encodings, values
above U+10FFFF, lone continuation bytes and truncated sequences. They scan the
entire input before publishing a result, including bytes beyond the requested
prefix. These full-input checks belong to `utf8_boundaries` and strict truncation
operations 0/1, and every SourceFile operation; the production prefix and metric callers accept already-valid
Rust strings. The JSON fragment
encoder performs its own incremental validation. All listed component algorithms
are implemented in HIA; the surrounding Rust owners remain tracked separately.

### Native buffer interface

The eight buffer components expose this HIA signature:

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
| `40` for `truncate`                                  | Five little-endian `u64` result fields.                                                |
| `0` for `source_file` | A complete 40-byte query header or the complete emitted span plan; see its operation-specific contract below. |
| `0xffffffff`                                          | Invalid frame/state; also invalid UTF-8 for the original matching/validation entries. |
| `0xfffffffe`                                          | Insufficient output or workspace capacity.                                            |
| `0xfffffffd`                                          | Invalid location format, or invalid UTF-8 in JSON fragments, strict truncation or SourceFile.      |

Caller allocations must stay live for the call and mutable ranges must be
disjoint. The direct seed wrapper and bootstrap compiler profile have a
1,048,576-byte capacity. The production B3 ELF entry receives the actual live
buffer extent; that compiler capacity is not a maximum file size. The patch
adapter checks all length arithmetic and uses fallible allocation. All modules
leave the source unchanged. The matching and UTF-8 modules leave workspace
unchanged, reserve it for future use and accept length zero. Their successful
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

`truncate` exports `codex_hia_truncate`. It borrows the complete source without
a 1 MiB limit, requires 40 output bytes, and reads a 16-byte workspace containing
little-endian `u64 [operation, budget]`. The workspace is read-only, including
on success; unaligned buffers and extra capacity are supported.

| Operation | Input and budget contract |
| --- | --- |
| `0` / `1` | Arbitrary bytes, fully validated as canonical UTF-8; character markers with a byte budget, or token markers with a token budget. |
| `2` / `3` | Empty source; saturating tokens-to-bytes or bytes-to-tokens arithmetic. |
| `4` / `5` | Same truncation results as `0` / `1` for valid UTF-8 supplied by Rust `&str`. These entries rely on that precondition and do not validate arbitrary bytes. |

The truncation result is `[prefix_end, suffix_start, removed_units,
original_tokens, kind]`, where kind is unchanged (`0`), character marker (`1`)
or token marker (`2`). Scalar operations return `[value, 0, 0, 0, 0]`.
Capacity checks precede operation checks and strict UTF-8 validation. Unknown
operations and nonempty scalar inputs return `0xffffffff`; short buffers return
`0xfffffffe`; invalid UTF-8 on operations 0/1 returns `0xfffffffd`. Errors write
nothing, and successful calls preserve bytes beyond the 40-byte result.
Markers do not consume the prefix/suffix budget. Character markers count Unicode
scalars; token markers use the original byte-budget arithmetic. Saturation and
the original `None` result when rendered text equals the input are preserved.

### SourceFile owner and buffer interface

`source_file` exports `codex_hia_source_file`. Its four operations own
parsing, preferred endings, replacement selection and output order. The Rust
adapter owns one text backing, frames requests, checks native-selected spans
and compacts retained text after edits. It does not parse lines, choose
replacements or render and reparse intermediate state.

The exact ABI is [`source_file_buffer_contract.json`](source_file_buffer_contract.json).
All fields are little-endian `u64`. The read-only workspace starts with a
64-byte header `[operation, pool_count, line_count, replacement_count,
inserted_count, preferred_ending, parse_text_id, reserved_zero]`, followed by
pool lengths, 32-byte old-line records, 24-byte replacement triples and
inserted text IDs. Its length must match these tables exactly.

| Operation | Query / emit |
| --- | --- |
| `0` / `1` | Parse original contents into logical lines. |
| `2` / `3` | Apply ordered replacements to existing logical lines. |
| `4` / `5` | Project each logical line's text. |
| `6` / `7` | Select text and ending spans for final contents. |

Parsing borrows the original contents as text pool 3; its four declared pool
lengths are `[1, 2, 1, source.len]`. Other operations borrow the concatenation
of all declared pool strings. Pool IDs 0/1/2 are fixed LF/CRLF/CR, and every
actual text ID is at least 3. HIA validates the complete source as canonical
UTF-8 and checks pool and subspan boundaries. Ending codes are none (`0`),
LF (`1`), CRLF (`2`) and CR (`3`).

Success returns `0`. Every query writes exactly the 40-byte header
`[required_full_plan_bytes, record_count, logical_line_count, total_text_bytes,
preferred_ending]`; emit writes that header and all 32-byte span records.
The byte total includes endings for parse, apply and contents, and excludes
them for line-text projection. Minimum output/workspace capacity checks
precede frame validation, UTF-8 validation, span/count checks and final emit
capacity. Statuses `0xfffffffe`, `0xffffffff` and `0xfffffffd` respectively
mean short capacity, invalid frame/order/range/arithmetic, and malformed
UTF-8. Every returned error leaves source, workspace and output unchanged;
success preserves output beyond its complete header or plan.

The first observed ending selects the preferred style, defaulting to LF.
That style survives total deletion and later insertion. Inserted strings with
internal CR/LF remain one logical line across subsequent edits. Even an empty
replacement list repairs absent endings on surviving lines. Legal
`usize::MAX` skips/deletes consume only the finite remaining line table;
nonmonotonic order and `start + old_length` overflow are separate invalid
preconditions. The surrounding patch grammar, `compute_replacements`,
normalizing update path and filesystem effects remain Rust owners.

### Typed scalar interface

`token_budget` exports `codex_hia_token_budget(value: u64, operation: u64) -> u64`.
Operation `0` computes saturating multiplication by four; operation `1` computes
saturating addition of three followed by division by four. Every other full
64-bit operation value traps before returning. `u64::MAX` remains a valid input
and result, so there is no reserved error sentinel. Rust uses a private typed
operation enum; all three public arithmetic helpers execute this HIA entry.
The original buffer operations 2/3 retain their separate tested ABI.

`toolchain.json` explicitly locks this scalar profile. The builder checks the
assembled entry signature and export, admits the pinned two-argument native
wrapper, and requires its relocation section to be empty. It removes only that
empty section when namespacing the object, then proves `.text` is unchanged.
The shared Cargo admission helper keeps its existing six-section, unique-export,
no-import and exact-source/compiler/archive checks. Unknown profiles and a
buffer entry whose first defined function is not `f0` are rejected.

The character counter uses v9 `buffer.load.u64.le` only after proving at least
eight source bytes remain. The instruction checks the live borrowed extent
and accepts unaligned offsets; the shorter tail retains individual byte reads.
The build preserves each checked source's v8 or v9 schema when requesting ELF
emission. It does not silently reinterpret one schema as another.

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

### Current nine-module SourceFile increment

The formal v9 B1/B2/B3 build and SourceFile qualification ran on Linux x86-64
GNU with Rust 1.96.1. The 9,828-path source snapshot and exact compiled
source/Core/archive identities are recorded in
[`verification.json`](verification.json#source_file_increment). A separate
identity report confirms all 40 compiled artifacts of the eight inherited
modules are unchanged from the published `7fe65ae` checkpoint.

| Current check | Observed result |
| --- | --- |
| Complete original SourceFile | 8 tests; 224,253 original-Rust comparisons; zero skips. The independent rlib includes the complete original 3,851-byte file from `a3f319cf`, bound by SHA256 and Git blob. |
| Separate invalid preconditions | Nonmonotonic ordering and index-addition overflow both fail; no post-panic state or release-overflow equivalence is claimed. |
| Raw SourceFile ABI | 5,631 calls; 4,423 error/no-write cases, 604 query calls, 604 emit calls and 1,024 concurrent native calls. Includes 2.2 MB sources and a 1,120,040-byte plan. |
| Cargo artifact admission | 58 checks with `source_file` as mutation target, including acceptance and source binding for all nine modules. |
| Scalar build admission | 115 checks on this nine-module build; the separate typed scalar profile remains unchanged. |
| Current Cargo / installed executables | Pending the published nine-module workflow; earlier local `rama-net` SIGKILL attempts do not establish a pass. |

The full original-file oracle checks initial and repeated-edit states through
all four actual feature-selected methods. Its coverage includes mixed endings,
all Unicode scalars, owned input/projection storage, embedded newline strings,
total deletion and reinsertion, finite MAX requests, large line tables and
concurrency. The raw ABI gate separately verifies exact frames, UTF-8 and span
boundaries, queries, capacities, canaries and error atomicity.

After those local gates, publication changes are limited to these three HIA
metadata documents and the CI workflow. The workflow adds scoped
`just fix --locked -p codex-apply-patch --features hia-native` and a clean-diff
check after its test/lint steps. Implementation, tests and ABI-contract bytes
remain unchanged. This is not a claim that the final published tree has
already passed Cargo or installed-executable CI.

The bounded public-API benchmark used the genuine development full B3 build
whose SourceFile source, Core and linked artifacts are identical to the
formal build. The recorded binding report verifies the five compiled
SourceFile artifacts and the benchmark input, compiler and executable hashes.
Each of its nine histories used identical Rust optimization,
equal iterations per pair and three alternating samples. All cases stayed
within three seconds. The earlier and optimized runs retain their original
reports and hashes.

| API history | Earlier HIA | Optimized HIA | Original Rust in optimized run | Optimized / Rust |
| --- | ---: | ---: | ---: | ---: |
| 2 MiB single-line roundtrip | 289.83 ms | 10.16 ms | 0.988 ms | 10.28x |
| 2 MiB single-line empty update | 366.07 ms | 13.30 ms | 1.201 ms | 11.07x |
| 786,432-byte ASCII line update | 257.78 ms | 59.69 ms | 2.633 ms | 22.67x |
| 786,432-byte Unicode line update | 419.75 ms | 234.15 ms | 4.656 ms | 50.29x |
| 131,072 short lines, empty update | 524.09 ms | 200.23 ms | 9.140 ms | 21.91x |

The two long-line histories improved by 28.52x and 27.52x between recorded
runs. Small histories retain proportionally larger overhead: the empty
roundtrip takes 2.568 microseconds versus 0.0201 microseconds, or 127.91x.
Across all nine cases the remaining ratio is approximately 10–128x.
`whole_product_performance_qualified` remains `false`.

### Published eight-module checkpoint: 7fe65ae

The following component and string-owner results belong to the eight-module
checkpoint, before SourceFile. The truncation oracle binds all 815 original
production tokens to the source at `a2014bc6bfa1c1c9957edb3f14f8ae7d9ddcc095`.

| Checkpoint check | Observed result |
| --- | --- |
| Original Rust truncation oracle | 7 tests; 229,173 public-API comparisons, including Unicode boundaries, saturation, marker collisions, large inputs and concurrency. |
| Truncation ABI | 2,888 calls; 757 error/no-write cases, 288 strict/trusted plan comparisons and 1,024 concurrent calls. |
| Typed scalar ABI | 74,552 native calls: 74,536 valid results and 16 invalid-operation traps; full-width limits, random values and 16,384 concurrent calls. |
| Scalar build admission | 114 checks covering actual compiler/ELF/source identities, v8/v9 preservation, entry profiles, wrapper shape and rejected mutations. |
| Cargo artifact admission | 56 checks with the original matching module as mutation target, repeated with the scalar module; the shared Cargo helper is unchanged. |
| String owner | 38 native and 26 default tests passed, zero skips; both modes passed strict all-target Clippy. Formatting and scoped fix made no source changes. |
| Unchanged components | All five compiled artifacts for each of the six unchanged buffer modules and the scalar module are byte-identical between the f33 and v9 builds. |
| Development build | The explicit seed-only path built all eight modules; it remains separate from production selfhost qualification. |

The exact published `7fe65ae990187e6ff1130c791f902728b4e50197`
[push workflow](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43653376966)
and [PR workflow](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43653380224)
both completed successfully. They passed 139 native patch/string tests, 319
native truncation-consumer tests, 4,473 native CLI/arg0/TUI tests with six
existing skips, and 444 default owner/consumer tests. The PR run recorded one
flaky retry. Relocated patch and full Codex executable gates also passed.
These are eight-module checkpoint results; they do not qualify the new
nine-module SourceFile owner or whole-product performance.

The bounded optimized public-API benchmark records scalar helpers at 6.24–9.28 ns
versus 0.56–0.88 ns for the original Rust. Approximately 1 MiB character
truncation at budget 512 takes 1.61 ms for ASCII and 2.07 ms for Unicode,
respectively 1.26 and 2.39 times the Rust cost. Character truncation at budget
zero still costs 1.87–3.00 ms, approximately 41–50 times the reference. Small
inputs also retain overhead. Large unchanged token calls were approximately
1.00–1.03 times the Rust cost. All 17 cases used equal per-pair iteration counts,
three alternating samples and identical Rust optimization levels; each case
finished within three seconds. These measurements do not qualify whole-product
performance. Exact source, artifact, raw-output and report identities are in
[`verification.json`](verification.json#native_optimization).

### Published seven-module CI checkpoint: a3f319cf

The [push workflow](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43648398946)
and [PR workflow](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43648457597)
both completed successfully for `a3f319cfba26b3206d9bfecbdefed2515ce4a19c`.
The exact-head push run passed 139 native patch/string tests, 319 native
truncation-consumer tests, 4,473 native CLI/arg0/TUI tests with six existing
skips, and 444 default owner/consumer tests without HIA artifacts. Compiler and
component oracles, receipt checks, actual namespace startup, and relocated
apply_patch/full Codex executable qualification also passed. The full CLI gate
retained the required truncation symbol and checked startup and large patch
behavior; it did not execute every linked algorithm.

This is source-bound evidence for the seven-module checkpoint. It does not
qualify the nine-module SourceFile increment, full workspace, default native
dispatch or other platforms.

### Inherited six-module checkpoint: a2014bc6

The following results belong to published commit
`a2014bc6bfa1c1c9957edb3f14f8ae7d9ddcc095`, with 6 HIA modules and 5 connected
production algorithms. They are historical evidence, not a rerun against the
current nine-module candidate. [`verification.json`](verification.json)
retains the separately scoped source, artifact and report identities.

| Component                          | Observed checks                                                                                                                                                                                                                |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Patch-line matching                | 2,327 valid cases, 86 invalid cases and 135 buffer-boundary calls against the actual Rust source.                                                                                                                              |
| Full UTF-8 validation              | 75,109 native calls, 2,093 original Rust comparisons and 56 Core VM comparisons.                                                                                                                                               |
| Production string prefix           | 5 tests; 18,559 Rust comparisons and 2,048 allocation-free calls, including large inputs and concurrent callers.                                                                                                               |
| Metric tags                        | 6 tests; 40,992 Rust comparisons; 10,535 ABI calls covering streaming state, capacity and finalization.                                                                                                                        |
| Markdown locations                 | 7 tests; 164,791 Rust comparisons; 1,289 ABI calls including 523 error/no-write cases and 170 streams.                                                                                                                         |
| ASCII JSON fragments               | 7 tests; 27,075 comparisons through the actual full string crate; 957 ABI calls including 659 error/no-write cases and 90 streams.                                                                                             |
| Real Cargo callers                 | 135 passed with `hia-native`; 125 passed with default features; zero skipped in both caller runs.                                                                                                                              |
| Build and artifact identity        | 52 receipt/admission checks passed, including all 6 modules, source/compiler mutations, malformed receipts, symbol checks and archive-member checks.                                                                           |
| Native lint gate                   | The listed production caller crates passed strict `cargo clippy --all-targets` with `hia-native` enabled and warnings denied.                                                                                                  |
| Relocated full CLI                 | Help/version and four 2 MiB patch updates matched the default Rust CLI through both patch dispatch paths and line-ending modes. The copied native executable defines all 5 production symbols and needs no HIA shared library. |
| Native Core consumers              | 3,872 executed tests passed; 9 were skipped and are not counted as qualified. Exact commands and log hashes are recorded separately.                                                                                           |
| Native CLI, arg0 and TUI consumers | 4,473 executed tests passed; 6 were skipped and are not counted as qualified. Exact commands and log hashes are recorded separately.                                                                                           |
| Full default Linux workspace       | 19,370 executed tests passed; 53 preexisting skips remain outside qualification. The 301 protocol tests and strict protocol Clippy also passed; source snapshots agree before/after tests and lint/format.                     |

At that checkpoint B1, B2 and B3 reproduced identical compiler bytes. Its
component reports bind their HIA sources, original Rust sources, adapters and tested static archives
to that six-module build. Raw diagnostic and namespaced shared-library identities
are recorded separately; streaming ABI checks use the namespaced entries.

That full CLI check proved symbol retention, relocated startup and patch
behavior for that binary. It does not execute every linked algorithm. The
consumer commands and their exact test summaries are recorded separately
under `product_integration_gates`; neither checkpoint establishes whole-product
HIA ownership, default release dispatch or cross-platform qualification.

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

| Capability                  | Current owners                                                                         | Required next implementation                                                                                                                                                                                     |
| --------------------------- | -------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Model transport             | `codex-api`, `codex-client`, `http-client`, `websocket-client`, provider crates        | HTTP/TLS, SSE/WebSocket events, retry, cancellation and provider request behavior.                                                                                                                               |
| Authentication and identity | `login`, `keyring-store`, `secrets`, `aws-auth`, `workload-identity`, `agent-identity` | Login, refresh, storage, redaction and platform identity interfaces.                                                                                                                                             |
| Threads and turns           | `core`, `core-api`, `protocol`, `thread-store`                                         | Turn state, ordered events, incremental context and concurrent ownership.                                                                                                                                        |
| History and recovery        | `state`, `history`, `message-history`, `rollout`, `thread-store`                       | Existing session/database formats, atomic persistence, resume and crash recovery.                                                                                                                                |
| Tools, processes and files  | `tools`, `exec`, `exec-server`, `shell-command`, `file-system`, code-mode crates       | Tool execution, PTY/pipes, process groups, cancellation and owned file effects.                                                                                                                                  |
| Permissions and sandboxing  | `execpolicy`, `sandboxing`, platform sandboxes, `network-proxy`, `bwrap`               | Existing authorization decisions, isolation and denial behavior on each platform.                                                                                                                                |
| MCP                         | `codex-mcp`, `rmcp-client`, `mcp-server`                                               | Initialization, catalogs, calls, notifications, cancellation and transports.                                                                                                                                     |
| App Server v2               | `app-server`, protocol/transport/client/daemon crates                                  | Public JSON-RPC behavior, schemas, events and mixed app/exec host configurations.                                                                                                                                |
| CLI and TUI                 | `cli`, `tui`, `arg0`, terminal utilities                                               | Flags, exit status, terminal event/rendering paths and existing snapshots.                                                                                                                                       |
| SDK and frontends           | `sdk/`, `codex-cli/`, `apps/`                                                          | Public client interfaces, frontend lifecycle and packaging.                                                                                                                                                      |
| Patch application           | `apply-patch`, `file-search`                                                           | Matching and the complete SourceFile owner are connected behind `hia-native`; patch grammar, replacement planning, normalized updates and filesystem/search effects still need migration.                                                                                                                   |
| String utilities            | `utils/string`                                                                         | Prefix, metric, Markdown, JSON-fragment and truncation/token routines are connected behind `hia-native`; truncation performance, UUID helpers and complete owner/default/platform qualification remain open. |
| Hepta cells and adapters    | `hepta-*` crates                                                                       | Existing cell, Agentd, Codex adapter, identity, recovery and learning/adoption boundaries.                                                                                                                       |
| Platforms and release       | Linux/macOS/Windows integrations, build and release paths                              | Supported architectures, packages, clean installation and end-to-end platform tests.                                                                                                                             |
| HIA toolchain               | The pinned Hepta compiler and runtime                                                  | Required host interfaces, broader platform support and complete compiler/runtime ownership.                                                                                                                      |

All 15 complete capability migrations remain pending. Connected component
algorithms advance individual owners; their complete crates and default release
dispatch have not been migrated.

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
python3 -B hia/tests/test_native_truncate_caller.py --library-dir "$native_output" --rustc "$rustc_binary" --report "$build_parent/truncate-caller-tests.json"
python3 -B hia/tests/test_truncate_abi.py --library-dir "$native_output" --report "$build_parent/truncate-abi-tests.json"
python3 -B hia/tests/test_token_budget_abi.py --library-dir "$native_output" --report "$build_parent/token-budget-abi-tests.json"
python3 -B hia/tests/test_native_source_file_caller.py --library-dir "$native_output" --rustc "$rustc_binary" --report "$build_parent/source-file-caller-tests.json"
python3 -B hia/tests/test_source_file_abi.py --library-dir "$native_output" --report "$build_parent/source-file-abi-tests.json"
python3 -B hia/tests/test_scalar_build_admission.py --artifacts "$native_output" --report "$build_parent/scalar-admission-tests.json"
python3 -B hia/tests/test_build_receipt.py --artifacts "$native_output" --mutation-module token_budget --report "$build_parent/scalar-receipt-tests.json"
python3 -B hia/tests/test_build_receipt.py --artifacts "$native_output" --mutation-module source_file --report "$build_parent/source-file-receipt-tests.json"

"$rustc_binary" --edition=2024 --test --cfg 'feature="hia-native"' hia/tests/native_patch_caller.rs -L "native=$native_output" -l static=codex_hia_seek_sequence -o "$build_parent/patch-caller-tests"
"$build_parent/patch-caller-tests"

cd codex-rs
just test -p codex-apply-patch -p codex-utils-string --features hia-native --locked
just test -p codex-utils-string -p codex-utils-output-truncation \
  -p codex-protocol -p codex-context-fragments \
  --features codex-utils-string/hia-native --locked
env -u CODEX_HIA_NATIVE_LIB_DIR just test -p codex-apply-patch -p codex-utils-string \
  -p codex-utils-output-truncation -p codex-protocol -p codex-context-fragments --locked

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

The `Codex HIA native components` workflow runs its configured gates against
the checked-out revision. Commands listed above do not establish a completed
run; only the scoped observed results do. Build products and logs stay outside
the repository.
