use sqlx::Row;
use sqlx::SqlitePool;

use crate::EvidenceError;

pub(crate) async fn verify_quick_check(pool: &SqlitePool) -> Result<(), EvidenceError> {
    let results = sqlx::query_scalar::<_, String>("PRAGMA quick_check(1)")
        .fetch_all(pool)
        .await
        .map_err(classify_sqlx_error)?;
    if results.len() == 1 && results[0] == "ok" {
        Ok(())
    } else {
        Err(EvidenceError::Corrupt(
            "SQLite quick_check reported invalid evidence storage".to_string(),
        ))
    }
}

struct SchemaObjectSpec {
    name: &'static str,
    object_type: &'static str,
    table_name: &'static str,
    required_sql_fragments: &'static [&'static str],
}

const REQUIRED_SCHEMA_OBJECTS: &[SchemaObjectSpec] = &[
    SchemaObjectSpec {
        name: "authbus_replay_sequences",
        object_type: "table",
        table_name: "authbus_replay_sequences",
        required_sql_fragments: &[
            "create table",
            "issuer_id",
            "key_epoch",
            "subject_id",
            "scope_digest",
            "sequence",
            "envelope_digest",
            "primary key",
            "length(key_epoch) = 8",
            "length(sequence) = 8",
            "length(scope_digest) = 32",
            "length(envelope_digest) = 32",
            "without rowid",
        ],
    },
    SchemaObjectSpec {
        name: "governance_decisions",
        object_type: "table",
        table_name: "governance_decisions",
        required_sql_fragments: &["create table", "governance_decisions"],
    },
    SchemaObjectSpec {
        name: "governance_receipts",
        object_type: "table",
        table_name: "governance_receipts",
        required_sql_fragments: &["create table", "governance_receipts"],
    },
    SchemaObjectSpec {
        name: "governance_decisions_thread_seq",
        object_type: "index",
        table_name: "governance_decisions",
        required_sql_fragments: &["create index", "governance_decisions", "thread_id", "seq"],
    },
    SchemaObjectSpec {
        name: "governance_receipts_thread_seq",
        object_type: "index",
        table_name: "governance_receipts",
        required_sql_fragments: &["create index", "governance_receipts", "thread_id", "seq"],
    },
    SchemaObjectSpec {
        name: "governance_decisions_no_update",
        object_type: "trigger",
        table_name: "governance_decisions",
        required_sql_fragments: &[
            "before update",
            "on governance_decisions",
            "raise(abort",
            "governance decisions are immutable",
        ],
    },
    SchemaObjectSpec {
        name: "governance_decisions_no_delete",
        object_type: "trigger",
        table_name: "governance_decisions",
        required_sql_fragments: &[
            "before delete",
            "on governance_decisions",
            "raise(abort",
            "governance decisions are immutable",
        ],
    },
    SchemaObjectSpec {
        name: "governance_receipts_no_update",
        object_type: "trigger",
        table_name: "governance_receipts",
        required_sql_fragments: &[
            "before update",
            "on governance_receipts",
            "raise(abort",
            "governance receipts are immutable",
        ],
    },
    SchemaObjectSpec {
        name: "governance_receipts_no_delete",
        object_type: "trigger",
        table_name: "governance_receipts",
        required_sql_fragments: &[
            "before delete",
            "on governance_receipts",
            "raise(abort",
            "governance receipts are immutable",
        ],
    },
    SchemaObjectSpec {
        name: "provider_invocation_intents",
        object_type: "table",
        table_name: "provider_invocation_intents",
        required_sql_fragments: &[
            "create table",
            "provider_invocation_intents",
            "attempt_id",
            "request_binding_id",
            "host_request_binding_id_sha256",
            "ephemeral_input_sha256",
            "length(ephemeral_input_sha256) = 64",
            "ephemeral_input_sha256 not glob '*[^0-9a-f]*'",
            "ephemeral_input_witness_sha256",
            "length(ephemeral_input_witness_sha256) = 64",
            "ephemeral_input_witness_sha256 not glob '*[^0-9a-f]*'",
            "(ephemeral_input_sha256 is null) = (ephemeral_input_witness_sha256 is null)",
            "payload_sha256",
        ],
    },
    SchemaObjectSpec {
        name: "provider_invocation_terminals",
        object_type: "table",
        table_name: "provider_invocation_terminals",
        required_sql_fragments: &[
            "create table",
            "provider_invocation_terminals",
            "foreign key",
            "provider_invocation_intents",
            "on delete restrict",
        ],
    },
    SchemaObjectSpec {
        name: "provider_invocation_intents_thread_seq",
        object_type: "index",
        table_name: "provider_invocation_intents",
        required_sql_fragments: &[
            "create index",
            "provider_invocation_intents",
            "thread_id",
            "seq",
        ],
    },
    SchemaObjectSpec {
        name: "provider_invocation_intents_binding_seq",
        object_type: "index",
        table_name: "provider_invocation_intents",
        required_sql_fragments: &[
            "create index",
            "provider_invocation_intents",
            "request_binding_id",
            "seq",
        ],
    },
    SchemaObjectSpec {
        name: "provider_invocation_terminals_thread_seq",
        object_type: "index",
        table_name: "provider_invocation_terminals",
        required_sql_fragments: &[
            "create index",
            "provider_invocation_terminals",
            "thread_id",
            "seq",
        ],
    },
    SchemaObjectSpec {
        name: "provider_invocation_intents_host_binding_seq",
        object_type: "index",
        table_name: "provider_invocation_intents",
        required_sql_fragments: &[
            "create index",
            "provider_invocation_intents",
            "host_request_binding_id_sha256",
            "seq",
        ],
    },
    SchemaObjectSpec {
        name: "provider_invocation_intents_host_binding_required",
        object_type: "trigger",
        table_name: "provider_invocation_intents",
        required_sql_fragments: &[
            "before insert",
            "on provider_invocation_intents",
            "host_request_binding_id_sha256",
            "raise(abort",
        ],
    },
    SchemaObjectSpec {
        name: "provider_invocation_intents_no_update",
        object_type: "trigger",
        table_name: "provider_invocation_intents",
        required_sql_fragments: &[
            "before update",
            "on provider_invocation_intents",
            "raise(abort",
            "provider invocation intents are immutable",
        ],
    },
    SchemaObjectSpec {
        name: "provider_invocation_intents_no_delete",
        object_type: "trigger",
        table_name: "provider_invocation_intents",
        required_sql_fragments: &[
            "before delete",
            "on provider_invocation_intents",
            "raise(abort",
            "provider invocation intents are immutable",
        ],
    },
    SchemaObjectSpec {
        name: "provider_invocation_terminals_no_update",
        object_type: "trigger",
        table_name: "provider_invocation_terminals",
        required_sql_fragments: &[
            "before update",
            "on provider_invocation_terminals",
            "raise(abort",
            "provider invocation terminals are immutable",
        ],
    },
    SchemaObjectSpec {
        name: "provider_invocation_terminals_no_delete",
        object_type: "trigger",
        table_name: "provider_invocation_terminals",
        required_sql_fragments: &[
            "before delete",
            "on provider_invocation_terminals",
            "raise(abort",
            "provider invocation terminals are immutable",
        ],
    },
    SchemaObjectSpec {
        name: "provider_effect_intents",
        object_type: "table",
        table_name: "provider_effect_intents",
        required_sql_fragments: &[
            "create table",
            "provider_effect_intents",
            "effect_key",
            "payload_sha256",
            "record_sha256",
            "schema_version integer not null check (schema_version = 1)",
        ],
    },
    SchemaObjectSpec {
        name: "provider_effect_acknowledgements",
        object_type: "table",
        table_name: "provider_effect_acknowledgements",
        required_sql_fragments: &[
            "create table",
            "provider_effect_acknowledgements",
            "foreign key",
            "provider_effect_intents",
            "on delete restrict",
            "status text not null check (status in ('accepted', 'completed', 'rejected'))",
        ],
    },
    SchemaObjectSpec {
        name: "provider_effect_uncertainties",
        object_type: "table",
        table_name: "provider_effect_uncertainties",
        required_sql_fragments: &[
            "create table",
            "provider_effect_uncertainties",
            "foreign key",
            "provider_effect_intents",
            "reason_code",
            "on delete restrict",
        ],
    },
    SchemaObjectSpec {
        name: "provider_effect_intents_seq",
        object_type: "index",
        table_name: "provider_effect_intents",
        required_sql_fragments: &[
            "create index",
            "provider_effect_intents",
            "effect_key",
            "seq",
        ],
    },
    SchemaObjectSpec {
        name: "provider_effect_acknowledgements_key_seq",
        object_type: "index",
        table_name: "provider_effect_acknowledgements",
        required_sql_fragments: &[
            "create index",
            "provider_effect_acknowledgements",
            "effect_key",
            "seq",
        ],
    },
    SchemaObjectSpec {
        name: "provider_effect_uncertainties_key_seq",
        object_type: "index",
        table_name: "provider_effect_uncertainties",
        required_sql_fragments: &[
            "create index",
            "provider_effect_uncertainties",
            "effect_key",
            "seq",
        ],
    },
    SchemaObjectSpec {
        name: "provider_effect_intents_no_update",
        object_type: "trigger",
        table_name: "provider_effect_intents",
        required_sql_fragments: &[
            "before update",
            "on provider_effect_intents",
            "raise(abort",
            "provider effect intents are immutable",
        ],
    },
    SchemaObjectSpec {
        name: "provider_effect_intents_no_delete",
        object_type: "trigger",
        table_name: "provider_effect_intents",
        required_sql_fragments: &[
            "before delete",
            "on provider_effect_intents",
            "raise(abort",
            "provider effect intents are immutable",
        ],
    },
    SchemaObjectSpec {
        name: "provider_effect_acknowledgements_no_update",
        object_type: "trigger",
        table_name: "provider_effect_acknowledgements",
        required_sql_fragments: &[
            "before update",
            "on provider_effect_acknowledgements",
            "raise(abort",
            "provider effect acknowledgements are immutable",
        ],
    },
    SchemaObjectSpec {
        name: "provider_effect_acknowledgements_no_delete",
        object_type: "trigger",
        table_name: "provider_effect_acknowledgements",
        required_sql_fragments: &[
            "before delete",
            "on provider_effect_acknowledgements",
            "raise(abort",
            "provider effect acknowledgements are immutable",
        ],
    },
    SchemaObjectSpec {
        name: "provider_effect_uncertainties_no_update",
        object_type: "trigger",
        table_name: "provider_effect_uncertainties",
        required_sql_fragments: &[
            "before update",
            "on provider_effect_uncertainties",
            "raise(abort",
            "provider effect uncertainties are immutable",
        ],
    },
    SchemaObjectSpec {
        name: "provider_effect_uncertainties_no_delete",
        object_type: "trigger",
        table_name: "provider_effect_uncertainties",
        required_sql_fragments: &[
            "before delete",
            "on provider_effect_uncertainties",
            "raise(abort",
            "provider effect uncertainties are immutable",
        ],
    },
    SchemaObjectSpec {
        name: "memory_mutation_shadow_observations",
        object_type: "table",
        table_name: "memory_mutation_shadow_observations",
        required_sql_fragments: &[
            "create table",
            "memory_mutation_shadow_observations",
            "dry_run_id",
            "proposal_id",
            "projected_memory_writes between 0 and 2",
            "unique(proposal_id, snapshot_sha256)",
            "disposition = 'blocked'",
            "reason = 'ready'",
            "evidence_sha256",
        ],
    },
    SchemaObjectSpec {
        name: "memory_mutation_shadow_proposal_seq",
        object_type: "index",
        table_name: "memory_mutation_shadow_observations",
        required_sql_fragments: &[
            "create index",
            "memory_mutation_shadow_observations",
            "proposal_id",
            "seq",
        ],
    },
    SchemaObjectSpec {
        name: "memory_mutation_shadow_turn_seq",
        object_type: "index",
        table_name: "memory_mutation_shadow_observations",
        required_sql_fragments: &[
            "create index",
            "memory_mutation_shadow_observations",
            "turn_sha256",
            "seq",
        ],
    },
    SchemaObjectSpec {
        name: "memory_mutation_shadow_no_update",
        object_type: "trigger",
        table_name: "memory_mutation_shadow_observations",
        required_sql_fragments: &[
            "before update",
            "on memory_mutation_shadow_observations",
            "raise(abort",
            "memory mutation shadow observations are immutable",
        ],
    },
    SchemaObjectSpec {
        name: "memory_mutation_shadow_no_delete",
        object_type: "trigger",
        table_name: "memory_mutation_shadow_observations",
        required_sql_fragments: &[
            "before delete",
            "on memory_mutation_shadow_observations",
            "raise(abort",
            "memory mutation shadow observations are immutable",
        ],
    },
    SchemaObjectSpec {
        name: "channel_ingress_events",
        object_type: "table",
        table_name: "channel_ingress_events",
        required_sql_fragments: &[
            "create table",
            "channel_ingress_events",
            "event_id text not null unique",
            "target_thread_sha256",
            "length(target_thread_sha256) = 64",
            "unique(scope_sha256, source_event_sha256)",
            "schema_version integer not null check (schema_version = 1)",
            "length(evidence_sha256) = 64",
            "evidence_sha256",
        ],
    },
    SchemaObjectSpec {
        name: "channel_ingress_receipts",
        object_type: "table",
        table_name: "channel_ingress_receipts",
        required_sql_fragments: &[
            "create table",
            "channel_ingress_receipts",
            "receipt_id text not null unique",
            "event_id text not null unique",
            "terminal_kind in ('accepted', 'rejected', 'indeterminate')",
            "terminal_kind = 'accepted' and thread_id is not null and turn_id is not null",
            "terminal_kind in ('rejected', 'indeterminate') and thread_id is null and turn_id is null",
            "schema_version integer not null check (schema_version = 1)",
            "length(evidence_sha256) = 64",
            "foreign key(event_id)",
            "channel_ingress_events(event_id)",
            "on update restrict",
            "on delete restrict",
        ],
    },
    SchemaObjectSpec {
        name: "channel_ingress_events_scope_seq",
        object_type: "index",
        table_name: "channel_ingress_events",
        required_sql_fragments: &[
            "create index",
            "channel_ingress_events",
            "scope_sha256",
            "seq",
        ],
    },
    SchemaObjectSpec {
        name: "channel_ingress_receipts_scope_seq",
        object_type: "index",
        table_name: "channel_ingress_receipts",
        required_sql_fragments: &[
            "create index",
            "channel_ingress_receipts",
            "scope_sha256",
            "seq",
        ],
    },
    SchemaObjectSpec {
        name: "channel_ingress_events_no_update",
        object_type: "trigger",
        table_name: "channel_ingress_events",
        required_sql_fragments: &[
            "before update",
            "on channel_ingress_events",
            "raise(abort",
            "channel ingress events are immutable",
        ],
    },
    SchemaObjectSpec {
        name: "channel_ingress_events_no_delete",
        object_type: "trigger",
        table_name: "channel_ingress_events",
        required_sql_fragments: &[
            "before delete",
            "on channel_ingress_events",
            "raise(abort",
            "channel ingress events are immutable",
        ],
    },
    SchemaObjectSpec {
        name: "channel_ingress_receipts_no_update",
        object_type: "trigger",
        table_name: "channel_ingress_receipts",
        required_sql_fragments: &[
            "before update",
            "on channel_ingress_receipts",
            "raise(abort",
            "channel ingress receipts are immutable",
        ],
    },
    SchemaObjectSpec {
        name: "channel_ingress_receipts_no_delete",
        object_type: "trigger",
        table_name: "channel_ingress_receipts",
        required_sql_fragments: &[
            "before delete",
            "on channel_ingress_receipts",
            "raise(abort",
            "channel ingress receipts are immutable",
        ],
    },
];

