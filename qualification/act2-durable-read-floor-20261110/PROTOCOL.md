# ACT-2 original-owner read floor and real App fence qualification

Parent: Hepta #5641 `5b21f1405513dd0d59f7dd990258cfd36737fc52`; companion desktop #301 maintained `cc33ab6c44f3c945d83cb96be71d861e5613f99e` (original candidate `0e884b4cf6831d7cb614b87786c40137a575672d`).

Fresh literal preparation, thread status/read and UI refresh check the original writer's committed Notes receipts. Every candidate request/receipt is validated in 64-row pages; Rust uses exact u64 revisions and detects same-revision content conflicts. More than 1024 candidates returns unavailable. Original source authority/current-owner checks remain. Deadlines limit the caller's wait, not a promise that SQLite computation stops instantly.

The workflow explicitly selects the ignored 1024/1025 capacity test. Source tests include reopen and a new lease reading predecessor receipts. The actual App test creates a new attachment, accepts its fresh current read and rejects the old real revision captured before subsequent edits. It does not physically replace an App checkpoint or rewind the source checkpoint.

The separate actual-App fence test covers two owned lifecycles, fence-first and apply-first. The fixture-only delayed frame has passed original FinalUse but has not entered the physical FIFO. A new authorized cancel reaches the real App, then the same held bytes are released without another grant. This is neither FIFO reordering nor a production retry guarantee; normal I/O errors still invalidate the channel.

All new native/actual-App results are pending. Source plus destination common rollback, external changes absent from source history, asynchronous report delivery, original pending cancellation responsibility, complete DynamicToolCall authority, production activation and learned benefit remain separate gates.
