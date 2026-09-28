# ui.native technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0  
**Module:** `ui.native`  
**Owner / deputy:** `ui-platform` / `accessibility`  
**Lane:** `LANE-B-RUNTIME`  
**Canonical branch:** `work/ui-native-qualified-integration-20260928`  
**Review:** PR #1139; this is a draft product candidate, not an accepted release.

This guide describes the implementation anchored at
`a0d911f50bddf35da7b3a8cd7e671373a3c128fb`, source tree
`49c8342e46b7d711bb97bd294b4e700915ed9b36`. Subsequent documentation or diagnostic
commits do not prove execution of that implementation. Qualification must bind
its actual final checkout, tree, workflow, dependency locks, runner and logs.
The fixed synthetic-merge base is `a126987b84737dbc2ee2592442a314117bddb4a2`.

Read [CURRENT_DELIVERY.json](CURRENT_DELIVERY.json) for the explicitly separated
source, verification and open-work states. The earlier guides are preserved
byte-for-byte under `history/`; their old candidate names, journal-v3 capacity
statements and completion assertions are historical, not current contracts.
The dated closure records likewise describe their own revisions. In a conflict,
this guide states the present intended contract; a contradiction with actual
source or an executed test is a defect, not permission to trust the document.

## 1. Identity, mission and ownership

The module supplies native desktop presentation and bounded local platform
operations over existing runtime owners. It does not create another domain
store, provider executor, release selector or authority issuer. Application
configuration is fixed for a process generation; changing endpoint, trust or
policy requires a new bootstrap rather than silently changing the authority of
an already displayed confirmation.

The native shell owns local presentation, its operation journal and update
coordination metadata. The gateway owns authenticated read transport. The
kernel final-use owner remains responsible for grants, nonce consumption,
epochs, expiry and revocation. Local clipboard, notification and path policy
are additional ceilings, not substitutes for that authority. Accessibility
and release acceptance remain independently reviewed facts.

## 2. Source binding and implementation status

`apps/hepta-native` is the only Rust desktop application root. Its ordinary
bootstrap is `src/main.rs`; the retired JavaScript intent prototype must not
return as a second product entrypoint. A historical branch, patch capsule,
source archive or passing result for another commit cannot establish delivery
of the current candidate.

`CURRENT_SOURCE.json` in the application defines the current-source inventory
policy. Its v3 policy recomputes identity for a checkout; it is not a stored
per-file pass receipt. Source maps identify an explicit source anchor and are
not automatically current after a code change. This revision does not claim
that all global generated projections, source-object maps or documentation
metrics have been regenerated and verified. Those checks remain necessary.

The whole-batch retirement repair and the GUI readiness/picker/pagination work
are ordinary committed source. Current native formatting, compilation, strict
lint and the six-subject acceptance set are not established as passed. A
successful Python infrastructure job is not a successful Rust or GUI job.

## 3. Boundary, responsibilities and non-goals

Permitted local state includes window/focus information, exact dispatch facts,
opaque session references and signed-update staging/recovery records. Runtime
facts, model or memory mutations, private signing keys, credential issuance and
release decisions remain with their respective owners.

Missing authority, a stale authenticated view, changed request semantics,
unsupported persistence, contradictory identity or an unknown effect result
must not be repaired by executing anyway. A UI timeout does not prove that an
admitted operation was cancelled. Closing observation ends local observation;
it does not turn UNKNOWN into a terminal OS success or known non-execution.

## 4. Internal architecture and component decomposition

`main.rs` composes the signed endpoint, keyring, policy, journal, kernel gate,
update manager and GUI. `backend.rs` and `native_http.rs` handle the authenticated
loopback read path. `security.rs` adapts exact confirmations to the kernel
final-use owner. `journal.rs`, `journal_storage.rs` and `retirement.rs` own local
operation persistence; `private_state.rs` validates the private root.

`ui.rs` owns the presentation and one supervised task slot. `ui/task_supervisor.rs`
linearizes admission and cancellation. `ui/readiness.rs` binds a GUI callback
witness to the authenticated view; `ui/history_page.rs` bounds visible history
rows; `ui/native_picker.rs` runs the platform file dialog. Operations and updates
remain in their existing `ui/operations_view.rs` and `ui/update_views.rs` paths.

