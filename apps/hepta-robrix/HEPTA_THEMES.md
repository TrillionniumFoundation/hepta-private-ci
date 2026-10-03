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

## Adaptive destination and media follow-up (runtime not yet accepted)

The real Dock-load regression reproduces Console selecting Home after a compact
transition. Applying the authoritative Console selection after loading the tree
passes both that regression and the actual wide/compact/short/wide CUA replay,
with a clean runtime log. Home selection is unchanged.

The production fixture image previously drew at0x0. Keep its finite Fill width
and bound the actual Image.walk height; the real drawn-geometry regression now
requires positive size within320x96. Actual native pixels confirm the image.
Compact RoomScreen uses its existing stack Back/title header once, removing the
redundant78px title. Fixture branding explicitly says SAMPLE at every width.

Twenty scoped app tests pass. Continuous chat replay still fails acceptance:
Research selected on mobile becomes the older saved Design Lab on return to
wide, and the fixture draft is lost because its account-free path bypasses the
production TimelineUiState owner. No claim of SDK draft loss or preservation is
made from that fixture limitation. A separate stale-sublist error appears in
OpenGL render_view only on compact-to-desktop restoration, despite readable
pixels. The strict native diagnostic gate rejects it. Preserve the Console-only
success separately; fix the actual retained draw-tree owner before accepting
chat resize. No renderer diagnostic is suppressed.

The next owner-level Dock repair closes the retained-sublist runtime failure:
normal and preserving-items layout replacement detach only their own old tab
content draw lists before dropping the tab bars. The original renderer and
generation diagnostics are unchanged. Two real drawn-Dock tests are red before
the repair and green after it; unrelated live sublists and stable tab body IDs
are preserved. Sixteen framework tests and the strict log gate pass. The exact
native wide→compact Research→short→wide replay now has zero generation errors.
`qualification/native-dock-retirement.json` binds source, binary and before/after
logs. The separate destination mismatch remains visible and unaccepted.

## Current-room adaptive handoff and synthetic owner evidence

The subsequent repair selects the newest canonical destination at the new
Dock's actual load boundary. Its one-shot intent is bound to the current
account/epoch, cleared at login/logout/state restoration, and deferred under
an active modal. Stale target widgets cannot consume it; ordinary later room
navigation wins. Selected thread state is retained through adaptive ownership
transfer, while obsolete mobile history is retired through the existing path.

The explicit account-free chat fixture now uses the real TimelineUiState store,
SavedState and RoomInputBar restoration. It has no Matrix client, SDK timeline,
request consumer, subscription, task, send context or media request sender.
The fixed synthetic drafts are never submitted. Real tests reproduce and fence
two stale-return cases: an old dropped owner must not resurrect a cleared draft,
and must not replace a newer owner marker or parked draft. Matching current
owners still return state normally. Cursor/selection and repeated thread-state
handoff are checked, without claiming SDK reply/edit or network acceptance.

Actual native wide→compact→Back→Research→short→wide replay now retains separate
Design Lab and Research drafts. Returning to Design Lab restores its own draft;
Console adaptive return stays unconfigured, and the canonical fixture room order
survives its real filter action. `qualification/native-adaptive-handoff.json`
binds this replay to the built binary and strict runtime log. A new browser
continuous replay observes the actual selected Dock/stack owner and checks the
same destination/draft/authority contract; its hosted outcome is pending.
All three material replicas remain visually in progress.

## Verified adaptive browser result and material refinement

Exact f4b2a57e qualification37110627397 passed native and browser. The browser
artifact ZIP, exact source/tree/app-tree and all99 included file hashes/set
were independently verified. Its11-step continuous trace retains two separate
fixed drafts through real Dock/stack owner handoffs; compact→short retains the
same editor, while a new adaptive owner restores the saved state. Three actual
wide/short/restored-room PNGs visibly confirm the drafts. Login's7 checks and
all3 pointer/1 keyboard theme checks pass. This does not qualify live SDK
reply/edit or delivery. `qualification/adaptive-f4b2a57e.json` records the scope.

The next material stage differentiates selected tabs (Titanium cyan underline,
Prism lilac face, Ceramic amber top seam) and room selection edges. Existing
reply-preview content gains a recessed Rust panel inside its cached content,
so ordinary and collapsed previews share the material without changing their
collapse/action owner. Actual native inspection caught and rejected an initial
texture-only approach that painted no card for ordinary short previews.

Application-owned SVG icon color now has an explicit shader hook. A real
before/after shader-identity test catches the earlier untagged DrawSvg fallback;
all runtime style helpers must preserve owned face/icon shaders. User SVGs,
explicit avatar colors and image textures remain outside these inputs. The
composer's real enable/disable routine clears its disabled accent border and
uses a distinct foreground-on-accent token; no send capability is added.
Synthetic geometric avatars and the sample reaction symbol use Rust SDF, not
missing font glyphs. The original approved space texture is only a Titanium
rail decoration under real Rust controls, with source/package SHA validation.

The default sidebar is246px, without overriding a user's saved Dock layout.
Two-line previews reserve their line budget in the actual Html/Label widgets;
new browser geometry evidence must show all six fixture previews unclipped.
The earlier f4 browser clipping remains a real failed visual case until new
hosted pixels verify this change. Detailed material/reference fidelity and
broader accessibility remain in progress.

## Delayed-font rich-text correction (hosted proof pending)

58a94b59 passed both jobs, and both ZIPs plus all77 native/99 browser included
hashes and exact sets were verified. All18 main A/B/C chat PNGs were inspected.
The browser's first-line snippets improved, but Foundation's wrapped second line
remained visibly sliced. A fully visible34px Html box was insufficient evidence;
that visual case remains failed in the preceding result.

Pinned TextFlow had a second permanent per-style metrics cache. A real delayed
font response left it at(0,-0), while a fresh TextFlow saw(0.92499983,0.27499998).
A real Html test also handed DrawText row height0 instead of14.879999. Both are
red on the original cache and green when the probe uses DrawText's existing
bounded, font-revision-aware layout cache. Ready-font shared-cache reuse,
two-line wrapping, body contents and native glyph offsets are preserved. The
native glyph-offset comparison alone was already green before the repair due
to the Linux batching path; it is not claimed as the browser pixel reproduction.

The unchanged old native/browser PNGs now form a pixel regression outside all
application resource paths. Using measured fixture geometry, native's first
ink starts2.7px below the box top; browser's starts9.7px below it and is rejected.
Fresh native/browser captures must check actual high-contrast ink rows, complete
two-line sample text, and real TextFlow row metrics. Existing container, font,
login, focus, draft, theme, resource and zero-error gates remain. Independent
later captures are preserved even when an ink check fails; failure is not waived.

The same read-only observer is enabled only in explicit account-free native
fixtures as well as browser fixtures. It exports geometry/metrics and fixed
sample-state comparisons, never text content or actions. The new core patch is
exact-SHA guarded and fresh-original application matches the compiled bytes.
Local18 framework tests, native build/runtime checks and44 script tests pass;
the full app suite and final web pixel verdict require the new hosted run.
