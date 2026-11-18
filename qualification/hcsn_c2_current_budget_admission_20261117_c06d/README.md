# C2 current-budget admission HOLD

This source-only contract binds the published original-decision parent and wall
ledger without admitting a new six-fit replay. It performs no model, Torch,
optimizer, native-host, or execution-key operation.

## Decision

- `HOLD_INCOMPLETE_HISTORY`; `all_closed=false`.
- Full fit replay remains `0/6`.
- The two successful checkpoint-continuation diagnostics comprise 12 fit
  continuations and 52 known optimizer calls. They are not six full-training
  replays and do not resolve lifetime optimizer calls.
- The six charged remainders are exactly `43200 - original whole_process_wall`.
  Their sum, `172938.8845898183`, is the original-decision charged remainder
  before the six separate 600-second exit reserves. The corresponding original
  worker-active ceiling is `169338.8845898183`.
- Later-attempt wall, per-fit exit overhead, current remaining balance, current
  worker-active ceiling, lifetime optimizer calls, and the original controller
  terminal state remain `UNKNOWN`.
- The runtime identity hash is recorded, but its authoritative bytes are not
  Git-bound in this lineage. Cursor state is absent for every parent. No current
  replay admission can form a coherent source/runtime/model/data identity.

`admission.py` therefore fails closed if a consumer attempts to allocate a key,
admit resources or replay, relabel diagnostics, fill an unknown, change the
original wall arithmetic, or claim identity completion. Tests are synthetic and
use only the Python standard library.

## Read-only verification

```bash
python3 admission.py
python3 -m unittest -v test_admission.py
python3 -O -m unittest -v test_admission.py
python3 verify_frozen_sources.py
python3 -O verify_frozen_sources.py
```

Passing these checks grants only the source-level fail-closed behavior described
above. It grants no training, replay, checkpoint, numerical, resource, or
production qualification.