`updater.rs`, `update_storage.rs` and `update_handoff.rs` implement signed staging,
replacement coordination and readiness. `hepta-native-updater` is the separate
replacement helper; `hepta-native-credential` provisions or deletes a selected
system-keyring capability. Neither helper authorizes a release on its own.

## 5. Contracts, ports and compatibility

The upstream module port remains `ModulePort::runtime.agentd::ui.native`.
Native runtime reads require a verified signed endpoint manifest, an explicit
loopback address and protocol 2. The product uses `keyring_mac_v2`; it does not
fall back to exposing the shared keyring secret as a bearer token. Request
proofs bind route, time window, nonce and server incarnation, and response
proofs bind the request, status and body. See [GATEWAY_V2.md](GATEWAY_V2.md).

Legacy bearer consumers are a separate compatibility surface, never an implicit
native-product downgrade. Gateway read access does not provide OS-effect
permission. Its existing bounded connection/request limits remain separate
from native UI task admission. A successful health probe is not GUI readiness,
and a GUI frame is not proof of physical display, keyboard or screen-reader
acceptance.

## 6. Data authority, persistence and migrations

The current writer uses journal v6 and segmented retirement v2. Journal readers
recognize the explicit legacy schemas in source; migration must preserve every
identity and cannot grant a reconstructed receipt to an identity-only legacy
tombstone. The active journal still has a 4096-record and 8-MiB bound. The former
32768-entry legacy retirement frontier is not the capacity contract for v6
segmented retirement. Removing that fixed ceiling does not make memory, disk or
startup work unlimited.

An operation key is interpreted with its endpoint and session incarnation. The
record additionally binds subject, displayed revision, action, payload digest,
final-use binding and grant digest. Reuse with different semantics is a conflict.
Private roots and files must remain current-principal owned and non-redirected;
a missing or unsafe store must not become a new empty replay registry.

Retirement publishes full immutable records before the referencing segments,
then publishes the retirement head before removing closed active records. The
whole input batch is semantically validated before record writes. In particular,
an already retired identity with no committed record reference cannot receive
a new receipt, even when batched with a new identity. Exact previously archived
receipts remain immutable and readable across restart.

The chain detects partial rollback and corruption; it is not an independent
anti-rollback authority when every local file is restored together. Recovery
must retain evidence and require the appropriate owner reconciliation rather
than silently selecting an older apparently valid snapshot.

## 7. Runtime, concurrency and transaction model

There is one runtime owner and one pending supervised UI worker. Runtime-bound
work waits through the same cancellation-aware lock path, with a 30-second
pre-admission wait limit. Taking the mutex is not admission. Only
`TaskAdmission::begin()` resolves the cancellation/admission race. After entry,
the worker remains owned until joined and must finish the owner's durable
protocol; no timeout detaches it or starts a replacement effect.

The effect sequence remains immutable input validation, durable Prepared,
platform permission, kernel final-use claim, durable Invoking, current
verified-use fence, final local policy, OS adapter and durable observation.
Permission denial before dispatch can be recorded as rejection. Once the OS
boundary may have been entered, errors must remain uncertain unless a trusted
terminal observation establishes otherwise.

The closing UI stops new work, invalidates actionable presentation and requests
pre-admission cancellation when possible. The existing shutdown deadline blocks
update activation if clean runtime closure is not established. It is not a
promise that arbitrary filesystem or OS work can be killed within the deadline.

## 8. GUI readiness, failure semantics and recovery

Startup and update-readiness persistence now execute in a `Ready` task on the
existing supervisor instead of in a paint callback. A first callback records
the exact view identity in presentation memory. A later monotonic callback for
the same view establishes that the earlier callback returned and produces the
witness. No filesystem write or runtime-owner wait is required to produce it.

After bounded owner-lock acquisition and admission, the worker revalidates the
session ID/generation, runtime generation, displayed revision, content digest
and module identity against the current owner view. Only then can it record
startup or confirm the running update process. A changed view invalidates the
witness. A pending-update read failure is propagated, not converted to absence.
Readiness failure requests safe shutdown and denies update activation.

This witness is deliberately not a physical rendering or accessibility receipt.
Regular initial signature/keyring/session bootstrap still occurs before the GUI
is created. Its I/O must not be confused with the eliminated per-frame readiness
I/O. Frame count exhaustion is a failure, not an identity reset.

