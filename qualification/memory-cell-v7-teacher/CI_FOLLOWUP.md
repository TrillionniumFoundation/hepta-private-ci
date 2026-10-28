# V7 发布 CI 收尾

本次仅处理 `79ddbb46ae908678c6844099c999652e13e63ef1` 发布新增的两项 CI 问题，保持全部原始归档、冻结源码和科学结论不变。

- `.codespellrc` 只对 `qualification/memory-cell-v7-teacher/evidence/publication-review/V7_CODESPELL_REVIEW.json` 增加精确路径排除。三条新增 finding 来自机器审计 JSON 引用原拼写误报；普通源码和报告没有新增拼写错误，不扩大全局词典。
- `.github/blob-size-allowlist.txt` 按现有政策，为有意保留的原始证据资产增加一条精确路径：`qualification/memory-cell-v7-teacher/evidence/raw-runs-20261028.tar.gz`。归档仍为 932,459 B，SHA256 仍为 `22abddc211535a93ea1477430fbd656f7e891b43350ff4bee9cb9ed07c762ccb`；不改变 512,000 B 的默认门。

原 head 的 Codespell 222 条中，219 条与 #4004 base 完全一致。合同检查也在两边报告相同的历史引用问题：`qualification/memory-cell-v2/sources/github-history.json:389` 指向 `.github/workflows/ci.yml`。两边 cargo-deny 均失败，但日志取得遇到 `Transport closed`，没有证据证明两者原因相同。

只读快照时间为 2026-10-28 04:52 UTC；当时 blocking-ci 和 architecture source-head 尚未结束。两条精确规则修正不代表全仓 CI 已通过，后续 CI 结果另行核对。

[完整只读 CI 归因报告](evidence/publication-review/V7_CI_FINAL_REVIEW.json.gz) 使用固定 gzip mtime 保存。解压后的原 JSON SHA256 为 `5184cfba5825cdd574685bf26641fab3df14baff27d6f607854374584e966a21`；不改写已有机器证据来消除 lint。
