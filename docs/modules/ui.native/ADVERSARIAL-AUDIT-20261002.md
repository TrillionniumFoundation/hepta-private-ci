# ui.native: Rust-only product and presentation audit, 2026-10-02

Status: **continuation in progress; complete product closure and new-source qualification pending**.
This is a source, product-completeness and acceptance plan for the existing Rust
application. It does not declare production readiness, independent acceptance,
deployment qualification or release authorization. Findings below describe the
immutable baseline unless an explicitly identified later result says otherwise.

## 1. Exact candidate, evidence and integration boundary

| Identity | Observed value |
| --- | --- |
| Reviewed native PR | [#1308](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1308), open Draft at observation |
| Reviewed native branch | `work/ui-native-adversarial-audit-20261001` |
| Reviewed candidate | `978c1923eda66373e9dce4fe0efa890bc60ac404` |
| Reviewed candidate tree | `1d8aa1f0d23094d9c5c3c52cd695c865c2b9a8d3` |
| Frozen implementation | `0a129b41c2a2d42ca907ea8257bf780108bc664f` |
| Frozen implementation tree | `f90313f067446c629b8da50058ee1bd2101e76e7` |
| Qualified native integration base | `9be52d267d02a76f73e8a94fd086191c351d1c70` |
| Observed current main | `c6f90d48c40f7b5267db587bb3c3f4934f1414a8` |
| Main/native common ancestor | `a126987b84737dbc2ee2592442a314117bddb4a2` |
| New audit continuation | `work/ui-rust-scifi-audit-20261002`; initially based on the reviewed candidate |

The GitHub run API was checked on 2026-10-02:
[run 36842710605, attempt 1](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/36842710605)
has `status=completed`, `conclusion=success`, and `head_sha=978c1923...`.
It finished at 2026-10-01 09:42:17 UTC. Its result is real historical execution,
not a success inferred from a PR description or the presence of tests.

The [final accepted evidence report](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/6683ce427810b0bac92b5fbf407d66feba0890c6/docs/modules/ui.native/history/20261001-978c-accepted/README.md)
is on separate evidence ref `6683ce427810b0bac92b5fbf407d66feba0890c6`.
It records all nine jobs, six platform head/merge subjects, 48 storage traces,
package checks and independent aggregate replay. Its three merge subjects use
ordered parents `9be52d2...`, `978c1923...` and merge identity
`d64ceb854bb045302f5624f3b63f365a6b34739b`. The existing developer/technical
guides preserve publication-time pending/failure observations. Keep those
records intact and use the final report to resolve their historical status.

**This evidence does not qualify current main or this continuation.** At the
observation above, the native candidate was 216 commits ahead of and six commits
behind main. Main still had the older JavaScript native prototype. Main-only
changes include `997e7be...` (dependency-scoped qualification and removal of
editorial development gates), `87bb35d...` (native CI transport, durable lease
transitions and private recovery fixtures), and the four commits concluding in
`c6f90d4...` that preserve owner-selected administrator merging and scope policy
tests. Shared Cargo, authority, runtime, NDU, workflow and documentation paths
changed. These must be reconciled, not overwritten from either historical tree.

The baseline `.github/workflows/ui-native-qualification.yml` triggers native PR
qualification only for `work/ui-native-qualified-integration-20260928` and pins
`BASE_SHA=9be52d2...`. A PR into main is not automatically covered by that trigger.
Any new target/base must be explicit, immutable, included in exact-head and
ordered-parent merge subjects, and passed to the aggregate. Do not relax main's
independent checks, restore superseded editorial gates, enable auto-merge, or
treat a clean merge as executed compatibility evidence.

## 2. What the application currently owns

The canonical implementation remains Rust 2024 with eframe/egui 0.36.2, Glow and
AccessKit. See [the canonical Rust ADR](ADR-0001-CANONICAL-RUST-SHELL.md).
Retired `apps/hepta-native/src/native.js` and `shell-runtime.js` must not return.
This audit does not introduce another framework, webview or parallel runtime.

The shell owns presentation, opaque session references, a local operation
journal, platform capability transport and its updater. It does not own domain
truth, issue final-use grants, sign authority or select releases. The real
backend is `LoopbackGatewayBackend`, which verifies the signed protocol-v2
endpoint and mutual keyring MAC, reads `/healthz` and `/api/hepta/runtime`, and
rejects bearer-only product fallback. `codex-hepta-native-gateway` delegates
runtime status to `codex_hepta_runtime::HeptaRuntime`; it is read-only.

The current `Runtime`, `Operations`, `Updates`, and `Accessibility` screens do
not constitute a complete interactive console for every project domain.
Displaying raw runtime JSON does not implement TaskFlow editing, model control,
knowledge/memory editing, training selection, or other owner mutations. A future
domain control needs its registered owner contract and explicit authorization;
it must not add arbitrary HTTP mutation or direct owner-store writes to the UI.

### Requirement-to-code and evidence map

Paths below are relative to `apps/hepta-native` unless prefixed `codex-rs`.
Test names identify existing coverage to preserve; they are not new execution
claims for the continuation.

| User-visible requirement | Rust entrypoint and real owner | Existing regression/evidence surface | Acceptance still needed |
| --- | --- | --- | --- |
| Start a trusted desktop session | `src/main.rs::run`, `src/runtime.rs::connect_runtime`, `src/backend.rs::LoopbackGatewayBackend`; keyring and signed endpoint trust | `tests/backend.rs::authenticated_gateway_health_is_required`, `gateway_protocol_must_match_the_signed_manifest`, `unauthenticated_legacy_gateway_is_rejected_by_product_shell`; Linux installed gateway/keyring harness | Recoverable setup/unavailable state, real desktop launch, final-source native matrix |
| Read current runtime state | `src/runtime.rs::refresh_runtime_view`, `src/native_http.rs`, gateway `HeptaRuntime::status_json` | `tests/runtime.rs::authenticated_backend_status_owns_view_identity`, `stale_backend_view_is_rejected_before_authority_or_platform_entry`; `src/ui/input_event_tests.rs::diagnostic_render_failure_invalidates_presentation_binding_and_readiness` | Structured readable overview; adversarial diagnostic layout; reconnect/expiry visibility |
| Prepare an exact effect proposal | `src/ui/binding_prepare.rs`, `NativeShellRuntime::prepare_platform_binding`; `kernel.authority` issues the independent signed grant | `src/ui/binding_prepare_tests.rs` covers blocked confirmation, edited input, changed view, cancellation, shutdown and different screens; `binding_prepare_snapshot_tests.rs` | Full-screen snapshots and real input; proposal preparation must remain non-authorizing |
| Perform a local capability once | `NativeShellRuntime::request_platform_capability`, `src/security.rs::KernelFinalUseGate`, `src/platform.rs::SystemPlatformAdapter`; contracts final-use owner | `tests/runtime.rs` covers session/subject/grant/payload identity, denied permission, missing authority and receipt-write failure; `codex-rs/hepta-contracts/tests/final_use_linearization.rs` | All-Rust platform transport, current final-use denial/race tests, operation-bound completion evidence |
| Select grant/update files safely | `src/ui/native_picker.rs`, `src/ui/task_supervisor.rs`, `src/file_input.rs` | `src/ui/task_supervisor_tests.rs` covers stale ticket, wrong target, cancellation, invalid/drop paths; `src/ui/input_event_tests.rs` covers actual paste/focus | Interpreter-free dialogs; physical cancel, navigation, drag/drop, IME and focus restoration |
| See history and recover uncertainty | `NativeShellRuntime::operation_history_page`, `reconcile_pending`, `close_operation_observation`; `src/journal*.rs`, `src/retirement*.rs` own records | `tests/runtime.rs::indeterminate_retry_reconciles_instead_of_replaying_or_reclaiming`, `crash_after_dispatch_before_ack_reconciles_invoking_without_reinvoke`; `tests/retirement_recovery.rs` | Visible distinction among success, rejection, pending, unknown and closed-unknown; bounded page/layout performance |
| Stage and confirm an update | `src/updater.rs::UpdateManager::verify_and_stage`, `src/update_confirmation.rs`, updater helper and existing trust owner | `tests/security_updater.rs`, `tests/update_product.rs::updater_does_not_accept_exit_zero_as_product_startup`, `src/update_root_storage_tests.rs`, child-fault qualification | New-source package execution, cancellation/rollback UX, production signing and independent release selection |
| Close without losing ownership | `src/ui/shutdown.rs`, `src/ui/task_supervisor.rs`, `NativeShellRuntime::close` | `tests/shutdown_recovery.rs::reconnect_cannot_acquire_replacement_before_old_owner_is_closed`; supervisor admission/cancel tests and admitted-binding drain test | Repeated Close/Escape, all active lanes, process exit and installed update handoff |
| Read and operate an accessible bilingual UI | `src/ui.rs::Locale`, `src/fonts.rs`, AccessKit feature, real egui widgets | `src/ui_tests.rs::locale_selection_covers_chinese_and_safe_english_fallback`, input-event tests, current pending/stale binding text snapshot | Complete visual/keyboard snapshots, glyph coverage, physical screen readers, Chinese IME and mixed DPI |

## 3. Testable meaning of “the entire UI uses Rust”

The target concerns **first-party product application logic and its executable
closure**, not merely source filenames. Rendering, interaction, state machines,
native dialogs, notification transport and product-installed identity helpers
must be implemented in Rust. Rust calls into OS APIs and reviewed upstream
native libraries are allowed; this is not a claim that an operating system,
driver, renderer dependency or every transitive dependency is written in Rust.
Static fonts, icons and images are assets, not alternate UI implementations.

For a complete product claim:

1. Trace normal startup and every supported interaction from each shipped binary
   through included strings, generated resources, subprocesses and package files.
2. Reject first-party runtime JavaScript/TypeScript, HTML-script UI, embedded
   Python, AppleScript, PowerShell or C# executed through an interpreter. A Rust
   wrapper around such a script does not satisfy the requirement.
3. Exercise installed-package interactions with Python, Node and PowerShell
   unavailable. Verify process creation as well as package inventory. Do not
   remove a feature, turn a failing test into a skip, or silently fall back to a
   scripted helper to make this check pass.
4. Preserve capability/resource identity, final-use fences, request bounds,
   cancellation, deadlines and unknown-effect semantics in every adapter port.
   An unimplemented platform action stays visibly unavailable and is recorded
   as incomplete; it does not become “all features complete”.
5. Version or explicitly retire compatibility surfaces with a caller inventory.
   Do not delete another UI module or alter its public contract just because it
   is absent from the native screen navigation.

### Baseline non-Rust inventory

| Surface | Product reachability at `978c1923...` | Required disposition |
| --- | --- | --- |
| `src/ui/native_picker.rs` includes `portal/file_chooser.py` | Linux picker executes `/usr/bin/python3 -I -c`; macOS uses `osascript`; Windows uses PowerShell `OpenFileDialog` | Rust-native dialog/portal implementation with equivalent ticket, bounds and cancellation behavior |
| `src/platform.rs` includes `portal/open_uri.py` | Verified Linux FD handoff executes Python; capability safety is real but interpreter dependence remains | Rust FD transport preserving verified object identity and conservative observations |
| `src/platform.rs` includes `portal/windows_toast.ps1` | Windows toast uses PowerShell/WinRT; macOS uses `osascript`; Linux invokes `notify-send` | Rust OS notification adapters, bounded outputs and unchanged delivery-uncertainty policy |
| `packaging/windows/Register-HeptaNativeIdentity.ps1` | Installed identity registration includes C# compiled through PowerShell | Rust identity registration helper and equivalent COM/ABI/shortcut verification |
| `codex-rs/hepta-native-gateway/src/lib.rs::CONTROL_SHELL` | Authenticated `GET /` serves HTML/CSS and inline JavaScript `fetch`; active even though its containing file is Rust | Explicitly replace/retire browser UI after compatibility review; preserve authenticated data routes |
| `apps/hepta-control-ui/src/*.js` | Separate `ui.control` compatibility/shadow source on this candidate; newer browser work is open [PR #1069](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1069) | Explicit scope and migration plan before any repository-wide all-UI Rust claim; no silent adoption or deletion |
| `tools/ui-native-projections/*.mjs`, `scripts/hepta_ui_native_*.py`, `apps/hepta-native/tools/*.py` | Build, package, test and evidence tooling; not shipped interactive runtime logic | May remain tooling; prove it is not imported or launched by installed product paths |

“Rust desktop rendering implemented” is already source-supported. “Every UI
product path is Rust” and “every platform capability is implemented” are not
supported for this baseline. Passing a filename scan cannot establish either.

## 4. Findings and prioritized continuation

These are architecture/product findings, not a claim of a new exploitable P0.
Newly reproduced security failures belong in a separately identified red/green
record with exact source, fixture and result.

| Priority / ID | Baseline observation | Required closure |
| --- | --- | --- |
| P1 / RUST-01 | Runtime script paths listed above contradict a literal all-Rust product requirement | Port bounded adapters, review hidden/generated code, execute no-interpreter package matrix |
| P1 / INTEGRATION-01 | Qualification uses the native integration branch and old fixed base, not observed main | Reconcile main changes; bind actual target/base; execute final exact/merge checks without borrowing historical results |
| P1 / PLATFORM-01 | macOS/Windows verified-resource Open/Reveal correctly fail closed | Authenticated capability-consuming receiver, object/receiver binding, independent issuer, operation/session/grant/resource ACK and reconciliation receipt |
| P1 / STARTUP-01 | `main.rs:69-148` and `ui.rs:248-259` complete configuration/trust/keyring/connect work before the window at `main.rs:167` | Recoverable startup/unavailable presentation without granting authority or discarding state; bounded cancellation and retry tests |
| P1 / UX-01 | Baseline uses default widgets, a raw JSON home screen and a long operation form; only history has a dedicated scroll region | Structured honest status, clear hierarchy, adaptive scroll/layout, explicit state feedback and full-screen regression coverage |
| P2 / PERF-01 | Worker serialization is bounded to 4 MiB, but `ui.rs::runtime_view` sends the full text to a per-frame text widget | Measure bounded worst-case layout; virtualize/chunk diagnostics or otherwise bound actual work without hiding status or widening limits |
| P2 / I18N-01 | Chinese locale relies on optional machine-local fonts; Accessibility is primarily explanatory labels | Verified glyph/fallback handling, keyboard/IME tests, contrast and accessible-name evidence; retain honest unsupported states |

Keep source repairs in coherent review stages. UI styling cannot close platform
capability, owner integration or independent acceptance gaps. Conversely, an
old security/storage pass cannot establish visual quality. Capture separate
evidence for both kinds of work and rerun affected checks after later edits.

### Applied continuation changes and bounded local observations

The continuation now implements Linux portal picker, retained-descriptor OpenURI
and notifications through Rust `zbus`; macOS AppKit dialogs/UserNotifications;
and Windows native dialogs/WinRT notifications. The standalone native workspace
includes `platform-adapters`, whose reviewed native SDK boundary owns the small
OS-specific unsafe calls. The application consumes safe Rust APIs. macOS and
Windows dialog/notification helpers invoke the same executable with standalone
typed modes, use bounded inherited pipes and verify executable identity. Parent
I/O uses owned nonblocking handles and cooperative polling; no pipe worker can
outlive a timed-out operation. Exit observation drains bounded output before
classifying a complete reply, including a child that wrote immediately before exit.

Notification readiness digest/nonce identifies the intended child; it does not
independently establish the parent's final-use authority. The helper is an
unprivileged, same-principal OS notification facade. The parent retains final-use
and journal ownership, and helper/OS acceptance emits neither a delivery-success
receipt nor a capability grant. Cancellation or timeout after admission remains
indeterminate. The 8-second notification and 130-second picker limits cover
active protocol work; initial executable hashing and kernel kill/reap/scheduling
are outside those timers. Linux's 64 KiB application portal-response limit is
checked after zbus decoding; its 128 MiB raw-frame ceiling remains a distinct
resource boundary. These limits must not be described as a hard wall-clock or
transport-memory guarantee.

Windows registration is now the explicit Rust command
`hepta-native.exe --register-notification-identity`. It uses the current executable,
fixed AUMID and native SDK property variants, then verifies persisted shortcut
target/AUMID before atomically publishing the marker. It never runs automatically
from startup or a notification. Unsigned package schema v3 advertises this exact
command and drops the installed PowerShell registrar. Old Python portal and
PowerShell registrar source remain historical/unshipped artifacts. Linux Zenity
selection is explicitly retired: requesting it returns an actionable error.
This is a compatibility change requiring an installed XDG FileChooser backend.
It must be called out rather than presented as a successful dialog fallback.
The old script-executing Windows test is replaced by workspace adapter tests of
the production Rust COM commit/persist/readback in an owned temporary shortcut,
with wrong-target and wrong-AUMID controls. Marker publication sequencing has
separate tests. These newer tests require fresh Windows execution and do not
inherit either the old script fixture's result or the earlier Linux test count.

The Rust shell now has shared dark/cyan/violet visual tokens, status cards,
consistent navigation, bounded diagnostic previews and scrolling operation/update
forms. The first diagnostic view is bounded before expensive widget layout;
the full bounded snapshot remains cached, but this preview does not expose every
diagnostic byte. High-contrast selection,
English/Chinese text and minimum/default/large-text snapshot cases are present.
These are source-level improvements with local visual observations, not physical
accessibility or performance qualification.

Ordinary launch now presents input-configuration failures in the native recovery
window. Retry reloads configuration, endpoint trust and credential inputs only;
success exits that loop before state, updater or session initialization. Failures
after stateful initialization offer exit-only recovery. Machine/helper/update
handoff invocations remain noninteractive. Regressions cover retry/close, no
state creation or trust repair during input reload, malformed machine arguments,
bounded Unicode details and visible recovery controls.

The gateway root-route repair is applied in the continuation worktree. Its final
commit/tree is not yet frozen.
`codex-rs/hepta-native-gateway/src/lib.rs::route_authenticated_request`
now returns an authenticated JSON native-client discovery descriptor for
`GET /`, with schema `hepta.native-client-discovery.v1`; the embedded HTML/CSS/
JavaScript `CONTROL_SHELL` is removed. Presentation belongs to the Rust native
application. The extended route regression
`exposes_authenticated_native_discovery_health_and_closed_runtime_status`
asserts unauthenticated 401, authenticated JSON content type, exact descriptor,
native MAC-v2 response proof and replay rejection. Its final-source execution
result must be retained with the coordinated validation logs.

This is an intentional **breaking presentation change** for consumers expecting
an HTML browser canary at the root URL. They must use the Rust desktop client;
machine clients should use authenticated `/api/hepta/runtime` and `/healthz`.
Those machine routes, their representations and existing authentication/final-use
boundaries are not changed by this presentation repair. Retained legacy CLI and
machine-contract names are compatibility interfaces, not a claim that a browser
UI still exists. This closes one scripted presentation path at source level;
it does not close separate `ui.control` Rust gaps or establish native OS execution.

The separate JavaScript `ui.control` implementation remains a whole-UI Rust gap.
A local reproduction also found duplicate concurrent operation dispatch,
cross-session reuse of old acknowledgements, shallow mutable snapshots and
unscoped terminal reconciliation. These are module-local integrity findings,
not proof of native/kernel authority bypass. A Rust port must reserve an exact
session/generation/method/operation before transport, preserve immutable bounded
snapshots, and reject stale reconciliation; copying those JavaScript semantics
would preserve the defects. Domain owner implementation/integration remains
separate work and is not complete because the native shell has four screens.

The continuation qualification workflow now targets
`work/ui-native-adversarial-audit-20261001`, pins parent `978c1923...`, and rejects
a pull-request event whose base ref or SHA differs. It also verifies the
candidate manifest's parent and the base/implementation/candidate ancestry.
The six platform subjects, release storage subject, strict same-run aggregate,
read-only permissions and storage budgets are unchanged. This is qualification
of a stacked continuation, not a merge with main. Frozen metadata remains
pending until all product edits have been reviewed and committed.

Local workflow regression execution on 2026-10-02 passed 11 identity-step cases
(`PYTHONPATH=scripts python3 -m unittest test_hepta_ui_native_identity -v`) and
16 existing workflow cases (`test_hepta_ui_native_workflow` with the same runner).
These execute the real workflow shell against isolated fixture repositories,
including base drift, forged manifest, foreign ancestry, dirty-tree refusal,
LF merge identity and storage aggregate rejection. They do not qualify the
unfinished Rust source, a hosted platform job or the new complete candidate.

### Local diagnostic execution on 2026-10-02

These observations were made in a coordinated worktree before ordinary source
publication, with later formatting, packaging and private registrar/marker
factoring changes. They are diagnostic
results, not receipts for an immutable candidate or physical target platform.

| Scope | Observed result | Exact limitation |
| --- | --- | --- |
| Linux native workspace `just test --locked --workspace --all-targets` | 275 passed, 4 ignored; 4.981 s test execution | After the picker exit/drain race repair; OS-only adapter cases do not execute on Linux |
| Native strict Clippy with `--workspace --all-targets --all-features -- -D warnings` | Linux passed; Windows GNU x86_64 and macOS ARM64 cross-target checks passed | After the pipe repair; compilation/lint does not establish target-OS execution |
| Registrar/marker migration follow-up | 5 marker-ordering tests passed; strict Windows workspace Clippy passed again | After private registrar/marker factoring; new COM tests compile but require Windows execution; the earlier 275-test run predates this factoring |
| Standard four-owner test command shown in section 7 | 214 passed, no skips; 0.898 s test execution | Gateway/owner source unchanged by the later picker-only repair; includes authenticated root discovery regression |
| Four-owner strict Clippy and repository formatting | Passed; Bazel lock update passed with no lock drift | Source formatting follows tests as required by repository instructions |
| Rust-rendered virtual-window image fixtures | 26 raster captures passed | After initial pipe rewrite, before the picker-only exit/drain fix; synthetic states and virtual graphics are not physical acceptance |
| Ordinary missing-configuration launch | Retry created a new recovery window; Close exited | Earlier binary before final pipe fixes; no successful backend connection or immutable-current-source claim |
| Workflow identity/construction/aggregate plus native positive-contract guards | 38 focused Python cases passed | Isolated fixture repositories/source mutations; excludes frozen-source tests until publication |
| Unsigned package v3 security suite | 35 passed, including deterministic packages and strict registrar command mutations | Fixture executable bytes; no installed registration, signing or notification delivery |
| Projection generator | Source-discovery cases pass; committed-registry/receipt cases intentionally pending regeneration | Generated `test-registry.json` still describes the old source; no pass is recorded for the full projection suite |

Raw coordinated logs include `native-tests-final-exit-race.log`,
`native-{linux,windows,macos}-clippy-final-exit-race.log`,
`native-marker-ordering-tests.log`, `native-windows-clippy-final-registrar.log`,
`owner-tests-final.log` and `owner-clippy.log`. Bind and retain their bytes in the
new evidence record before treating them as reusable diagnostic artifacts.
Do not add earlier repeated test runs to these counts or attach their results to
the final source without recording the exact intervening changes.

## 5. Visual and interaction acceptance matrix

The design goal is a high-end science-fiction operations console implemented
inside the existing Rust renderer. This means restrained dark surfaces, clear
type hierarchy, purposeful accent colors, consistent spacing and recognizable
focus/status affordances. Decorative telemetry, invented progress, excessive
glow, unreadable microtype and color-only status are unacceptable. There is no
claim that the baseline meets this goal.

Rows below define acceptance. Local snapshots and virtual-window observations
cover only identified subsets; the matrix is **not a set of observed passes**. Record the
exact source, platform, renderer, window size, scale, locale and test state with
each artifact. Automated headless text/painter snapshots, real GPU/window
screenshots and independent physical acceptance are different evidence classes.

| Dimension | Required cases | Observable pass condition |
| --- | --- | --- |
| Screens and hierarchy | Runtime, Operations, Updates, Accessibility; startup/unavailable/recovery | Primary purpose, current trust state, next safe action and navigation remain legible; raw diagnostics are secondary |
| Layout | 800x560 minimum, 1180x760 default, 1440x900; 100%, 150%, 200% scale; narrow long labels and long paths | No clipped/overlapping required controls, unreachable actions or hidden error text; bounded scrolling and readable truncation/detail |
| Locale and text | English and Chinese, CJK present/missing, long Unicode, combining marks, multiline paste | No silent missing-glyph acceptance or lossy path conversion; labels and entered values stay distinct; byte limits enforced after paste |
| Keyboard and focus | Tab/Shift+Tab, Enter/Space, Escape, screen switches, return from picker, repeated activations | Predictable focus order and visible focus; correct target restoration; one activation per deliberate action; cancellation is not success |
| State honesty | Authenticating, current, stale, failed refresh, queued, admitted, terminal, rejected, quarantined, indeterminate, closed-unknown | Text and visuals distinguish authority and observation states; stale views never enable effects; unknown does not appear successful |
| File selection | Choose/Cancel, navigation during picker, replacement target, late callback, drag/drop, invalid path, oversized/malformed input | Exact ticket/target binding; stale or invalid results cannot overwrite a current field or authorize an effect |
| Effect proposal | Change action/subject/id/payload/view before and after preparation; double-click execute | Prepared binding invalidates on any bound change; final-use owner revalidates; no duplicate dispatch or self-signed grant |
| Updates and exit | Invalid/expired signature, partial stage, cancel, repeated Close, active picker/read/mutation, helper crash, lost ACK, rollback | Explain recoverable state; retain evidence; drain admitted work; activation only after confirmed close and running-process readiness |
| Accessibility | Semantic names/roles, screen-reader order, focus, contrast, reduced motion and high contrast | Text labels supplement color; focus is visible; requested reduced motion honored; real platform assistive-technology observations retained |
| Visual identity | All states and sizes, screenshots reviewed together | Consistent Rust-owned tokens for typography, spacing, surfaces and status; no arbitrary marketing/demo data; aesthetic judgment recorded separately from functional tests |

For this iteration, suggested design measurements are at least 4.5:1 normal-text
contrast and 3:1 large-text/essential-control contrast. These are project review
targets; measuring them is not, by itself, a declaration of accessibility
standard conformance. Any new motion must have a reduced-motion behavior and
must not interfere with reading, focus or fault diagnosis.

## 6. Performance, bounds and authority acceptance

Preserve every semantic ceiling in `apps/hepta-native/STORAGE_BUDGETS.json`.
The existing release storage protocol covers 4096 active records, one million
retired identities, their combined population, 20 fresh-process observations,
WAL/snapshot bytes, durability syscalls, write amplification and raw percentiles.
At baseline the ceilings include 2000 ms open P95, 25/100/250 ms mutation
P50/P95/P99, 25 ms history-page P95, 256 MiB RSS, and 30000 ms index-rebuild P95.
Do not weaken these budgets, strip the tested executable, extend production
5/35-second update deadlines or equate fresh-process runs with cold disk cache.

Add UI-specific measurements separately: normal and maximum-size diagnostics,
64-receipt history pages with longest valid content, rapid navigation/paste,
blocked workers and picker, first meaningful paint, input-to-visible-response,
frame CPU time, idle CPU, and memory after repeated refresh/reconnect. Preserve
raw samples and final hardware/renderer information. Proposed initial review
targets are P95 frame CPU <=16.7 ms and visible input acknowledgement <=100 ms
on the declared reference host; these are **not yet measured or installed CI
gates**. Select and record a reference-host profile before treating a number as
acceptance. Storage success does not establish these UI responsiveness targets.

Every effect continues through immutable request validation, verified resource
confirmation, durable Prepared, local permission, current final-use claim,
durable Invoking, final policy/object verification, platform handoff, and a
durable terminal or indeterminate observation. Test wrong endpoint, protocol,
session, subject, operation, revision, resource, payload, issuer, grant, expiry
and revocation; also race each mutable wait with cancellation/replacement.
Unauthorized, malformed or stale input must cause zero platform entry. Lost
reply, helper exit, timeout and cancellation after admission must not prove
non-execution or authorize replay. A successful portal ACK proves handoff only.

## 7. Verification and evidence handoff

Run checks against the final source, not merely the initial audit checkout.
Follow root `AGENTS.md`: use `just test`, dedicated test modules and corresponding
`insta` snapshots for every user-visible UI change. Review snapshot changes.
Use scoped lint/fix and repository formatting; preserve unrelated concurrent
edits. Dependency or compile-time asset changes also require applicable Bazel
lock/data updates. Do not run a workspace-wide suite without its required approval.

```bash
# Repository root: check-only app commands
cargo +1.95.0 fmt --manifest-path apps/hepta-native/Cargo.toml --all --check
cargo +1.95.0 check --manifest-path apps/hepta-native/Cargo.toml --locked --workspace --all-targets --all-features
cargo +1.95.0 clippy --manifest-path apps/hepta-native/Cargo.toml --locked --workspace --all-targets --all-features -- -D warnings
python3 scripts/check_hepta_ui_native_convergence.py
python3 -m unittest discover -s scripts -p 'test_hepta_ui_native_*.py' -v

# From codex-rs: repository test runner
just test --manifest-path ../apps/hepta-native/Cargo.toml --locked --workspace --all-targets
just test --locked --all-targets --all-features \
  -p codex-hepta-native-gateway -p codex-hepta-contracts \
  -p codex-hepta-private-state -p codex-utils-private-state
```

These are verification commands, not this document's execution results. The
structural checker is expected to reject changed product bytes still bound to
the old freeze. Commit ordinary source first, then refresh source identities
and generated projections with reviewed tooling; never rewrite historical
receipts or manufacture success to bypass this guard. This document does not
regenerate those frozen files. The installed Linux gateway/keyring/Xvfb harness
is `apps/hepta-native/tools/linux_product_qualification.py`; its virtual input
evidence does not establish physical IME/screen-reader/DPI acceptance.

For each repair, retain: reproducible failing case; exact pre/post source;
implemented change; focused and aggregate command outcomes; screenshots or
snapshot diff when visible; known exclusions; final immutable workflow/base/
head/tree/run/attempt; and artifact digests. Mark each stage `passed`, `failed`,
`not_run` or specifically `blocked`. Never sum repeated runs as unique coverage.

### Source-freeze publication procedure

1. Finish ordinary source, native workspace/lockfile, platform adapters, package
   v3, workflow and regression review; publish that source as commit `I` with its
   exact Git tree. Require parent `978c1923eda66373e9dce4fe0efa890bc60ac404` to be
   an ancestor. Do not freeze an uncommitted or merely local proposed SHA.
2. Resolve `implementation_paths()` and `local_cargo_dependency_paths()` from
   the convergence checker on `I`. The current closure includes
   `apps/hepta-native/platform-adapters`, including its tests, via Cargo target
   dependencies. Add `STORAGE_BUDGETS.json` to the inventory selection. Hash exact
   Git blob bytes from `I`, sorted by path; hash their canonical UTF-8 JSON map
   with sorted keys and compact separators. Do not hash changing worktree bytes.
3. In a metadata-only continuation, change the top-level implementation SHA/tree
   in the seven files listed by `STATE_FILES`. Archive the prior current frozen
   inventory unchanged, then publish the new count, digest and selection paths.
   Refresh current dependency/path policies and branch navigation. Preserve
   historical nested SHAs, source inventories, receipts and success/failure logs.
4. Set the current qualification manifest's exact parent to `978c1923...`, keep
   the final review head unresolved until the metadata commit is published, and
   keep fresh run/artifact fields empty and promotion flags false. Archive the
   old local-diagnostic object intact before writing a separately scoped new
   diagnostic object. Update current adapter/test maps and pending gaps only.
   Storage budget semantics may not change; only their two source anchors move.
5. Run the reviewed projection generator (`node tools/ui-native-projections/generate.mjs
   --write`) and reproducibility tests, then current-source, registry, dependency
   and native Python regressions. The old `prepare_current_source.py` v3 helper
   is incompatible with this v6 freeze and must not be used to rewrite it.
6. Publish metadata candidate `C`, require `I` to be an ancestor of `C`, and
   verify clean product bytes against `I`. Execute all six platform head/ordered
   merge subjects, release storage measurements and strict same-run aggregate
   against the exact final candidate/workflow/base. Retain every raw artifact.
   Any ordinary product repair starts a new source/freeze cycle; metadata cannot
   rebind old execution to new bytes or qualify current main automatically.

## 8. Remaining gates and current completion statement

Repository-controlled work still includes whole-UI Rust closure (`ui.control`),
verified macOS/Windows Open/Reveal adapters, final visual/interaction evidence, current-main
integration where selected, measured source coverage, and sustained soak.
Outstanding environment/independent gates include:

- Physical Windows, macOS, Linux X11 and Wayland installed-package execution,
  including real notification identity/delivery and file-dialog behavior.
- Multi-monitor/mixed-DPI, Chinese IME, screen-reader, keyboard/focus, contrast
  and reduced-motion acceptance by the responsible reviewers.
- Windows ordinary/elevated/token-owner/impersonation and platform filesystem
  ownership/ACL cases beyond the executed source fixtures.
- Production key custody, rotation/revocation, Developer ID/notarization,
  Authenticode, Linux distribution signing and target-host installation trust.
- Independent supply-chain/SBOM/provenance acceptance, operator acceptance and
  explicit release/promotion decisions.

The prior accepted report also records unchanged `utility.ndu` and
`intelligence.control` source-map drift as whole-project blockers. Their current
status must be rechecked against the selected integrated tree; this UI audit
does not resolve them or transfer old execution claims to newer owner sources.

This report supplies a reviewed baseline, native source repairs, bounded local
observations and an executable acceptance plan. Complete whole-UI implementation,
physical visual acceptance, final-source tests and new exact-source qualification
are pending. `productionQualified`,
`deploymentQualified`, `independentAcceptanceComplete` and `releaseAuthorized`
remain false. A later repair must update its actual result and residual gap;
it must not turn this plan or the historical baseline pass into a new pass.
