# 最终研究提交的独立交付核验

本目录核验的研究提交固定为 [`9b03618be452d264cd7a3778677144ebc9b45fc2`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/9b03618be452d264cd7a3778677144ebc9b45fc2)，tree 为 `4807ef7e29ed3c0ce091b1233b213b17313746f1`。这些后置收据单独保存在 evidence archive 分支，研究提交没有因为记录自己的验证而改变。

## 已完成的交付核验

- [最终提交核验](FINAL_HEAD_VERIFICATION.json)和[完整日志](FINAL_HEAD_VERIFICATION.log)：实际仓库 blob-size checker 检查 972 个变更 blob，0 违规、0 豁免，最大 480,000 bytes。三套源码封存 67/104/92 项均匹配，派生 manifest、工具校验和及复现命令均通过，研究工作区前后保持干净。
- [公开报告验证](PUBLIC_REPORT_VERIFICATION.json)：五份最终报告/主比较文件从无凭证公开地址首次 HTTP 200 下载，88,128 bytes 与最终版本逐字节及 SHA256 一致。
- [最终发布事务](FINAL_PUBLICATION_JOURNAL.json)：保存 16 个分阶段交付提交、45 个文件版本对象及主研究分支的非强制更新结果；完整 raw 的 544 对象事务另见研究提交中的 `experiments/evidence_tools/ARCHIVE_PUBLICATION.json`。
- [文件身份索引](INDEX.json)：绑定本目录所有原始 JSON/log 收据的 Git blob、SHA256 和字节数。

两套 raw 已在不可变提交 [`8dc7defc17974d67766f35f340eb7bf6e692aefb`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/8dc7defc17974d67766f35f340eb7bf6e692aefb) 公开并从公开 URL 完整恢复。两份独立复审与归档原审计逐字节一致；新读出 0/1 与同种子复现 0/4 保持不变。原 policy 历史 raw 与原 roundtrip receipt 仍未恢复，新复现保留独立身份。

## CI 的时间与范围

[首次快照](CI_INITIAL_OBSERVATION.json)记录 17:16:30 UTC；[最后快照](CI_FINAL_OBSERVATION.json)记录 2026-10-29 17:20:17 UTC 的 workflow 状态及随后完成的日志和基线文件身份核验。

在最后快照中，当前 head 的 blob-size CI 实际通过；Codespell 为 15 条普通文本诊断，涉及的 9 个文件均与冻结基线同 blob，新增文本和压缩 archive 诊断均为 0。v8 成功范围是 metadata，两项 build 被跳过；架构 source-head 和 blocking workflow 仍在运行。历史 b244 的成功不用于替代该 head 的状态。

这里没有声称全仓 CI 绿色或生产准入。实时状态见 [PR #4157](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4157)。研究保持 `DENY_ALL`、draft、未合并主线。
