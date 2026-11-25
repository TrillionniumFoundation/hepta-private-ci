# Root-private cognitive publication material

`RootCognitiveMaterialRegistration` and `VerifiedCognitiveMaterial` reuse the
original cognitive owner, SQLite recovery copy and exact-cut verifier. They do
not supply a Current checkpoint, a writer, an issuer or permission to recover.
This is a physical-material API; actual Root service publication and recovery
must still be wired and qualified separately.

## Registration and launch order

The trusted launcher fixes the original agent layout, non-Root owner UID and
Root-private destination. No checkpoint message selects any of those paths.
The original recovery factory first returns its sole recovered store, which
may have selected a new active generation. Before protected checkpoint binding,
writer construction or Session release, the fixed one-shot launch channel asks
Root to verify the recovered owner. Root derives the generation itself with
the original private active-pointer parser and compares its complete logical
cut with the independently retained Current. Only this trusted launch phase
may install the generation registration.

`RootCognitiveMaterialRegistration::bind_registered_layout` retains the actual
database and parent descriptors and exposes read-only device/inode identity
for the existing protected Root registration. It also retains the active
pointer's descriptor, complete bounded bytes and metadata, or its absence.
Normal database contents and timestamps may change; registered database and
parent identities cannot. Pointer replacement, including a new pointer with
the same filename contents, is refused. FIFO pointers are rejected without
waiting for a writer. No capture automatically re-registers a generation.

Root death releases these descriptors. Persisted device/inode numbers alone
cannot exclude inode reuse afterwards. A new Root lifetime needs the original
trusted cold bootstrap, actual Host lifetime checks and independent Current
and physical-material validation before granting authority again.

## One publication attempt

1. The original owner holds its coherent transaction. Root does not acquire
   the live store's lifetime-exclusive recovery lock.
2. The registered source creates one new `RootSqliteMaterialSource` capture.
   Fresh original retained-descriptor checks bind database/WAL/journal bytes
   and reject changes during copying. SHM is not copied. The database and each
   retained sidecar are bounded to 128 MiB, with a 256 MiB aggregate limit.
3. `materialize_private_candidate` writes only the original default database
   filename in a fresh destination for the same agent. The destination and
   every ancestor must be Root-owned and not writable by group/other; the
   destination itself is mode 0700. Existing DB/WAL/SHM/journal files are
   refused. File and directory synchronization are required.
4. `CognitiveStore::verify_root_material_candidate` authenticates the bounded
   original schema and complete prospective cut before SQLite integrity
   expressions. It uses the original private-copy consolidation, full
   checkpoint, integrity and synchronization, then a final retained-descriptor
   read-only full-cut/integrity comparison. It returns path/cut evidence only.
5. Root must retain this durable material before its original Prepare/Commit
   CAS can reference that exact cut. Registry publication fencing remains the
   original service's responsibility; do not hold its lease lock over the
   potentially large copy and SQLite validation.

Metadata stability detects drift; it does not prove coherent SQLite pages.
The complete independent cut, exact schema and SQLite integrity checks remain
mandatory. A prospective cut is not Current until the original Root backend
has durably committed and independently acknowledged it. Unknown publication
results retain both predecessor and proposed material for original recovery;
they never authorize replay, a new nonce, counter reset or a fresh owner.

## Scope and validation

The new fixtures cover an actual Root process capturing UID 60001 source
files, live WAL copying without the owner-exclusive lock, exact-cut mismatch,
original recovered-generation selection, immutable pointer/parent/database
identity, protected destinations and no activation. Ordinary regressions cover
Root admission, schema-before-CHECK ordering and nonblocking FIFO rejection.
Root fixtures are ignored by default and must run explicitly as actual Root
against a protected destination; no fake-UID bypass is provided.

These authored fixtures and source review do not qualify a deployed Root
service, Dirty recovery, physical devices, a native-kernel daemon or an ELF
size gate. Record actual command/source/result receipts when running them.
