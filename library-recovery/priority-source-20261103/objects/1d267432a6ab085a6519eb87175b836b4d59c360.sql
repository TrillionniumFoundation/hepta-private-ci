-- Preserve migration 0016 and existing terminal evidence. SQLite REPLACE
-- bypasses DELETE triggers when recursive_triggers is OFF. Guard both logical
-- identity and the implicit rowid conflict target before replacement begins.
-- Official writers never assign rowid. A legacy explicit rowid=-1 causes
-- automatic-rowid inserts to fail closed because SQLite uses -1 before assign.
CREATE TRIGGER cognitive_operation_destination_terminal_no_replace
BEFORE INSERT ON cognitive_operation_destination_terminal
WHEN EXISTS (
    SELECT 1 FROM cognitive_operation_destination_terminal
    WHERE (destination_id = NEW.destination_id AND operation_id = NEW.operation_id)
       OR rowid = NEW.rowid
)
BEGIN
    SELECT RAISE(ABORT, 'operation destination terminal proof is immutable');
END;
