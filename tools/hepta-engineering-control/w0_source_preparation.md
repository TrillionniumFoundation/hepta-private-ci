# W0 source-preparation snapshot

`w0_snapshot.py` is a bounded, read-only pre-entry tool. It records a proposal
from committed Git bytes and observes checkout cleanliness. It does not select
canonical source, admit a lane, pass W0, issue a receipt or checkpoint, or grant
runtime, merge, promotion, release, activation, tool, network, or external-effect
authority.

## Commands

Both identities must be lowercase full 40-hex commit IDs. `--source` must equal
the checkout `HEAD`, and `--base` must be its ancestor.

```bash
python3 tools/hepta-engineering-control/w0_snapshot.py snapshot \
  --root /absolute/repository --base BASE40 --source SOURCE40
```

The snapshot is printed to standard output. If it must be retained for a drift
check, save it outside the observed checkout so that saving it cannot change the
clean-state observation.

```bash
python3 tools/hepta-engineering-control/w0_snapshot.py check \
  --root /absolute/repository --base BASE40 --source SOURCE40 \
  --snapshot /outside/repository/w0-proposal.json
```

Exit `0` from `check` means only that no drift was detected between two
point-in-time source-preparation observations. Exit `2` is a bounded input or
canonical-shape rejection (`W0_INPUT_REJECTED:<code>`). Exit `3` is snapshot
drift (`W0_DRIFT:<code>`). None is a formal readiness decision.

## Captured facts

The proposal binds base/source commit, tree and ordered parents; all paths in
`DOCUMENT_SYSTEM.json` by Git blob and full-file SHA-256; the canonical
contract, protocol, source binding, path ownership, readiness, CNS, HNMF,
algorithm and delivery inputs; every module guide and execution-dossier digest;
and exact seven-lane coverage of forty modules. Exclusive owned roots are
checked for prefix collisions across modules. Shared roots are reported for
lease review and are not automatically treated as collisions.

Cleanliness is a current checkout observation, represented by a boolean and a
digest of bounded porcelain output. It is not a TTL, lease, or freshness
certificate. Every use must recompute the snapshot. Provenance and contract
drift are compared before this dirty-state marker.

## Deliberately open gates

The output always keeps formal W0, formal receipt issuance, canonical selection,
lane admission, and all authority flags false. It explicitly lists the source
receipt, branch-purpose manifest, reviewed lane envelopes, independent semantic
acceptance, external gates, and integration checkpoint as not supplied or open.
A dirty checkout and any shared-root lease review are additional blockers.