pub(crate) async fn verify_provider_host_bindings(pool: &SqlitePool) -> Result<(), EvidenceError> {
    let missing: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM provider_invocation_intents
         WHERE host_request_binding_id_sha256 IS NULL",
    )
    .fetch_one(pool)
    .await
    .map_err(classify_sqlx_error)?;
    if missing == 0 {
        Ok(())
    } else {
        Err(EvidenceError::Corrupt(format!(
            "{missing} provider intent rows predate host request binding evidence; explicit migration is required"
        )))
    }
}

pub(crate) async fn verify_provider_ephemeral_input_projection(
    pool: &SqlitePool,
) -> Result<(), EvidenceError> {
    let invalid: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM provider_invocation_intents
         WHERE CASE
             WHEN json_valid(payload_json) = 0 THEN 1
             WHEN json_type(payload_json, '$.binding.ephemeral_input_sha256') IS NULL
                  AND json_type(payload_json, '$.binding.ephemeral_input_witness_sha256') IS NULL
             THEN ephemeral_input_sha256 IS NOT NULL
                  OR ephemeral_input_witness_sha256 IS NOT NULL
             WHEN json_type(payload_json, '$.binding.ephemeral_input_sha256') = 'text'
                  AND json_type(payload_json, '$.binding.ephemeral_input_witness_sha256') = 'text'
             THEN ephemeral_input_sha256 IS NOT
                      json_extract(payload_json, '$.binding.ephemeral_input_sha256')
                  OR ephemeral_input_witness_sha256 IS NOT
                      json_extract(payload_json, '$.binding.ephemeral_input_witness_sha256')
             ELSE 1
         END",
    )
    .fetch_one(pool)
    .await
    .map_err(classify_sqlx_error)?;
    if invalid == 0 {
        Ok(())
    } else {
        Err(EvidenceError::Corrupt(format!(
            "{invalid} provider intent rows have invalid ephemeral input projections"
        )))
    }
}

