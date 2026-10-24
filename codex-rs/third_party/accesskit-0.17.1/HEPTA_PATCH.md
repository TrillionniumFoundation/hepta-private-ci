# Original AccessKit Linux atomic editing compatibility patch

This directory retains AccessKit's original `accesskit 0.17.1`,
`accesskit_consumer 0.26.0`, `accesskit_atspi_common 0.10.1`, and
`accesskit_unix 0.13.1` from upstream commit
`405d578cdfd8496ee79020d24cfaac8c29a8a48f`. The original Apache-2.0, MIT and
Chromium license texts remain here. `HEPTA_UPSTREAM.json` records every retained
original file hash and the changed/new source file list. `HEPTA_PATCH.diff`
contains the source changes against that exact upstream commit. The enclosing
workspace retains only these four crates; no renderer is included or replaced.

The patch adds the standard `org.a11y.atspi.EditableText` interface to the
original AccessKit Unix D-Bus connection. It is advertised only when a text
input explicitly supports the new `EditText` action and is not read-only or
disabled. It has no socket driver, private text model or keyboard emulator.

`SetTextContents`, `InsertText`, `DeleteText`, `CopyText`, and `CutText` create one
typed request containing the complete observed text and the original text-run
range identity. Insertion positions use AT-SPI Unicode scalar offsets; insertion
lengths use bytes. An offset inside a composed grapheme or a byte prefix inside
a UTF-8 code point is refused instead of rounded. The Hepta-specific compatibility
limit is 16 KiB of resulting text, with NUL refused. Invalid and oversized
requests are rejected before queueing a UI operation. No application callback
runs while the consumer tree lock is held.

The original Hepta App consumes this request through its existing bounded
accessibility mailbox. It rechecks the original `RoomKey`, active widget branch,
IME state, observed/current text, run identities, original draft and exact size
limit. Edits use the original `TextInput::replace_range` and undo history;
copy/cut use the original `Cx::copy_to_clipboard`. There is still only one
`ChatWorkspace` and no authority is granted by accessibility.

## Qualification and remaining API boundary

The D-Bus boolean reports that an operation could be dispatched against the
observed adapter tree. As with the original AccessKit selection actions, the
application may process it asynchronously and must refuse a subsequently stale
request. Verify the resulting original text/selection/history; a true dispatch
boolean alone is not mutation evidence.

The independent PasteText candidate additionally requires the exact original
SDK source and patch in `third_party/makepad-patches`, and the explicit original
UI `native-clipboard-sdk` feature. EditableText alone never advertises native
clipboard capability: the original UI adds the separate `PasteText` action only
with that feature. Without the action, the standard method returns false before
queueing. This remains true even when another crate enables a dependency's
features. The candidate queues a degenerate
revision-bound `Paste` action, starts the original SDK's unique clipboard ticket,
and revalidates the same room, text-run and complete text after its asynchronous
reply. Raw input/IME/focus and later semantic intents retire the pending request.
Returned text uses the same atomic `Replace` validation and original undo path.
No global `TextInput` event, synthetic key, or uncorrelated Xlib read is used.
Unsupported backends report unavailable; no reply can select a different room.

Five-method baseline evidence does not establish PasteText; the candidate must
run `native-editable-text-smoke.py --request-scoped-paste` on its exact built
source, including native clipboard readback and a held response released only
after an actual room change. None of these tests establishes physical IME,
Wayland or human Orca qualification. The test harness retains these limits
explicitly. Run the upstream core/consumer tests, new AT-SPI boundary
tests, original Hepta editor tests and the real D-Bus window test before promotion:

```sh
cargo test --manifest-path codex-rs/third_party/accesskit-0.17.1/Cargo.toml \
  -p accesskit -p accesskit_consumer -p accesskit_atspi_common
cargo check --manifest-path codex-rs/third_party/accesskit-0.17.1/Cargo.toml \
  -p accesskit_unix
```

The original UI Cargo root supplies all four `[patch.crates-io]` entries. Cargo
does not inherit patches from dependency workspaces: the Desktop UI root must
also supply all four entries at the same fixed Hepta source revision. Inspect
the resolved graph and regenerate the applicable lock under the product Rust
toolchain. Do not mix a patched `accesskit` type with registry adapter crates.

After formatting or a reviewed source change, regenerate provenance from the
exact original Git objects. This command verifies all 53 upstream identities,
computes the full current patch (including added source files and the narrowed
vendor workspace), proves that applying it reproduces every current source
byte, and updates the separate installed notice hashes. It does not rewrite
source or hide removed files. Omit `--write` for a check-only gate:

```sh
python3 -B apps/hepta-control-ui/test/refresh-native-accesskit.py \
  --upstream-repo /absolute/local/accesskit-git --write
```
