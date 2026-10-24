# Native CPU owner profile

`hepta-native-cpu` is one frozen ELF for the reviewed Asterinas
`g2-trusted-daemon` initial transaction. It requires the actual HOS2BOOT v3
page, fixed Root/Manager/Workload/Recovery Process identities and the original
8 MiB file / 16 MiB load limits. Ordinary execution has no supported fallback.
This module is separate from ordinary Agentd's full App Server profile.

## Authority and lifecycle

Root mounts devtmpfs, proc, sysfs, cgroup2 and the retained `/dev/vda` ext2 state
before publishing its private startup marker. Manager and Recovery each open
`/dev/hepta-control` in their own final kernel-created Process, then drop to
UID/GID 60001 with empty groups, zero capability sets, NNP and no dumpability.
The workload retains its independent UID 60002 and session. No device descriptor
is transferred across processes, and no child exec inherits an HOS2 role.

The original FleetRegistry registers the Agent. Only the original Supervisor
allocates Starting generations and retains process leases. Its
`KernelInitialProcessDriver` takes one Manager slot, then one Recovery slot;
these finite slots are not renewal or a process factory. It retains real
pidfds, boot/start identity and exclusive child-reaper custody. Original exact
Agentd Health checks perform promotion. The native profile never reports
AppServerReady.

Root initializes a fresh explicit installation under `/state/hepta-native`.
Existing or partial state is refused. The original Root authority directory,
clock, lease registry, key, issuer sequence, protected checkpoint, physical
material archive and two consumer frontiers are the only authority owners.
The acceptance-plan JSON contains only scenario and nonce; it cannot choose
registrations, keys, paths, leases or a recovery cut.

The same retained HostAuthorityService captures a sealed bootstrap, serves all
five original lanes and confirms the zero-argument recovered-owner readiness
notification. The Host connects all five lanes before awaiting the live Root
feed, activates its two original FinalUse owners, reads an actual opaque
Current receipt and opens the sole writer through
`open_with_protected_recovery_and_ready`. No JSON-derived token or local-state
hash substitutes for protected Current.

## Exact CPU operations

The native Root installs a typed admission for one exact native boot/capability
space/manage-slot scope. The existing Notes exact-effect lease algorithm is
shared as a stateless helper: it retains one short exact payload-bound effect
lease in the original AuthorityLeaseRegistry, then signs only under the original
joint writer/effect dispatch boundary. Notes lease IDs and domain bytes remain
unchanged. CPU effects use the same canonical key, revocation head and sequence.
No protected lease check is bypassed or weakened into a wildcard.

The writer's candidate-D read queries the original immutable outbox. It reserves
nothing. `prepare_operation` still atomically verifies the next original D,
exact K-to-D binding and terminal predecessor. Dispatch uses the attached
ProductionHos2Target and original FinalUse path; reconciliation only observes
an existing D. Native history is retired only through `retire_hos2_through`,
which rebuilds and publishes the actual durable terminal prefix first.

Native command admission closes before drain. A process-local serial gate joins
already entered work without owning any operation ledger. Drain also inspects
original durable HOS2 pending state, so queued, indeterminate or corrupt state
cannot become an empty-work claim. Shutdown waits for the existing command
future and joins the original RuntimeTasks before writer release and SQLite
pool closure. Unknown effects retain the existing fail-closed recovery path.
Once shutdown has stopped the monitor, pending work may remain unresolved.
The bounded shutdown then returns an error and does not release the writer;
a timeout is never reported as successful drain. The retained original ledger
and protected material must be recovered by a legitimate successor.

## Acceptance and remaining scope

The current entry implements `steady-state-v1`: lower to 25 ms, pause at zero,
and resume to 50 ms per original 100 ms period. Root transcribes actual prepared
payloads, terminal receipts, Current and physical material, consumer frontiers,
history retirement and measured CPU/heartbeat windows. Store device/inode
come from the running writer's actual active database path after its original
recovery factory, not the earlier fresh-administration database. It also reports actual
role credentials and privilege-boundary refusals. The final VM return must be
the original kernel poweroff/debug-exit result; a transcript alone is not a pass.

`manager-exit-after-terminal-v1` retains the Manager's complete actual Current,
physical image and both complete consumer frontiers before an actual pidfd
SIGKILL. Root observes `POLLIN` and `waitid(WNOWAIT)` for that same child; the
original Supervisor remains the exclusive reaper and owns Failed, restart
budget, the actual next Starting generation and Health promotion. Root waits
for the independent original watchdog and the original local lease's real
expiry. Process death alone never retires a local writer lease.

The trusted fresh installation issues 20-second writer authority leases. This
leaves recovery headroom within the unchanged native Recovery grace of 30
seconds after Manager closure. A successor receives a new original lease,
never an extension of the old lease; the 5-second watchdog/effect policy and
300-second native grant retain their original bounds. Actual guest execution
must verify that startup, physical material and operation timing fit these
bounds. Expiry or a missed window fails acceptance.

The same canonical issuer rotates the actual retained writer proof. The
original recovered-checkpoint CAS and physical installer adopt only the retained
Current image, retain the original owner lock through checks, then release that
lock before the same Host factory and zero-argument Ready handshake. Recovery
opens its own native descriptor, queries the original D using the complete
immutable request, and compares it with the original ledger's verified terminal
and event ID. The read-only terminal accessor adds no event or effect. Only
then does the original writer retire the durable prefix. A fresh request after
the watchdog has consumed the recovery allowance must retain an actual native
refusal without another CPU revision.

Cross-boot adoption, more than the two initial management images, grant renewal
beyond the original 300-second native lease and power-loss qualification remain
separate requirements. Neither finite scenario establishes those results.

Compile and test the affected original crates with `just test --locked -p
codex-hepta-agentd -p codex-hepta-memory -p codex-hepta-supervisor --lib`.
The supervisor's `kernel_initial::child::tests` exercise real Linux pidfd,
identity, termination and reap behavior. Existing exact Notes lease tests must
remain green after the shared-admission extraction. Then build the real binary
with default features, using the existing release profile and environment
size overrides (`OPT_LEVEL=z`, `LTO=fat`, `CODEGEN_UNITS=1`), and pass that exact
frozen ELF/build receipt to the native owner runner. A successful host build is
neither ELF-size admission nor a native owner-cycle result.