pub(crate) async fn verify_schema_manifest(pool: &SqlitePool) -> Result<(), EvidenceError> {
    for spec in REQUIRED_SCHEMA_OBJECTS {
        let row = sqlx::query(
            "SELECT type AS object_type, tbl_name, sql
             FROM sqlite_schema WHERE name = ?",
        )
        .bind(spec.name)
        .fetch_optional(pool)
        .await
        .map_err(classify_sqlx_error)?
        .ok_or_else(|| {
            EvidenceError::Corrupt(format!(
                "required SQLite schema object {} is missing",
                spec.name
            ))
        })?;
        let object_type: String = row.get("object_type");
        let table_name: String = row.get("tbl_name");
        let sql: Option<String> = row.get("sql");
        let Some(sql) = sql else {
            return Err(EvidenceError::Corrupt(format!(
                "required SQLite schema object {} has no definition",
                spec.name
            )));
        };
        let normalized_sql = sql
            .split_ascii_whitespace()
            .collect::<Vec<_>>()
            .join(" ")
            .to_ascii_lowercase();
        if object_type != spec.object_type
            || table_name != spec.table_name
            || spec
                .required_sql_fragments
                .iter()
                .any(|fragment| !normalized_sql.contains(fragment))
        {
            return Err(EvidenceError::Corrupt(format!(
                "required SQLite schema object {} has an invalid definition",
                spec.name
            )));
        }
    }
    Ok(())
}

