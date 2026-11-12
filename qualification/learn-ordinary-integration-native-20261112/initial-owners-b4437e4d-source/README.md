# Original owner initialization in one Prepared operation

The source retains the actual original files, signers, Dataset capability, Trainer, signature journal and witness. A single original Prepared operation encloses assembly, and the outer factory postcheck still runs before unpacking initialization errors. The old public constructors retain their original owner-read contract. New internal constructors borrow a sealed existing source; no timestamp, key, role or success receipt is synthesized.

Seven small source/guard commits and their exact Git bundle are retained. Four added actual-file native tests have not been executed. Final frozen b4437e4d passed 55 affected source tests with identical clean source before and after; this includes negative guards and exact caller sets within a scoped source pool, not the complete Rust caller index. The original source-only 53-test failure, both intermediate dirty guard failures, their exact patches, and the final successful raw log are all preserved. The inherited Root LocalDecision marker mismatch from the earlier base was not silently reclassified as passing: its actual source migration is owned by a separate Root successor.

This does not establish the whole path, bounded-session admission, native compilation, full caller closure or cold restart. Complete positive, NoUpdate and daemon plus Root cold restart counts remain zero.
