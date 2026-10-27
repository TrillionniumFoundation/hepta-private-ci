# secret-service 4.0.0: actual zbus 6.1 port

Original published source, MIT OR Apache-2.0:
https://static.crates.io/crates/secret-service/secret-service-4.0.0.crate

Original archive SHA-256:
`e4d35ad99a181be0a60ffcbe85d680d98f87bdc4d7644ade319b87076b9dbfd4`.

Both original license files and `Cargo.toml.orig` are retained. The normalized
manifest requires zbus 6.1 with its client proxy API. The existing async-io
feature names select its maintained default runtime, Tokio aliases remain,
and MSRV is 1.89. Crypto dependencies and both plain/DH algorithms are unchanged.

## Port

- Replace merged `zvariant` paths with the maintained zbus root types; use
  `Variant`/`OwnedVariant` and the zbus derives.
- Adapt proxy visibility, owned property results, `proxy::CacheProperties`, and
  builder errors deferred to `build()`.
- Keep the public blocking service/collection/item operations. They now call
  `zbus::block_on` on the same asynchronous proxy operations; public blocking
  methods never enclose other blocking methods inside a `block_on` call.
- Reuse the async session negotiation, locking and prompt handling for blocking
  calls instead of maintaining a second wire implementation.
- Keep `Error::Zvariant` as the local conversion-error category, explicitly map
  local variant conversions now that wire and transport errors share zbus's
  error type, and recognize the new missing-socket `Error::Connection` wrapper.

The keyring public API and every keyring Rust implementation file are unchanged.
The secret-service low-level foreign payload types necessarily belong to zbus 6
instead of zbus 4; this is a private workspace patch, not a claim of universal
binary compatibility for arbitrary secret-service consumers.

The synchronous API remains for synchronous execution. As documented by zbus,
it must not be called from a runtime task that it would block; Tokio users use
the async API or a blocking worker. Both the default and optional Tokio runtime
feature selections passed the isolated real-service checks.

## Verification

Real GNOME Secret Service, private D-Bus sockets and synthetic encrypted files
cover plain/DH transport, binary/Unicode credentials, properties, ambiguous
delete/read, version-1 attributes, concurrency and persistence after daemon
restart. A separate real D-Bus fixture covers Completed, dismissed and malformed
prompt results through both public interfaces. An unchanged libdbus client
independently checks metadata and stored-credential interoperability.

The server may add `xdg:schema` asynchronously and reports `text/plain` for a
binary content type; the unchanged libdbus implementation observes the same
behavior. The test suite compares these server effects rather than changing
production credential serialization. Original failed fixture assumptions remain
in the evidence. Full workspace/platform/Bazel gates are still required.
