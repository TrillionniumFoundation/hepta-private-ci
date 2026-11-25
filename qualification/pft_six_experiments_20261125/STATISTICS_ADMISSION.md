# Fixed-objective statistics admission

This engineering change extends the existing `distributed.Receiver` used by
the PFT2 TCP peer. It does not rerun or relabel the frozen PFT1–PFT6 evidence.

The receiver retains the parent, coordinate and objective identity, protects
registered inputs from caller mutation, rejects boolean counts/dimensions,
and deduplicates an exact declared data digest even when the client ID changes.
It rejects nonfinite/asymmetric/clearly non-PSD statistics, an estimated rank
larger than the sample count, an inconsistent moment in a numerically exact
null direction, and aggregate overflow before admitting a contribution.

The PSD/rank tolerance scales with float64 precision and feature dimension.
Small **positive** eigenvalues remain possible data directions, including
ill-conditioned examples whose targets concentrate entirely in that direction.
Near-zero and rounding-level negative directions are inconclusive. These
checks do not prove that a contribution came from real data, detect all
inconsistent statistics, or supply Byzantine, Sybil or privacy protection.
Changing a declared data digest or submitting partly overlapping datasets can
still evade exact-content deduplication; that needs separately verified source
provenance. Header IDs also need an independently trusted source.

`freeze(cutoff_id)` records a deterministic statistics snapshot and closes the
candidate. The cutoff is an explicit application event, not a trusted wall
clock. Identical retransmissions remain idempotent; new arrivals require
`fork()` and produce a distinct snapshot linked to the prior snapshot. A cold
restore retains this boundary. Callers with retained identities must pass
`expected_header` and `expected_snapshot_id`; a self-contained checksum alone
cannot authenticate a rewritten checkpoint.

The TCP worker checks its actual ridge cost and parent bytes against the frozen
objective and parent digests before opening the peer. It freezes and persists its ledger after convergence and
server shutdown, and includes `statistics_snapshot_id` alongside its actual
candidate hash. An open legacy checkpoint remains readable. Frozen records
cannot be reopened implicitly by `restore`.

Engineering validation uses small fixed matrices, an independent augmented
least-squares oracle, malformed packet controls, order/duplicate controls and
checkpoint/fork controls. It does not use trained models, teacher calls,
real-user data or the frozen research fixtures:

```sh
python3 -m unittest discover -s qualification/pft_six_experiments_20261125 -p test_distributed_admission.py -v
```

The caller must serialize `accept`, `freeze` and `checkpoint`; the existing TCP
peer already owns a lock and closes its server before freezing. This does not
establish multi-host P2P reachability, actual Hepta adoption, a new independent
scientific sample or an end-to-end training speedup.
