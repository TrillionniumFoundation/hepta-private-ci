CREATE TABLE IF NOT EXISTS fleet_host_incarnations (
    host_id TEXT PRIMARY KEY,
    boot_identity TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK(generation > 0),
    updated_at_ms INTEGER NOT NULL
) STRICT;
CREATE TABLE IF NOT EXISTS fleet_seen_boots (
    host_id TEXT NOT NULL,
    boot_identity TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK(generation > 0),
    PRIMARY KEY(host_id, boot_identity),
    UNIQUE(host_id, generation)
) STRICT;
CREATE TABLE IF NOT EXISTS fleet_execution_holds (
    execution_id TEXT PRIMARY KEY,
    allocation_id TEXT NOT NULL UNIQUE,
    host_id TEXT NOT NULL REFERENCES fleet_hosts(host_id),
    boot_identity TEXT NOT NULL,
    context_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('prepared', 'running', 'stop_requested', 'stopped')),
    process_id INTEGER,
    process_group INTEGER,
    process_start_ticks INTEGER,
    prepared_at_ms INTEGER NOT NULL,
    containment_dev INTEGER NOT NULL,
    containment_ino INTEGER NOT NULL,
    stopped_at_ms INTEGER,
    CHECK((process_id IS NULL AND process_group IS NULL AND process_start_ticks IS NULL)
       OR (process_id > 0 AND process_group > 0 AND process_start_ticks >= 0)),
    CHECK(state != 'stopped' OR stopped_at_ms IS NOT NULL)
) STRICT;
CREATE INDEX IF NOT EXISTS fleet_execution_pending_idx
    ON fleet_execution_holds(state, host_id, execution_id);
CREATE UNIQUE INDEX IF NOT EXISTS fleet_execution_containment_live_idx
    ON fleet_execution_holds(boot_identity, containment_dev, containment_ino)
    WHERE state != 'stopped';