/// Migration 0008 adds `source` with `ALTER TABLE`; SQLite keeps the original
/// CREATE statement in `sqlite_schema`, so the normal schema-manifest oracle
/// cannot observe that column.  Check the projected table shape explicitly.
pub(crate) async fn verify_provider_effect_ack_source_schema(
    pool: &SqlitePool,
) -> Result<(), EvidenceError> {
    let table_sql = sqlx::query(
        "SELECT sql FROM sqlite_schema
         WHERE type = 'table' AND name = 'provider_effect_acknowledgements'",
    )
    .fetch_optional(pool)
    .await
    .map_err(classify_sqlx_error)?
    .ok_or_else(|| {
        EvidenceError::Corrupt(
            "provider effect acknowledgement table definition is missing".to_string(),
        )
    })?
    .try_get::<Option<String>, _>("sql")
    .map_err(classify_sqlx_error)?
    .ok_or_else(|| {
        EvidenceError::Corrupt(
            "provider effect acknowledgement table definition is missing".to_string(),
        )
    })?;
    // `ALTER TABLE ... ADD COLUMN` is part of migration 0008, so verify the
    // exact CHECK expression in sqlite_schema instead of relying only on
    // PRAGMA table_info (which does not expose CHECK constraints).  Removing
    // the constraint while leaving currently stored values valid must still
    // fail closed before a direct SQL writer can introduce an unknown source.
    let normalized_table_sql = table_sql
        .chars()
        .filter(|character| !character.is_ascii_whitespace())
        .collect::<String>()
        .to_ascii_lowercase();
    const SOURCE_CHECK: &str =
        "sourcetextcheck(sourceisnullorsourcein('dispatch_response','status_lookup'))";
    if !normalized_table_sql.contains(SOURCE_CHECK) {
        return Err(EvidenceError::Corrupt(
            "provider effect acknowledgement source CHECK constraint is invalid".to_string(),
        ));
    }

    let columns = sqlx::query("PRAGMA table_info(provider_effect_acknowledgements)")
        .fetch_all(pool)
        .await
        .map_err(classify_sqlx_error)?;
    let source = columns.iter().find(|row| {
        row.try_get::<String, _>("name")
            .ok()
            .is_some_and(|name| name == "source")
    });
    let Some(source) = source else {
        return Err(EvidenceError::Corrupt(
            "provider effect acknowledgement source column is missing".to_string(),
        ));
    };
    let column_type: String = source.try_get("type").map_err(classify_sqlx_error)?;
    let not_null: i64 = source.try_get("notnull").map_err(classify_sqlx_error)?;
    if !column_type.eq_ignore_ascii_case("TEXT") || not_null != 0 {
        return Err(EvidenceError::Corrupt(
            "provider effect acknowledgement source column has an invalid definition".to_string(),
        ));
    }
    let invalid_values: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM provider_effect_acknowledgements
         WHERE source IS NULL OR source NOT IN ('dispatch_response', 'status_lookup')",
    )
    .fetch_one(pool)
    .await
    .map_err(classify_sqlx_error)?;
    if invalid_values != 0 {
        return Err(EvidenceError::Corrupt(
            "provider effect acknowledgement source provenance is invalid".to_string(),
        ));
    }
    Ok(())
}

