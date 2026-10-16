-- Isolated SDK 0.18 fixture. Upstream Matrix.org Apache-2.0 migrations 001–014.
PRAGMA foreign_keys=ON;

-- 001_init.sql
-- basic kv metadata like the database version and store cipher
CREATE TABLE "kv" (
    "key" TEXT PRIMARY KEY NOT NULL,
    "value" BLOB NOT NULL
);

CREATE TABLE "media" (
    "uri" BLOB NOT NULL,
    "format" BLOB NOT NULL,
    "data" BLOB NOT NULL,
    "last_access" INTEGER NOT NULL,

    PRIMARY KEY ("uri", "format")
);


-- 002_lease_locks.sql
CREATE TABLE "lease_locks" (
    "key" TEXT PRIMARY KEY NOT NULL,
    "holder" TEXT NOT NULL,
    "expiration" REAL NOT NULL
);


-- 003_events.sql
CREATE TABLE "linked_chunks" (
    -- Identifier of the chunk, unique per room. Corresponds to a `ChunkIdentifier`.
    "id" INTEGER,
    -- Which room does this chunk belong to? (hashed key shared with the two other tables)
    "room_id" BLOB NOT NULL,

    -- Previous chunk in the linked list. Corresponds to a `ChunkIdentifier`.
    "previous" INTEGER,
    -- Next chunk in the linked list. Corresponds to a `ChunkIdentifier`.
    "next" INTEGER,
    -- Type of underlying entries: E for events, G for gaps
    "type" TEXT CHECK("type" IN ('E', 'G')) NOT NULL
);

CREATE UNIQUE INDEX "linked_chunks_id_and_room_id" ON linked_chunks (id, room_id);

CREATE TABLE "gaps" (
    -- Which chunk does this gap refer to? Corresponds to a `ChunkIdentifier`.
    "chunk_id" INTEGER NOT NULL,
    -- Which room does this event belong to? (hashed key shared with linked_chunks)
    "room_id" BLOB NOT NULL,

    -- The previous batch token of a gap (encrypted value).
    "prev_token" BLOB NOT NULL,

    -- If the owning chunk gets deleted, delete the entry too.
    FOREIGN KEY(chunk_id, room_id) REFERENCES linked_chunks(id, room_id) ON DELETE CASCADE
);

-- Items for an event chunk.
CREATE TABLE "events" (
    -- Which chunk does this event refer to? Corresponds to a `ChunkIdentifier`.
    "chunk_id" INTEGER NOT NULL,
    -- Which room does this event belong to? (hashed key shared with linked_chunks)
    "room_id" BLOB NOT NULL,

    -- `OwnedEventId` for events, can be null if malformed.
    "event_id" TEXT,
    -- JSON serialized `TimelineEvent` (encrypted value).
    "content" BLOB NOT NULL,
    -- Position (index) in the chunk.
    "position" INTEGER NOT NULL,

    -- If the owning chunk gets deleted, delete the entry too.
    FOREIGN KEY(chunk_id, room_id) REFERENCES linked_chunks(id, room_id) ON DELETE CASCADE
);


-- 004_ignore_policy.sql
-- Add an ignore_policy column, defaulting to FALSE for all media content.
ALTER TABLE "media"
    ADD COLUMN "ignore_policy" BOOLEAN NOT NULL DEFAULT FALSE;


-- 005_events_index_on_event_id.sql
-- Create a unique index on `events.event_id` and `events.room_id` .
CREATE UNIQUE INDEX "linked_chunks_event_id_and_room_id" ON events (event_id, room_id);


-- 006_events.sql
DROP INDEX "linked_chunks_id_and_room_id";
DROP INDEX "linked_chunks_event_id_and_room_id";
DROP TABLE "events";
DROP TABLE "gaps";
DROP TABLE "linked_chunks";

CREATE TABLE "linked_chunks" (
    -- Which room does this chunk belong to? (hashed key shared with the two other tables)
    "room_id" BLOB NOT NULL,
    -- Identifier of the chunk, unique per room. Corresponds to a `ChunkIdentifier`.
    "id" INTEGER NOT NULL,

    -- Previous chunk in the linked list. Corresponds to a `ChunkIdentifier`.
    "previous" INTEGER,
    -- Next chunk in the linked list. Corresponds to a `ChunkIdentifier`.
    "next" INTEGER,
    -- Type of underlying entries: E for events, G for gaps
    "type" TEXT CHECK("type" IN ('E', 'G')) NOT NULL,

    -- Primary key is composed of the room ID and the chunk identifier.
    -- Such pairs must be unique.
    PRIMARY KEY (room_id, id)
)
WITHOUT ROWID;

