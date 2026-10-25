# Original Makepad clipboard and X11 preedit candidate

This directory carries a reviewable patch to the original pinned Makepad SDK,
not a new renderer. `MANIFEST.json` fixes upstream commit
`337566c8b25d47f7e4fff6a202157b65bf183330`, every changed file's original and
patched bytes, the patch digest, and the complete resulting Git tree. The
original MIT license remains in the prepared source and is recorded by hash.

The current candidate also carries `sdk-num-traits-path.patch`. The original
Git Cargo graph resolves `num-traits` 0.2.20 from
`libs/rapier/vendor/num-traits`, while the literal paths in `makepad-half` and
`naga` would select the separate Vulkan 0.2.19 copy in a path build. The added
patch changes only those two manifest paths to the original 0.2.20 directory;
their version requirements, features and the dependency's source bytes stay
unchanged. The unrelated registry 0.2.19 package remains separate. The earlier
clipboard-only `f9efec87ff9d5690b8c9fd23ea0c8f3535a9d8eb` candidate failed this
graph gate; its receipts remain evidence of that failure. The original
`native-clipboard-read.patch` bytes and default Git SDK are unchanged.

`native-ime-preedit.patch` is applied after those two unchanged patches. It
repairs two X11 issues observed together in the original private IBus/Orca
window: a candidate popup's `VisibilityNotify` was published as window focus
even though `XGetInputFocus` stayed on the same window, and the preferred
Position input style did not deliver callback preedit to the application's
composition guard. Visibility now reaches the normal paint path without a
synthetic focus notification. Real `FocusIn`/`FocusOut`, including their
existing grab/pointer filters, remain unchanged.

