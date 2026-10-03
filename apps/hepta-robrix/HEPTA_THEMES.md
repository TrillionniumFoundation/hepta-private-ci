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
