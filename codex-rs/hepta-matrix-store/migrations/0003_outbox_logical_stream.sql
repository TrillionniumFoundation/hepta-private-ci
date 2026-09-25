ALTER TABLE outbox_messages ADD COLUMN logical_outbox_id TEXT;

UPDATE outbox_messages
SET logical_outbox_id = (
    SELECT txn.logical_outbox_id
    FROM outbox_txns AS txn
    WHERE txn.txn_id = outbox_messages.stable_txn_id
);

CREATE INDEX outbox_messages_by_logical_stream
ON outbox_messages(logical_outbox_id, outbox_id);
