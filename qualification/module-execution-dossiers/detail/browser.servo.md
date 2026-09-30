# browser.servo: execution dossier

Parent: `docs/modules/browser.servo/TECHNICAL.md`.  
Lane: `LANE-B-RUNTIME`.  
Work package: `BROWSER-WEB-C1`.  
Roots: `apps/hepta-browser`, `third_party/servo-patches`.

Status: the repository contains the seven-RPC durable Browser owner, committed b5a1 Servo lock and worker source, worker-side effect admission, bounded semantic observation, grant-scoped egress, signed persisted reconciliation, Linux containment source, two-builder/signed-provenance gates and a named long-lived Agentd Browser service. Exact-head/synthetic-merge success, signed artifacts from merged `main`, trusted target qualification, activation, independent acceptance, promotion and release remain separate.

## 1. Canonical identity

Selected Servo source:

```text
servo/servo@b5a1f5e6ec6f8685d40cd389802ced7abe4980f6
```

Canonical pin: `third_party/servo-patches/MANIFEST.json`.  
Canonical reviewed lock: `apps/hepta-browser/servo-worker/Cargo.lock`.

Machine truth:

- `docs/modules/browser.servo/GENERATED_SOURCE_REGISTRY.json` — exact seven RPCs, capability matrix and source-object hashes;
- `docs/modules/browser.servo/IMPLEMENTATION_MAP.json` — owner/callee/test mapping and claim boundary;
- `docs/modules/browser.servo/SERVO_CURRENT_PIN_TOPOLOGY.json` — pin, features and isolation topology;
- `docs/modules/browser.servo/SERVO_PIN_AUDIT.md` — upstream delta audit.

The registry is regenerated/checked by `apps/hepta-browser/scripts/generate-source-registry.mjs`. Pull-request prose and historical branch state are never capability evidence.

## 2. Closed operation set

The product operation set is exactly:

1. `open_profile`;
2. `admit_effect_grant`;
3. `observe_page`;
4. `navigate_or_act`;
5. `reconcile_operation`;
6. `reconcile_persisted_operation`;
7. `close_profile`.

Stable Browser owner entrypoints are the matching methods in `apps/hepta-browser/src/runtime.js`, delegated to `runtime-host.js`. Unknown/extra product operations fail the generated registry and implementation-map closure.

## 3. Current product-shaped composition

Browser-owned parent service:

- `apps/hepta-browser/src/agentd-protocol.js`;
- `apps/hepta-browser/src/agentd-service.js`;
- `apps/hepta-browser/src/agentd-service-main.js`.

Agentd-owned paths:

- `codex-rs/hepta-agentd/src/browser_servo_persistent.rs` — persistent port/control;
- `codex-rs/hepta-agentd/src/browser_revocation_feed.rs` — protected monotonic revocation feed;
- `codex-rs/hepta-agentd/src/bin/hepta-agentd-browser-service.rs` — named long-lived inherited-stdio service;
- `codex-rs/hepta-agentd/src/browser_servo.rs` and `hepta-agentd-browser` — legacy/diagnostic compatibility path.

The long-lived service retains one Browser control across bounded calls and has no network/UDS/WebDriver/CDP discovery listener. It is not automatically enabled inside the default Agentd daemon. A trusted supervisor/product process must explicitly start it with exact artifacts, authority state, revocation feed, profile/journal roots, observer policy and resource ceilings.

## 4. Effect transaction and final-use boundary

New effect transaction:

