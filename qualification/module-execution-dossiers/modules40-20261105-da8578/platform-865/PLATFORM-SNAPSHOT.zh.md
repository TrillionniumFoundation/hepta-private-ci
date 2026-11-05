# 86582104 平台单次快照

观察始于 **2026-11-05 17:04:02 UTC**。这是一次有限、跨 API 非原子的只读快照；没有重跑、取消或改变任何候选的 CI。

固定 source-head 为 `8658210499706130788c216ff14fd342809b45a4`，tree 为 `6bc86196d10cf83b010f9917e5e9cb471b5f6b68`，有序 parents 为 `775bf555b0a7faf6eed17627acb0d0433294b737`、`3a39c799a3f776b0aeedfce350341d865d3cc1c4`。[Draft PR #4893](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4893) 的 base 在本快照为固定 3a39。

| 工作流 | Run ID | 本快照已生成 job 的状态 |
| --- | ---: | --- |
| rust-ci-full | 42070758717 | 23 queued、1 in_progress |
| Architecture convergence | 42070758993 | 2 queued |
| Windows 原始回归 | 42070759181 | owners / process 两个分片均 queued |
| Rust UI foundation | 42070758912 | 5 queued |
| v8-canary | 42070759157 | metadata queued |
| blocking-ci | 42070759060 | 3 queued |
| Windows 私有状态安全专用 | 42070758907 | 1 queued |
| Production HOS2 proposal | 42070758971 | 1 skipped |

已生成的 39 个 job 中，37 queued、1 in_progress、1 skipped。queued 的 runner ID 为 0 或 null；API 对 queued 项返回的 started_at 字段不被当作真实测试开始。唯一 in_progress 是 ARM64 release job `127397711547`，当前 step 仅为 **Set up job**。本快照没有该候选的平台编译或测试结果，也没有观测到失败。

PR API 报告的 prospective merge 为 `d92254c4bcf6635778cf7941a27659fad3e6b3f8`，tree 同为 6bc861，有序 parents 为 3a39、865。该对象已按 immutable commit API 保存；没有取得任务实际 checkout 的日志，因此**不宣称这个 merge 已被执行**。

原始 run、job、source commit、PR 与 prospective merge metadata 全部保留在本目录。`summary.snapshot.json` 区分原 run 状态、job 状态、当前 step 和 runner ID；`summarize_snapshot.py` 可离线重复核验。

bb55 的 Windows 私有状态成功、797 的 Codespell 成功及其历史失败仍归属于各自固定身份，不转给 865。所有 40 个生产开关继续为 false，公共拓扑继续为 DENY_ALL。