CREATE TABLE "gaps" (
    -- Which room does this event belong to? (hashed key shared with linked_chunks)
    "room_id" BLOB NOT NULL,
    -- Which chunk does this gap refer to? Corresponds to a `ChunkIdentifier`.
    "chunk_id" INTEGER NOT NULL,

    -- The previous batch token of a gap (encrypted value).
    "prev_token" BLOB NOT NULL,

    -- Primary key is composed of the room ID and the chunk identifier.
    -- Such pairs must be unique.
    PRIMARY KEY (room_id, chunk_id),

    -- If the owning chunk gets deleted, delete the entry too.
    FOREIGN KEY (chunk_id, room_id) REFERENCES linked_chunks(id, room_id) ON DELETE CASCADE
)
WITHOUT ROWID;

-- Items for an event chunk.
CREATE TABLE "events" (
    -- Which room does this event belong to? (hashed key shared with linked_chunks)
    "room_id" BLOB NOT NULL,
    -- Which chunk does this event refer to? Corresponds to a `ChunkIdentifier`.
    "chunk_id" INTEGER NOT NULL,

    -- `OwnedEventId` for events.
    "event_id" BLOB NOT NULL,
    -- JSON serialized `TimelineEvent` (encrypted value).
    "content" BLOB NOT NULL,
    -- Position (index) in the chunk.
    "position" INTEGER NOT NULL,

    -- Primary key is the event ID.
    PRIMARY KEY (event_id),

    -- We need a uniqueness constraint over the `room_id`, `chunk_id` and
    -- `position` tuple because (i) they must be unique, (ii) it dramatically
    -- improves the performance.
    UNIQUE (room_id, chunk_id, position),

    -- If the owning chunk gets deleted, delete the entry too.
    FOREIGN KEY (room_id, chunk_id) REFERENCES linked_chunks(room_id, id) ON DELETE CASCADE
)
WITHOUT ROWID;


-- 007_event_chunks.sql
-- We're going to split the `events` table into two tables: `events` and `event_chunks`.
-- The former table will include the events' content, while the latter will include the location of
-- each event in the linked chunk.

-- Since we're going to get rid of the event chunks, we have to empty all the linked chunks.
DELETE FROM "linked_chunks";

-- Delete the events table that contains entries into an event chunk, along with the content of
-- those events.
DROP TABLE "events";

-- Events and their content.
CREATE TABLE "events" (
    -- The room in which the event is located.
    "room_id" BLOB NOT NULL,

    -- The `OwnedEventId` of this event.
    "event_id" BLOB NOT NULL,

    -- JSON serialized `TimelineEvent` (encrypted value).
    "content" BLOB NOT NULL,

    -- If this event is an aggregation (related event), the event id of the event it relates to.
    -- Can be null if this event isn't an aggregation.
    "relates_to" BLOB,

    -- If this event is an aggregation (related event), the kind of relation it has to the event it
    -- relates to.
    -- Can be null if this event isn't an aggregation.
    "rel_type" BLOB,

    -- Primary key is the event ID.
    PRIMARY KEY (event_id)
)
WITHOUT ROWID;

-- Entries inside an event chunk.
CREATE TABLE "event_chunks" (
    -- Which room does this event belong to? (hashed key shared with linked_chunks)
    "room_id" BLOB NOT NULL,
    -- Which chunk does this event refer to? Corresponds to a `ChunkIdentifier`.
    "chunk_id" INTEGER NOT NULL,

    -- `OwnedEventId` for events.
    "event_id" BLOB NOT NULL,
    -- Position (index) in the chunk.
    "position" INTEGER NOT NULL,

    -- Primary key is the event ID.
    PRIMARY KEY (event_id),

    -- We need a uniqueness constraint over the `room_id`, `chunk_id` and
    -- `position` tuple because (i) they must be unique, (ii) it dramatically
    -- improves the performance.
    UNIQUE (room_id, chunk_id, position),

    -- If the owning chunk gets deleted, delete the entry too.
    FOREIGN KEY (room_id, chunk_id) REFERENCES linked_chunks(room_id, id) ON DELETE CASCADE
)
WITHOUT ROWID;

