# PRED native TaskFlow collection

Base: f5f2ca267c7e58b3a14bfc1381bf84d67dd42a15 (#5523).
This is the first of two reviewable stages; scientific qualification remains HOLD.

`collect_native(database, identity=..., clock_id=..., cursor=...)` reads one
exact owner/run/step/attempt/intent/payload/binding/destination through a single
SQLite read transaction with mode=ro and query_only. It preserves original
attempts, observations and reconciliations separately, including UNKNOWN.

Availability is sampled from the collector monotonic clock after reading; native
timestamps stay raw metadata. The host supplies trusted database provenance,
clock identity and a single arrival sequencer. Each field is bounded in SQL
before Python materialization, including on the Python 3.10 API fallback.
Artifacts use immutable, canonical, size-bounded, SHA-checked bytes and create-only
saves. These integrity checks do not authenticate a database or its rows.

Two behavior tests use actual SQLite/WAL with synthetic owner records and exact
native migrations 0011/0013. They verify WAL visibility, read-only access, missing
rows and oversized-value rejection, including a simulated missing-setlimit API.
This is not a test on a Python 3.10 interpreter or a production owner.

No accepted/executed phase, business outcome, effect duration or physical-cost
label is inferred. Snapshot freezing and later readback association follow in
the second stage. Neither stage trains a model on native records.

The registered 189-fit diagnostic remains ORIGINAL_ARTIFACTS_NOT_LOCATED, not
declared lost. GitHub code/branch/PR and relevant workflow-artifact checks found
no published campaign. Bounded workspace and Mac/ROG directory checks did not
locate originals; the controller workspace query timed out. Earlier prose does
not replace COMPLETE, outer EXITED/0 or the checkpoint inventory. No formal fit
outcomes were opened, campaign rerun, or historical confirmation set reopened.
