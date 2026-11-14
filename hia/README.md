# Codex in HIA

This directory contains HIA implementations of Codex's patch-line matching and
UTF-8 prefix-boundary functions. The compiler is pinned to
[`TrillionniumFoundation/Hepta`](https://github.com/TrillionniumFoundation/Hepta)
at `f33d8da316de8fdf27b504371f1a5310997ff548`. Both implementations execute their
algorithms as native machine code produced from `.hepta` source.

The next integration work is to connect these implementations to the actual
Codex callers and migrate the remaining owners listed in
[`migration.json`](migration.json). Production dispatch still uses the existing
Rust implementation. The migration state is therefore:

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
| `16` for `seek_sequence`, `8` for `utf8_boundaries` | Number of output bytes written. |
| `0xffffffff` | Invalid input frame or UTF-8. |
| `0xfffffffe` | Output capacity is too small. |

Caller allocations must stay live for the call and mutable ranges must be
disjoint. Callers must enforce the locked capacity of 1,048,576 bytes per buffer
before entering a selfhost artifact. Both modules
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

## Build

Use Linux x86-64, Python, GNU `ld`, and a clean checkout of the Hepta revision
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
5. Link those HIA-produced objects with GNU `ld`.

The Python driver orchestrates this build and creates the initial B0 seed.
B1–B3 and the final component compilation execute native HIA compiler images.
The linker links the emitted object; it does not generate C or Rust source.

`build.json` records the compiler generation identities, source/Core hashes,
object inventory and shared-library hashes. A built component still needs its
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

The native B1–B3 compiler generations reproduced identical bytes, and both
components emitted by B3 passed their original Rust comparisons. This establishes
the three-generation compiler rebuild and the two component behavior checks.
Production integration, the full compiler/runtime surface and the wider Codex
capability map remain pending. `migration.json` records these scopes separately.

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
| Patch application | `apply-patch`, `file-search` | Connect the matching candidate, then implement parser and file-update owners. |
| String utilities | `utils/string` | Connect the prefix candidate, then implement truncation and the remaining helpers. |
| Hepta cells and adapters | `hepta-*` crates | Existing cell, Agentd, Codex adapter, identity, recovery and learning/adoption boundaries. |
| Platforms and release | Linux/macOS/Windows integrations, build and release paths | Supported architectures, packages, clean installation and end-to-end platform tests. |
| HIA toolchain | The pinned Hepta compiler and runtime | Required host interfaces, broader platform support and complete compiler/runtime ownership. |

All of these production capability migrations remain pending. The two
implemented functions advance the patch and string rows; they do not migrate
their entire crates or their production callers.

The search implementation preserves the original four-pass search complexity.
Long repeated context can require quadratic work; the input byte limit is not
an execution deadline. Production integration must retain cancellation and
execution budgets without changing a timed-out search into a false no-match.

## Retiring superseded files

Retire an old implementation after its HIA replacement owns the actual call
path and passes the original behavior tests, API/session compatibility checks,
required platform tests and clean-install end-to-end workflow. Then remove
unused source, dependency declarations, build rules and process artifacts in
the same verified change, retaining the tests, licensing and release assets
needed by the final version.

The present candidate has no legacy paths ready for retirement. Completing
production dispatch is the next prerequisite for removing either original
function; the wider capability map determines the rest of the repository
cleanup.


## Experimental Codex patch-caller integration

The native-selfhost build also emits ELF namespaced shared libraries,
libcodex_hia_seek_sequence.so and libcodex_hia_utf8_boundaries.so. These are
derived from the B3-emitted objects with GNU objcopy symbol renaming and GNU ld.
This permits both components in a single process without f0 symbol collision.
The original f0 shared libraries remain available for original-Rust comparison.

The opt-in codex-apply-patch hia-native feature routes the actual file-update
seek_sequence call sites through the HIA-produced machine implementation. Its
Rust adapter only constructs and decodes the established borrowed-buffer ABI.
Set CODEX_HIA_NATIVE_LIB_DIR to the native build output when building with this
feature, and make that directory available to the dynamic loader at runtime.

If framing exceeds the locked 1 MiB capacity, native patch matching raises a
ComputeReplacements error rather than silently reporting "no match". The
original Rust matcher remains the default implementation while this feature
undergoes whole-crate, full apply-patch and platform acceptance. No production
release is migrated merely by introducing the feature. The native caller's
source-level parity and oversize boundary are tested independently in
hia/tests/native_patch_caller.rs, using the actual namespaced HIA ELF.

This is Linux x86-64 only. Runtime packaging, cancellation/deadline behavior,
large-input strategy and other Codex owners remain pending. The complete
`codex-apply-patch` feature-enabled crate suite passed 99/99 tests on desktop
with the B3-emitted native matcher. An initial real Cargo run caught an invalid
`try_fold` accumulator type in the experimental adapter; it was fixed before
the passing run. The workflow now gates the same real crate suite in addition
to the narrower original-source oracle.

## Experimental Codex UTF-8 public caller integration

The `codex-utils-string` `hia-native` feature uses the namespaced B3-produced
`libcodex_hia_utf8_boundaries.so` for the **public**
`take_bytes_at_char_boundary(&str, usize) -> &str` call. Its small Rust adapter
only frames borrowed bytes, invokes the native ABI and checks that the returned
index preserves Rust's slice/UTF-8 boundary contract. The UTF-8 scanning and
boundary selection execute in HIA machine code. Without the feature, the
unmodified original Rust function remains the default and the original-source
oracle is still extractable.

On Linux x86-64, set `CODEX_HIA_NATIVE_LIB_DIR` at build time and make that
native directory available to the runtime dynamic loader (`LD_LIBRARY_PATH`
or explicit package rpath). A missing native artifact is a build error, not a
silent fallback. Input frames larger than the pinned 1 MiB limit panic rather
than misrepresent the original result or use the Rust algorithm unnoticed.
This limitation makes this an experimental, explicitly selected feature, **not**
a release-wide migration. The feature-enabled string crate passed its complete
21/21 tests on desktop, including original behavior comparisons, the exact
native frame boundary and oversize rejection. Its CI counterpart now runs from
the real workspace and links the namespaced native ELF.

Both native caller features still need proper package/linker installation,
Linux and other supported-platform qualification, caller-wide cancellation and
bounded-cost policy, and clean-install end-to-end acceptance before replacing
the corresponding Rust production owners or removing legacy code.
