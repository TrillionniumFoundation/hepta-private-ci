# C2 original start budget ledger — current balance remains HOLD

This evidence-only reconciliation binds retained desktop campaign bytes to the six
original C2 start parents. It executes no model, Torch, optimizer, native
training, or new idempotency key.

The immutable campaign roster records six HCSN terminal commands with
`returncode=2`, `fit_status=budget_exhausted`, a 14,400-second hard wall, and
exact `whole_process_wall_seconds`. Charging those complete outer-wall values
against the frozen 43,200-second per-fit cap, with zero parent refund, closes the
original decision's non-refunded per-fit charged remainders. Their `math.fsum`
is exactly `172938.8845898183`, matching the pre-existing decision.

The 600-second finalization reserve remains inside each 43,200-second cap. It is
not already deducted from that aggregate. The separately recorded worker active
ceilings subtract 600 seconds per fit and sum to `169338.8845898183`.

This does **not** establish current remaining balances. The original replay
controller's terminal/finalization state, its later per-fit charges, and
cancelled-attempt optimizer/wall charges remain `UNKNOWN`. With no refunds,
current balances can only be no greater than these original-decision charged
remainders. No replay admission or resource allocation is created.

Run the deterministic zero-execution check with:

```sh
python3 qualification/hcsn_c2_original_budget_ledger_20261114_c06d/verify_ledger.py
```

Full independent training replay remains `0/6`; lifetime optimizer calls and
the original controller terminal remain `UNKNOWN`. Global status remains
`HOLD / all_closed=false`.
