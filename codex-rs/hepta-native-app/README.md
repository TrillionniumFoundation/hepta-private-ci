# Hepta Rust native application

`codex-hepta-native-app` is the selected desktop host for `ui.native`.
It uses **eframe/egui 0.36.2** for the native window and AccessKit semantics,
but it does not become a second runtime kernel: Agentd remains the lifecycle and
composition owner and Codex App Server remains the session/turn execution spine.

The older `apps/hepta-native` JavaScript package remains a bounded compatibility
and contract fixture while consumers migrate to this Rust host.

## Platform matrix

| Platform | Host | External effects | Self-update |
|---|---|---|---|
| Linux x86_64/aarch64 | Tier 1 | `FinalUseAuthority` + clipboard/open/reveal/notification | signed portable-binary replacement + predecessor rollback |
| macOS Apple Silicon/Intel | Tier 1 shell | `FinalUseAuthority` + clipboard/open/reveal/notification | portable developer flow only; notarized `.app` update remains a release gate |
| Windows 11 x86_64/aarch64 | Preview | runtime/window/read-only UI; effect path remains fail-closed while the kernel FinalUse state store has no hardened Windows implementation | fail-closed for the same reason; Authenticode/MSIX is a release gate |

Never weaken the Windows gate in this crate. The fix belongs in the canonical
`codex-hepta-contracts::FinalUseAuthority` durable state owner.

## Build

The workspace toolchain is Rust 1.95.0.

On Linux install the native eframe prerequisites used by CI:

```bash
sudo apt-get install -y \
  libxcb-render0-dev libxcb-shape0-dev libxcb-xfixes0-dev \
  libxkbcommon-dev libssl-dev libdbus-1-dev
```

Then:

```bash
cd codex-rs
cargo check -p codex-hepta-native-app --all-targets
cargo test -p codex-hepta-native-app
cargo clippy -p codex-hepta-native-app --all-targets -- -D warnings
cargo build -p codex-hepta-native-app --release
```

The package produces two binaries:

- `hepta-native` — the application/window host.
- `hepta-native-updater` — a narrow post-exit replacement helper. It accepts
  only `--job <absolute-path>` and re-verifies the signed job before replacing
  the running binary.

## Runtime composition

A normal launch points at one exact Agentd generation:

```text
hepta-native \
  --agentd-socket /absolute/run/agentd-control.sock \
  --agent-id 018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12 \
  --generation 7
```

`AgentdBackend` performs real bounded JSON-over-UDS requests for:

1. health,
2. session ingress,
3. capability negotiation,
4. lifecycle,
5. event cursor.

The native session fence binds Agentd identity, process generation, process
observation and session-ingress identity. A changed Agentd process/session
requires reconnect; it is never silently reused.

The application worker owns `NativeShellRuntime` off the UI thread. UI state
is presentation-only and contains no backend mutation authority.

## Operation identity and crash recovery

External effects use:

```text
(session_id, session_generation, operation_id)
```

as the durable identity.

Before an OS adapter is entered, `NativeShellRuntime` writes a bounded Pending
record to `KeyringOperationStore`. Only after that durable intent succeeds may
the effect be dispatched.

The store intentionally does **not** retain clipboard text, notification body or
other full effect payloads. It retains bounded identity/resource metadata and the
canonical payload digest.

Rules:

- an identical terminal operation returns its receipt;
- a pending/indeterminate retry calls `reconcile`, never `dispatch`;
- the same `operation_id` observed under another session/generation is fenced;
- restart loads pending records and reconciles them without replay;
- if the OS exposes no process-independent terminal receipt, the operation
  remains indeterminate rather than being guessed successful or retried;
- if the OS credential store is unavailable, the application can remain
  read-only but effect insertion fails before the adapter.

The current OS reconciliation surface can independently confirm a matching
clipboard value. Open/reveal/desktop notification do not expose a sufficiently
strong process-independent receipt, so they remain indeterminate after a lost
terminal observation.

## Final-use authority

Native OS effects consume the existing kernel contract:

```text
SignedFinalUseGrant
    -> FinalUseAuthority::claim(expected_binding)
    -> VerifiedUseToken
    -> FinalUseAuthority::with_verified_use(...)
    -> one OS adapter call
```

The adapter cannot mint its own token.

Launch with a pinned authority bootstrap:

