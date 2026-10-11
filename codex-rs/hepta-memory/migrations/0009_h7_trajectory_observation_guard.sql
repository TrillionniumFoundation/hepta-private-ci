-- H7-LQ v1 is an observation-only writer.  Keep the broader event vocabulary
-- in the base table for a future typed feedback migration, but reject rows
-- that would look like policy feedback/reward before that contract exists.
-- A trigger makes this boundary hold for direct SQL as well as the typed API;
-- the immutable loader still re-validates every historical row on reopen.
CREATE TRIGGER cognitive_h7_trajectory_events_observation_guard
BEFORE INSERT ON cognitive_h7_trajectory_events
WHEN NEW.event_kind NOT IN ('turn_start', 'terminal')
  OR NEW.reward_bps <> 0
  OR (NEW.event_seq > 1 AND NEW.causal_parent_sha256 IS NULL)
BEGIN
    SELECT RAISE(ABORT, 'H7-LQ trajectory rows require typed observation provenance');
END;