## 9. Security, privacy and threat controls

The native client cannot mint grants. Signing keys never belong in UI state,
repository fixtures intended for release, logs or session records. Runtime
status and operation records should expose only the data required by their
contracts; logs must not dump grant payloads, bearer material or signing secrets.
A public-key fingerprint or CI artifact digest does not itself grant authority.

Mutable path-string OpenPath and RevealPath remain disabled in the system
adapter. Repeated canonicalization, an allowlisted directory or a file-picker
string does not solve the final resource substitution window. Enable these
operations only when a platform adapter consumes the already verified resource
capability and the appropriate replacement-race tests and host checks pass.

Clipboard terminal success requires immediate exact readback equality. A
mismatch or read failure is indeterminate. Notification launcher exit, including
zero, does not establish external delivery. The current reconciliation adapter
cannot manufacture an OS operation receipt; UNKNOWN remains UNKNOWN. Windows
notification identity remains an explicit product integration requirement.

## 10. Native file input and cancellation

Choose-file buttons for grants, update manifests and update packages now use
concrete platform adapters: a static macOS choose-file invocation, a static
Windows OpenFileDialog invocation and optional `/usr/bin/zenity` on Linux. A
missing adapter is an explicit error. No user input is interpolated into shell
commands, and no silent shell fallback is selected.

The supervisor retains the exact single-use ticket created when the dialog
opens. Switching screens, replacing the target or cancelling the intent makes
old callbacks stale. A cancelled old dialog cannot cancel a newer ticket, and
an old successful result cannot populate a new target. Focus is restored only
after accepted delivery. Drag/drop retains the same target-binding protocol.

The adapter bounds output to 16 KiB, accepts strict UTF-8 and one absolute path,
and rejects multiple-path delimiters, NUL and relative paths. The dialog has a
120-second observation budget. Child reaping and output-reader joining retain
ownership even if an OS call blocks; they do not confer a hard end-to-end
shutdown bound. Selected paths are reopened by the existing bounded regular-file
reader. A chooser result is neither execution authority nor a resource handle.
Physical dialog behavior on each platform is still unverified in this revision.

## 11. Performance, capacity and hot-path policy

Authenticated status JSON is rendered once per successful refresh, then reused
across frames. Refresh start/failure invalidates that cache and the current-view
indicator. The top bar no longer claims an authenticated current view solely
because a prior connection succeeded. Cached text never substitutes for current
runtime or final-use validation.

The operation view constructs at most 64 receipt rows per page. Navigation is
clamped after history shrink and uses stable operation identity for controls.
All active records remain owned by the journal; presentation pagination does
not compact, delete or forget deduplication facts. This bounds layout work, not
all runtime snapshot allocation: the existing active history is still copied
into a presentation result.

Retirement membership and record references remain memory-resident, and startup
still validates the entire chain. A rebuildable authenticated disk index and
million-record measurements are NOT implemented by this revision. The active
journal still performs vector lookup/clone and full snapshot writes. An exact
lookup index, append/checkpoint format and write-amplification reduction remain
open work, not a measured speedup. Any later optimization must preserve the
same authoritative owner and pre-dispatch/terminal durability barriers.

## 12. Observability and operations

Expose distinct prepared-not-dispatched, awaiting trustworthy observation,
terminal-observed and observation-closed-UNKNOWN states. Closing observation
cannot be presented as effect cancellation. Report capacity pressure before
operators are tempted to delete the journal. Archive through the owner only,
and retain complete identity/receipt references needed to reject replay.

Startup diagnostics bind the authenticated endpoint and view. An explicit
`--check-connection` exercises bootstrap without claiming GUI execution. Ordinary
GUI startup records are additional observations, not independent acceptance.
Safe diagnostics include source identity, low-cardinality failure family,
operation identity, phase and digests; avoid raw payloads and secret material.

Keep current-head and synthetic-merge logs separate. If a transport-provided
summary contradicts GitHub's primary job/step record, do not promote a pass.
Preserve the discrepancy. An artifact rejected for digest mismatch remains
rejected even when separate primary logs are retrieved for troubleshooting.

## 13. Verification and qualification

