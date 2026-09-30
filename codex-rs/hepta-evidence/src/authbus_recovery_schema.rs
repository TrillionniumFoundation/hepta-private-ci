//! Schema bindings for replay recovery and the Evidence-owned time floor.

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
    SchemaObjectSpec {
        name: "authbus_time_floor",
        object_type: "table",
        table_name: "authbus_time_floor",
        required_sql_fragments: &[
            "singleton integer primary key check (singleton = 1)",
            "observed_at_ms integer not null check (observed_at_ms >= 0)",
            "revision integer not null check (revision >= 1)",
            "without rowid",
        ],
    },
    SchemaObjectSpec {
        name: "authbus_time_floor_identity_immutable",
        object_type: "trigger",
        table_name: "authbus_time_floor",
        required_sql_fragments: &[
            "before update of singleton on authbus_time_floor",
            "raise(abort",
            "authbus time-floor identity is immutable",
        ],
    },
    SchemaObjectSpec {
        name: "authbus_time_floor_monotonic",
        object_type: "trigger",
        table_name: "authbus_time_floor",
        required_sql_fragments: &[
            "before update of observed_at_ms, revision on authbus_time_floor",
            "new.observed_at_ms <= old.observed_at_ms",
            "new.revision != old.revision + 1",
            "raise(abort",
            "authbus time floor must advance monotonically",
        ],
    },
    SchemaObjectSpec {
        name: "authbus_time_floor_delete_forbidden",
        object_type: "trigger",
        table_name: "authbus_time_floor",
        required_sql_fragments: &[
            "before delete on authbus_time_floor",
            "raise(abort",
            "authbus time floor cannot be deleted",
        ],
    },
];
