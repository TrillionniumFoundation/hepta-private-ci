-- Bounded maintenance scans use state + fixed-width big-endian expiry so the
-- next expired reservation can be selected without a full live-row scan.
CREATE INDEX authbus_quota_reservation_expiry_state_idx
ON authbus_quota_reservation(state, expires_at_ms, reservation_id);
