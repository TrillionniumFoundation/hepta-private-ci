#!/usr/bin/env python3
"""Centralize kernel.evidence transitive SQLite opens and consume strict lint blockers."""
from pathlib import Path
import re

R = Path(__file__).resolve().parents[1]

def load(p): return (R / p).read_text(encoding="utf-8")
def save(p, s): (R / p).write_text(s, encoding="utf-8")

def rep(p, old, new):
    s = load(p)
    if new in s and old not in s: return
    if s.count(old) != 1: raise SystemExit(f"{p}: expected one match for {old[:80]!r}")
    save(p, s.replace(old, new, 1))

def ins(p, anchor, value):
    s = load(p)
    if value in s: return
    if s.count(anchor) != 1: raise SystemExit(f"{p}: ambiguous anchor {anchor!r}")
    save(p, s.replace(anchor, anchor + value, 1))

def drop(p, value):
    s = load(p)
    if value not in s: return
    if s.count(value) != 1: raise SystemExit(f"{p}: ambiguous removal {value!r}")
    save(p, s.replace(value, "", 1))

def rx(p, pattern, replacement):
    s = load(p)
    if replacement in s and re.search(pattern, s, re.S | re.M) is None: return
    out, n = re.subn(pattern, replacement, s, count=1, flags=re.S | re.M)
    if n != 1: raise SystemExit(f"{p}: regex did not match exactly once")
    save(p, out)

state = "codex-rs/state/src/sqlite.rs"
state_lib = "codex-rs/state/src/lib.rs"
ops_cargo = "codex-rs/hepta-operations/Cargo.toml"
ops_dest = "codex-rs/hepta-operations/src/destination_dedupe.rs"
ops_store = "codex-rs/hepta-operations/src/durable_store.rs"
auth_cargo = "codex-rs/hepta-authbus/Cargo.toml"
auth_schema = "codex-rs/hepta-authbus/src/authority_schema.rs"
auth_store = "codex-rs/hepta-authbus/src/authority_store.rs"
auth_quota = "codex-rs/hepta-authbus/src/quota_store.rs"
auth_trust = "codex-rs/hepta-authbus/src/trust_store.rs"
sync = "scripts/kernel_evidence_integration_sync.py"

helpers = '''/// Centralized FULL/WAL SQLite profile for authoritative component stores.
pub async fn open_durable_component_pool(
    path: &Path,
    max_connections: u32,
) -> Result<SqlitePool, Error> {
    if max_connections == 0 {
        return Err(Error::Protocol(
            "durable component pool requires at least one connection".to_string(),
        ));
    }
    let options = SqliteConnectOptions::new()
        .filename(path)
        .create_if_missing(true)
        .journal_mode(SqliteJournalMode::Wal)
        .synchronous(SqliteSynchronous::Full)
        .foreign_keys(true)
        .busy_timeout(Duration::from_secs(5))
        .log_statements(LevelFilter::Off);
    SqlitePoolOptions::new()
        .max_connections(max_connections)
        .connect_with(options)
        .await
}

/// One-connection transient database used only to materialize migration schema.
pub async fn open_transient_migration_pool() -> Result<SqlitePool, Error> {
    SqlitePoolOptions::new()
        .max_connections(1)
        .connect("sqlite::memory:")
        .await
}

'''
s = load(state)
if helpers not in s:
    if s.count("impl SqliteConfig {\n") != 1: raise SystemExit("ambiguous SqliteConfig impl")
    save(state, s.replace("impl SqliteConfig {\n", helpers + "impl SqliteConfig {\n", 1))
rx(
    state,
    r"    pub async fn open_durable_evidence_pool\(&self, path: &Path\) -> Result<SqlitePool, Error> \{.*?^    \}\n",
    "    pub async fn open_durable_evidence_pool(&self, path: &Path) -> Result<SqlitePool, Error> {\n        open_durable_component_pool(path, 5).await\n    }\n",
)
ins(state_lib, "pub use sqlite::SqliteConfig;\n", "pub use sqlite::open_durable_component_pool;\npub use sqlite::open_transient_migration_pool;\n")
ins(ops_cargo, "codex-hepta-types = { workspace = true }\n", "codex-state = { workspace = true }\n")
ins(auth_cargo, 'codex-hepta-types = { path = "../hepta-types" }\n', "codex-state = { workspace = true }\n")

