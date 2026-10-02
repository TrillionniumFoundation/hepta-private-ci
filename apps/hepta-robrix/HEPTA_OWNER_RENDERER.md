# Owner-backed native presentation

The pinned Makepad 493d23a normal target uses retained Robrix Root/Window,
navigation, PortalList, controls and resources. The Cargo graph omits the
upstream Matrix client, login, SQLite, credential and model owners. Exact
upstream provenance is recorded separately; unused application modules are not
shipped. Agent conversations use the original finite shared chat protocol.
NativeShellRuntime retains the original OS keyring, private recovery references,
Fleet pending receipts, platform final-use guards and Console controls.

Chat needs a separately enrolled Root bridge and chat-purpose key. Send persists
its original intent before invoking the owner. Lost acknowledgements retain that
intent; inspection only queries the original operation. Unknown conversation
creation, resume or cancellation currently have no receipt query and remain
blocked rather than replaying. The UI cannot authorize model or runtime effects.

Build the normal binary with `MAKEPAD_PACKAGE_DIR=resources` and use
`package_renderer.py --makepad-source CHECKOUT --binary ELF --output NEW_DIR`.
The script stages presentation resources and full licenses beside the normal
ELF; it does not install or configure services. Packaged launch anchors its cwd
to its executable directory. Root installation must retain the staged immutable
bundle and separately pair the original gateway/keyring configuration.

The original default renderer remains the admitted updater and platform entry.
This renderer exposes Chat and the existing Start/Stop/Restart/Inspect Console;
its unsupported updater handoff remains explicit. Native protocol tests and
an unconfigured X11 window are not proof of a live model conversation.

Both renderers read the original `--config` file. The optional
`chat_keyring_account` selects the independent Chat-purpose account; it contains
an account name, never the capability value. The original lifecycle account,
signed endpoint manifest, final-use authority and private state directory retain
their meanings. Only one renderer may hold that directory's recovery locks.

The normal Linux target links X11/Xcursor, ALSA/PulseAudio, OpenSSL 3,
xkbcommon and Wayland client/EGL libraries. Build hosts need their development
packages and an ordinary Rust/C toolchain. The packaged target has been checked
on an unprivileged X11 display with separate explicit test inputs, including
Chat/Console navigation and resource loading. A Wayland session and connected
installed conversations require their own acceptance; they are not inferred
from compilation or the X11 result.
