//! Read-only logical snapshots for the small, locally created recovery fixtures.
//! Match the recovery oracle's logical tables and schema (not physical page IDs).

use std::collections::BTreeMap;
use std::error::Error;
use std::ops::RangeInclusive;
use std::path::Path;

use codex_hepta_cognitive_store::ProductionAuthorityLease;
use codex_hepta_contracts::Sha256Digest;
use sha2::Digest;
use sha2::Sha256;
use sqlx::Connection;
use sqlx::Row;
use sqlx::SqliteConnection;
use sqlx::TypeInfo;
use sqlx::ValueRef;
use sqlx::sqlite::SqliteConnectOptions;

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
enum Cell {
    Null,
    Integer(i64),
    Real(u64),
    Text(String),
    Blob(Vec<u8>),
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct Table {
    columns: Vec<String>,
    rows: Vec<Vec<Cell>>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(super) struct LogicalSnapshot(BTreeMap<String, Table>);

pub(super) async fn snapshot(path: &Path) -> Result<LogicalSnapshot, Box<dyn Error>> {
    let options = SqliteConnectOptions::new()
        .filename(path)
        .read_only(true)
        .create_if_missing(false);
    let mut connection = SqliteConnection::connect_with(&options).await?;
    let mut transaction = connection.begin().await?;
    let mut tables: Vec<String> = sqlx::query_scalar(
        "SELECT name FROM pragma_table_list WHERE schema = 'main'
         AND type IN ('table', 'virtual') AND name NOT LIKE 'sqlite_%' ORDER BY name",
    )
    .fetch_all(&mut *transaction)
    .await?;
    tables.push("sqlite_schema".to_string());
    let mut result = BTreeMap::new();
    for table in tables {
        let columns: Vec<String> = if table == "sqlite_schema" {
            ["type", "name", "tbl_name", "sql"]
                .map(str::to_string)
                .to_vec()
        } else {
            sqlx::query_scalar("SELECT name FROM pragma_table_info(?) ORDER BY cid")
                .bind(&table)
                .fetch_all(&mut *transaction)
                .await?
        };
        let quoted: Vec<String> = columns
            .iter()
            .map(|name| format!("\"{}\"", name.replace('"', "\"\"")))
            .collect();
        // Only identifiers from this owned fixture's SQLite schema are dynamic.
        // Quote and escape each identifier; never interpolate SQL values.
        let mut query = sqlx::QueryBuilder::<sqlx::Sqlite>::new("SELECT ");
        query
            .push(quoted.join(", "))
            .push(" FROM \"")
            .push(table.replace('"', "\"\""))
            .push("\"");
        let mut rows = Vec::new();
        for row in query.build().fetch_all(&mut *transaction).await? {
            let mut cells = Vec::new();
            for index in 0..columns.len() {
                let value = row.try_get_raw(index)?;
                cells.push(if value.is_null() {
                    Cell::Null
                } else {
                    match value.type_info().name() {
                        "INTEGER" => Cell::Integer(row.try_get(index)?),
                        "REAL" => Cell::Real(row.try_get::<f64, _>(index)?.to_bits()),
                        "TEXT" => Cell::Text(row.try_get(index)?),
                        "BLOB" => Cell::Blob(row.try_get(index)?),
                        kind => {
                            return Err(format!("unexpected SQLite storage class {kind}").into());
                        }
                    }
                });
            }
            rows.push(cells);
        }
        rows.sort();
        result.insert(table, Table { columns, rows });
    }
    transaction.commit().await?;
    connection.close().await?;
    Ok(LogicalSnapshot(result))
}

/// Require exactly the first authority-bound lease row, not an arbitrary
/// mutation hidden by removing the entire lease table from the comparison.
pub(super) fn assert_initial_lease_transition(
    before: &LogicalSnapshot,
    after: &LogicalSnapshot,
    authority: &ProductionAuthorityLease,
    lease_id: &str,
    generation: u64,
    recorded_between: RangeInclusive<u64>,
) -> Result<(), Box<dyn Error>> {
    let old = before
        .0
        .get("cognitive_local_leases")
        .ok_or("missing original lease table")?;
    let new = after
        .0
        .get("cognitive_local_leases")
        .ok_or("missing recovered lease table")?;
    assert!(old.rows.is_empty(), "fixture must begin without a lease");
    assert_eq!(new.columns, old.columns);
    assert_eq!(
        new.rows.len(),
        1,
        "writer admission must append exactly one lease"
    );
    let observed: BTreeMap<_, _> = new
        .columns
        .iter()
        .cloned()
        .zip(new.rows[0].iter().cloned())
        .collect();
    let recorded_at = match observed.get("recorded_at_unix_seconds") {
        Some(Cell::Integer(value)) => u64::try_from(*value)?,
        _ => return Err("lease recording time is not an integer".into()),
    };
    assert!(recorded_between.contains(&recorded_at));
    let token = authority.fencing_token_digest()?;
    let previous = Sha256Digest::for_bytes(b"hepta-memory:local-lease:genesis:v1");
    // Independently construct the public persisted v2 lease contract. This
    // catches wrong authority/owner/sequence/state/fence or extra lease fields.
    let mut hasher = Sha256::new();
    for part in [
        b"hepta-memory:local-lease:v2".as_slice(),
        lease_id.as_bytes(),
        &1_u64.to_be_bytes(),
        authority.agent_id.as_str().as_bytes(),
        &generation.to_be_bytes(),
        token.as_str().as_bytes(),
        b"active".as_slice(),
        &authority.authority_epoch.to_be_bytes(),
        &authority.owner_epoch.to_be_bytes(),
        &authority.lease_expires_at_unix_seconds.to_be_bytes(),
        previous.as_str().as_bytes(),
    ] {
        hasher.update((part.len() as u64).to_be_bytes());
        hasher.update(part);
    }
    let lease_digest = Sha256Digest::from_sha256_output(hasher.finalize());
    let expected = BTreeMap::from([
        ("lease_id".to_string(), Cell::Text(lease_id.to_string())),
        ("lease_sequence".to_string(), Cell::Integer(1)),
        (
            "owner_agent_id".to_string(),
            Cell::Text(authority.agent_id.to_string()),
        ),
        (
            "generation".to_string(),
            Cell::Integer(i64::try_from(generation)?),
        ),
        (
            "fencing_token".to_string(),
            Cell::Text(token.as_str().to_string()),
        ),
        ("state".to_string(), Cell::Text("active".to_string())),
        (
            "authority_epoch".to_string(),
            Cell::Integer(i64::try_from(authority.authority_epoch)?),
        ),
        (
            "owner_epoch".to_string(),
            Cell::Integer(i64::try_from(authority.owner_epoch)?),
        ),
        (
            "lease_expires_at_unix_seconds".to_string(),
            Cell::Integer(i64::try_from(authority.lease_expires_at_unix_seconds)?),
        ),
        (
            "previous_sha256".to_string(),
            Cell::Text(previous.as_str().to_string()),
        ),
        (
            "lease_sha256".to_string(),
            Cell::Text(lease_digest.as_str().to_string()),
        ),
        (
            "recorded_at_unix_seconds".to_string(),
            Cell::Integer(i64::try_from(recorded_at)?),
        ),
    ]);
    assert_eq!(
        observed, expected,
        "only the exact authorized lease may be appended"
    );
    let mut normalized = after.clone();
    normalized
        .0
        .get_mut("cognitive_local_leases")
        .ok_or("missing lease table")?
        .rows
        .clear();
    assert_eq!(
        &normalized, before,
        "all other logical rows and full logical schema must remain identical"
    );
    Ok(())
}

/// Exercise the transition oracle against mutations of the real observed cut.
/// These copies never touch the database and never stand in for a native result.
pub(super) fn assert_transition_mutations_rejected(
    before: &LogicalSnapshot,
    after: &LogicalSnapshot,
    authority: &ProductionAuthorityLease,
    lease_id: &str,
    generation: u64,
    recorded_between: RangeInclusive<u64>,
) -> Result<(), Box<dyn Error>> {
    let reject = |candidate: LogicalSnapshot| {
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            assert_initial_lease_transition(
                before,
                &candidate,
                authority,
                lease_id,
                generation,
                recorded_between.clone(),
            )
        }));
        assert!(
            !matches!(result, Ok(Ok(()))),
            "the exact-transition oracle accepted a mutated snapshot"
        );
    };
    let table = after
        .0
        .get("cognitive_local_leases")
        .ok_or("missing lease table")?;
    for index in 0..table.columns.len() {
        let mut changed = after.clone();
        changed
            .0
            .get_mut("cognitive_local_leases")
            .ok_or("missing lease table")?
            .rows[0][index] = Cell::Null;
        reject(changed);
    }
    let mut duplicate = after.clone();
    duplicate
        .0
        .get_mut("cognitive_local_leases")
        .ok_or("missing lease table")?
        .rows
        .push(table.rows[0].clone());
    reject(duplicate);
    let mut changed_schema = after.clone();
    changed_schema
        .0
        .get_mut("sqlite_schema")
        .ok_or("missing logical schema")?
        .rows
        .push(vec![Cell::Text("unexpected schema row".to_string())]);
    reject(changed_schema);
    let mut changed_other = after.clone();
    changed_other
        .0
        .get_mut("_sqlx_migrations")
        .ok_or("missing migration ledger")?
        .rows
        .push(vec![Cell::Text("unexpected non-lease row".to_string())]);
    reject(changed_other);
    Ok(())
}
