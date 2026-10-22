-- REPLACE can delete an existing proof without firing DELETE triggers when
-- recursive_triggers is OFF. Reject every identity collision before that
-- implicit deletion, including an explicitly supplied SQLite rowid.
-- The original writer keeps using INSERT with an automatically assigned rowid.
CREATE TRIGGER cognitive_operation_pre_boundary_rejections_no_replace
BEFORE INSERT ON cognitive_operation_pre_boundary_rejections
WHEN EXISTS (
    SELECT 1 FROM cognitive_operation_pre_boundary_rejections
    WHERE rowid = NEW.rowid
       OR (
           operation_id = NEW.operation_id
           AND (
               entered_claim_sha256 = NEW.entered_claim_sha256
               OR settled_claim_sha256 = NEW.settled_claim_sha256
           )
       )
)
BEGIN
    SELECT RAISE(ABORT, 'pre-boundary rejection proofs are immutable');
END;
