# C2 current-budget admission contract — HOLD

The six original start parents and the original-decision wall ledger are now
byte-bound, but they are not a current executable replay budget. Later replay
charges, cancelled-attempt wall and optimizer counts, controller finalization,
per-fit exit overhead, and exact current per-fit balances remain `UNKNOWN`.

This source-only contract makes those omissions fail closed. It preserves the
six completed-epoch parent identities while requiring a future admission to
account for every non-refunded attempt, resolve the controller terminal state,
bind current resource evidence, and provide a non-null execution key. The old
runner's `resume_supported=false` and missing cursor remain explicit blockers.

Synthetic fixtures exercise metadata validation only. They do not import
Torch, deserialize checkpoints, run a model or optimizer, allocate resources,
launch replay, or grant scientific or production qualification.

Status: **HOLD / full replay 0/6 / all_closed=false**.
