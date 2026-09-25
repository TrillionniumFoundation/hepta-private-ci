# Hepta Native

Long-running refresh, reconciliation, final-use execution and update staging run
through one serialized worker slot so the native event loop never performs those
I/O operations directly.

`apps/hepta-native` is the canonical Rust desktop shell for `ui.native` on the
`work/ui-native-current-source-20260925` convergence line. The branch contains
the actual eframe/egui/AccessKit application, not only the history of PR #830.
The retired JavaScript `native.js` and `shell-runtime.js` surfaces are not
product entrypoints.

The shell is deliberately not a second execution spine. Runtime facts come
from the loopback-only `codex-hepta-native-gateway`; final-use authority comes
from `kernel.authority`; domain state remains with its existing owners. The UI
owns only presentation state, a bounded durable local-operation journal, opaque
session references and the updater state machine.

Repository source now composes:

- signed endpoint discovery and OS-keyring bearer authentication;
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
