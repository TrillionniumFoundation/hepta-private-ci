# channel.matrix production transport trusted-computing boundary

Status: **source contract; target execution still requires exact external evidence**.

The only production physical-send composition is the statically linked
`MatrixSdkClient` in `codex-hepta-matrix-sdk`, constructed by `matrixd` and
passed directly to the durable outbox sender. The public transport trait exists
for deterministic fixtures; it is not a production plugin registry and cannot
replace the product callsite.

`TRANSPORT_TCB.json` is the canonical registry. Safe Rust is admitted only under
the crate-level `forbid(unsafe_code)`. Unsafe Rust, FFI, dynamically loaded
libraries and a remote sidecar that performs the physical Matrix send are not
qualified production modes. The final-use broker remains a separate authority
service, but it cannot perform or report the Matrix effect.

The registered transport identity binds homeserver, Matrix user, device, session
generation, room, binding revision and Matrix-plane generation. Target evidence
also binds Matrixd, Agentd and test-binary SHA-256 values, configuration digest,
homeserver image digest, process-identity ledger, runner image and target triple.
A transport implementation's self-reported identity is never sufficient by
itself.

Run the executable source guard with:

```sh
python3 scripts/channel_matrix_transport_tcb.py --output /tmp/transport-tcb.json
```

The guard verifies the sealed raw-send boundary, private permit adapter, absence
of a public raw SDK client, exact product composition, the closed implementation
inventory and the absence of dynamic/FFI transport seams. This source guard does
not establish a real homeserver run, process-crash qualification, activation,
promotion or release.
