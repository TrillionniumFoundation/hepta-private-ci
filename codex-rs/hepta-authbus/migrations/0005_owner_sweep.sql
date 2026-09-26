-- Bounded owner maintenance scans only pre-dispatch and dispatch-attempted
-- reservations ordered by their fixed-width big-endian expiry.
CREATE INDEX authbus_reservation_active_expiry
    ON authbus_quota_reservation(expires_at_ms, reservation_id)
    WHERE state IN ('held', 'dispatch_attempted');
