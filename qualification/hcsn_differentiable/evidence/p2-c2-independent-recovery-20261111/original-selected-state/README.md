# Original selected C2 state bytes

Join the ten original-c2-selected-state.zip.part-* files in ascending
offset order from ARCHIVE-PARTS.json, then verify the complete SHA-256 before
opening the ZIP. Each part is at most 450,000 bytes; no blob policy is relaxed.

The ZIP preserves 368 original files, including four completed fit best
checkpoints, two incomplete fit last checkpoints, all 289 small immutable epoch
commit records, original torn journals and zero-byte interrupted artifacts.
Original intermediate checkpoint bytes, nonempty full-development logit
payloads and the complete prepared dataset are intentionally outside this
selected archive. Their source identities remain in the original records.

Both original incomplete fit terminals and the controller terminal remain
unknown. There is no new training, replay of training, automatic resume or
adoption. Qualification remains HOLD_NO_GO.
