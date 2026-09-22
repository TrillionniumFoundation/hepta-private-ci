//! Schema bindings for the replay checkpoint owner added in migration 0012.

use super::SchemaObjectSpec;

pub(super) const REQUIRED_SCHEMA_OBJECTS: &[SchemaObjectSpec] = &[
    SchemaObjectSpec {
        name: "authbus_restore_checkpoint",
        object_type: "table",
        table_name: "authbus_restore_checkpoint",
        required_sql_fragments: &[
            "singleton integer primary key not null check (singleton = 1)",
            "generation blob not null check (length(generation) = 8)",
            "checkpoint_digest blob not null check (length(checkpoint_digest) = 32)",
            "updated_at_ms integer not null",
        ],
    },
    SchemaObjectSpec {
        name: "authbus_restore_checkpoint_pending",
        object_type: "table",
        table_name: "authbus_restore_checkpoint_pending",
        required_sql_fragments: &[
            "singleton integer primary key not null check (singleton = 1)",
            "generation blob not null check (length(generation) = 8)",
            "checkpoint_digest blob not null check (length(checkpoint_digest) = 32)",
            "created_at_ms integer not null",
        ],
    },
    SchemaObjectSpec {
        name: "authbus_retired_epochs",
        object_type: "table",
        table_name: "authbus_retired_epochs",
        required_sql_fragments: &[
            "issuer_id text not null",
            "key_epoch blob not null check (length(key_epoch) = 8)",
            "retirement_digest blob not null check (length(retirement_digest) = 32)",
            "retired_at_ms integer not null",
            "primary key(issuer_id, key_epoch)",
            "without rowid",
        ],
    },
];
