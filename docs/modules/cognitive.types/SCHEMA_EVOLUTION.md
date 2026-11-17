# cognitive.types schema evolution

## Change classes

| Change                                                             |    Same schema/version? | Required action                                |
| ------------------------------------------------------------------ | ----------------------: | ---------------------------------------------- |
| Documentation clarification with no semantic effect                |                     Yes | confirm source and wire behavior are unchanged |
| Additional internal helper                                         |                     Yes | normal review                                  |
| Stronger validation rejecting states already forbidden by contract |             Usually yes | compatibility fixture and consumer review      |
| Stronger validation rejecting previously legitimate states         |                      No | new schema/version or migration exception      |
| New optional wire field                                            |                      No | new schema version                             |
| New enum variant                                                   | No for closed consumers | new schema version                             |
| Field rename, type or meaning change                               |                      No | new schema ID/version                          |
| Digest or canonicalization change                                  |                      No | new digest profile and migration               |
| Authority interpretation change                                    |                      No | security review and new contract               |

## Version rules

- Schema IDs and contract IDs are immutable once published.
- `schemaVersion` participates in the domain-bound digest.
- Unknown versions are rejected; there is no best-effort downgrade.
- A decoder never ignores unknown critical fields.
- Cross-version adapters are explicit, bounded and tested in both directions where reversal is possible.
- Durable owners retain enough metadata to interpret historical versions.

## Compatibility digests

The legacy canonical digest remains stable for existing V1 callers. The domain-bound digest is additive and explicitly selected by new integrations. A migration does not overwrite stored legacy digests without recording the profile.

## Validation changes

Before tightening a validator:

1. enumerate current golden vectors and durable examples;
2. determine whether the rejected state was intended or accidentally accepted;
3. run shadow validation against production-like data;
4. publish mismatch counts;
5. use same-version hardening only when semantics were already forbidden;
6. otherwise introduce a new version and adapter.

The zero-origin plasticity case is the reference example: creation from old weight zero is legitimate. The explicit strict profile rejects a zero resulting weight or a relation-sign conflict. Existing Wire V1 validation continues to accept its historical zero-weight synapse, empty plasticity/forget and broader topology values where the original validator allowed them. Enabling the strict profile for a consumer requires an explicit migration decision.

## Retirement

A legacy surface may be retired only after every named consumer has a canonical binding, shadow receipts show exact equality for the declared observation window, the production call site is switched, rollback is rehearsed, historical reads remain possible where required, and exact-head plus synthetic-merge qualification receipts pass.
