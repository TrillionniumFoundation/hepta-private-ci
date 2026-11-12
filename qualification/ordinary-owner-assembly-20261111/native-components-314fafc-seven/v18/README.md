# V43 original evidence-format failure

The original v18 harness completed with exit 1 at `314fafca93fcc8d4d7dd0c6e3d8256800b3c96fd`. The actual product Rust file remained exactly `1e5270f82571964dcf3817b26f48a9550bd1e9d8`. Only the evidence copy `native-components-d4d6e32-seven/v17/FORMATTED_SOURCE.rs` was reformatted under its evidence-directory context, and the original executor correctly rejected that dirty source tree.

The original complete terminal, seven reached launchers, two execution records, exact stdout from complete original tees, actual patch and evidence after-file are retained. Physical-source cleanup failed for that exact artifact; the other four cleanup checks passed. No compilation, QA, callers, ordinary native or Root17 tests were reached. V44 moves the original evidence bytes to a text attachment without changing product code, checker, formatter rules, caller inventory or permissions. No PASS or NoUpdate is inferred.