sqlite_imports = (
    "use sqlx::sqlite::SqliteConnectOptions;\n",
    "use sqlx::sqlite::SqliteJournalMode;\n",
    "use sqlx::sqlite::SqlitePoolOptions;\n",
    "use sqlx::sqlite::SqliteSynchronous;\n",
)
def old_pool(max_conn, mapper):
    return f'''        let options = SqliteConnectOptions::new()
            .filename(path)
            .create_if_missing(true)
            .journal_mode(SqliteJournalMode::Wal)
            .synchronous(SqliteSynchronous::Full)
            .foreign_keys(true)
            .busy_timeout(Duration::from_secs(5));
        let pool = SqlitePoolOptions::new()
            .max_connections({max_conn})
            .connect_with(options)
            .await
            .map_err({mapper})?;
'''
def new_pool(max_conn, mapper):
    return f'''        let pool = open_durable_component_pool(path, {max_conn})
            .await
            .map_err({mapper})?;
'''

drop(ops_dest, "use std::time::Duration;\n")
ins(ops_dest, "use std::time::UNIX_EPOCH;\n\n", "use codex_state::open_durable_component_pool;\n")
for x in sqlite_imports: drop(ops_dest, x)
rep(ops_dest, old_pool(4, "sqlx_error"), new_pool(4, "sqlx_error"))

ins(ops_store, "use codex_hepta_types::StableId;\n", "use codex_state::open_durable_component_pool;\n")
for x in sqlite_imports: drop(ops_store, x)
rep(ops_store, old_pool(4, "sqlx_error"), new_pool(4, "sqlx_error"))
rep(
    ops_store,
    '''        .await?
        {
            if status.state != DurableOutboxState::Acknowledged {
''',
    '''        .await?
            && status.state != DurableOutboxState::Acknowledged
        {
''',
)
rep(
    ops_store,
    '''                .await
                .map_err(sqlx_error)?;
            }
        }
        let operation = load_operation_tx(&mut tx, scope_id, operation_id)
''',
    '''            .await
            .map_err(sqlx_error)?;
        }
        let operation = load_operation_tx(&mut tx, scope_id, operation_id)
''',
)

drop(auth_store, "use std::time::Duration;\n")
ins(auth_store, "use std::path::Path;\n", "\nuse codex_state::open_durable_component_pool;\n")
for x in sqlite_imports: drop(auth_store, x)
rep(auth_store, old_pool(5, "storage"), new_pool(5, "storage"))
ins(auth_schema, "use sqlx::SqlitePool;\n", "use codex_state::open_transient_migration_pool;\n")
drop(auth_schema, "use sqlx::sqlite::SqlitePoolOptions;\n")
rep(
    auth_schema,
    '''    let reference = SqlitePoolOptions::new()
        .max_connections(1)
        .connect("sqlite::memory:")
        .await
        .map_err(storage)?;
''',
    "    let reference = open_transient_migration_pool().await.map_err(storage)?;\n",
)
for p in (auth_store, auth_quota, auth_trust):
    rep(
        p,
        ".is_some_and(|database| database.is_unique_violation())",
        ".is_some_and(sqlx::error::DatabaseError::is_unique_violation)",
    )

inventory = '''        "codex-rs/hepta-authbus/Cargo.toml",
        "codex-rs/hepta-authbus/src/authority_schema.rs",
        "codex-rs/hepta-authbus/src/authority_store.rs",
        "codex-rs/hepta-authbus/src/quota_store.rs",
        "codex-rs/hepta-authbus/src/trust_store.rs",
        "codex-rs/hepta-operations/Cargo.toml",
        "codex-rs/hepta-operations/src/destination_dedupe.rs",
        "codex-rs/hepta-operations/src/durable_store.rs",
'''
ins(sync, '        "codex-rs/Cargo.lock",\n', inventory)

for p in (ops_dest, ops_store, auth_schema, auth_store):
    s = load(p)
    if "SqlitePoolOptions::new()" in s or ".connect_with(options)" in s:
        raise SystemExit(f"{p}: direct pool constructor remains")
print("centralized transitive SQLite constructors and consumed strict lint blockers")
