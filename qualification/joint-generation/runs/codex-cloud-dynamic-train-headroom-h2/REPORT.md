# H2: startup implementation failure, zero measurements

**Actual terminal: worker exit 1, overall exit 1. H2 is consumed; no inference/headroom result exists.**

The single invocation ran at 2026-10-23T16:10:36.526689+00:00 through 2026-10-23T16:10:37.017153+00:00. Frozen source was `f3c9d89bf10be3e0d7664d3ba5c3eb17cc782665`, execution commit `a5bec822cf5c235c52c7a6ab20bf74297a9795e8`, freeze SHA256 `cf555cd1571d2019b6c9c2e1ca737ff9392682a0e2b19aae580425d699413e52`.

The exact failure is `independent.accounting.AccountingError: invalid arm` during dependency initialization at `WorkLedger("H2-TRAIN-R&D-not-qualification", total_cap=4_000_000_000)`. The ampersand is outside the existing name grammar `[A-Za-z0-9][A-Za-z0-9_.:/-]{0,95}`. The failure is a code defect, not a model or scientific result.

Only `dependency_imports` ran. The retained diagnostic has ledger=null, known mathematical units=0, unsettled units=0, inputs={}, attempted_calls=[] and service_calls=[]. Thus TRAIN was never constructed, the T11 archive/models were not restored, no model/native forward ran, and all 36 planned service calls remain unexecuted. No useful utility/timing boundary can be inferred from this failure. The protected historical evidence was verified unchanged at exit.

Full worker/descendant CPU was 0.491702000 s; launcher-own CPU before its final receipt was 0.027556463 s, combined 0.519258463 s. Wall time was 0.490468164 s. Zero declared mathematical work does not mean zero actual research cost. The retained console and exact outer process receipt are in `../codex-cloud-dynamic-h2-source-preflight/actual-worker-{console.log,execution.json}`.

The original START, PARTIAL, freeze and console remain intact. The subsequent one-line source correction removes only the ampersand from the label; the accounting rules, budget, task, models, order and formulas are unchanged. A production-AST/real-WorkLedger regression passes without worker import, data, model or service execution. It does not turn the failed invocation into a pass. Earlier seven handmade boundary/algebra tests passed but did not exercise that actual label; this targeted regression closes that missed startup defect.

The existing H2 protocol consumes any exception and disallows rerun/output aliases. No H2 continuation or renamed recovery has been run. A concrete [technical recovery draft](../../training_diagnostics/dynamic-h2/TECHNICAL_RECOVERY_DRAFT.md) is prepared for parent review; it retains the original failure and research cost and proposes exactly the previously unexecuted 36 calls under an explicit amended once-only rule.

D1 remains a separate real CPU-cap failure with cache slots unrun. H1 remains only the old-price conditional TRAIN oracle calculation; direct same-NC/full cost and static NDU TRAIN utility are still missing. Therefore current-weight dynamic viability is unresolved; there is no evidence justifying a larger critic or a declaration that every dynamic policy is impossible. All r2/CORE failures and test states remain unchanged. No new formal test, AV generation, merge, deployment or authority change occurred.
