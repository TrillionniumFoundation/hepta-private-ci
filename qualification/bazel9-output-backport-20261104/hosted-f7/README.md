# Native Windows output-drain qualification

Source `f7e1283370bd3e343df09416ae75717f2d558c75` completed native job `126354758118` in run `41762993935` successfully. The complete original 18 Windows wrapper GTests plus the two exact upstream regression cases passed, then the unchanged original Robrix two-case target and its Clippy target passed. Both exact Rust case names and the full `2 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out` summary occur once in the full job log.

Only `tools/test/tw.exe` differs in the complete copied embedded-tools repository. The original installed Bazel tools and the qualified copy remained unchanged through the original product test and Clippy. Product Bazel stays 9.0.0; the isolated upstream builder stays its official 8.4.2. The original 30-minute budget, assertions, required cases and failure propagation remain unchanged.

This evidence preserves the complete decoded job log and exact artifact identity. Independent ZIP/source/output replay and shared CI preparation integration are still pending at this checkpoint. The source branch, protected main, Draft/HOLD state and Library originals are unchanged by this evidence-only commit.
