# Matrixd owner-peer contract qualification

The b9 source (`b9afe1f469ad12c5cd520af0ecef4c8e22f295ed`, tree
`c00dc49a3cf072e594737c437f18e6c70fd36b0d`) ran 34 Matrixd unit tests in
Windows main shard 3: 33 passed and
`health_tracks_real_task_state_and_owner_uds_serves_exact_identity` failed
with OS 10054, `ConnectionReset`.

- Run: <https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45585341998>
- Job: `139107875678`
- Actual merge: `276d0c1425f266bc2ad8b6024a0468ff58e2384d`; its tree is the
  same `c00dc49a3cf072e594737c437f18e6c70fd36b0d` as the source head.
- Complete original job log: 570,985 bytes, SHA-256
  `c9b1db9f91033379235b365ddea33e771ecce7df1babe28deabc2e2b42159edf`.

`serve_connection` checks `ensure_current_user_peer` before reading any
control request. The current Windows `codex-uds` implementation explicitly
returns `Unsupported`; the server's per-connection task does not send an
unauthenticated response. The old test expected a successful owner-local
Health response on every platform. Its expectation did not match this
existing backend contract. The three socket-path tests in the same target
passed; they establish different properties from peer authentication.

The candidate changes tests only:

- The original owner-UDS positive test and every assertion in its body are
  retained for the eight operating systems supported by the existing
  kernel-peer identity implementation.
- The original Health and lifecycle assertions also execute independently
  on every platform.
- Other platforms, including Windows, bind a real listener and connect a
  real stream, send a valid fenced CancelTurn for an active turn, and invoke
  the actual handler. The test requires its exact `Unsupported` error,
  zero response bytes, no cancellation or approval transport call, and an
  unchanged complete durable control snapshot. EOF or connection reset is
  permitted only for the already rejected stream. The two-second I/O bound
  remains unchanged.

Production peer authentication, protocol, dispatch, permissions, timeouts
and durable authority are unchanged. Passing the new negative test will
qualify rejection by this backend. It will not restore or qualify Windows
owner-local Matrixd control functionality. Adding such functionality needs
a separately justified identity mechanism.

At source preparation, `just fmt` and `git diff --check` passed. The
candidate has not yet run Rust tests or the Windows branch; those remain
required in the scoped Matrixd and normal platform CI gates. The original
b9 failure is preserved and is not relabelled as a pass.