1. validate profile/principal/process/profile generation;
2. validate current page generation, document digest, page revision and actionable surface;
3. normalize the typed action and bind proposal provenance, destination, payload digest, effect grant, authority epoch and deadline;
4. Browser issues a request-digest/epoch-only authority challenge;
5. Agentd verifies the independently signed grant and enters live `FinalUseAuthority::with_dispatch_boundary`;
6. Browser binds the witness and fsyncs an indeterminate journal record;
7. Browser writes exactly one private worker command;
8. Servo dequeues and revalidates page/document/navigation/actionable state;
9. Servo reserves the operation identity;
10. Servo emits `dispatch_boundary` immediately before effect execution or a proven `dispatch_rejected { localDispatchCrossed:false }`;
11. Browser forwards the bound receipt and Agentd releases final-use authority;
12. page/remote/business terminality is persisted and reconciled separately.

A pipe write is not admission. Timeout before a proven boundary triggers child containment and remains indeterminate unless no-dispatch is proven. Crossed identities never regain dispatch authority.

## 5. Durable effect state

`FileBrowserOperationJournal` uses `hepta.browser.operation-journal.v2` and enforces:

- immutable semantic identity;
- exact duplicate no-op;
- terminal monotonicity and conflicting-terminal rejection;
- exact schema/field/checksum hydration;
- private non-symlink file and parent paths;
- file plus parent-directory fsync;
- crash-torn unterminated-tail repair before later append;
- I/O failure fencing;
- bounded index, line and file sizes;
- atomic compaction;
- crash-safe generation retirement/high-water;
- no generation resurrection;
- no persisted full typed action or raw sensitive payload.

The memory journal is test-only. A durable generation cannot be reopened as fresh, and unresolved effects block profile advancement/close.

Post-process-loss terminalization requires a signed `hepta.browser.persisted-effect-observation.v2` receipt bound to observer identity/generation/time/frontier and exact operation semantics. Wrong, stale, future, rollback, misbound or invalidly signed evidence leaves the operation indeterminate.

## 6. Semantic observation and action safety

The real worker emits bounded `hepta.browser.semantic-observation.v1` data: origin/revision, title, visible text, links, forms, visible actionable controls, bounded selectors, viewport and semantic/actionable digests. Password values, hidden controls, control values and raw HTML are excluded.

Before worker admission, Servo recomputes page/document/navigation/actionable state. Click/type/focus selectors must remain in the exact admitted visible surface. Disabled, invisible, password and non-text-entry targets fail closed. Every crossed effect invalidates the old observation and requires a new observation before another effect.

## 7. Network and profile isolation

Servo has no direct external route. A private profile channel reaches `GrantScopedEgressBroker`, which freezes granted DNS/IP answers, rejects private/special destinations, validates HTTP origins and HTTPS CONNECT/SNI, applies response/time/size bounds, and blocks redirect/subresource/profile-scope escape. Profile expiry and explicit close terminate worker and broker leases.

Each profile generation receives a fresh random directory and host-private ownership manifest bound to profile, principal, generation and grants. Real E2E checks cookie/localStorage/cache isolation and absence of non-loopback worker listeners.

## 8. Process isolation and capacity

Linux source controls:

- empty tmpfs root;
- cleared environment;
- Bubblewrap `--unshare-all` without shared network;
- narrow read-only runtime/font/CA closure;
- one private writable profile and one verified worker;
- exact Bubblewrap/`prlimit` executable digests;
- parent-death cleanup;
- default RLIMIT_AS 8 GiB, RLIMIT_CPU 300 seconds, RLIMIT_NOFILE 4096, RLIMIT_NPROC 256.

Current capacity:

- default 16 active profile-affine workers, hard ceiling 64;
- one WebView and one outstanding effect per current worker;
- 128 origins/profile;
- 1024 grants/profile;
- 64 queued mutations per serialization key;
- 256 KiB semantic observation;
- 1 MiB protocol frame;
- 64 MiB journal with early compaction;
- explicit driver/authority/channel deadlines.

The parent service remains one-in-flight. Pool capacity is not a claim of parent-RPC multiplexing.

## 9. Current capability matrix

Implemented/admitted:

- navigate;
- click;
- type;
- focus;
- scroll;
- wait;
- semantic observation;
- worker effect admission/rejection;
- grant-scoped egress;
- live and signed persisted reconciliation;
- Linux isolation source;
- persistent inherited-stdio Agentd service.

