# Direct exchange of frozen statistics

`direct_snapshot.py` is a separate engineering entry for two configured peers.
It reads one already retained aggregate from each original PFT2 host archive,
projects it into the checked `Receiver` contract, exchanges it directly, and
freezes the resulting candidate. It generates no new training data or labels.
The original `multihost.py`, its failed network attempts, and its twelve-case
numerical report remain historical evidence with their original source identity.

## Before execution

Retain a separate SHA-256 of each UTF-8 configuration file. The configuration
binds the new three-file source roster, both peer endpoints, a unique round,
the actual parent, the original generator source, the entire local compressed
archive, the selected original record, and the projected contribution digest of
each peer. Each host receives only its own archived statistics and both digest
commitments. The transport uses no controller relay or SSH forwarding.

The current engineering profile is exactly two peers, one selected record per
peer, a 45-second delivery deadline and one-second retry interval. Each frame and
incoming exchange has one absolute two-second deadline, so slow fragments do not
restart a per-read timer. The listener closes in a `finally` block on delivery
failure. Teardown is separate from the delivery budget: the server poll interval
is 20 ms and an already active request has at most its remaining two seconds,
apart from host scheduling and finite filesystem/numerical work. An output
directory is create-exclusive; an uncertain or completed attempt is refused on
re-entry. A different source or endpoint requires a distinct retained admission,
not reinterpretation of the previous attempt.

Run with the registered installed interpreter:

```sh
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 python3 direct_snapshot.py \
  CONFIG.json --expected INDEPENDENT_CONFIG_SHA256
```

Source and input checks occur before the output claim and before sockets open.
The receiver rejects a different socket source address, a contribution whose
owner differs from its sender, and a payload outside the retained contribution
roster. Normal receipt validation, exact data-digest duplicate rejection and
immutable candidate snapshots remain active. A node binds outgoing connections
to its registered local address rather than leaving interface selection implicit.

## Retained observations

Each host retains `STARTED.json`, `END.json`, the projected worker configuration,
the checked ledger and its frozen snapshot, and the worker result. Successful
frame events include actual local and peer socket endpoints. Raw application
frames are stored by SHA-256 and checked on duplicate writes. The final result
requires two admitted contributions and an actual incoming application frame.
The host runtime's original exit/stdout/stderr remain independent evidence.

After both hosts terminate, compare both retained contribution rosters, snapshot
identities, frame digests in each direction, and independently solved candidates.
Exact-byte equality and numerical tolerance are different reported checks.
The full deployment/preflight, failed connects, transport, solve and result
retrieval costs are separate measurements; the inner wall clock is not complete
end-to-end training cost.

An IP address and digest pin do not authenticate a Byzantine peer, prove honest
data or establish privacy. This direct frozen-input check does not qualify new
cross-user learning, a multi-host crash/recovery campaign, WAN operation,
foundation-model improvement, native runtime adoption or useful-work settlement.
Old frozen E1–E6 counters and scientific matrices are not restarted here.

`test_direct_snapshot.py` uses the actual two-process TCP entry and original
statistics, checks retained frame bytes, and rejects source/owner/payload/input
substitution and replayed output ownership. Loopback control results are distinct
from an actual two-host observation.