The candidate prefers callback preedit when the original XIM service supports
it. Callback caret updates send only `XNSpotLocation`, retaining the original
caret/DPI and above/below-screen placement calculation. The original libX11
[release history](https://sources.debian.org/src/libx11/2:1.8.12-1/README.md/)
records callback/OnTheSpot `XNSpotLocation` support in 1.8.2 and `XNArea`
support in 1.8.11; sending both to the observed 1.8.7 client rejects the latter.
Position retains its own spot/area update and remains a creation fallback,
followed by Nothing. These fallback styles still deliver committed text, but
cannot establish the callback-based composition qualification.

A refused callback caret update keeps the existing XIC and preedit; it never
switches a live composition to Position. Position's first spot-at-creation
refresh is limited to an inactive XIC. Unsupported callback placement must
remain an explicit runtime coverage gap, not a reason to discard composition.
The exact candidate still requires the original real IBus guard/commit/undo,
candidate placement inspection, focus, clipboard and Orca consumer gates;
this patch manifest grants none of those results.

The change adds one bounded, request-scoped clipboard read to the original
`CxOsOp` path and X11 connection. It returns a unique nonblocking ticket. It
never emits a global `TextInput` event or follows a later focused field. The
original UI must retain the requested room/editor/text-run identity and check
it again after the reply. One outstanding native read, a 64 KiB maximum, and a
two-second deadline bound the transport. Unsupported backends return
`Unavailable`; INCR and invalid UTF-8 are refused. Clipboard reading supplies
text only and carries no Hepta execution authority.

## Reproducible independent build source

The normal `native-presentation` feature stays on original SDK `337566c8` and
does not compile this clipboard API. The explicit `hepta-robrix-ui` feature
`native-clipboard-sdk` is required for this candidate. Desktop forwards it as
`trill-shell/hepta-native-clipboard-sdk` through the same original UI/core.
Only candidate nodes advertise the separate `PasteText` action. On the baseline
the standard EditableText PasteText method returns false and queues no request.

Use the existing original Git clone and the complete original `cargo metadata`
for the product's explicit candidate feature. Both metadata captures and every
candidate build/test must use that same feature. Metadata does not compile the
new API, so its first capture can still resolve the original upstream SDK:

```sh
cargo metadata --manifest-path /absolute/candidate-desktop/ui/Cargo.toml \
  --format-version 1 --features trill-shell/hepta-native-clipboard-sdk \
  > /absolute/original-native-metadata.json
```

Prepare the independent source and override:

```sh
python3 -B apps/hepta-control-ui/test/prepare-native-clipboard-sdk.py \
  --upstream-repo /absolute/existing/makepad-git \
  --destination /absolute/new/makepad-prepared \
  --metadata /absolute/original-native-metadata.json \
  --cargo-config-output /absolute/new-sdk-overrides.toml
```

The helper performs no network access, installation, Cargo cache writes, or
global configuration changes. It verifies the exact upstream, applies the
patch to a new checkout, and checks the complete staged Git tree. It generates
an explicit Cargo override for **every resolved SDK package** in the supplied
metadata. A platform-only override is invalid: sibling path dependencies would
otherwise introduce two distinct `Cx`/`Script` type sources. Invoke Cargo with
the generated `--config` only for this independent candidate.

After resolving the same features with that explicit Cargo configuration,
capture the complete candidate Cargo metadata, then run:

```sh
cargo --config /absolute/new-sdk-overrides.toml metadata \
  --manifest-path /absolute/candidate-desktop/ui/Cargo.toml \
  --format-version 1 --features trill-shell/hepta-native-clipboard-sdk \
  > /absolute/candidate-native-metadata.json

python3 -B apps/hepta-control-ui/test/verify-native-clipboard-sdk.py \
  --prepared-source /absolute/new/makepad-prepared \
  --original-metadata /absolute/original-native-metadata.json \
  --candidate-metadata /absolute/candidate-native-metadata.json \
  --cargo-config /absolute/new-sdk-overrides.toml
```

Save its JSON output as the candidate's SDK source profile. Verification checks
the actual prepared Git tree and files, all resolved SDK crate manifests and
versions, and every original SDK-to-SDK dependency edge. It rejects retained Git
copies, substituted path sources, missing UI feature and incomplete Desktop
feature forwarding; unrelated registry crates already present
in the original graph remain distinct. Product packaging
must record the original commit, patch hash, exact patched tree, override
configuration hash and actual resolved package manifests. Do not identify the
candidate as unmodified upstream or replace an existing product pin silently.

Keep the original SDK lockfile on the normal development branch. Resolve and
commit the path-SDK lockfile only on an independent candidate branch/worktree,
and retain its external override, source receipt and prepared source for every
`--locked` build. Never merge that candidate lockfile into the baseline, set a
global Cargo patch, or use `--all-features` as a baseline build shortcut. Normal
native builds use `hepta-native-makepad`; candidate builds use the explicit
clipboard feature and the generated config together.

`apps/hepta-native/resources/NATIVE-SDK-PATCH.json` separately binds the actual
original MIT license, exact source manifest, all four complete patches and this
provenance note. These seven files are installed under `dependency-notices/makepad/`; the
font resource inventory remains unchanged. The native UI exports the compiled
notice contract so startup can refuse a mismatched bundle.

This source profile is not compilation or runtime evidence. Native X11 build,
clipboard-owner timeout/oversize refusal, cross-room and IME fencing, original
undo/redo, and D-Bus PasteText readback must pass on the exact built source before
promotion. Wayland PasteText and physical assistive-technology evaluation remain
separate coverage.


## Native edit transaction candidate (reconstructed, unqualified)

The additional `native-ime-transactions.patch` opts the composer into typed
Preview/Committed/Cancelled outcomes under `native-ime-sdk` (also enabled by
`native-clipboard-sdk`). Legacy Changed remains available to other consumers.
The SDK mints an origin scope before production and records ordered snapshots;
the application binds that scope to one RoomKey. Rejected edits rotate scope,
invalidating already-produced successors. Cancellation restores the original
SDK text, selection and undo history rather than deleting the preview alone.

This is the native replace_last protocol, not mobile full-state/range sync;
those replacement events fail closed in scoped mode. Programmatic replacement
while scoped composition is active returns Composing, even outside the preview.
An in-field mouse/touch press during composition cancels only: after redraw a
new press can select. Programmatic set_selection cancels then selects, with its
actual before-state preserved if a later same-batch edit is rejected.

Scope fencing covers widget outcomes already produced. Origin-less late raw OS
IME commits cannot be attributed to an old session by this patch; platform/XIC
session fencing and the original libpinyin window remain separate qualification.

This source was reconstructed from retained editing commands after the local
working environment changed. It is not byte-identical recovery of the earlier
unpublished candidate. The current MANIFEST fixes its new source identity. No
Rust build or tests have run on this reconstructed candidate. The earlier
candidate stopped at missing wayland-client.pc before UI compilation, with zero
Rust/UI tests executed; its metadata verification is not transferred here.
The added real-SDK test source does not establish a passing compile, test run,
live input result, or product promotion. Preparation and actual dependency-graph
verification must precede a new qualified build using this exact source.
