# E5 per-request source trace recount (shadow only)

**Purpose:** Existing `e5_cross_cohort.py` checks the four 64/256/1024/4096 Cell aggregate claim packets. This additional, independent read-only stage compares one cohort's **original request trace rows** with its declared counters. A self-generated digest or Worker claim is not a signed physical observation.

Use `python experiments/shared_stem_cell/e5_trace_recount.py --cohort /evidence/cohort.json --trace /evidence/requests.json --output /sealed/recount.json`. Source and trace inputs must be independently staged. No background network download, pretrained model loading, Neuron installation, effect, or production token is performed.

The request trace requires separate request ID, Cell ID, Scope, positive generation, preprocessor SHA, fence SHA, input content SHA, backend forward ID, backend batch ID, cache-hit status, final-use declaration, and failed-request status. The separate cohort and trace must match five SHA-bound identities: run, model, host, Worker, and plan.

The independent code reconstructs exact reported total requests, unique Cell coverage, source input count, backend-forward identities, unique backend batch IDs, cache hits, failure count and FinalUse check count. It rejects duplicate requests, changed Scope/generation/fence/preprocessor on cache-hit reuse, reused forward IDs for distinct cache misses, changed batch identities, missing FinalUse declarations, and any counter mismatch. It does **not** verify an actual native backend, true model forward count, worker signature, real cache-memory sharing, release authorization, or post-crash recovery.

The 15 local synthetic mechanism/fault tests passed against an equivalent isolated local implementation. New exact-HEAD GitHub Action must independently demonstrate the pushed code and tests are valid. No actual 64/256/1024/4096 target-host trace is included. Every result has `real_worker_execution_independently_verified=false`, `final_use_claims_authenticated=false`, `production_promotion_permitted=false`, `authority=DENY_ALL`.

**Production gates remain open:** signed physical Worker origin, source manifest/host verification, process-lifetime RSS, actual microbatch/queue p95/p99, CPU/GPU/power, revoked cached feature FinalUse, WAL crash/reopen and independently witnessed NDU. No shortcut into selected Stem, Artifacts CAS or production routes.
