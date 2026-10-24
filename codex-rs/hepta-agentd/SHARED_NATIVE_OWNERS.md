# Shared ownership of the full and native Agentd entry points

The full library and native executable compile the same original authority,
process, writer, checkpoint, and lifecycle modules. The native entry is a
separate Rust source root in this same package. It does not reference the full
Agentd library as an external crate. Cargo's existing dependency versions,
default features and release profile remain in effect.

This boundary is necessary because linked startup constructors retain code even
when ordinary methods are not called. The measured original native build at
Hepta bb886c81 and OS cc5137c9 still contained 436 constructors and produced a
17,945,208-byte stripped static ELF. That artifact did not pass the unchanged
8 MiB initial-file limit. Source restructuring is not proof of a smaller or
accepted binary; the original build, packaging and ELF admission must run again.

## Source ownership

| Module | Responsibility |
| --- | --- |
| shared_owner_modules.rs | One declaration list for the original shared authority and process owners. |
| native_owner_main.rs and native_owner_modules.rs | Native source root and fixed original native composition. |
| state_core.rs and control_core.rs | Original generic state, transport, locking and lifecycle bodies. |
| state.rs and control.rs | Full profile and existing public/default API adapters. |
| state_native.rs and control_native.rs | Fixed native profile of those same shared bodies. |
| config_native.rs and process_identity.rs | Original validated process configuration and identity without a full execution configuration. |
| production_writer_owner.rs | Sole shared production writer host implementation. |
| production_writer_host.rs and production_writer_native.rs | Full and native source-root composition of that owner. |
| production_protected_host.rs | Original protected recovery and launch-ready construction. |
| production_protected_config.rs | Full configuration adaptation to the same recovery construction. |
| objective_claims.rs | Original pure objective claim helpers reused by both roots. |
| lifecycle_signal.rs | Original shutdown signal implementation shared by both roots. |

The native configuration does not create a second SQLite writer, lease
registry, issuer, checkpoint, consumer ledger or Supervisor. Root issuance,
actual process identity, held pidfds, generation fences, Current publication,
drain and retirement remain enforced by the original owners.

## SQLite dependency boundary

The codex-sqlite crate owns the original SQLite connection configuration, read
barrier, fd-bound physical recovery and Root material publication implementation.
The codex-state crate reexports those same nominal types under its existing
public names. Its application-specific migrations, error handling, close
ordering and telemetry remain in its private runtime extension. Memory imports
the shared SQLite types directly so that generic storage does not bring the
full protocol and execution-policy registration graph into the native executable.

Moved production files must be deleted from the former source directory in the
same change. The old and new paths must never contain independent writable
owners. Cargo.lock and the Bazel lock must be produced by the actual resolver.

## Validation

Run the original full Agentd tests, the shared SQLite and state tests, and
Memory tests through just test. The shared SQLite tests include original
Root-only parent tests and controlled child helpers; select the parents
explicitly instead of launching child helpers as independent tests.

Then build the actual native target using its original release profile, default
features, dependency inputs and static flags. Run the original symbol packaging,
readelf checks and unchanged file/LOAD/segment limits. Native execution,
continuous CPU control, failure recovery and retained-disk restart require
their actual guest runs and independently checked retained state.

A source inventory, a host test, or a smaller ELF alone does not establish
native execution or persistence. Earlier failures remain separate evidence
bound to their actual source pairs.
