//! Schema bindings for the Evidence-owned AuthBus monotonic time floor.

use super::SchemaObjectSpec;

pub(super) const REQUIRED_SCHEMA_OBJECTS: &[SchemaObjectSpec] = &[
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
