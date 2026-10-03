# Hepta chat materials: first implementation stage

One real Robrix Rust/Makepad widget tree now has three selectable materials:
Deep Space Titanium, Polar Prism (default), and Obsidian Ceramic. The selector
is in the chat chrome, above the existing dock; Console remains a secondary dock
tab. App/HomeScreen/RoomsSideBar/RoomsList/RoomScreen/PortalList/Message and
RoomInputBar still own the interaction. There is no DOM or alternate renderer.

The generated concepts are visual direction, not screenshots used as UI. Opaque
SDF surfaces, different corner radii/edge weights/sheen, an orbital horizon,
prism facets and a ceramic seam are drawn in Rust. Text, error, disabled, focus,
selection, code, context menu and input roles were adapted for dark surfaces.
Provider artwork, user media and rich-text colors remain their own content.
Only explicitly tagged Hepta material shaders participate in palette resolution;
matching bytes in arbitrary shader uniforms, vectors, images or avatars do not.

Theme selection changes paint data and the existing AppPreferences field. It
never reapplies/recreates the widget tree or replaces chat/auth/Console owners.
Preferences use the existing account-scoped serialization and persistence/error
path; missing/unknown theme values fall back to Prism. Fresh signed-out startup
uses Prism until account preferences are restored. A separate signed-out global
preference store is not implemented, and browser window-state persistence remains
the existing no-op. TSP and other unsupported platform features remain unsupported.

## Account-free comparison

Build with `ui-fixture`, then select exactly one explicit mode:

- native: `--hepta-ui-fixture chat-titanium`, `chat-prism` or `chat-ceramic`
- browser: `?hepta-ui-fixture=chat-titanium`, `chat-prism` or `chat-ceramic`

These feed synthetic room-list data and message content into the production
widgets. Startup returns before Matrix, keyring and Console owners. The composer
is a real editable RoomInputBar with no timeline/send context; it cannot deliver
messages. The persistent room header identifies the fixture. No sample members,
connectivity or encryption state are presented as live service observations.

## Evidence and remaining gates

Locally: actual application type-check; 16 focused application tests including
full template error capture, real TextInput identity/text/cursor/selection,
material-slot ownership and palette/radius switching; 35 qualification-script
tests. Three focused tests exercise real drawn navigation stops: initial/ordered
forward/reverse/wrap, empty tree, and blocked modal scope. The source-equivalent
previous traversal fails initial/wrap and modal-scope checks; the new traversal
passes. The pinned framework patch keeps exact original-source SHA guards.

The earlier e861 browser receipt established initial Tab stalling, skipped SSO
stops and non-wrapping endpoints. `qualification/usability-e861.json` records
verified evidence; it is not a current pass. SSO tiles now register real nav
stops, show focus, and route non-repeating key-up activation through the existing
busy/enabled handler. The original non-submitting browser usability gate remains.

Hosted native/browser captures now cover all three chat materials at 1180×760,
520×760 and 800×560 in addition to login/Console. The dark pixel check retains
opaque-footer, >=4.5 glyph contrast and <=3 px field-centering requirements.
Actual screenshots, full theme-switch interaction, active SDK reply/edit target
preservation, modal keyboard behavior, IME/accessibility and live Matrix flows
remain acceptance work. This stage is not a claim of completed visual recreation,
production readiness, live-account qualification or deployment.


## First pixel review and repair stage

`qualification/themes-1ee5455b.json` binds the inspected run to its ZIP and
screenshot hashes. Native's job passed but its log contained the same unbound
DrawSplitter shader as the failed browser Console capture. Native acceptance is
therefore rejected; the tightened gate permits only the known headless audio
fallback. Login font/typing passed, while strict browser navigation was not reached.

The repair reserves header/icon/subtitle geometry, aligns names and timestamps,
uses one quiet timeline plane, gives the real multiline composer more height,
and removes purple chrome from Titanium/Ceramic. Avatar fallback paint has its
own narrowly owned uniform; explicit avatar colors and images remain untouched.
The fixture now exercises production ImageMessage, reply-preview and reaction
widgets with synthetic content and no timeline/delivery authority. Native narrow
capture records the list then selects the real room with a pointer action.
Browser theme checks separately cover pointer-retained composer focus and
keyboard-retained selector focus, while comparing real editor identity, draft,
room/tab, fixture account and Console authority. No active SDK reply/edit claim is
made. New exact-source native/web captures and pixel comparison remain required.


## Second runtime review

`qualification/themes-d39edeae.json` records the exact d39 run. The splitter
shader is fixed. Browser forward/reverse traversal reaches every SSO/control,
but initial Tab selects the footer. Its Fit layout registers before the deferred
Fill login form. Initial selection now uses top-left geometry within the existing
active nav scope; established traversal and scroll-to-focus remain unchanged.
A real deferred-order test is red on the previous code and green on the repair.

A pointer theme click preserved real draft/editor/room/tab/account/Console state
but stole focus. The pinned Button's second unconditional focus assignment is
removed. The real App theme action also preserves a pointer-origin editor only
while room/tab/user/editor identity and current visible area remain valid, with
no modal lock or intervening keyboard/navigation/account event. Keyboard theme
activation keeps its own selector focus. Fixtures use Rust SDF symbols instead
of unsupported decorative font glyphs; previews and the real image widget have
bounded geometry. Actual rendered acceptance remains pending.

Native's tightened gate now exposes an older stale draw-list generation during
Console resizing. Its caller is not yet established. The exact-source patch adds
at most three truncated backtraces and retains the original error and failing
gate. Independent later scenes may still be captured for diagnosis, but any
recorded failure prevents a qualification pass. Ceramic was not reached in the
d39 browser run and has no accepted current pixel evidence.

## Third runtime review and bounded input repair

`qualification/themes-798a59c0.json` records the verified browser ZIP, all 86
included hashes, nine reviewed chat PNGs, and actual interaction traces. All
seven login usability checks and all three pointer theme switches pass. Keyboard
selection fails despite correct selector focus: pinned Button had no KeyDown or
KeyUp activation handler. The new handler uses the existing Button actions and
callbacks, arms once on Enter/Space and clicks on matching release. Repeats,
modifier shortcuts, lost focus, disabled/hidden/invalid areas, navigation and
modal-blocked input cannot activate an armed button. Five focused tests cover
these bounded contracts; this is not broad modal/accessibility certification.
The final guarded binary selects all three themes using keyboard only, with
visible selector focus and clean logs. Hosted browser checking remains required. Passed pointer focus/state logic is unchanged.

On the existing enabled native desktop, resize reproduces the exact stale-area
caller: ScrollBars::catch_fling_on_press read a retired DrawList before deciding
whether the event was even a press. The pinned repair rejects non-press and
invalid/freed areas before hit testing. Four real old/new regressions retain
valid mouse/touch fling-catching, and the repeated wide/compact/short/wide
runtime log is clean. Original diagnostics and strict gates remain intact.

That replay reveals a separate destination bug: returning to desktop selects
Dock Home while the navigation rail remains Console. An early canonical-action
attempt did not survive Dock rebuilding and was excluded, along with its
insufficient test. Home foreground now uses the owned contrast token. Adaptive
Console/room/thread ownership transfer needs a real replay-based repair.

The three materials still fail likeness acceptance. Browser room previews clip,
the reaction glyph is unsupported, the image fixture is absent, and default
profile/attachment accents retain purple in A/C. A numeric image-size attempt
did not fix actual pixels and was excluded. Native room previews and reaction
are readable, so native success must not substitute for browser acceptance.