Use pinned Rust 1.95.0 and locked dependency resolution. Required native commands
are in the developer guide. Test-source discovery is insufficient: the compiled
`cargo test --lib -- --list` output must contain both retirement claim tests,
then those tests and the full applicable suites must actually execute.
`retirement_claim_tests.rs` is now mounted in the parent module explicitly.

The source-integrity workflow is read-only and may provide quicker Linux
feedback. Its result is not the required six-subject qualification. Full
acceptance still requires Linux/macOS/Windows exact-head and deterministic-merge
checks, owner integration, strict formatting/lint, native tests, real binaries,
packaged self/fault profiles and applicable installed-product exercises.

Run `36450557375` for source `6ff6cd07c25c9af4fd6d6f59348eb79fa1fec8c1`
completed with Python infrastructure success but native formatting and compiled
test discovery failure; full native tests and Clippy were skipped. That failed
historical run proves nothing about subsequent GUI changes. No complete passing
six-subject result is claimed here. Retain real outcomes, including failure,
timeout, cancelled, skipped and missing jobs, without translating them to pass.

## 14. Signed updates, activation and rollback

Signed manifests bind channel, target, package, predecessor, evidence, protocol,
selector/generator identities and validity window. Staging and helper activation
use the existing update owner locks. A GUI close request alone cannot activate:
its admitted worker must be joined and runtime close confirmed without failure.

The helper re-verifies the staged package and predecessor. ActivatedUnconfirmed
must not be cleared by a static self-test or exit zero. Readiness requires the
normal installed process, its handoff and authenticated view, with the GUI
witness checked as described above. Unsafe or uncertain recovery remains
RecoveryRequired. Rollback cannot overwrite an unrelated newer binary.

Formal installed release upgrade/rollback, schema-compatible downgrade policy,
production key rotation/revocation, Windows replacement and macOS signed bundle
behavior still require actual implementation/host evidence where missing.
Unsigned ZIP packages and source state machines are not signed installer
qualification. The release contract is normative for independent promotion.

## 15. Implementation sequence and remaining work packages

First close current correctness and source delivery: execute the mounted
retirement tests, fix current compiler/format/lint failures, refresh derived
registries and validate exact source objects. Complete this before accepting
performance or UI readiness claims for the final candidate.

Next optimize storage under the existing journal owner. A derived disk index
must be rebuildable from a verified chain and bound to its exact frontier.
Missing, stale or corrupt index state must never be interpreted as an identity
being unretired. Specify startup, rebuild, lookup and recovery budgets separately.
Do not promise constant-time startup without an appropriate trusted checkpoint.

For active-journal optimization, measure lookup, allocation, serialization,
file/directory synchronization and full-operation latency separately. Preserve
no-write exact duplicates and post-failure fencing. A new append/checkpoint
format needs explicit migration and crash-cut coverage, not a hidden change to
v6 byte interpretation. Retain a comparison against the unchanged snapshot path.

Then exercise real chooser/focus behavior, implement verified resource handoff
where supported, and qualify installation/update/recovery on target hosts.
Accessibility, IME, DPI, endurance, production signing custody and independent
release selection remain separate work packages and evidence gates.

## 16. Development workflow and historical retirement

All implementation changes must be normal reviewable commits on the named
candidate. The three temporary write-enabled preparers have been replaced by
read-only retirement notices, and the invalid patch capsule has been removed.
Qualification must not silently patch, format, commit or push its tested source.
A formatting proposal may be reviewed and committed separately, after which the
new exact candidate must be tested again.

Historical guides and implementation maps are preserved under `history/` for
migration/audit context. Relative links inside those archived bytes refer to
the original document location and may require consulting the anchored source.
They are not alternative current entrypoints. Keep generated global module
indexes synchronized through their normal generation commands; do not edit a
successful receipt by hand to hide drift or the lack of an executed check.

## 17. Definition of module completion

Completion is layered: implementation exists; build module/test tree includes
it; ordinary product calls use it; exact-head checks pass; deterministic merge
checks pass; target-host behavior is accepted; independent release gates pass.
No one Boolean or source map may stand for all of those states.

This revision advances ordinary source implementation and documents remaining
work. It does not establish production implementation, deployment qualification,
independent acceptance, signing, promotion or release. All corresponding flags
remain false until their own retained evidence and authorized decisions exist.
No historical pass, source archive, GUI fixture or CI hash can authorize an OS
effect or a production release.
