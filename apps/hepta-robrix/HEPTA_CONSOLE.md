# Hepta Console in the Robrix foundation

This is a work-in-progress Makepad port, not acceptance of the superseded egui UI.
The chat application is the pinned upstream Robrix application. Console is a
secondary dock tab; compact layouts expose the same widget through navigation.
The pre-login Console setup screen does not create a Matrix session or grant
console authority.

## Current implementation boundary

| Capability | Implementation | Qualification |
| --- | --- | --- |
| Robrix chat/login/rooms/timeline/composer | Preserved upstream Makepad sources, secure SDK migration in progress | Native/browser compile and rendered interaction qualification pending |
| Console dock and compact navigation | Makepad widget, persisted dock migration | 3 dock migration tests passed in the integrated source; rendered navigation pending |
| Read-only authenticated native status | Signed endpoint + explicit trust + existing keyring capability; `NativeShellRuntime` refresh/fences | 5 headless facade tests and 4 widget-owner lifecycle tests passed in the integrated source; no live accounts used |
| Browser console | Explicit unavailable state | Browser capability transport not integrated |
| Platform operations/confirmation | Not ported | Disabled; do not substitute an unsigned gateway mutation |
| Update preparation/activation/recovery | Not ported | Disabled; this application is not an updater candidate handoff entrypoint |
| Windows registrar / AuthBus repair | Paused independent work | Not touched; no qualification implied |
| Agentd conversation adapter | Separate authenticated backend exists | Not yet attached to the Robrix room model; never invent Matrix room IDs |

## Explicit read-only native configuration

Start with `--console-config /absolute/operator-owned/console.json`.
No default credentials, key generation, or Matrix-to-console authority conversion
exists. The selected JSON must use this schema and absolute paths:

```json
{
  "schema": "hepta.robrix-read-console.v1",
  "endpoint_manifest": "/absolute/signed-endpoint.json",
  "trusted_keys": "/absolute/trusted-keys.json",
  "state_dir": "/absolute/dedicated-read-console-state"
}
```

The dedicated state contains `read-console-journal.json`, not the legacy operation
journal or updater installation state. Existing pending platform effects are
rejected, never reconciled through a fake adapter. The facade exposes no mutation
method. Configuration loading, keyring access, authentication and network reads
run on one bounded background owner lane. Failed observations invalidate current
runtime presentation; the UI must not show an old observation as current.

Future operation and update ports must reuse the existing final-use, confirmation,
durable journal and exact connection-versus-state error boundaries. Disabled
features cannot be represented as accepted or completed. Existing qualification
receipts from the old UI remain historical and do not qualify this port.

## Scoped local evidence

The integrated Rust source at `f76086607` passed these checks on 2026-10-02:

- Headless `hepta-native --no-default-features --lib console::tests`: 5 passed.
- Actual Robrix `--features ui-fixture --lib hepta_console::tests`: 4 passed.
- Actual Robrix `--features ui-fixture --lib hepta_dock_tests`: 3 passed.
- Actual Robrix `--features ui-fixture --lib ui_fixture::tests`: 1 passed.
- Actual native Robrix `cargo check --features ui-fixture`: passed.

During the run the integrated branch advanced to `7c4b8e99`; the diff was only
qualification workflow/scripts, with no tested Rust or Cargo changes. These are
focused tests and typechecking, not rendered UI, login, screen-reader, installed
security, browser transport or production acceptance. Warnings in unrelated
native portal and browser-dispatch imports remain outside a strict lint claim.
Local linking used workspace-only development links to installed OS libraries;
no system files/settings were modified. Hosted qualification installs official
development packages and is the authority for actual Xvfb/native pixels.
