# 首次 CI 成功后发现归档源快照漏项

实际 [CI run 41370810857](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41370810857)
完成四个真实场景，122 项独立审核通过，counter 和清理条件均通过。
这项真实执行结果保留，不因归档缺陷改写为未运行。

根审核下载 artifact 后发现其中缺少源快照
`.github__workflows__hcsn-v11-cgroup-economics.yml`。快照名以点开头，
`upload-artifact@v4` 的默认隐藏文件排除使其未进入归档；runner 上的独立
审核可以读取该文件，因此当时审核通过不能证明下载物完整。

本修复只在 upload step 增加 `include-hidden-files: true`，上传范围仍限于
`evidence/hcsn-v11-cgroup/`。该目录由 driver 生成，只包含明确的源码、
输入身份、进程记录和日志；没有扩展到 checkout 根目录、凭证或环境转储。
没有修改 meter、fixture、独立审核及原始成功结果。旧源码提交
`2291ae5390875fe5baecfec8a1a757326061df49` 和第一版归档/日志继续保留。

需重新触发同一 PR 的真实 CI，下载新 artifact，核对该隐藏快照及全部
IDENTITY 清单成员的大小、SHA 和 Git blob，才能关闭归档完整性缺口。
新的 CI 或完整下载核对尚未由本次本地修改证明。