```text
--authority-config /absolute/final-use-bootstrap.json
--authority-state-dir /absolute/private/final-use-state
```

Bootstrap JSON:

```json
{
  "schema_version": 1,
  "signer_id": "owner-configured-signer",
  "verifying_key_hex": "<64 lowercase hex characters>",
  "head": {
    "authority_epoch": 1,
    "revision": 1,
    "revoked_grant_ids": []
  }
}
```

`FinalUseAuthority` owns signature verification, current epoch/revocation state,
single-use nonce consumption and durable replay protection. The UI only accepts
an externally issued `SignedFinalUseGrant` and binds it to the exact action,
resource, session, operation, displayed revision and canonical payload digest.

Do not put signing private keys in the application, UI settings, updater job or
keyring operation journal.

## Platform adapters

Registered effect classes are deliberately narrow:

- `copy_text` — `arboard`;
- `open_path` — absolute existing path only;
- `reveal_path` — absolute existing path only;
- `notify` — desktop notification.

Platform commands are invoked as executable + separate arguments; no shell
command string is constructed.

Linux uses `xdg-open`, macOS uses `/usr/bin/open`, and Windows code is
present but cannot be reached through a valid FinalUse authority until the
Windows durable authority store is hardened.

## Signed updater

Launch with:

```text
--update-key-hex <64 lowercase hex characters>
--update-state-dir /absolute/private/native-update-state
```

A signed update manifest has this strict shape:

```json
{
  "schema_version": 1,
  "version": "1.2.3",
  "package_path": "/absolute/path/hepta-native.candidate",
  "package_sha256": "<sha256>",
  "predecessor_sha256": "<sha256>",
  "target_os": "linux",
  "target_arch": "x86_64",
  "backend_protocol_version": 2,
  "selected_by": "independent.reviewer",
  "generator_principal": "candidate.generator",
  "restart_args": ["--agentd-socket", "...", "--agent-id", "...", "--generation", "7"]
}
```

The detached signature covers a domain separator plus canonical JSON bytes of
the manifest and is stored in:

```json
{
  "manifest": { "...": "fields above" },
  "signature_hex": "<128 lowercase hex characters>"
}
```

Update admission verifies:

- Ed25519 signature against the pinned update key;
- exact current predecessor digest;
- candidate package digest;
- OS and architecture;
- backend protocol compatibility;
- independent selection (`selected_by != generator_principal`);
- bounded restart arguments.

On Unix the candidate and job are staged under a private same-user directory.
The helper re-verifies all signed inputs after the application exits, retains the
predecessor, replaces the binary, and invokes `--post-update-probe`. A failed
probe restores the predecessor and keeps the failed candidate for diagnosis.

A successful portable-binary update is not evidence of macOS notarization,
Windows Authenticode/MSIX qualification or release approval.

## UI and accessibility

The application exposes four pages:

- **Runtime** — Agentd session/generation/revision/digest and negotiated
  capabilities;
- **Operations** — FinalUse-bound effect request and durable operation journal;
- **Updates** — signed-manifest staging;
- **Settings** — platform matrix and runtime identity.

Keyboard navigation:

- `Cmd/Ctrl+R` refresh;
- `Alt+1..4` switch pages;
- `Esc` dismisses transient errors.

eframe's default native feature set enables AccessKit. All input controls receive
explicit semantic labels. The viewport uses logical points and lets the native
backend apply the OS scale factor for HiDPI.

The built-in locale layer currently supplies English and Chinese UI strings
based on `sys-locale` or an explicit `--locale` override.

## Qualification hooks

`--post-update-probe` performs a real Agentd connect + coherent view read and
exits without opening the window. The updater uses this hook before considering
a replacement healthy.

`--qualification-window-smoke` opens the real eframe window and requests close
after the first UI frame. Linux qualification runs it under Xvfb.

Focused source tests cover:

- no duplicate dispatch on retry;
- restart reconciliation without replay;
- cross-session operation fencing;
- same-revision digest drift rejection;
- missing FinalUse authority rejects before OS effect;
- real Agentd UDS request/response composition;
- update signature tamper rejection;
- failed post-update probe predecessor restoration.

Passing these tests proves the Rust source boundary. Signing/notarization,
packaged screen-reader acceptance, operator acceptance, promotion and release
remain separate evidence states.