pub(crate) async fn verify_foreign_keys(pool: &SqlitePool) -> Result<(), EvidenceError> {
    let violation = sqlx::query("PRAGMA foreign_key_check")
        .fetch_optional(pool)
        .await
        .map_err(classify_sqlx_error)?;
    if violation.is_some() {
        Err(EvidenceError::Corrupt(
            "SQLite foreign_key_check found invalid evidence references".to_string(),
        ))
    } else {
        Ok(())
    }
}

pub(crate) fn classify_migrate_error(error: sqlx::migrate::MigrateError) -> EvidenceError {
    let detail = error.to_string();
    match error {
        sqlx::migrate::MigrateError::Execute(error) => classify_sqlx_error(error),
        sqlx::migrate::MigrateError::ExecuteMigration(error, version) => {
            classify_migration_execution_error(error, version)
        }
        sqlx::migrate::MigrateError::VersionMissing(_)
        | sqlx::migrate::MigrateError::VersionMismatch(_)
        | sqlx::migrate::MigrateError::VersionNotPresent(_)
        | sqlx::migrate::MigrateError::Dirty(_) => EvidenceError::Corrupt(detail),
        _ => EvidenceError::Unavailable(detail),
    }
}

fn classify_migration_execution_error(error: sqlx::Error, version: i64) -> EvidenceError {
    let detail = error.to_string();
    let invalid_ephemeral_backfill = version == 6
        && (sqlite_primary_code(&error) == Some(19)
            || detail.to_ascii_lowercase().contains("malformed json"));
    if invalid_ephemeral_backfill {
        EvidenceError::Corrupt(detail)
    } else {
        classify_sqlx_error(error)
    }
}

pub(crate) fn classify_sqlx_error(error: sqlx::Error) -> EvidenceError {
    let detail = error.to_string();
    match sqlite_primary_code(&error) {
        // SQLITE_CORRUPT, SQLITE_SCHEMA, SQLITE_NOTADB. SQLx exposes the
        // extended numeric code, whose low byte is the primary result code.
        Some(11 | 17 | 26) => EvidenceError::Corrupt(detail),
        _ => EvidenceError::Unavailable(detail),
    }
}

fn sqlite_primary_code(error: &sqlx::Error) -> Option<i32> {
    error
        .as_database_error()?
        .code()?
        .parse::<i32>()
        .ok()
        .map(|code| code & 0xff)
}
