# Shared Windows Bazel setup: original native acceptance

Exact source `8f7a9cde3bc30b133fc7fa2446fe5d38c163d3c9` / tree `c9e302c2871047645c552fce0d96a60693cb1bf0` passed [original job 126363529064](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41765728268/job/126363529064). The unchanged builder ran through the shared setup action, not a duplicate research-only step.

The complete 18 original wrapper GTests plus the two exact upstream regressions passed. Both unchanged Robrix cases, the full 2/0/0/0/0 summary, original scoped Clippy and source/installed-tools/override stability checks passed. All command arguments and exact original output identities are in the structured receipt; the complete decoded job log is retained losslessly in gzip format.

Independent read-only replay [41767325983](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41767325983) passed on the exact 388277-byte original ZIP. It verified the full ZIP digest and member CRCs, six helper and 108 Robrix Git inputs, 50 helper and 15 Robrix outputs, exact test sets and Clippy. The 591 embedded tool entries differ only at `tools/test/tw.exe`. The final tree-stability result comes from the exact source-bound native finalizer; no separate retained after-tree inventory is invented.

This accepts this narrow candidate. PR #4752 still points at `767f069` until composition; historical or research-source results do not become current-head full-product qualification. The complete private CI, research, external-chain and source-recovery gates remain separate. HOLD_NO_GO; no Library original deletion.
