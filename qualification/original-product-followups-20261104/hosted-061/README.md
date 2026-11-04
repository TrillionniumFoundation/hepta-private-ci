# Original Core and Supervisor followups

The exact 061ec434 source completed the original two-platform qualification in run 41770058343. Each platform ran the same two required, previously failing Core cases and the entire one-case Supervisor restart integration binary. All 13 original commands, formatter and scoped Clippy passed; tracked source and both test binaries remained unchanged. No test deadline or retry policy was relaxed.

Windows inventoried 2331 Core cases, selected exactly 2 and retained 3 original ignored cases; 2326 other runnable cases were explicitly outside this qualification. Linux inventoried 2422 Core cases, selected exactly 2 and retained 1 original ignored case; 2419 other runnable cases were outside this qualification. These counts do not claim full Core execution. The Supervisor target had exactly 1 runnable case and no ignored case on each host.

The full decoded original job logs are preserved as ordered independently hashed RFC1952 parts; concatenate the decoded parts in numeric order. OBSERVED_RUNTIME.json records exact commands, case names, counts, binary identities and the original artifact identities. Independent original-ZIP replay is pending separately. Original negative evidence remains in ancestor a3bf4c98.

This checkpoint records scoped native regressions only. Full combined product gates, remaining failures and activation decisions remain open.
