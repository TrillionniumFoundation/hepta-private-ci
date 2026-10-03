# Hepta native platform and compatibility host

The canonical product UI is now the actual Robrix-derived Makepad implementation
in `apps/hepta-control-ui/rust/robrix-ui`. Native and Web compile its same Rust
widgets. Conversation navigation, timeline and composer lead the app; Console is
an internal tab. Follow the [shared design source](../hepta-control-ui/CHAT_DESIGN.md).

This crate preserves the previous egui/AccessKit host and validated native
platform/owner/recovery contracts for compatibility and composition work. It is
not the default product UI and its historical qualification does not qualify the
new Makepad host. Console operational widgets have not yet been ported into that
host. The implementation inventory below describes this preserved native layer.

The shell is deliberately not a second execution spine. Runtime facts come
from the loopback-only `codex-hepta-native-gateway`; final-use authority comes
from `kernel.authority`; domain state remains with its existing owners. The UI
owns only presentation state, a bounded durable local-operation journal, opaque
session references and the updater state machine.

Repository source now composes:

- signed endpoint discovery and OS-keyring mutual MAC v2 authentication (no secret on the wire);
- the read-only authenticated native gateway;
- session/generation/operation semantic fencing;
- durable `Prepared -> Invoking -> Indeterminate/Terminal` recovery;
- a durable exact retirement frontier for terminal-operation compaction;
- kernel-owned final-use claims with Unix and Windows durable stores;
- bounded local OS launchers and conservative indeterminate semantics;
- signed staged updates with predecessor fencing and durable recovery states;
- deterministic unsigned Linux, macOS and Windows development packages.

See [DEVELOPMENT.md](DEVELOPMENT.md) for architecture, configuration, normal
startup, failure semantics and qualification commands. Historical PR #830
remains available through Git history; this current guide, implementation map
and exact-candidate receipts are authoritative.

Source composition is not production acceptance. Platform signing and
notarization, installed notification identity, physical screen-reader/IME/DPI
acceptance, target-host performance, independent selection and release remain
separate gates and stay false until independently observed.


Ordinary installed launch supports `--config /absolute/config.json` or the
platform user configuration directory. `--check-connection` verifies the real
signed endpoint, keyring, gateway and coherent view without opening a window;
it is not update readiness. The product requires a signed protocol-v2 endpoint.
See `DEVELOPMENT.md` and `docs/modules/ui.native/GATEWAY_V2.md` for migration,
configuration, exact limits, normal-process update confirmation and test commands.
