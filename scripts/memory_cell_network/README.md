# Memory cells over loopback TCP

This research layer runs a durable placement authority and long-running workers
as separate OS processes. Requests and checkpoint bytes cross authenticated HTTP
connections. Each worker has its own checkpoint directory, `owner.sqlite`, and
`fences.sqlite`. No worker reads another worker's database or checkpoint path.

The listener and client deliberately accept only `127.0.0.1`. The integration
tests establish real TCP/process behavior on one host. They do not establish
multi-host performance, distributed consensus, high availability, TLS deployment,
or production acceptance. A tiny randomly initialized decoder tests transport and
lifecycle mechanics; its output is not a pretrained memory quality result.

## Source authority and lifecycle

Run the authority with `--source-root` and `--scope` to bind the existing
`MemoryService`. Every frontier request then calls `MemoryService.authority_view`
against its durable source owner. A service correction or revocation is visible
on the next network admission without an extra frontier synchronization call.
Only the authority receives the source directory. Workers receive scope, roots,
manifest pins, placement metadata, checkpoint bytes, and questions; they receive
no source facts or answer list.

Bound mode rejects manual `frontier` RPC writes. An authority without a bound
source service has an explicit operator-managed frontier RPC for isolated
mechanism experiments. That mode must not be used as a cached replacement for a
live source owner. `Authority(database, source_frontier=provider)` also accepts a
trusted callable returning `Frontier` for embedding into a service.

One bound service owns one `(scope, cell_id, role)` identity. Independent source
services should use distinct scopes and authorities. Combining multiple source
owners into one scope requires an explicit common epoch and withdrawal owner;
independent database epochs are not interchangeable.

| Operation | Mechanism |
| --- | --- |
| Stage | Transfer the three fixed checkpoint files; verify the independently retained manifest pin, tensor digest/layout, configuration digest, scope, and provenance; fsync before atomic rename. |
| Publish | Compare-and-swap the expected placement generation; register its immutable manifest and roots. Exact retries return the same generation. |
| Read | Fetch the current placement and source frontier over TCP; latch both locally; execute behind `ParametricOwner` admission and output barriers. |
| Migrate | Export actual bytes from the current owner; validate a separate target copy; advance the placement with CAS. The previous node fails its placement fence. |
| Revoke | Latch monotonic source withdrawals at each contacted node. New reads reject before a model callback; an already-running callback's result is discarded if its frontier changes. |
| Recover | Stage a separately trained clean replay with surviving source roots and publish a new generation. This does not claim that old weights have been mathematically unlearned. |
| Restart | Reopen the authority, owner, and fence databases. An observed frontier or placement cannot be rolled back by restarting a worker. |
| Lose authority | Fail closed. Workers do not grant reads from a cached authorization lease. |

Migration can cause an availability gap between the placement commit and the
target's first successful load. The target stages and validates bytes before CAS;
full base-model compatibility is checked when its decoder loads the adapter.
The implementation does not claim a fault-tolerant consensus transition. A lost
authority database cannot be reconstructed from a quorum of workers. Node-local
fences reject only states older than what that node has already observed.

## Processes and Python API

Use a Python environment with the dependencies from `scripts/memory_cell`.
Create a private local key file containing exactly 32 random bytes, and pass its
path to each process. The key is never a command-line value. Its holders are
trusted publishers and readers; this protocol does not provide separate user
roles. HMAC authenticates the request and binds the response to a random request
nonce; it does not encrypt HTTP traffic.

```sh
python -B scripts/memory_cell_network/network_serve.py authority \
  --root /tmp/memory-authority --key-file /tmp/memory-key \
  --ready-file /tmp/memory-authority-ready.json \
  --source-root /tmp/memory-source --scope example --cell-id memory

python -B scripts/memory_cell_network/network_serve.py worker \
  --root /tmp/memory-node-a --key-file /tmp/memory-key \
  --ready-file /tmp/memory-a-ready.json --node-id a \
  --authority http://127.0.0.1:AUTHORITY_PORT --model /path/to/pinned/base
```

The ready file contains `{endpoint, pid, role}` after binding. Start another
worker with a different root and node ID. Supply `--port` to reuse a known port
after restarting. Use `--cell-role procedural` when the bound source service was
created with that role.

Add `scripts/memory_cell_network` and `scripts/memory_cell` to `PYTHONPATH`:

```python
from network_client import NetworkClient

client = NetworkClient(authority_url, {"a": node_a_url, "b": node_b_url}, key)
client.stage("a", snapshot_directory, retained_manifest_sha256, scope)
initial = dict(scope=scope, cell_id="memory", node_id="a", generation=0,
               manifest_sha256=retained_manifest_sha256, roots=sorted(source_roots))
client.publish(initial, expected_generation=None)
before = client.read(scope, "memory", [question])
migration = client.migrate(initial, "b")
after = client.read(scope, "memory", [question])
```

`read` returns the original decoder journal, including raw text/token IDs,
admitted/consumed adapter digests, and input provenance flags. Research controls
`control="base"` and `control="shuffled"` remain available and explicitly labeled.
Neither is a publishable checkpoint. Each read constructs and releases a decoder
in its worker; restarting the worker also provides a fresh-process check. Models
are lazy-loaded and use two Torch threads. No answer overlay replaces raw output.

`client.service_reader(active, question)` is a callback for
`MemoryService.invoke_parameter`. It additionally binds the service's active
manifest to the network's current placement, preserving the service's source
admission and the network's independent placement/withdrawal barriers.

The protocol caps each wire body at 96 MiB and checkpoint weights at 64 MiB. File
names are fixed; remote paths are never accepted. Query fields are closed and
bounded. These research bounds are not memory-efficiency or throughput claims.

## Verification and review stages

`run_tests.sh` uses a trained tiny decoder and actual independent worker processes
over TCP. The tests cover raw generation and controls, byte-identical migration,
stale-node rejection, revocation during inference, restart, rolled-back authority
state, unavailable authority, transfer tampering, authentication failure, clean
replay, and idempotent migration. They require permission to create loopback
sockets; a sandbox denial is a test failure, never a skipped success.

For reviewable commits, the dependencies divide into: (1) wire, authority and
durable observations; (2) checkpoint transport, worker and client; (3) process CLI
and network integration tests; (4) source-service binding and documentation.