-- For consistency, rename gaps to gap_chunks.
ALTER TABLE gaps RENAME TO gap_chunks;


-- 008_linked_chunk_id.sql
-- We're changing the format of the linked chunk keys, and not migrating them over.
DELETE FROM "linked_chunks";

-- We're changing the name of `room_id` to `linked_chunk_id` in the linked chunks table, and it's
-- part of a primary key, so we'll recreate all the impacted tables.
DROP TABLE "event_chunks";
DROP TABLE "linked_chunks";
DROP TABLE "gap_chunks";

CREATE TABLE "linked_chunks" (
    -- Which linked chunk does this chunk belong to? (hashed key shared with the two other tables)
    "linked_chunk_id" BLOB NOT NULL,
    -- Identifier of the chunk, unique per room. Corresponds to a `ChunkIdentifier`.
    "id" INTEGER NOT NULL,

    -- Previous chunk in the linked list. Corresponds to a `ChunkIdentifier`.
    "previous" INTEGER,
    -- Next chunk in the linked list. Corresponds to a `ChunkIdentifier`.
    "next" INTEGER,
    -- Type of underlying entries: E for events, G for gaps
    "type" TEXT CHECK("type" IN ('E', 'G')) NOT NULL,

    -- Primary key is composed of the linked chunk ID and the chunk identifier.
    -- Such pairs must be unique.
    PRIMARY KEY (linked_chunk_id, id)
)
WITHOUT ROWID;

-- Entries inside an event chunk.
CREATE TABLE "event_chunks" (
    -- Which linked chunk does this event belong to? (hashed key shared with linked_chunks)
    "linked_chunk_id" BLOB NOT NULL,
    -- Which chunk does this event refer to? Corresponds to a `ChunkIdentifier`.
    "chunk_id" INTEGER NOT NULL,

    -- `OwnedEventId` for events.
    "event_id" BLOB NOT NULL,
    -- Position (index) in the chunk.
    "position" INTEGER NOT NULL,

    -- Primary key is the event ID.
    PRIMARY KEY (event_id),

    -- We need a uniqueness constraint over the `linked_chunk_id`, `chunk_id` and
    -- `position` tuple because (i) they must be unique, (ii) it dramatically
    -- improves the performance.
    UNIQUE (linked_chunk_id, chunk_id, position),

    -- If the owning chunk gets deleted, delete the entry too.
    FOREIGN KEY (linked_chunk_id, chunk_id) REFERENCES linked_chunks(linked_chunk_id, id) ON DELETE CASCADE
)
WITHOUT ROWID;

-- Gaps!
CREATE TABLE "gap_chunks" (
    -- Which linked chunk does this event belong to? (hashed key shared with linked_chunks)
    "linked_chunk_id" BLOB NOT NULL,
    -- Which chunk does this gap refer to? Corresponds to a `ChunkIdentifier`.
    "chunk_id" INTEGER NOT NULL,

    -- The previous batch token of a gap (encrypted value).
    "prev_token" BLOB NOT NULL,

    -- Primary key is composed of the linked chunk ID and the chunk identifier.
    -- Such pairs must be unique.
    PRIMARY KEY (linked_chunk_id, chunk_id),

    -- If the owning chunk gets deleted, delete the entry too.
    FOREIGN KEY (chunk_id, linked_chunk_id) REFERENCES linked_chunks(id, linked_chunk_id) ON DELETE CASCADE
)
WITHOUT ROWID;


-- 009_related_event_index.sql
-- Add an index to speed up queries that look for related events in a room.
CREATE INDEX "relates_to_idx"
    ON "events" ("room_id", "relates_to");

-- Add an index to speed up queries that look for related events in a room, with an additional
-- filter.
CREATE INDEX "relates_to_rel_type_idx"
    ON "events" ("room_id", "relates_to", "rel_type");


-- 010_drop_media.sql
-- The media cache is separate now.
DROP TABLE "media";


-- 011_empty_event_cache.sql
-- After the merge of https://github.com/matrix-org/matrix-rust-sdk/pull/5648,
-- we want all events to get a `TimelineEvent::timestamp` value (extracted from
-- `origin_server_ts`).
--
-- To accomplish that, we are emptying the event cache. New synced events will
-- be built correctly, with a valid `TimelineEvent::timestamp`, allowing a
-- clear, stable situation.

