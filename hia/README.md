# Codex in HIA

This directory contains HIA implementations of Codex's patch-line matching and
UTF-8 prefix-boundary functions. The compiler is pinned to
[`TrillionniumFoundation/Hepta`](https://github.com/TrillionniumFoundation/Hepta)
at `f33d8da316de8fdf27b504371f1a5310997ff548`. The components execute their
algorithms as native machine code produced from `.hepta` source.

The `hia-native` Cargo feature connects the actual patch-update matcher and
public string-prefix API to HIA machine code on Linux x86-64 GNU. Their Rust
adapters frame borrowed inputs and check native results. Static archives are
verified at build time and incorporated into the caller binary.

The feature remains opt-in. Other owners listed in
[`migration.json`](migration.json), other platforms, and the default release
dispatch still need migration. The whole-product state is therefore:

```json
{
  "production_dispatch_migrated": false,
  "whole_codex_rewritten": false
}
```

## Implemented components

| HIA module | Original source/function | Behavior implemented |
| --- | --- | --- |
| [`seek_sequence.hepta`](seek_sequence.hepta) | [`seek_sequence`](../codex-rs/apply-patch/src/seek_sequence.rs) | Exact, trailing-whitespace, trimmed and Unicode punctuation matching; original pass precedence, first match, empty patterns, start bounds, EOF behavior and both line-ending modes. |
| [`utf8_boundaries.hepta`](utf8_boundaries.hepta) | [`take_bytes_at_char_boundary`](../codex-rs/utils/string/src/lib.rs) | The largest complete UTF-8 prefix within a byte budget, plus complete validation of the incoming UTF-8 bytes. |
| [`utf8_prefix.hepta`](utf8_prefix.hepta) | The public string-prefix caller | Constant-size boundary selection for an already-valid Rust `&str`, preserving borrowing and allocation-free calls for arbitrarily large strings. |

The UTF-8 input checks reject overlong encodings, surrogate encodings, values
above U+10FFFF, lone continuation bytes and truncated sequences. They scan the
entire input before publishing a result, including bytes beyond the requested
prefix. These checks and both component algorithms are written in HIA.

### Native buffer interface

Each shared object exposes the same HIA signature:

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

| Component result | Meaning |
| --- | --- |
| `16` for `seek_sequence`, `8` for either UTF-8 module | Number of output bytes written. |
| `0xffffffff` | Invalid input frame or UTF-8. |
| `0xfffffffe` | Output capacity is too small. |

Caller allocations must stay live for the call and mutable ranges must be
disjoint. The direct seed wrapper and bootstrap compiler profile have a
1,048,576-byte capacity. The production B3 ELF entry receives the actual live
buffer extent; that compiler capacity is not a maximum file size. The patch
adapter checks all length arithmetic and uses fallible allocation. All modules
leave the source and workspace unchanged. Module errors leave the output
unchanged; successful calls preserve output bytes beyond the result length.
The workspace is reserved and may have length zero.

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

Both the direct native development build and the final B3-produced components
have completed real original-source comparisons on the desktop host with Rust
1.95.0. The final native self-host build passed the following checks; the
recorded results and artifact identities are in
[`verification.json`](verification.json).

| Component | Observed checks |
| --- | --- |
| Patch-line matching | 2,327 valid cases, 86 invalid cases and 135 buffer-boundary calls; all matched the original Rust behavior and buffer contract. |
| UTF-8 boundaries | All six tests passed with zero skips: 75,109 native calls, 2,093 original Rust comparisons and 56 Core VM comparisons. |
| Static patch caller | Eight tests passed, including multi-megabyte lines/patterns, an offset table exceeding 1 MiB, both modes, EOF and maximum start values. |
| Static string caller | Five tests passed: 18,559 original Rust comparisons, 9 MB input, 2,048 allocation-free calls and eight concurrent callers. |
| Real Cargo callers | 122 tests passed with `hia-native`; 117 passed with the default feature set; zero skipped in either run. |
| Installed patch executable | Two 2 MiB file updates passed against the original Rust CLI, with identical file bytes, exit status, stdout and stderr in both line-ending modes. The copied executable defines the native HIA symbol and has no HIA shared-library dependency. |
| Build and artifact identity | 46 checks passed, including altered sources/compiler images, malformed receipts, weak/undefined symbols and duplicate archive members. |
| Native lint gate | Strict Clippy passed for both production caller crates with `hia-native` enabled. |

The native B1–B3 compiler generations reproduced identical bytes, and both
components emitted by B3 passed their original Rust comparisons. This establishes
the three-generation compiler rebuild and the two component behavior checks.
The current production callers have additional static-link and whole-crate
gates below. Full compiler/runtime and wider Codex qualification remain pending. `migration.json` records these scopes separately.

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

| Capability | Current owners | Required next implementation |
| --- | --- | --- |
| Model transport | `codex-api`, `codex-client`, `http-client`, `websocket-client`, provider crates | HTTP/TLS, SSE/WebSocket events, retry, cancellation and provider request behavior. |
| Authentication and identity | `login`, `keyring-store`, `secrets`, `aws-auth`, `workload-identity`, `agent-identity` | Login, refresh, storage, redaction and platform identity interfaces. |
| Threads and turns | `core`, `core-api`, `protocol`, `thread-store` | Turn state, ordered events, incremental context and concurrent ownership. |
| History and recovery | `state`, `history`, `message-history`, `rollout`, `thread-store` | Existing session/database formats, atomic persistence, resume and crash recovery. |
| Tools, processes and files | `tools`, `exec`, `exec-server`, `shell-command`, `file-system`, code-mode crates | Tool execution, PTY/pipes, process groups, cancellation and owned file effects. |
| Permissions and sandboxing | `execpolicy`, `sandboxing`, platform sandboxes, `network-proxy`, `bwrap` | Existing authorization decisions, isolation and denial behavior on each platform. |
| MCP | `codex-mcp`, `rmcp-client`, `mcp-server` | Initialization, catalogs, calls, notifications, cancellation and transports. |
| App Server v2 | `app-server`, protocol/transport/client/daemon crates | Public JSON-RPC behavior, schemas, events and mixed app/exec host configurations. |
| CLI and TUI | `cli`, `tui`, `arg0`, terminal utilities | Flags, exit status, terminal event/rendering paths and existing snapshots. |
| SDK and frontends | `sdk/`, `codex-cli/`, `apps/` | Public client interfaces, frontend lifecycle and packaging. |
| Patch application | `apply-patch`, `file-search` | Matching is connected behind `hia-native`; parser and file-update owners still need migration. |
| String utilities | `utils/string` | Prefix selection is connected behind `hia-native`; truncation and remaining helpers still need migration. |
| Hepta cells and adapters | `hepta-*` crates | Existing cell, Agentd, Codex adapter, identity, recovery and learning/adoption boundaries. |
| Platforms and release | Linux/macOS/Windows integrations, build and release paths | Supported architectures, packages, clean installation and end-to-end platform tests. |
| HIA toolchain | The pinned Hepta compiler and runtime | Required host interfaces, broader platform support and complete compiler/runtime ownership. |

All complete capability migrations remain pending. The two connected functions
advance the patch and string rows; their entire crates and default release
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

"$rustc_binary" --edition=2024 --test --cfg 'feature="hia-native"' hia/tests/native_patch_caller.rs -L "native=$native_output" -l static=codex_hia_seek_sequence -o "$build_parent/patch-caller-tests"
"$build_parent/patch-caller-tests"

cd codex-rs
just test -p codex-apply-patch -p codex-utils-string --features hia-native --locked

cargo build --locked -p codex-apply-patch --features hia-native --bin apply_patch
cp "${CARGO_TARGET_DIR:-target}/debug/apply_patch" "$build_parent/hia-apply_patch"
cargo build --locked -p codex-apply-patch --bin apply_patch
python3 -B ../hia/tests/test_installed_patch.py \
  --binary "$build_parent/hia-apply_patch" \
  --reference-binary "${CARGO_TARGET_DIR:-target}/debug/apply_patch" \
  --report "$build_parent/installed-patch.json"
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
