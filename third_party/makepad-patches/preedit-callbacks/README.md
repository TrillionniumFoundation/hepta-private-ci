# Explicit X11 callback preedit candidate

This candidate changes the existing Makepad XIM negotiation and caret update
path. The original Hepta `ImeRouter`, `TextInput`, `ChatWorkspace`, and action
guards remain the only input/state owners. There is no synthesized IME event,
global keyboard injection path, clipboard API, or execution authority here.
The normal Git SDK and the historical clipboard candidate are unchanged.

## Problem and scope

At upstream `337566c8b25d47f7e4fff6a202157b65bf183330`, input-context creation
tries `XIMPreeditPosition` before `XIMPreeditCallbacks`. Position style lets
the input method render preedit without informing the original editor. The
existing SDK callback-to-`TextInputEvent { replace_last: true, .. }` path and
Hepta composition guard therefore receive no preedit when Position succeeds.
In addition, `set_ime_rect` can replace a callback context with Position if
the IM rejects the implementation-specific callback spot attributes.

`native-preedit-callbacks.patch` prefers the already implemented callbacks,
with the same original status styles and commit path. A callback spot update
failure retains that exact context and logs the positioning limitation once
per window. It does not silently remove composition protection to position
the candidate window. Position/Nothing are still creation-time compatibility
fallbacks; **they do not qualify for this profile's preedit guarantee**.

The real IBus candidate window also exposed a separate focus transition bug.
X11 VisibilityNotify sends WindowGotFocus even while the same native window
already has focus. The original Window handler then restored a stale
last_known_area, cancelled TextInput composition, and queued HideTextIME.
An owned-window GDB trace established that chain through XUnsetICFocus;
its visibility callsite differs from genuine FocusIn. This patch restores
the saved editor only on the actual false-to-true window focus transition.
Duplicate gain notifications preserve the current editor and preedit;
WindowLostFocus followed by WindowGotFocus still restores the saved editor.
The matching true-to-false loss guard retains that saved editor across
repeated loss notifications, instead of replacing it with the already
cleared focus. Events belonging to another window keep their isolation.

The preparation helper permits exactly widgets/src/window.rs and its sibling
window_focus_tests.rs only for this explicit preedit profile. Arbitrary
widget changes and either widget file in the clipboard profile remain
rejected. The sibling tests dispatch real Window focus events and preedit
through an actual drawn SDK TextInput; they cover repeated gain, repeated
loss followed by return, genuine loss/return, and other-window isolation. These source tests do not replace
the real private IBus acceptance below.

The second patch is the byte-identical existing `sdk-num-traits-path.patch`.
It makes an explicit path build use the same original num-traits 0.2.20 vendor
source as Git package discovery. It does not introduce a dependency version
change. The whole prepared SDK tree, both patches, original/patched files,
and MIT license are fixed by this directory's `MANIFEST.json`.

The runtime emits `makepad-x11-ime profile=preedit-callbacks-v1` plus the
actual selected `style=callback|position|nothing|unavailable` and X11 window
ID when each input context is created. A rejected callback spot update emits
`callback-spot=unsupported context=retained` once per window. These messages
contain no user text; they establish negotiation only, not IME success.

## Prepare and bind the complete Cargo graph

Use a new Desktop candidate worktree, a separate target directory, the
same integrated Hepta companion as product execution, and the exact existing
native/text feature set.
This profile reuses the source preparation/verification tools through their
explicit `--profile preedit-callbacks` argument. Omitting the argument retains
their historical clipboard behavior. The preedit-only profile rejects the
`native-clipboard-sdk` feature; it must not advertise PasteText.

First capture complete original `cargo metadata` with the actual native
product features. Then create a new prepared SDK and all-crate override:

```sh
python3 -B apps/hepta-control-ui/test/prepare-native-clipboard-sdk.py \
  --profile preedit-callbacks \
  --upstream-repo /absolute/existing/makepad-git \
  --destination /absolute/new/makepad-preedit \
  --metadata /absolute/original-native-metadata.json \
  --cargo-config-output /absolute/new/preedit-overrides.toml
```

Resolve the same feature set with this explicit `cargo --config` in that
candidate worktree, saving its separate Cargo.lock and complete metadata.
Do not alter a Cargo cache, normal lockfile, global configuration, or live
installation. A platform-only override is invalid because sibling SDK
packages would then use different sources and incompatible types.

```sh
python3 -B apps/hepta-control-ui/test/verify-native-clipboard-sdk.py \
  --profile preedit-callbacks \
  --prepared-source /absolute/new/makepad-preedit \
  --original-metadata /absolute/original-native-metadata.json \
  --candidate-metadata /absolute/candidate-native-metadata.json \
  --cargo-config /absolute/new/preedit-overrides.toml
```

Save the result before and after the locked build/tests. The verifier binds
the upstream commit/full tree, complete staged patched tree, every SDK crate
manifest, SDK-to-SDK dependency edges, exact patch/config/metadata digests,
and refuses tracked source flags or undeclared worktree changes. Existing
registry copies remain distinct. The profile is source evidence on the
trusted build host, not remote attestation against a malicious host.

## Qualification and promotion

Source preparation is not a passing build or runtime test. On the exact
built binary and resource bundle, collect a fresh isolated X11/IBus run:

1. Require `style=callback` for the actual editor window. A fallback or
   unavailable context leaves the preedit acceptance gate failed.
2. Type through the real libpinyin engine. While preedit is active, verify
   the original editor's composition and disabled room/action guards before
   accepting the candidate or committing text. Preserve actual screenshots,
   editor readback, engine identity, and binary/source/resource hashes.
3. Commit and cancel composition; confirm correct original text, undo/redo,
   draft isolation, and guard release. A diagnostic marker alone cannot pass
   any of these assertions. Test candidate-window position independently;
   retained callbacks can still have a positioning limitation.
4. Re-run the original AT-SPI EditableText and original input-owner tests.
   No clipboard/PasteText, Wayland, physical display, or production Root
   authority claim follows from an isolated X11 test.

Only then select and package an explicit product profile, including the exact
source/patch/license notices and runtime evidence. The historical five-file
clipboard notice contract must not be relabelled as this different SDK.
Until those steps pass, this remains an unpromoted candidate.
