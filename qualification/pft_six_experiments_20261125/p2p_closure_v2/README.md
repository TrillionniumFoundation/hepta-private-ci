# PFT2: direct physical peer closure, version 2

The previously blocked two-host transport is now closed using the machines' existing authenticated Hepta SSH transport. Both configured physical hosts, `ai395` and `pocket4`, generate their own non-IID data and sufficient statistics. The statistics travel directly between those hosts over USB4. The controller provisions code and retrieves completed evidence; it does not relay the training statistics between peers.

## Recorded result

The frozen experiment uses dimensions 8, 16, 32, and 64 with new seeds 271801–271803. These twelve transport qualification cases are separate from the original E1–E6 training budgets.

| Measurement | Observed result |
| --- | --- |
| Completed two-host cases | 12 of 12 |
| Independent evidence checks | 18 per case, all passed |
| Actual remote process exits | 17, then 0 in every case |
| Restarted contribution count | Five: four local and one durably received |
| Complete contribution count at each peer | Eight |
| Candidate agreement | Identical full floating-point candidate SHA256 at both peers |
| Maximum relative difference from independent NumPy ridge solve | 7.700594136418377e-16 |
| Application frame bytes sent, both directions | 6,925,364 |
| Frame-level sender/receiver hash and byte agreement | Exact in both directions for every case |
| Supervisor elapsed time, all twelve cases | 16.26187083683908 seconds |
| Launcher elapsed time through process completion | 16.36607716884464 seconds |
| Weighted local coefficient average worse on independent held-out inputs | 12 of 12 cases |

These results support direct decentralized execution of a fixed-basis linear ridge subproblem. They do not establish inversion of an entire nonlinear model, privacy of sufficient statistics, Byzantine data validity, or permissionless membership.

## Diagnosis and isolated repair

The original direct application-port runs remain failed evidence. New read-only diagnosis found working routes and a physical Thunderbolt/USB4 link. Both machines could connect to the other's existing SSH port, with or without a per-socket interface binding. A task-specific listener on the observed USB4 address did start successfully, but the reverse peer's application-port connections still timed out. Interface binding alone did not fix that failure. The firewall service was active; reading its rule set required privileges unavailable to the diagnostic process, so no particular firewall rule is claimed as the proven cause.

The existing Hepta SSH configuration already provided a trusted peer alias, a dedicated known-hosts file, an existing key identity, and a descriptor-passing transport selector. The selected socket was a direct USB4 connection from `ai395` to `pocket4`. The experiment uses strict host-key checking and batch authentication, disables agent forwarding, and makes no firewall, shared-route, key, or trust-store changes. The original private address receipts remain private; public receipts identify the registered hosts and content hashes.

## Protocol and recovery

Each peer starts from the same parent vector, coordinate identifier, objective identifier, protocol version, and source bundle. Each local dataset contributes `G = X.T @ X` and `b = X.T @ (y - X @ parent)` for the objective

`0.5 * sum(||X @ action - residual||²) + ridge/2 * ||action||²`.

Each machine independently sums the same eight contributions in canonical identifier order and solves `(sum(G) + ridge * I) @ action = sum(b)`. The prior is charged once in this global solve.

The wire protocol sends batches in order 3, 1, 0, 2 and repeats them. It first sends an intentionally stale-parent contribution, which must be rejected. A contribution identity binds the parent, basis, objective, node, batch, and dataset hash. Repeated frames are idempotent; conflicting versions of an existing batch and repeated dataset hashes under another contribution are rejected. Numerical admission checks dimensions, finite values, symmetry, and positive semidefiniteness within the documented numerical tolerance.

On the first valid external contribution, the `pocket4` process fsyncs its ledger, retains the exact crash checkpoint in a compressed artifact, and calls `os._exit(17)` before acknowledging that contribution. The initiating node observes SSH's actual exit code 17, waits the predeclared 0.35 seconds, and starts a new peer process. That process reads the existing ledger and does not regenerate its local data. The archived checkpoint bytes, their SHA256, the restored ledger SHA256, the old PID, and the new PID all agree. Retransmission produces one additional duplicate at the recovered peer.

Once solved, the contribution set is frozen. Further admission, a second solve, and a mutable resume of a solved or published round are rejected. Resume also checks the requested node, dimension, seed, actual parent, basis, and objective instead of trusting only a self-contained envelope hash.

## Cost interpretation

The per-node evidence records feature/data generation, `G,b` formation, admission, encoding and decoding, pipe reads and writes, checkpoint writes and readbacks, restore work, solve work, and the fault wait. The terminal receipts separately record final result publication and readback. The complete supervisor and launcher clocks include both remote processes, both SSH sessions, the fault gap, and final per-case persistence.

At dimension 64, the mean solve stage was 6.40 ms on `pocket4` and 12.18 ms on `ai395`. The initiating node's mean elapsed time through final result readback was 2.123 seconds per case. A local millisecond solve is therefore not the system-level training cost.

The nodes execute concurrently. Pipe-read time includes waiting for the other node's computation and disk operations, and overlaps SSH startup measurement. Those counters cannot be added across hosts. The recovered node's process-wall field covers its second process; the overall launcher clock covers the full lifecycle. Some crash-time fsync and Python overhead remains unclassified inside the complete wall interval. Application bytes exclude SSH encryption overhead, TCP/IP headers, and retransmissions. Dependency preparation, code deployment, later archive packaging, evidence retrieval, and independent audit are separate operational stages.

## Evidence and reproduction

- `results/pft2_direct_peer_ssh.json` is the independent frozen-evidence audit, including every case and phase counter.
- `evidence/execution_receipts.json` binds configured-host job IDs to complete durable terminal states and complete stdout/stderr streams.
- `evidence/archives/` contains both hosts' exact result, terminal, statistics, and crash artifacts, with independent host manifests. Every archive is below 512,000 bytes.
- `evidence/verification.json` records the focused state tests and the separately labeled local subprocess protocol check.
- `evidence/network_resolution.json` describes the diagnosis without publishing private network addresses.
- `evidence/original_pft2_multihost_pre_disruption.json` preserves the recovered original v1 summary bytes, SHA256 `07241b551cef0e12ba4408e36ae0fe808c7943f7d2ffdf289430f6878dc74296`. It does not replace the earlier disruption-recovery wrapper.
- `ARCHIVE_INDEX.json` lists publication paths, exact byte counts, and SHA256 values.

Run the independent numerical and transport audit from this directory:

```sh
python3 audit_evidence.py --archives evidence/archives --output /tmp/pft2_peer_audit.json
python3 test_protocol_state.py
```

The audit requires NumPy and the original pinned `../multihost.py`, SHA256 `9880293805ec22e1b9b990e37c0927a4a788e8be988d353af669ea0906342be6`. It never launches a peer, regenerates training statistics, or trains a model. Its independent held-out linear inputs are used only to compare already frozen candidates.

The first archive-packaging attempt grouped all three dimension-64 cases and exceeded the repository's per-blob gate. That packaging failure is retained in the execution receipts. The accepted archives split those cases without rerunning computation or transport.

`PUBLIC_HOOK.md` describes how a separately qualified feature provider can supply local statistics for a real frozen model. Such a run needs its own experiment identity, source and capsule bindings, budgets, and held-out evaluation; it does not inherit scientific success from these synthetic transport cases.
