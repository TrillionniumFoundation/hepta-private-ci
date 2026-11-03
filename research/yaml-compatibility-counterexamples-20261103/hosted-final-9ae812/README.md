# Final hosted YAML qualification at 9ae81201

Exact source commit: 9ae81201f2761e7217f019c40b40de952ca4579d.
Exact tree: 3dfb1975ffd153afeced621c8efab12dfe8cc568.
Run: https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41680954821

All seven original qualification jobs passed. All seven downloaded ZIP sizes and SHA256 digests were checked against the GitHub artifact metadata. Every command stdout/stderr byte hash matched its receipt. Every one of the 89 before/after source and qualification inputs matched the actual published Git blob and SHA256; no input changed.

The five full original `just test --locked -p PACKAGE` calls ran 10, 49, 175, 420 and 166 native tests: 820 passed and zero skipped. Commands keep the repository stack setting. The complete Cargo all-features graph contains 1,524 packages and selects neither serde_yaml nor unsafe-libyaml.

The Bazel job first checked the committed lock, then ran the original generator, rechecked, and ran the actual YAML utility Bazel tests. All four commands returned zero. Generated MODULE.bazel.lock bytes equal the committed file, SHA256 5a6fbcf975d99e97e5562677643f3960e34929d423d22e788c6d41a43247ae26. The lock is not duplicated here.

The 8,156,923-byte reproducible Cargo metadata stdout is also not duplicated; its exact SHA256 is 60c4633d48cded5e1f0f5d3906529ace1d33db612e74ec97121b73a17e968969 and it remains artifact 13251324967. All other small command outputs and the seven complete receipts are retained.

Original blocking scope job 126074137768 in run 41680955193 succeeded in 29 seconds with all 59 original scope/readiness regressions passing. It dispatched the full original required downstream jobs. The earlier five-minute all-history checkout cancellation remains in the independently published scope-fix evidence.

These results apply to the exact source above and to the documented four consumer crates plus utility. They do not qualify arbitrary Serde enum APIs, a later combined dependency graph, all operating systems or production acceptance. Original blocking CI still has other failures and remains authoritative. No budget, timeout, test selector, required CI policy or release flag is relaxed.
