# Independent SQLite shim revision review

The reviewed delta changes only the test file `codex-rs/hepta-memory/src/objective_sender_tests.rs` among the ten checkpoint-current candidate files. The manifest comparison and exact file/patch fingerprints are in `sqlite-shim-revision-review.json`. The previous candidate and its review are retained separately.

The new `independent_writer_connection` creates a separate original `codex_state::SqliteConfig` pool at the same `store.path()`, acquires one connection, detaches it, and closes that separate pool. The original `SqliteConfig::open_durable_evidence_pool` uses WAL, full synchronous durability and foreign keys. The selected connection then explicitly sets `PRAGMA busy_timeout = 0`, retaining the former immediate-conflict behavior rather than the helper's default five-second wait.

The lockfile-selected `sqlx-core 0.9.0` implementation documents and implements `PoolConnection::detach` as extraction of the raw connection while releasing its floating pool guard. Thus the subsequent `pool.close().await` does not require that detached connection to be returned. The retained handle is genuinely independent of the original owner's pool/transaction and continues to compete on the same SQLite database write lock.

The three replacements are restricted to connection setup for `checkpoint_current_holds_the_original_write_lock_through_acknowledgement`, the acknowledged snapshot locking regression, and `checkpoint_holds_original_sqlite_write_serialization_until_acknowledgement`. The patch does not change their BEGIN/ROLLBACK operations, the SQLITE_BUSY code 5 assertion, ACK waiting points, subsequent writable check, test attributes, or production source. No new allow attribute suppresses the warning. Source review found no concrete blocker or weakening of the tested write-serialization property.

This review did not run Cargo, Rust, Agentd, or a guest. The earlier 327-pass record belongs to the preceding candidate bytes; the owning agent's separate execution records determine the revised candidate's qualification. This review also does not establish a production checkpoint backend or terminal-lease checkpoint support.
