# cognitive.store authoritative entry point

This directory has one current architecture decision:

- **Unique production-write facade:** `AgentdProductionWriterHost`.
- **Physical owner:** `hepta-memory::CognitiveStore` over `cognitive_1.sqlite3`.
- **Serving capability:** `DurableCognitiveReadStore`, which has no mutation or raw-backend escape.
- **Semantic oracle:** `AdmittedCognitiveStoreV2`; it is not a second database.
- **External prerequisites:** an independently authenticated current-cut witness and an externally verified live production-authority lease.

`TECHNICAL.md` defines the module, `PRODUCTION_CLOSURE.md` fixes composition and evidence boundaries, and `IMPLEMENTATION_MAP.json` is the machine-readable status.  The remaining files are normative lifecycle and operator references:

- `adr/ADR-0001-retention-pruning.md`
- `BACKUP_WAL_DERIVED_ARTIFACTS.md`
- `PRIVACY_EXPORT_DELETE.md`
- `SCHEMA_COMPATIBILITY.md`
- `ERROR_CATALOG.md`
- `RETRY_RECONCILE_MATRIX.md`
- `SLO.md`
- `THREAT_MODEL.md`

Run `python3 scripts/cognitive_store_architecture.py` before any cognitive-store change.  Exact source-head and deterministic base-merge execution belongs to `.github/workflows/cognitive-store-qualification.yml`; source presence or prose never substitutes for its terminal receipts.
