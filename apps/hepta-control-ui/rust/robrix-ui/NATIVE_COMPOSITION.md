# Original App composition for a fixed external workspace

`native-presentation` adds an observation-only composition mode to the existing
Robrix-derived Makepad `App`. It is a candidate Linux development interface. It
does not install a `NativeHost`, a Chat owner, a signer or an Objective writer.
The original `PresentationCommand::RequestSend` still returns `SendUnavailable`.

The intended caller is Desktop's existing Session projection. That caller moves
its one `DraftBook`, reducer and Bridge into a `NativeChatComposition`; the
original App borrows the chosen original `ChatWorkspace`. The Desktop adapter
is a separate repository change and must pin the actual published commit that
introduces this API. The older presenter-only commit does not provide it.

## Source and ownership

This change starts from Hepta
`56630b12b8a4c69fff2c47b95b36d88a7389c39f`, tree
`15ff893b92898185ea709e847b244e4d66ae2bf4`. Makepad remains exactly
`337566c8b25d47f7e4fff6a202157b65bf183330`, root tree
`c6e18be7754f9634492ec5251bac3e8b4f7e09b7`. No SDK source or Cargo lock is
changed by this interface. Robrix copyright and MIT notices remain in
`licenses/ROBRIX-MIT.txt`.

`ChatSourceSlot` is initially empty. `AppMain::after_new_from_script` adopts one
source before the SDK dispatches the first event. A composition supplies its
existing workspace directly: that path never constructs an empty standalone
workspace or copies the draft into a renderer-owned String. Standalone and
existing owner-host launches still construct the original default workspace or,
only with `ui-fixtures`, the original fixture. A second adoption is refused
without evaluating its constructor. Live style reapplication retains the
existing `#[rust]` source and input router.

The immutable and mutable workspace methods must return the same object for
the App's lifetime. The first Desktop adapter selects one Personal, Research or
Build slot before startup and retains the entire `DraftBook`. Switching between
those Desktop slots is absent: independent workspaces can have coincident
`RoomKey` values, so a safe switch needs a scope/generation binding that also
fences late input events. Original conversation navigation within the selected
workspace still uses the original presenter epochs. This is not the complete
three-slot Desktop UI.

The original App owns exactly one `ImeRouter`. Event dispatch, pointer gating,
composing state, focus synchronization and adaptive-layout holding remain in
the original modules. The client does not normalize keys in parallel or install
another input route. Native IME, accessibility and mobile acceptance still need
their own implementation and device tests.

The original native editor visibly reports rejected over-limit/NUL edits and
keeps the last valid text. After composition ends, its current reconciliation
resets the editor state when the widget text differs from that valid draft.
Selection/undo preservation therefore differs from Desktop's egui transaction
rollback. This interface does not claim that those editing behaviors are equal.

## Original lifecycle, two launch modes

`run_native` retains the existing `NativeHost` mode. Its owner, draw witness,
invalidation and safe-close callbacks remain in `native_host/render.rs`.
`run_native_presentation` selects the new observation-only mode. Both call the
same original `app::app_main` through `native_launch` and share its thread-local
admission guard. Reentry on that thread cannot replace a pending launch. This
is not a cross-thread lock or proof of the operating system's permitted UI
thread; callers must honor the existing Makepad event-loop requirements.

Enabling both Cargo features compiles both modes; it does not activate both in
one App. There is no empty `NativeHost` implementation for the new mode. Native
presentation never calls `observe_rendered`, creates a readiness witness or
represents a Session observation as owner authorization.

The resource callback runs in the original `app_main!` configure phase, before
script registration and App construction. The original
`SignalToUI::set_ui_signal` is then installed as the client's waker. Its bounded
worker may notify the UI when a response is available. A 250 ms UI timer covers
coalesced signals and reevaluates silent observations. A timer or signal never
renews the recorded receipt age of an old response.

`OwnedComposition` invokes client cleanup once on window close or Shutdown;
drop also covers failed adoption and abnormal loop exit. It marks the callback
as consumed before calling it, so unwinding cannot invoke it twice. The callback
must release only its client channels without waiting for blocking I/O. This is
not Session, Agentd or run cancellation. An existing request already in flight
can still complete. No total transport deadline is introduced by this API.

The launcher reports success only after adoption and Shutdown with no reported
resource error. This is an event-loop result, not proof of readable pixels, an
IME session, device authority, admitted chat or completed external operations.

## Console through the existing widgets

