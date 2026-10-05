# Makepad Web IME candidate for review

Status: integrated source-overlay candidate. Focused controller/DTO checks have passed; formal WASM packaging and actual-browser input acceptance remain pending. The SDK cache is never modified.

## Inputs and integration

- Exact upstream: `337566c8b25d47f7e4fff6a202157b65bf183330`
- Apply `makepad-wasm-ime.patch` with `patch --batch --forward --fuzz=0 -p1 -d <generated-platform-copy>`
- `makepad-wasm-ime.json` contains patch SHA and exact before/after SHA for all four changed files
- Existing clock and instance-layout patches affect other files, so these identities are independent of their order
- Register this identity and its files in `prepare-makepad-platform.mjs` and include it in `build-manifest.json`
- The `web.js` stylesheet extraction tokens are preserved for the existing strict-CSP packaging step
- Existing static message-bridge generation must run against the new WASM because three inbound message registrations, one outbound registration and clipboard-response wire schema changed
- Node tests accept `MAKEPAD_PLATFORM_ROOT=<actual generated platform directory>`; the default is the generated `rust/target/robrix-build/makepad-platform/` overlay
- DTO test accepts the same variable plus `RUSTC=<compiler path>`

## Responsibilities

Rust TextInput remains the owner of draft text, validation, selection, composition, undo and product actions. The hidden textarea is the native editor/IME mirror. Ordinary browser edits use the existing `TextInputEvent.full_state_sync` consumer. Rust owns navigation, deletion, Enter, select-all and undo key commands. No product transcript state or new clipboard permission is added in JavaScript.

`ToWasmImeRequestState` supplies a synchronization boundary: a pending owner draw runs before the next native edit can submit a stale DOM snapshot. It calls existing `call_draw_event`, without GPU repaint or `NextFrame`; normal presentation remains on RAF. This is the main integration-review point: browser/WASM evidence must verify it does not introduce frame/liveness regressions.

`SyncImeState` updates the textarea's actual text and selection. It does not overwrite an active native composition; a Rust programmatic edit around marked text is carried into the composition's next owner update. On focus loss, the old hidden DOM target is retired after its controller is deactivated, so late composition callbacks cannot mutate the new field. Browser blur does not automatically steal focus back. A native empty preedit remains a live composition even if Rust reports no nonempty marked range; only compositionend/blur/hide or an unrelated owner change closes that native session.

Selection endpoints and direction are kept separate on the wire. Reversed bounds are normalized for DOM setters, and direction-only updates apply without collapsing selection. In this pinned SDK, TextInput's ordinary `sync_ime_state` call sends sorted bounds and cannot express its anchor direction. The bridge therefore must not echo programmatic synchronization back as a new selection-only edit: `last_state` is refreshed after the DOM setter, including its actual direction, and deferred select callbacks are deduplicated. This preserves the Rust-owned Shift+Arrow anchor. The tests cover direct reversed DTOs as well as the actual sorted-owner contract. Composition bounds normalize to an ascending nonempty interval or no marked range.

## Text encoding

The upstream generic String wire codec has an independent non-BMP defect:

- `libs/wasm_bridge/src/wasm_bridge.js:939`: `push_str` sends UTF-16 `charCodeAt` values
- `libs/wasm_bridge/src/to_wasm.rs:216`: Rust decodes each value as a Unicode scalar
- `libs/wasm_bridge/src/from_wasm.rs:143`: Rust sends Unicode scalars
- `libs/wasm_bridge/src/wasm_bridge.js:966`: JavaScript uses `String.fromCharCode`, truncating astral scalars

Only the new IME full-text DTO and existing clipboard response are changed to explicit `Vec<u32>` scalar payloads. JS uses codePointAt/fromCodePoint, while selection/composition wire positions remain UTF-16. Invalid scalar values recover to U+FFFD, offsets are clamped and floored away from surrogate interiors, and native input is explicitly bounded at 1,048,576 UTF-16 units. Oversized JS edits restore the prior accepted mirror and raise a text-free RangeError; no draft content is logged.

The older `ToWasmTextInput` message entry remains registered and unchanged. This candidate does not fix its generic String codec, nor does it qualify every non-TextInput editor/custom input consumer in Makepad. The newly bound full-state textarea path is intended for the Robrix TextInput-based fields. Mobile Safari/Android's existing keyboard guard is unchanged; mobile keyboard support is not claimed.

## Clipboard toolbar no-op evidence

The two toolbar ops, not actual clipboard operations, are deliberately capability no-ops:

- `platform/src/cx_api.rs:1449–1470` documents ShowClipboardActions as the native floating menu and other platforms as no-op
- `platform/src/os/windows/windows.rs:1198–1200`, `os/apple/macos/macos.rs:2019–2021` and `os/linux/x11/linux_x11.rs:822–823` explicitly ignore these mobile toolbar operations
- Actual browser copy/cut/paste uses the user's ClipboardEvent data and `TextCopy`/`TextCut`/FullTextState. No navigator.clipboard reads or new permissions
- `TextInput` unconditionally pushes `HideClipboardActions` after text changes (`widgets/src/text_input.rs:3198`), which is why its missing Web arm surfaced during ordinary typing

## Verification performed

- 24 actual-controller Node lifecycle tests pass (controller extracted unchanged from patched web.js; DOM and Rust host are test doubles)
- 5 lightweight Rust tests compile and run the actual DTO conversion implementation with minimal surrounding type stubs: astral text/UTF-16, malformed scalars, out-of-range positions, split surrogate and empty text
- JS module syntax check passes
- Patch applies to a fresh four-file copy with fuzz=0 and exact after-SHA matches

These are focused checks, not a complete Rust/WASM or browser pass. No browser, listener, package installation or full Cargo build was run here.

## Required hosted acceptance

Keep strict application health assertions intact. Against the newly packaged WASM, verify:

1. Existing three-theme draft/resize/Console round-trip retains the owner draft and never logs unknown platform operations
2. Native-like compositionstart/update/input/end ordering in Chromium, Firefox and WebKit: visible Chinese preview; final commit clears marked state; cancel removes preview; end plus final input does not duplicate; two consecutive identical commits are retained
3. `A😀𠮷中` and selection replacement around astral characters preserve exact owner text and caret, not just the DOM mirror
4. A control key immediately followed by text within one frame (Arrow, Backspace/Delete, Ctrl/Cmd+A, Undo) cannot restore stale text/selection; Shift+Enter inserts one newline and IME confirm Enter never submits the app
5. Copy/cut/paste uses exact current owner selection, cut deletes once, paste replaces selected text, no stale clipboard response survives empty focus
6. Switching input owner during composition retires old events; hide/reopen, blur/focus and theme navigation do not leak another field's draft or lose the expected one
7. IME anchor remains by the actual caret after viewport resize and horizontal/vertical input scrolling
8. No new inline stylesheet, eval/new Function, console error, CSP violation or automatic crash upload
