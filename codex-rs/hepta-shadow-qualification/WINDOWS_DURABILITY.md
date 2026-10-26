# Shadow Windows artifact development and technical contract

`durable_windows` is a safe consumer adapter to the single `codex-utils-path`
retained private-artifact backend. Shadow keeps `#![forbid(unsafe_code)]`.
Directory bootstrap, new-file write, bounded read, private file/directory
inspection and directory barrier use that common full-identity/DACL predicate.
An inventory holds a read-only retained directory over the full walk and checks
its exact unchanged snapshot afterward. It cannot derive a writer capability.

The backend exclusively creates a missing private leaf with its descriptor
applied atomically. It never fixes security or adopts an incompatible existing
directory. Artifact writes are acknowledged only after actual file and original
writable-directory barriers and verification. Errors and partially completed
effects remain errors. There is no Windows unconditional privacy-success branch.

Run the original declared Shadow Windows 31-case scope through `just test`
without changing identities, limits or assertions. Shared backend negative
controls are a separate scope. Compilation, a collector pass, or API-shaped
probe traces do not qualify the actual original product cases. Native runner
receipts must bind exact clean source before/after, compiler, full result IDs
and zero retries. This change does not establish a missing helper, SSHSIG input
ownership, production observer or physical power-loss acceptance.

See [canonical API, callers and evidence](../utils/path-utils/PRIVATE_ARTIFACTS_WINDOWS.md)
and the existing [cross-crate qualification boundaries](DURABLE_ROUNDTRIP.md).
Dossier identities, formats, bootstrap policy and migration rules remain owned
by the current caller; there is no implicit data or permission migration.
