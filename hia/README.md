# Codex in HIA

This directory contains twelve native HIA components compiled with
[`TrillionniumFoundation/Hepta`](https://github.com/TrillionniumFoundation/Hepta)
at `0de5657a80f96b138525ac7ee9ce11712a83a10d`. Their algorithms execute as
machine code compiled from the checked-in `.hepta` sources.

The opt-in `hia-native` Cargo feature connects ten components to existing
production paths on Linux x86-64 GNU: patch matching, four string operations,
template parsing, rendering and ordered indexing, and middle truncation with
full-width token-budget arithmetic. Rust retains allocation,
owned strings and AST storage, generic iterator effects, public formatting,
and checked transport across borrowed-buffer interfaces. Static archives are
verified at build time and incorporated into the caller binary.

Two other components have narrower scopes. `utf8_boundaries` is a diagnostic
full-input UTF-8 validator; production prefix selection uses `utf8_prefix`.
`uuid_matches` implements the public `find_uuids` API behind the feature and
passes its original-source comparisons, but has no current repository
production caller. Neither is counted among the ten symbols required in the
installed full CLI.

[`verification.json`](verification.json) records exact source, artifact and
report identities. [`migration.json`](migration.json) tracks the remaining
owners. Template and truncation performance equivalence, complete owner migration, default
native releases and other platforms remain open:

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
| [`truncate.hepta`](truncate.hepta) | [`truncate.rs`](../codex-rs/utils/string/src/truncate.rs) | Middle-truncation boundaries, removed scalar counts and original marker behavior; strict byte and trusted string entries. |
| [`token_budget.hepta`](token_budget.hepta) | Token/byte arithmetic helpers | Full-width saturating multiplication and addition through a typed scalar entry. |

The template feature propagates through
`codex-cli/hia-native` → `codex-login/hia-native` →
`codex-utils-template/hia-native`. The template adapter does not substitute a
Rust ordered set, comparison or map lookup for the HIA index. The public
`Clone`, `Debug`, equality and ordered iterator behavior remains compatible.
These are component algorithm migrations, not complete Rust-owner retirement.

The full-input UTF-8 validator rejects overlong encodings, surrogates, values
above U+10FFFF, lone continuations and truncation, including invalid bytes
beyond the requested prefix. The production prefix and metric callers accept
already-valid Rust strings. JSON fragments and template parsing perform their
own incremental validation within their documented framing contracts.

### Native buffer interface

Eleven buffer components expose this HIA signature; `token_budget` uses the
separate scalar interface described below:

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
| `40` for `truncate` | Five little-endian `u64` result fields. |
| `0xffffffff`                                          | Invalid frame/state; also invalid UTF-8 for the original matching/validation entries. |
| `0xfffffffe`                                          | Insufficient output or workspace capacity.                                            |
| `0xfffffffd`                                          | Invalid location format, or invalid UTF-8 in JSON fragments or strict truncation.               |

Caller allocations must stay live for the call and mutable ranges must be
disjoint. The direct seed wrapper and bootstrap compiler profile have a
1,048,576-byte capacity. The production B3 ELF entry receives the actual live
buffer extent; that compiler capacity is not a maximum file size. The patch
adapter checks all length arithmetic and uses fallible allocation. All buffer modules
leave the source unchanged. The patch and UTF-8 modules leave workspace
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


### Truncation and scalar token-budget interfaces

`truncate` borrows the complete input without copying it or imposing the seed
compiler's buffer-size limit. A 16-byte read-only workspace contains the
little-endian operation and budget. Operations 0/1 validate arbitrary UTF-8
bytes for character/token plans; operations 4/5 require valid UTF-8 and are
used by the Rust `&str` caller. Trusted character plans count the removed
range, using checked unaligned word reads; trusted token plans inspect at
most four bytes around each cut. Operations 2/3 retain the original framed
scalar conversions and require empty input.

The 40-byte result contains prefix end, suffix start, removed marker units,
original approximate token count and marker kind (unchanged 0, characters 1,
tokens 2). Framed scalar results put the value in the first word and zero the
remaining fields. Capacity errors (`0xfffffffe`) precede operation/input
errors (`0xffffffff`), which precede invalid UTF-8 (`0xfffffffd`). Returned
errors preserve all three buffers. Successful calls preserve the workspace
and output after byte 39.

HIA chooses both UTF-8 cuts, assigns the odd budget remainder to the suffix,
counts removed Unicode scalars, and preserves the original token-marker
accounting. Rust assembles the owned string and marker text, checks returned
boundaries and retains the original equality check for marker collisions.
The public APIs remain `truncate_middle_chars`,
`truncate_middle_with_token_budget`, `approx_token_count`,
`approx_bytes_for_tokens` and `approx_tokens_from_byte_count`.

Public arithmetic helpers call the separate scalar entry:

```c
uint64_t codex_hia_token_budget(uint64_t value, uint64_t operation);
```

Its `u64-pair-to-u64-v1` profile has no buffers or persistent state. Operation
0 returns `min(value * 4, u64::MAX)` and operation 1 returns
`min(value + 3, u64::MAX) / 4`. All `u64` input values and `u64::MAX` as a
result are valid. Every other operation traps; the Rust adapter's private
enum supplies only 0 or 1. Buffer wrapper status encoding does not apply to
this scalar result.

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

### Observed validation

The twelve-module native B3 build passed its component gates on Linux x86-64
GNU with Rust 1.96.1. All 24 original JSON reports were recovered byte for
byte and checked against their SHA-256 identities. The current commands,
inputs, outputs and report hashes are recorded in
[`verification.json`](verification.json).

| Scope | Observed result |
| --- | --- |
| Original-source and ABI comparisons | Fresh reports cover all twelve modules, including the original template parser/render/index comparisons and UUID public API. |
| Truncation | 7 public API tests and 229,173 original Rust comparisons; strict/trusted, no-write and concurrent ABI cases passed. |
| Scalar token budgets | 74,552 native calls; full-width boundary values, concurrent calls and invalid-operation traps. |
| Link receipts | 64 buffer-module mutation checks, 64 scalar receipt checks and 118 scalar build-admission checks. |
| Small combined owners | 168 native owner tests, 319 native consumer tests and 470 default owner/consumer tests; zero skips or retries. Installed apply_patch comparison and both strict lint modes passed. |
| Full default workspace | 19,432/19,432 passed, 53 existing skips and zero retries; all workspace binaries built. |
| Combined native owners | 8,746/8,746 passed, 15 existing skips and zero retries; covers patch/string/template owners plus CLI, arg0, Core, TUI and login. |
| Full CLI installation | Native/reference startup and patch behavior passed after relocation; all ten production symbols retained and no HIA shared-library dependencies. |

Both native and default strict lint gates passed. The complete tested source
remained unchanged during the gates; only the three declared documentation
files were updated afterward. The workflow is included in the tested source,
but local commands do not establish a successful remote CI run.

The installed CLI gate checks symbol retention, relocated startup and patch
behavior. It does not execute every linked algorithm. Skipped tests are not
counted as passes. Native macOS/Windows, default HIA releases and complete
product ownership remain unqualified.

### Performance remains open

Template rendering and truncation/token-budget performance still require
qualification. Prior measurements and their exact source revisions are
identified in `verification.json`; they are not relabeled as measurements of
this combined build. Independently developed optimization candidates are not
part of this source until their own functional and performance gates pass.

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
| Permissions and sandboxing  | `execpolicy`, `sandboxing`, platform sandboxes, `network-proxy`, `bwrap`               | Existing authorization decisions, isolation and denial behavior on each platform.                                                                                                                                                                                         |
| MCP                         | `codex-mcp`, `rmcp-client`, `mcp-server`                                               | Initialization, catalogs, calls, notifications, cancellation and transports.                                                                                                                                                                                              |
| App Server v2               | `app-server`, protocol/transport/client/daemon crates                                  | Public JSON-RPC behavior, schemas, events and mixed app/exec host configurations.                                                                                                                                                                                         |
| CLI and TUI                 | `cli`, `tui`, `arg0`, terminal utilities                                               | Flags, exit status, terminal event/rendering paths and existing snapshots.                                                                                                                                                                                                |
| SDK and frontends           | `sdk/`, `codex-cli/`, `apps/`                                                          | Public client interfaces, frontend lifecycle and packaging.                                                                                                                                                                                                               |
| Patch application           | `apply-patch`, `file-search`                                                           | Matching is connected behind `hia-native`; parser and file-update owners still need migration.                                                                                                                                                                            |
| String utilities            | `utils/string`                                                                         | Prefix selection, metric tags, Markdown location suffixes and JSON string fragments are connected behind `hia-native`; UUID matching is verified as a public API without a production caller; middle truncation and token arithmetic are connected; complete owner/default/platform qualification and performance equivalence remain. |
| Hepta cells and adapters    | `hepta-*` crates                                                                       | Existing cell, Agentd, Codex adapter, identity, recovery and learning/adoption boundaries.                                                                                                                                                                                |
| Platforms and release       | Linux/macOS/Windows integrations, build and release paths                              | Supported architectures, packages, clean installation and end-to-end platform tests.                                                                                                                                                                                      |
| HIA toolchain               | The pinned Hepta compiler and runtime                                                  | Required host interfaces, broader platform support and complete compiler/runtime ownership.                                                                                                                                                                               |

All 15 complete capability migrations remain pending. The ten connected
components advance individual algorithms; their complete Rust owners and
default release dispatch have not been migrated. Login template algorithms
are connected, while login and credential ownership remain separate work.

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
export NEXTEST_TEST_THREADS=4

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
python3 -B hia/tests/test_native_truncate_caller.py --library-dir "$native_output" --rustc "$rustc_binary" --report "$build_parent/truncate-caller-tests.json"
python3 -B hia/tests/test_truncate_abi.py --library-dir "$native_output" --report "$build_parent/truncate-abi-tests.json"
python3 -B hia/tests/test_token_budget_abi.py --library-dir "$native_output" --report "$build_parent/token-budget-abi-tests.json"
python3 -B hia/tests/test_scalar_build_admission.py --artifacts "$native_output" --report "$build_parent/scalar-admission-tests.json"
python3 -B hia/tests/test_build_receipt.py --artifacts "$native_output" --mutation-module token_budget --report "$build_parent/scalar-receipt-tests.json"

"$rustc_binary" --edition=2024 --test --cfg 'feature="hia-native"' hia/tests/native_patch_caller.rs -L "native=$native_output" -l static=codex_hia_seek_sequence -o "$build_parent/patch-caller-tests"
"$build_parent/patch-caller-tests"

cd codex-rs
just test -p codex-apply-patch -p codex-utils-string -p codex-utils-template \
  -p codex-cli -p codex-arg0 -p codex-core -p codex-tui -p codex-login \
  --features hia-native --locked --retries 0
env -u CODEX_HIA_NATIVE_LIB_DIR just test --workspace --locked --retries 0

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
the checked-out revision. A command listing is not a completed CI result. Build products and logs stay outside the repository.