Fail-closed/not connected:

- credential;
- upload;
- download.

Out of current target scope:

- macOS isolation;
- Windows isolation.

## 10. Required source and composition verification

Browser required lane:

```sh
npm --prefix apps/hepta-browser run verify:registry
node --test apps/hepta-browser/test/*.test.js
node --check apps/hepta-browser/src/*.js
```

The Browser suite includes journal durability/monotonicity/crash cuts, admission/rejection, timeout containment, page/action-surface drift, egress policy, profile isolation, protocol closure, worker resources, signed persisted reconciliation and deployment-verifier Python syntax.

Agentd lane:

```sh
cd codex-rs
cargo fmt --package codex-hepta-agentd -- --check
cargo test --locked -p codex-hepta-agentd browser_servo --lib
cargo test --locked -p codex-hepta-agentd --bin hepta-agentd-browser-service
cargo check --locked -p codex-hepta-agentd \
  --bin hepta-agentd-browser \
  --bin hepta-agentd-browser-service
cargo clippy --locked -p codex-hepta-agentd \
  --lib \
  --bin hepta-agentd-browser \
  --bin hepta-agentd-browser-service \
  --no-deps -- -D warnings
```

The complete Browser source gate is a mandatory dependency of `CI required`. Global document/integrity, architecture, Lane-B exact-head and deterministic synthetic-merge gates remain required.

## 11. Artifact and target qualification

Primary worker workflow requires committed b5a1 lock, exact toolchain, feature audit, locked compile/tests, complete Browser tests, real sandbox/resource probe, same-runner deterministic rebuild, dynamic closure, real worker/E2E/soak, deterministic SPDX 2.3 SBOM and exact build receipt.

Independent workflow rebuilds exact source/lock/flags on a second ephemeral GitHub-hosted runner. On `main`, both workflows emit Sigstore/GitHub OIDC SLSA provenance; the primary also emits an SPDX 2.3 SBOM attestation.

The manual main-only trusted-target gate requires different successful primary/independent run IDs, byte-identical artifacts and cryptographically verifies exact signer workflow, source SHA/ref, SLSA provenance, SPDX predicate, non-self-hosted signing builders, certificate and transparency/timestamp witness. It then reruns sandbox, real worker, public HTTPS, profile isolation and 32-cycle RSS/FD soak on the selected host.

A target receipt is evidence only. It leaves operator acceptance, activation, promotion and release false.

## 12. Fault and recovery cases

Required fault cuts include:

- dispatch record before/after fsync;
- first-create parent-directory barrier;
- short/torn append and repaired-prefix reopen;
- compaction and retirement temp-fsync/rename/high-water cuts;
- authority denial/revocation races;
- parent write/read timeout before admission;
- worker pre-admission rejection;
- worker/channel loss after admission;
- protocol corruption and cross-session drift;
- disk full/I/O fencing/journal capacity;
- profile expiry/close during background network activity;
- Browser/worker process kill and signed persisted recovery;
- DNS/private-address/redirect/subresource/SNI escapes;
- cross-profile cookie/storage/cache attempts;
- RSS/FD/process soak and descendant cleanup.

## 13. Completion and claim boundary

Repository source may claim the exact implementation and qualification mechanisms described above. It may not claim final completion until the final exact candidate has terminal-success required checks and merged-main signed artifacts/target evidence exist.

Still external/separately governed:

- trusted product/supervisor activation of the named service;
- independently trusted remote-business terminal receipts where required;
- functional credential/upload/download capabilities if enabled;
- independent operator acceptance;
- promotion and release;
- platform equivalents if macOS/Windows later enter scope.

Current truth:

```text
source_root_present = true
production_implementation = false
deployment_qualification = false
operator_acceptance = false
activation = false
promotion = false
release = false
```
