# Maintained zbus 6 compatibility backport

Source: open-source-cooperative/secret-service-rs pull request 122,
commit `7a91b597904c1847f18a06b72a19ee8153e0a578` (base
`d0500ec5efe1369f89015d315c9aecefc7d6d9b8`). This is an explicitly vendored
upstream proposal, not a claim that version 6.0.0 has been published or reviewed
upstream. Its MIT and Apache-2.0 license files are included unchanged.

The maintained zbus 6 release incorporates the former zbus_names, zvariant, and
zvariant_derive crates. Those retired packages have the unmaintained advisories
RUSTSEC-2026-0372, RUSTSEC-2026-0370, and RUSTSEC-2026-0371 respectively.
The proposal updates the wire/name types and wraps the async Secret Service API
with zruntime for the existing blocking API, since zbus 6 removed its blocking
API. The existing Diffie-Hellman negotiation, AES-CBC encryption, collection
selection, item lookup, prompts, and secret serialization remain in use.

One local hardening change constructs a blocking connection on a short-lived
initialization thread. This prevents optional zbus Tokio feature unification
from attaching the connection to an ambient current-thread Tokio runtime that
the synchronous credential API then blocks. zruntime's helper continues driving
the independent connection after initialization and when the credential store
is used from another thread. Thread creation/join failures remain errors.
Four local protocol regression tests cover prompt acceptance, dismissal,
disconnect, and malformed replies. Repository rustfmt is applied to the imported
Rust sources. Calls still block their caller; they do not gain async cancellation. Callers of
`connect_with_existing` remain responsible for driving their supplied connection.

The keyring store continues to hold the same mutex for the whole operation.
Prompt dismissal and disconnect continue to propagate through the original
error mapping; no fallback to a plaintext or in-memory credential store is
introduced. Secret values are neither logged nor retained by a new worker queue.

Source review and executable interoperability/runtime evidence are kept in
`qualification/dependency-closure-20261021`. Replace this path patch with a
published compatible upstream release once its blocking/runtime behavior passes
the same qualification. Do not remove the patch merely to suppress advisories.
