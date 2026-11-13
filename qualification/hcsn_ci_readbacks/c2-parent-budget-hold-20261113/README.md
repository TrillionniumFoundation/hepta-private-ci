# C2 six-fit start-parent and remaining-wall HOLD

Status: **HOLD_NO_GO**, `all_closed=false`, full independent replay `0/6`.

This evidence-only inventory decodes the immutable #6214 ZIP without running a model, Torch, an optimizer, native training, or a new idempotency key. Its complete central directory contains 556 entries: 555 archived originals plus `INDEX.json`.

The original campaign-v2 result bytes close the six intended start-parent identities at epochs `46/47/46/47/46/46`. The ZIP does not contain those six PT files. Its only six PT members are later checkpoints at epochs `116/76/126/50/127/72`; they are retained only as last-observed cumulative-wall lower bounds and are not substituted for the original parents.

No exact per-fit remaining-wall ledger can be reconstructed. The original controller terminal/finalization state and per-fit exit overhead are absent. The authoritative aggregate maximum (`172938.8845898183`) also differs from both naive result-wall and process-wall subtractions. `HOLD.json` therefore preserves every per-fit remainder as `UNKNOWN`; it does not refund old attempts or infer a decomposition.

Run the zero-execution consistency check with:

```sh
python3 qualification/hcsn_ci_readbacks/c2-parent-budget-hold-20261113/verify_hold.py
```

Historical OOM/cancelled attempts, known diagnostic optimizer calls 52, lifetime optimizer total `UNKNOWN`, and original controller terminal `UNKNOWN` remain unchanged.
