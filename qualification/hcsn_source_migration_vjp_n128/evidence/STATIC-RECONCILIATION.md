# Visit-897 N128 static-admission reconciliation

Global status: **HOLD**. Numerical admission remains **not executed**.

The original same-key desktop job `1a1d086d1a2-2564-1b95` is now authoritatively terminal: `failed`, exit 2, not cancelled, not timed out, with complete durable output. It failed before the inspector because the wrapper invoked `just fmt -- --base 994def…`; the repository formatter accepts `--base BASE` without the extra separator. The exact 374-byte stderr and all process flags are retained in `STATIC-ADMISSION-FAILED.json`.

No retry was sent, no replacement key was created, and no forward, adjoint, Torch, model, DDE, or optimizer operation ran. The source branch and frozen candidate source remain unchanged.

A separate post-failure static inspection recomputed all 19 inventory hashes, parsed the bounded source AST, and passed 29 frozen checks with zero candidate imports or numerical calls. It is retained as `STATIC-INDEPENDENT-REVIEW.json`. Because it occurred after the failed pre-admission job, it is explicitly **not** an admission pass and does not authorize numerical execution.

Historical failures and UNKNOWN entries outside this exact job remain unchanged. The candidate is still limited to one original visit-897 law, N128, fixed physics/support/delay, and first-cycle scalar-loss VJP intent; N512, full posterior migration, fullnetwork training, task benefit, production adoption, and finite-domain qualification remain open.
