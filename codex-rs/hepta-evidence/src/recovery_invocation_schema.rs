//! Actual SQLite keys required by the invocation recovery scan.
//! This verifies only the scan's row and association keys, inside its caller's
//! read transaction. It is not a complete evidence-schema validator.

use std::collections::BTreeSet;

use sqlx::Row;
use sqlx::SqliteConnection;

use crate::EvidenceError;
use crate::schema_validation::classify_sqlx_error;

const INTENT_UNIQUES: &[&[&str]] = &[&["attempt_id"], &["attempt_id", "request_binding_id"]];
const TERMINAL_UNIQUES: &[&[&str]] = &[&["receipt_id"], &["attempt_id"]];

pub(super) async fn verify(connection: &mut SqliteConnection) -> Result<(), EvidenceError> {
    for (table, required_uniques) in [
        ("provider_invocation_intents", INTENT_UNIQUES),
        ("provider_invocation_terminals", TERMINAL_UNIQUES),
    ] {
        let corrupt = |detail: &str| {
            EvidenceError::Corrupt(format!(
                "provider invocation recovery schema {table}: {detail}"
            ))
        };
        let columns = sqlx::query(
            "SELECT name, type, pk, \"notnull\" AS required
             FROM pragma_table_info(?) ORDER BY cid",
        )
        .bind(table)
        .fetch_all(&mut *connection)
        .await
        .map_err(classify_sqlx_error)?;
        let mut primary = Vec::new();
        let mut identity_columns = BTreeSet::new();
        for column in columns {
            let name: String = column.try_get("name").map_err(classify_sqlx_error)?;
            let declared_type: String = column.try_get("type").map_err(classify_sqlx_error)?;
            let position: i64 = column.try_get("pk").map_err(classify_sqlx_error)?;
            let required: i64 = column.try_get("required").map_err(classify_sqlx_error)?;
            if required == 1 && declared_type.eq_ignore_ascii_case("TEXT") {
                identity_columns.insert(name.clone());
            }
            if position != 0 {
                primary.push((position, name, declared_type));
            }
        }
        if primary.len() != 1
            || primary[0].0 != 1
            || primary[0].1 != "seq"
            || !primary[0].2.eq_ignore_ascii_case("INTEGER")
        {
            return Err(corrupt("seq must be the sole INTEGER rowid primary key"));
        }
        if required_uniques
            .iter()
            .flat_map(|columns| columns.iter())
            .any(|name| !identity_columns.contains(*name))
        {
            return Err(corrupt("identity key columns must retain NOT NULL TEXT"));
        }

        let indexes = sqlx::query(
            "SELECT name, \"unique\" AS is_unique, origin, partial
             FROM pragma_index_list(?)",
        )
        .bind(table)
        .fetch_all(&mut *connection)
        .await
        .map_err(classify_sqlx_error)?;
        let mut found = vec![false; required_uniques.len()];
        for index in indexes {
            let origin: String = index.try_get("origin").map_err(classify_sqlx_error)?;
            // A true INTEGER rowid alias has no backing primary-key index.
            // This also rejects INTEGER PRIMARY KEY DESC and WITHOUT ROWID,
            // which cannot be distinguished by table_info's INTEGER/pk alone.
            if origin == "pk" {
                return Err(corrupt("seq primary key must alias the SQLite rowid"));
            }
            let unique: i64 = index.try_get("is_unique").map_err(classify_sqlx_error)?;
            let partial: i64 = index.try_get("partial").map_err(classify_sqlx_error)?;
            if unique != 1 || partial != 0 {
                continue;
            }
            let name: String = index.try_get("name").map_err(classify_sqlx_error)?;
            let entries = sqlx::query(
                "SELECT cid, name, coll, \"key\" AS is_key
                 FROM pragma_index_xinfo(?) ORDER BY seqno",
            )
            .bind(name)
            .fetch_all(&mut *connection)
            .await
            .map_err(classify_sqlx_error)?;
            let mut keys = Vec::new();
            let mut plain_columns = true;
            for entry in entries {
                let is_key: i64 = entry.try_get("is_key").map_err(classify_sqlx_error)?;
                if is_key == 0 {
                    continue;
                }
                let cid: i64 = entry.try_get("cid").map_err(classify_sqlx_error)?;
                let name: Option<String> = entry.try_get("name").map_err(classify_sqlx_error)?;
                let collation: Option<String> =
                    entry.try_get("coll").map_err(classify_sqlx_error)?;
                if is_key != 1
                    || cid < 0
                    || collation
                        .as_deref()
                        .is_none_or(|value| !value.eq_ignore_ascii_case("BINARY"))
                {
                    plain_columns = false;
                }
                match name {
                    Some(name) => keys.push(name),
                    None => plain_columns = false,
                }
            }
            if plain_columns {
                for (position, expected) in required_uniques.iter().enumerate() {
                    if keys.iter().map(String::as_str).eq(expected.iter().copied()) {
                        found[position] = true;
                    }
                }
            }
        }
        if found.iter().any(|present| !present) {
            return Err(corrupt(
                "required exact unconditional column uniqueness is missing",
            ));
        }
    }
    Ok(())
}
