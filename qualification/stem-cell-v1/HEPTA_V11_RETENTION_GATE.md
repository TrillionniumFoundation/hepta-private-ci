# V11 — Original V6 bridge retention admission audit

**DRAFT / SHADOW_ONLY / DENY_ALL.** This increment audits historical V6 evidence. It neither retrains the Granite97M shared Stem nor fixes seed41's real continuation failure.

The original `bridge-v6-result.json` comes from #2338's V6 physical training lineage. Its contrastive Reader primary passed all three controlled warmup fittings, but retention after continuation passed only 2/3 seeds. V11 checks every original nine-row warmup and nine-row continuation inventory, exact seed identity, old/new candidate and paired-world denominators, original frozen runtime and producer verdict. It rejects dropping failed cases, changing denominators, replacing the precommitted contrastive primary with replay, reclassifying negative evidence as complete, claiming feedback/fresh evaluation, or silently modifying the original training report.

Acceptance conditions, evaluated independently for each seed:
- Candidate correct fraction >=95%.
- Paired-world correct fraction >=95%.
- Candidate correctness loss relative to that seed's own V6 bridge warmup <=5 percentage points.
- Paired-world correctness loss relative to that seed's own V6 bridge warmup <=5 percentage points.

For seed41, contrastive has 124/128 candidate correct (96.875%) and **60/64 paired-world correct (93.75%)**, a 6.25 percentage-point paired loss versus warmup 64/64; it fails. Seeds 47 and 53 pass the historical retention condition. This does **not** establish cross-task generalization or a new experiment.

Run the isolated synthetic contract tests with `PYTHONPATH=qualification/stem-cell-v1 python -m unittest -v qualification/stem-cell-v1/test_v11_retention_gate.py` and repeat with `python -O`. The dedicated source CI also runs the auditor against the **actual repository V6 JSON** to ensure the historical NO-GO cannot silently turn into a pass.

Research priorities remain: a new immutable, source-pinned V6 physical 3-seed continuation comparing replay, gradient regularization and frozen-bridge policies at explicitly measured lifecycle cost; only after prospective retention success can previously unopened fresh domains be evaluated. Existing V9 MiniLM Head LoCoMo results are separate and cannot be substituted.

**No model promotion, Cell division, main merge, NDU/FinalUse/production authority.**