`poll_console` runs outside Draw and without a live mutable workspace borrow.
It must be nonblocking: consume already received responses, apply the existing
reducer and freshness rules, and return a view. Desktop keeps host task/context
observations outside the original Chat history; local notices and draft captures
never become transcript messages.

The result uses the existing desktop and narrow-layout Console labels in
`robrix/home.rs`. Refresh uses the existing buttons after the original input
dispatch and only while Console is visible and composition is inactive.
`request_refresh` queues only the caller's read-only observation request. A
queued or in-flight refresh stays pending; it is not a successful response.
This interface adds no executable Console commands.

Console view text is capped at 32 KiB. Truncation preserves UTF-8 and appends an
explicit omission notice. It bounds a transient view, never a durable receipt,
source envelope or Chat history. Existing response and queue limits still apply.

## Original resource and notice inputs

`apps/hepta-native/resources/NATIVE-ASSETS.json` remains the contract: 29 assets,
15 notice texts and the exact Liberation corresponding-source archive.
`NATIVE_RESOURCE_MANIFEST_JSON` exposes those original catalog bytes, not font
payloads or a rendering attestation.

The omitted notice texts are restored byte-for-byte from
`768c52943abbf473c96ec72d4b30de1f57c4e824`, tree
`b30915a2498bfd98342ac1826f278b47c8855133`. All 15 match the current catalog's
existing lengths and SHA-256 digests. The already-present CJK OFL is unchanged.
`apps/hepta-native/resources/NOTICE_SOURCE.json` records each original Git blob,
digest and disposition. No old native runtime, owner, backend lock, build script
or qualification receipt is imported.

The old asset generator expects 30 assets including excluded artwork; its build
wrapper depends on the old complete native product. It must not be run as this
caller's builder. The caller prepares the current assets from its actual
resolved Git packages, verifies lengths/hashes, preserves the notices and exact
source archive, then sets the real `Cx.package_root` before App creation. No
runtime resource fetching is added.

The new feature follows the existing externally packaged native-host path in
`build.rs`, without copying fonts into Cargo's Git checkout. Outside Draw, the
renderer verifies that the original registered resources are Loaded and reports
an error on missing data. Preflight and Loaded state do not prove the bytes that
later produce pixels: the SDK can first read a font by its compiler-recorded
absolute source path. Filesystem changes between preflight and later reads are
also outside this check. Actual font consumption and readable CJK pixels remain
independent acceptance gates.

## Verification and remaining gates

The product workflow retains its existing source/base-merge browser lanes. The
separate `native-presentation` job runs both source-head and base-merge with the
original Rust 1.95.0 and locked Cargo graph. It explicitly tests the headless
`--no-default-features --features native-presentation` and the Linux package
with `--features ui,native-host,native-presentation`, then runs Clippy with
warnings denied. It records source/tree, lock, tool versions and raw output.
Default headless tests alone do not cover this feature.

The UI's original installer pins official nextest **0.9.146**. Two explicit
profiles retain the complete `--lib` selection with zero retries and emit
separate JUnit reports, including skipped cases. The new JUnit gate first
requires an absent output path, then binds the resulting report to the original
execution receipt, unchanged source identity, exact unfiltered command, raw log
hash and execution interval. It requires all five new headless test names and,
for the UI build, all eight names including the three launch tests. Missing,
skipped, failed, retried, duplicate or same-prefix replacement cases fail even
when older presenter tests pass. Nextest omits the root `skipped` attribute in
some valid reports; the gate checks testcase status and names independently.
Its synthetic XML/receipt rejection tests are separate Python gate tests, not
execution of the Rust tests or renderer.

Authored regressions cover the same draft allocation across adoption, unchanged
Send refusal, once-only cleanup, reentrant launch rejection, failed adoption,
unwinding and bounded UTF-8 text. Lifecycle tests use a test event-loop closure
to exercise actual admission/cleanup; they do not open a window. Compiling the
UI checks real App and Makepad APIs but does not qualify graphics or input.

Desktop separately needs the actual published Git dependency, normal Cargo lock
generation, default/shared/native gates, original Session socket/reducer tests,
and a complete resource bundle. Earlier egui-only evidence cannot qualify this
composition. A real native window, actual font use, physical IME, assistive
technology, Web integration, mobile devices, bare metal and full Desktop
workspace navigation each remain separate gates. Chat Send remains unavailable
until its independent original authority and durable owner are connected.
