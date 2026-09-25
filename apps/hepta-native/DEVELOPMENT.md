# ui.native current-source development guide

## 1. Candidate identity and claim boundary

The single convergence candidate is
`work/ui-native-current-source-20260925`. It descends from the initial
convergence ancestor `7ddbfac88525196e7a4b31387ceae194958275f5` and is merged
with current `main`; every qualification run records the exact current-main base
rather than treating the initial ancestor as the active integration base. The
Rust application was recovered from PR #830 source commit
`3198549d80d6c59887b82e2c50018ab818217c53`, then reviewed against the current
owner contracts. A merged historical branch is not implementation delivery;
the files, locks, maps, tests and qualification receipts for the present
candidate are the delivery identity.

`CURRENT_SOURCE.json` records SHA-256 fingerprints for the native application
and the exact current-owner integration surfaces used by it: the native gateway,
kernel final-use store, Windows private-state helper, Cargo locks and native
workflow. The file deliberately excludes itself. Qualification separately
records the checked-out commit, tree, main base and deterministic merge commit.
A missing fingerprint, dirty worktree, unlocked dependency resolution, failed
or skipped check is not a pass.

This guide distinguishes four states:

1. **source-composed** — the implementation exists in the named candidate;
2. **exact-head qualified** — the committed candidate executed its checks;
3. **merge qualified** — the deterministic current-main merge executed them;
4. **physically accepted/released** — external host, signing and operator gates
   were independently observed.

The present source may advance state 1 and, through retained CI receipts, states
2–3. It does not self-assert state 4.

## 2. Product and owner topology

`src/main.rs` is the only desktop product bootstrap. It constructs:

- `LoopbackGatewayBackend` from a verified signed endpoint manifest and an
  OS-keyring bearer capability;
- `NativeShellRuntime`, which owns one session/view state machine and its local
  operation lifecycle;
- `OperationJournal`, which owns only native dispatch/recovery facts;
- `PrivateStateRoot`, which fail-closes local journal/update state when its
  no-follow ownership, Unix mode or Windows protected-DACL identity changes;
- `KernelFinalUseGate`, which consumes `kernel.authority` and cannot mint grants;
- `SystemPlatformAdapter`, an additional local policy ceiling around OS effects;
- `UpdateManager`, which owns signed staging and recovery metadata; and
- `HeptaNativeApp`, the eframe/egui presentation with AccessKit integration.

The GUI owns one background-task slot for runtime refresh, reconciliation,
final-use effect execution and update verification/staging. Each click freezes an
owned request before handing it to the worker; the event loop only polls cached
outcomes and remains responsive while network, OS-adapter or package I/O is in
flight. The worker locks the same `NativeShellRuntime`; it is not a second owner
or execution spine. Competing effect/update buttons remain disabled until the
single task resolves.

The read-only `codex-hepta-native-gateway` remains the runtime adapter. The
native product uses **protocol 2 / `keyring_mac_v2`**, not bearer disclosure.
A fresh request nonce, exact route, short validity window and authenticated
server incarnation bind each request; the response proof binds the originating
request, status and full body. Both directions use the existing keyring secret
without placing that secret on the wire. Unknown/missing proofs or a signed
manifest for another version fail closed before session construction.
See [the exact v2 wire contract](../../docs/modules/ui.native/GATEWAY_V2.md).
Legacy bearer consumers remain separate and cannot be a fallback for this GUI.
Every accepted connection receives a fresh CSPRNG-derived session incarnation.

The UI never becomes the writer of runtime, model, memory, authority or release
facts. `codex-rs/hepta-private-state` is a Windows durability/ACL implementation
inside the existing `kernel.authority` owner, not a new authority module.

## 3. Ordinary authenticated startup

### 3.1 Build the three product binaries

From the repository root:

```sh
cargo +1.95.0 build \
  --manifest-path apps/hepta-native/Cargo.toml \
  --locked --release --bins
```

The release directory contains:

- `hepta-native` — GUI product process;
- `hepta-native-credential` — keyring capability provision/delete helper; and
- `hepta-native-updater` — separate replacement/rollback helper.

### 3.2 Provision the loopback shared capability

Choose a bounded stable account name and provision it once through the OS
keyring. The helper prints the account and token digest, never the bearer:

```sh
apps/hepta-native/target/release/hepta-native-credential \
  provision gateway.local
```

The same owner is available through the existing Hepta binary or a thin,
standalone gateway entry. The latter does not create state or another owner:

```sh
cargo +1.95.0 build --manifest-path codex-rs/Cargo.toml --locked \
  -p codex-hepta-native-gateway --bin hepta-native-gateway
codex-rs/target/debug/hepta-native-gateway \
  --listen 127.0.0.1:7373 --state-root /absolute/owner-provisioned-state \
  --auth-keyring-account gateway.local
```

The existing Hepta invocation is:

```sh
hepta --serve-ui \
  --listen 127.0.0.1:7373 \
  --auth-keyring-account gateway.local
```

The gateway refuses non-loopback or port-zero listeners, missing/duplicate
accounts, missing keyring entries and malformed bearer capabilities. It exposes
only authenticated `GET /`, `GET /healthz` and read-only runtime status. At most
64 loopback connections may execute concurrently; excess accepted sockets are
dropped before a request task is allocated, while each admitted request remains
bounded by header size and read/write deadlines.

### 3.3 Supply signed endpoint and trust material

The GUI requires absolute paths to:

- a trusted Ed25519 public-key set;
- a signed `hepta.endpoint-manifest.v1` binding endpoint ID, loopback address,
  protocol version **2**, keyring account, issue/expiry times and key ID; and
- a private state directory.

The endpoint account must be the same account provisioned above. The final
`--state-dir` component is created or reopened as a current-principal private
root: owner mode `0700` with no-follow opening on Unix, and a protected local
DACL with no reparse point on Windows. Missing, redirected or permission-drifted
state roots fail startup or the next journal/update transition. Private signing
keys do not belong in the repository, UI state directory or keyring session
record.

A normal read-only start is:

```sh
apps/hepta-native/target/release/hepta-native \
  --endpoint-manifest /absolute/config/endpoint.json \
  --trusted-keys /absolute/config/trusted-keys.json \
  --state-dir /absolute/private/hepta-native-state
```

Platform mutations additionally require an independently configured kernel
final-use owner and explicit local ceilings, for example:

```sh
apps/hepta-native/target/release/hepta-native \
  --endpoint-manifest /absolute/config/endpoint.json \
  --trusted-keys /absolute/config/trusted-keys.json \
  --state-dir /absolute/private/hepta-native-state \
  --final-use-authority /absolute/config/final-use-authority.json \
  --allow-root /absolute/approved/root \
  --allow-clipboard \
  --allow-notifications
```

Omitting `--final-use-authority` preserves read-only product startup and causes
effect requests to end as no-dispatch rejection. Local flags are ceilings, not
authority: they never replace a valid, current, exact-binding final-use grant.

### 3.4 Ordinary launch configuration and diagnostics

The installed desktop entry can now read an operator-owned JSON config rather
than requiring terminal-only bootstrap. Use `--config /absolute/config.json`, or
launch without arguments to read the platform default:

- Linux: `$XDG_CONFIG_HOME/hepta-native/config.json`, otherwise
  `$HOME/.config/hepta-native/config.json`;
- macOS: `$HOME/Library/Application Support/HeptaNative/config.json`;
- Windows: `%APPDATA%/HeptaNative/config.json`.

```json
{
  "endpoint_manifest": "/absolute/config/endpoint-v2.json",
  "trusted_keys": "/absolute/config/trusted-keys.json",
  "state_dir": "/absolute/private/hepta-native-state",
  "allow_clipboard": false,
  "allow_notifications": false,
  "allowed_roots": []
}
```

Optional `final_use_authority`, `updater_helper` and `font_file` values are
absolute paths. JSON is bounded to 64 KiB, rejects unknown fields and never
follows a final-component symlink/reparse point. A FIFO cannot hold startup
indefinitely. The expanded effective configuration is frozen into the restart
handoff; changing the original config file cannot silently change the pending
update's authority or endpoint.

`hepta-native --config /absolute/config.json --check-connection` executes normal
signature/keyring/gateway/session/view bootstrap and closes the session without
creating a GUI. Its redacted observation explicitly says `gui_observed=false`.
It is not a static smoke test, and it is not sufficient to confirm an update.

A normal GUI emits `last-startup.json` only after an authenticated coherent view
and its GUI frame callback. This records elapsed time, session, view revision and
digests, not domain payloads. A callback is not physical rendering, screen-reader
acceptance or release evidence; those fields remain false. Optional local CJK
font fallback is loaded from `--font-file` or known system locations, with a
32-MiB bound. Font files are not embedded in or redistributed with this project.

## 4. Operation identity, concurrency and recovery

The operation key is:

```text
(endpoint_id, session_id, session_generation, operation_id)
```