DELETE from linked_chunks;
DELETE from event_chunks; -- should be done by cascading
DELETE from gap_chunks; -- should be done by cascading
DELETE from events;


-- 012_store_event_type.sql
-- For the event decryption to happen in the event cache we need the ability to
-- fetch only `m.room.encrypted` events out of the store.
--
-- To accomplish that, we are emptying the event cache. New events inserted with
-- the event type and the session ID of the room key as separate columns.

DELETE from linked_chunks;
DELETE from event_chunks; -- should be done by cascading
DELETE from gap_chunks; -- should be done by cascading
DELETE from events;

DROP TABLE events;

-- Events and their content.
CREATE TABLE "events" (
    -- The room in which the event is located.
    "room_id" BLOB NOT NULL,

    -- The `OwnedEventId` of this event.
    "event_id" BLOB NOT NULL,

    -- The event type of this event.
    "event_type" BLOB NOT NULL,

    -- The ID of the session that was used to encrypt this event, may be null if
    -- the event wasn't encrypted.
    "session_id" BLOB NULL,

    -- JSON serialized `TimelineEvent` (encrypted value).
    "content" BLOB NOT NULL,

    -- If this event is an aggregation (related event), the event id of the event it relates to.
    -- Can be null if this event isn't an aggregation.
    "relates_to" BLOB,

    -- If this event is an aggregation (related event), the kind of relation it has to the event it
    -- relates to.
    -- Can be null if this event isn't an aggregation.
    "rel_type" BLOB,

    -- Primary key is the event ID.
    PRIMARY KEY (event_id)
)
WITHOUT ROWID;

-- Add an index to speed up queries that look for related events in a room.
CREATE INDEX "relates_to_idx"
    ON "events" ("room_id", "relates_to");

-- Add an index to speed up queries that look for related events in a room, with an additional
-- filter.
CREATE INDEX "relates_to_rel_type_idx"
    ON "events" ("room_id", "relates_to", "rel_type");

-- Add an index to speed up queries that look for related events in a room.
CREATE INDEX "event_type_index"
    ON "events" ("room_id", "event_type", "session_id");


-- 013_lease_locks_with_generation.sql
-- Add the `generation` column to handle _dirtiness.
-- Default value is `FIRST_CROSS_PROCESS_LOCK_GENERATION`.
ALTER TABLE "lease_locks" ADD COLUMN "generation" INTEGER NOT NULL DEFAULT 1;


-- 014_event_chunks_event_id_index.sql
-- Remove uniqueness constraint on event_id, replace with regular index.
-- Empties event cache as data migration is not needed.

DELETE FROM linked_chunks;
DELETE FROM event_chunks;  -- should be done by cascading
DELETE FROM gap_chunks;    -- should be done by cascading

DROP TABLE event_chunks;

-- Recreate event_chunks with new PRIMARY KEY
CREATE TABLE "event_chunks" (
    -- Which linked chunk does this event belong to? (hashed key shared with linked_chunks)
    "linked_chunk_id" BLOB NOT NULL,
    -- Which chunk does this event refer to? Corresponds to a `ChunkIdentifier`.
    "chunk_id" INTEGER NOT NULL,

    -- `OwnedEventId` for events.
    "event_id" BLOB NOT NULL,
    -- Position (index) in the chunk.
    "position" INTEGER NOT NULL,

    -- We need a uniqueness constraint over the `linked_chunk_id`, `chunk_id` and
    -- `position` tuple because (i) they must be unique, (ii) it dramatically
    -- improves the performance. Also, we don't have a ROWID, so we must use a PRIMARY KEY, hence
    -- we use this composite key as the primary key.
    PRIMARY KEY (linked_chunk_id, chunk_id, position),

    -- If the owning chunk gets deleted, delete the entry too.
    FOREIGN KEY (linked_chunk_id, chunk_id) REFERENCES linked_chunks(linked_chunk_id, id) ON DELETE CASCADE
)
WITHOUT ROWID;

-- Create a non-unique index on `event_id` for query performance.
CREATE INDEX "event_chunks_event_id_idx" ON "event_chunks" ("event_id");


INSERT INTO kv (key,value) VALUES ('version',X'0e');
INSERT INTO events (room_id,event_id,event_type,content) VALUES (X'01',X'02',X'03',X'04');
