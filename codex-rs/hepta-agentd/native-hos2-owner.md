# Original G2 native operation host

`attach_g2_native_operation_host` is an explicit Linux composition seam for a
trusted native launcher. Ordinary Agentd startup does not call it. It adds no
issuer, Registry generation, authority lease, consumer journal, database open
fallback, native process or kernel role.

| Input or retained object | Original owner and responsibility |
| --- | --- |
| `AgentdConfig` | Original Registry Starting identity and retained original writer-lock descriptor. |
| `AgentdRootProductionInputs` | Original Root's sealed descriptor, live pidfd, five authenticated lanes, exact Current, Device/Notes consumers and FinalUse grant provider. |
| `File` | This same image's actual `/dev/hepta-control` descriptor, opened before its original credential drop. It is not a Root descriptor transferred into another process. |
| `AgentdG2NativeImage` | Exact initial v3 or successor v4 discovery page from the kernel. Existing adapter validation checks actual PID, parent, namespace, slots and QueryAbi. Selecting v4 does not renew or adopt an image. |
| `ProductionHos2Target` | The original native HOS2 target backed by that exact process-bound device. |
| `AgentdRootProductionAttachment` | Retained original Root feed, protected checkpoint, grant provider and the same two frontier owners. |
| `AgentdProductionWriterHost` | Original protected recovery and one atomic config installation; the same writer dispatches and retires. |

The native constructor runs before any writer recovery. It then calls the
original `attach_root_production_operation_host` with the actual HOS2 target
and no Notes application channel. All original Current/cut, live-verifier,
sender-process and consumer checks remain in their original implementation.
There is no independently constructed retirement permit: `retire_through`
delegates to `ProductionDurableWriter::retire_hos2_through` with the retained
original target. A missing terminal or uncertain authority continues to fail.

The trusted launcher must keep `AgentdG2NativeOperationHost` alive through the
operation lifetime. `read_usage` returns the actual kernel observation;
`install_request` only constructs the original canonical request before K/D
is persisted. Its sequence must be allocated by the original operation owner.
It neither dispatches that request nor issues a FinalUse grant. Callers use
the original host's normal grant-bound dispatch. `acknowledge_current_receipt`
then delegates to the original writer's `acknowledge_current` and independently
reads the authenticated protected Current DTO before a source terminal can be
reported. It returns the actual observed cut; concurrent authorized work can
invalidate Current and this call grants no continuing exclusive access. It
does not reconstruct a token, reopen a fenced writer, create a physical backup
or infer an effect's result from Current alone.

This module is a composition component, not an execution receipt or a complete
native boot entry. A complete product still needs a tracked compact Root/owner
entry using original Supervisor `PrecreatedProcessDriver`/SpawnSpec, actual
kernel role identities, authenticated Root startup, independent physical
recovery material bound to Current, and actual retained native runs. The finite
Desktop G2 oracle additionally requires original-owner source/terminal/history
records and independent workload CPU observations. No code here emits those
records or claims full G2, image renewal, power-loss recovery or physical-device
qualification. Its compilation and integration results must be recorded for
the exact final source combination before execution.
# Root physical material owner (implementation stage)

`authority_host_checkpoint_material.rs` owns immutable Root0600 SQLite images
and Root0600 candidate records in one retained Root0700 directory outside the
registered cognitive directory. The original Root transition supplies the
complete candidate head and token; managers supply neither a digest nor a cut.
A record alone confers no Current status. Admission requires the actual original
protected Current to equal that candidate, including its original token.

The image is made by the original CognitiveStore's read-only live snapshot API,
checked against its original cut, synced, and retained by physical SHA-256. The
candidate record is synced before the original Current CAS. Reopening verifies
the existing record and image only. Missing/corrupt material cannot trigger a
fresh capture of the live store. The first profile allows at most 128 directory
entries and refuses exhaustion without removing older evidence.

`authority_host_checkpoint_material_worker.rs` supplies one Root worker and one
occupied operation. The caller waits at most its original configured deadline
(up to five seconds). Timeout does not release the worker's occupied capacity.
The original publisher pidfd is checked before and after live capture. The
worker runs asynchronous SQLite outside the Root's synchronous publication
mutex; the original caller retains its publication transaction while waiting.

`PreparedHostAuthoritySession::prepare_fresh_with_physical_material` is the
explicit product constructor. It uses the original registered-writer factory
and opaque fresh-store witness; its original writer lock stays held until the
material-backed genesis and both original consumer heads are published. The
fixed material directory is `state_dir/cognitive-material-v1`, with the same
Root0700 ancestry requirements as the original owners. The original filesystem
handoff then releases only Agentd data, not this Root material directory.

For this constructor, each original transition to Current captures and verifies
its image before the original CAS. ReadHead, replay ACK and Root handoff verify
the retained material of Current before returning it. A material error closes
the original publisher object. Dirty/Publishing/Fenced are never promoted by
material lookup. `open_with_physical_material` reopens only the existing live
registration and verifies existing material; it cannot repair a missing image.

`recover_with_physical_material(config_file, registration_file, owner_pidfd)`
is an explicit Root ceremony for an already registered successor. It reads the
actual old protected Current, obtains actual same-boot kernel retirement of the
old publisher, requires its original lease expired and the actual successor
alive, and validates the original adoption's exact epoch/generation/grant rules
before changing filesystem custody. The same original Registry dispatch fence
and retained writer proof cover restoration and adoption. It accepts no image,
digest, cut, new lease, reset flag or manager-computed recovery identity.

The original Root0600 writer lock and the original exclusive CognitiveStore
lock are retained during installation. Root temporarily takes custody of only
the exact registered cognitive directory. Installation reads the retained
independent image descriptor, verifies its physical digest and full original
cut, and creates a new original-format generation in that directory. Old DB,
WAL and journal generations remain intact; old pointer bytes are retained and
the original atomic active-pointer publisher selects the new generation.

Original Current adoption then carries the old cut byte-for-byte to the real
successor, with an immutable new candidate record referencing the same retained
image. No live capture occurs during this ceremony. Existing original consumer
frontiers reopen without initialization. Only the installed generation, new
pointer and registered directory are released to the original dedicated UID.
The opaque installation retains the exclusive store lock until that release.
An error keeps partial material and Root custody available for diagnosis;
retrying the fresh constructor is forbidden. The successor still needs the
original Agentd authority/recovery admission before it can write.

The first combined typecheck found the memory crate's `forbid(unsafe_code)`
correctly rejected raw credential reads. Those reads and installation ownership
changes now use safe workspace rustix APIs; the prohibition remains intact.
The dependency is Linux-only, Cargo.lock binds the existing rustix version,
and an actual `just bazel-lock-update` completed without MODULE lock changes.
Final combined typecheck, original-owner regressions and actual Root/native
execution are still required. Source availability establishes none of them and
does not establish a completed native G2 product.