The semantic record also binds subject, displayed revision, action/destination,
canonical serialized payload digest, exact final-use binding and grant digest.
An identical retry returns the existing record; reuse with changed semantics is
a conflict. A new session generation cannot consume an old generation receipt.
Owned Rust values are validated before asynchronous work, so platform permission
and invocation cannot observe different caller-mutated JavaScript objects.
Journal and updater operations revalidate their private state roots before local
state transitions; a changed root is not treated as a new empty store.

The journal phase machine is monotonic:

```text
Prepared -> Invoking -> Indeterminate -> Terminal
                 \---------------------> Terminal
Prepared ------------------------------> Terminal
```

`Invoking` is persisted and fsynced before the adapter boundary. Once an effect
may have entered the adapter, restart/retry never invokes it again. Only the
adapter's reconciliation path may move an uncertain operation to terminal.
Persistence failure poisons the journal owner until reopen; it is never
reinterpreted as a known no-effect result.

Journal schema v3 retains at most 4096 active records and 8 MiB. Terminal
compaction moves exact operation identities into a sorted, durable,
domain-separated SHA-256 retirement frontier instead of forgetting them. A
retired identity is rejected before permission, authority claim or dispatch,
including after full process restart and even if a caller changes payload
semantics. Legacy v2 journals open read-only-compatible and migrate to v3 on the
next persisted change. Duplicate, malformed or active/retired-overlapping
frontiers fail closed.

The exact retirement frontier is bounded at 32768 entries. Reaching that ceiling
fails closed; this is deliberate evidence that a later sharded/epoch retirement
format needs an explicit migration rather than silent resurrection.

## 5. Final-use and local platform boundary

For a mutation, the order is:

```text
durable Prepared
-> kernel final-use claim for the exact binding
-> durable Invoking
-> current verified-use fence immediately before physical entry
-> local path/clipboard/notification policy
-> OS adapter
-> durable observation or indeterminate reconciliation state
```

The kernel owner preserves signature, principal, session, action, destination,
payload, epoch, expiry, revocation and single-use nonce semantics. Unix uses the
existing owner-only/no-follow state store. Windows uses
`codex-hepta-private-state`, which accepts only absolute local-drive roots and
validates directory and per-file owner SID/DACL, reparse-point absence, file
identity and durable replace operations.
Both use the current v3 authority snapshot and append-only nonce log; neither
falls back to a UI-local signer or weaker replay registry.

Open/reveal/notification launchers are bounded to four concurrent child
processes and a one-second observation window. A timeout kills/reaps the child
where possible but remains **indeterminate**, because process termination does
not prove the OS did not accept the request. Such an operation is not replayed.
Clipboard may become terminal only after immediate readback matches. Windows
notification remains disabled until a packaged AppUserModelID/WinRT identity is
available; a generic command launch is not treated as notification success.

## 6. Signed updates and recovery

`SignedUpdateManifestV1` binds stable channel, package and predecessor digests,
platform, architecture, backend protocol, evidence digest, independent selector
and generator, issue/expiry times and signing key. Selection and generation
principals must differ.

The GUI verifies/stages the package, atomically records pending state and closes
before the independent updater begins. The helper re-verifies the signed package
and installed predecessor, preserves executable permissions, and replaces via
atomic copy. A separate runner lock serializes activation/startup recovery; the
existing short state-transition lock remains the transaction owner.

`ActivatedUnconfirmed` is **not** cleared by `--self-test`, exit code zero or a
caller-supplied file digest. The helper restarts the normal product with frozen
arguments and a random, argument-bound handoff. The new process must authenticate
its endpoint, retrieve a coherent runtime view and enter the GUI callback. Only
that installed process can persist `Confirmed` with its actual PID, session,
view identity and candidate digest. Linux hashes `/proc/self/exe` to bind the
loaded inode rather than a replacement at the same path. The helper observes
that exact receipt and acknowledges over a private inherited pipe. Parent loss
before acknowledgement or a 35-second watchdog ends the unconfirmed child.

The helper's readiness budget is 30 seconds. Failure or early process exit,
including exit code zero, requires observed child termination before rollback.
Missing/bad predecessor evidence, copy failure or unsafe reads become durable
`RecoveryRequired`; unresolved state cannot be cleared. An unrelated newer
installed binary is not overwritten by stale recovery. A rolled-back predecessor
is relaunched explicitly; an already-running candidate cannot continue normally
after its on-disk binary has been rolled back. Confirmed records remain queryable
and duplicate helper invocation does not reinstall the candidate.

Platform signing and notarization are separate from these source mechanics.
The gateway and endpoint manifest must remain compatible across rollback. The
v2 endpoint change is explicit: an old v1-only GUI needs an independently selected
v1 configuration, not an automatic downgrade of the security boundary.

