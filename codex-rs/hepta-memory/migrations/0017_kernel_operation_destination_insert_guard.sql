-- A terminal proof is create-only even when recursive_triggers is disabled.
-- SQLite REPLACE can remove a conflicting row without firing DELETE triggers.
-- Reject the duplicate identity before that implicit deletion can occur.
-- The destination owner handles legitimate replay by observing the existing
-- proof inside BEGIN IMMEDIATE; it does not insert the same identity again.
CREATE TRIGGER cognitive_operation_destination_terminal_no_reinsert
BEFORE INSERT ON cognitive_operation_destination_terminal
WHEN EXISTS (
    SELECT 1 FROM cognitive_operation_destination_terminal
    WHERE destination_id = NEW.destination_id AND operation_id = NEW.operation_id
) BEGIN
    SELECT RAISE(ABORT, 'operation destination terminal proof is immutable');
END;