## 7. Development, lock and package commands

The app pins Rust 1.95.0 and commits both the standalone native lock and the
current root workspace lock. Run:

```sh
cargo +1.95.0 fmt --manifest-path apps/hepta-native/Cargo.toml --check
cargo +1.95.0 clippy --manifest-path apps/hepta-native/Cargo.toml \
  --locked --all-targets --all-features -- -D warnings
cargo +1.95.0 test --manifest-path apps/hepta-native/Cargo.toml \
  --locked --all-targets

cargo +1.95.0 fmt --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-native-gateway -p codex-hepta-contracts \
  -p codex-hepta-private-state --check
cargo +1.95.0 clippy --manifest-path codex-rs/Cargo.toml --locked \
  -p codex-hepta-native-gateway -p codex-hepta-contracts \
  -p codex-hepta-private-state --all-targets --all-features --no-deps \
  -- -D warnings
cargo +1.95.0 test --manifest-path codex-rs/Cargo.toml --locked \
  -p codex-hepta-native-gateway -p codex-hepta-contracts \
  -p codex-hepta-private-state --all-targets --all-features
```

Build and validate an unsigned development package with:

```sh
python3 apps/hepta-native/tools/package_unsigned.py --self-test
python3 apps/hepta-native/tools/package_unsigned.py \
  --platform linux \
  --architecture x86_64 \
  --release-dir apps/hepta-native/target/release \
  --out-dir native-package
```

Use `macos` or `windows` on those runners. The packager emits a deterministic
ZIP, validates and extracts that ZIP into a fresh root for packaged-binary smoke,
records every binary digest, and emits a receipt that keeps
`productionSigningObserved`, `notarizationObserved` and `releaseAuthorized`
false. Package creation is not release selection.

## 8. Qualification and evidence

The branch workflow checks both exact candidate and a deterministic synthetic
merge with current main on Ubuntu 24.04, macOS 15 and Windows 2025. Each matrix
leg independently runs app and owner-integration format, strict Clippy and tests,
then builds release binaries, executes `--self-test` and
`--qualification-e2e`, creates the platform package and re-runs the packaged
binary from the freshly extracted ZIP. Failures and skipped steps are retained
as outcomes; an earlier lint failure must not be converted into a downstream pass.

`--qualification-e2e` uses isolated product state and deterministic fake backend
or platform observations. It exercises authenticated view composition,
generation fencing, permission denial, live final-use revocation, actual child
process death after durable `Invoking`, updater child death, predecessor restore
and durable `RecoveryRequired`. It does not invoke real user OS effects.

The workflow records wall-clock build/package/smoke durations and artifact sizes
as measurements. They are not target-host acceptance thresholds. Current source
fingerprints, commit/tree/base/merge identities and per-check outcomes travel
with each artifact.

## 9. Remaining independent gates

Repository source and CI cannot self-issue:

- Apple Developer ID custody and notarization;
- Windows Authenticode and installed AppUserModelID/notification identity;
- Linux distribution signing or repository ownership;
- physical keyboard, screen-reader, Chinese IME, focus-restoration and
  multi-monitor DPI acceptance;
- observed terminality for OS facilities that expose no transaction query;
- sustained target-host startup, RSS and interaction acceptance;
- independent release-channel selection, operator acceptance, promotion or
  release authority.

These remain false until separately observed. Source composition, green CI and
an unsigned package must never be used as substitutes for them.

## 10. Native graph and ordinary Linux product qualification

Local tests use nextest through the repository recipe. The standalone native
graph has its own config, avoiding workspace-only package selectors:

```sh
just test --manifest-path ../apps/hepta-native/Cargo.toml --locked --all-targets \
  --config-file ../apps/hepta-native/.config/nextest.toml --retries 0
```

`tools/linux_product_qualification.py` requires an isolated `dbus-run-session`
and Xvfb environment. It uses the verified extracted unsigned package, real
keyring provisioning, the normal gateway entry opening a private schema-v5
owner-format fixture, ordinary connection diagnostics, and two real GUI starts.
It checks visible-window creation, keyboard-event delivery, fresh sessions and
unchanged owner database/snapshot bytes. It deletes its random test keyring
account and secret fixture material. This is an executable CI qualification
case, not physical screen-reader/IME/DPI/long-run or independent acceptance.

New negative suites cover server spoofing, response substitution, version drift,
request replay, bounded HTTP/JSON, argument-bound restart, zero-exit-without-
readiness, rollback failure and executable permissions. Keep exact-head and
synthetic-merge receipts separate and never count skipped tests as passes.
