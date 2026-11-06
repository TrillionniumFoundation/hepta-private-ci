# main67 三项 run failure 的原件核对

本包取证窗为 2026-11-06 02:03:58–02:06:28 UTC，仅覆盖 run 42123581078、42123581186、42123581142，全部 job 记录绑定 source 67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed、run_attempt=1。

## 核心结论

完整 REST jobs 列表合计 12 项：8 success、4 cancelled、0 failure。四个取消项 127581904379 / 127581904887 / 127581904964 / 127581904089 的 steps=[]、runner_id=0、runner_name 为空、labels=[macos-15]。一次完整 job log 请求均返回 404 BlobNotFound。此记录不能确定取消原因，不能断言编译或测试失败，也不能把没有可读日志解释成从未执行。未提出产品补丁。

单 job GET 端点另有四份 connector 400 unsupported 原回执；之后未重试。未访问 check-runs。operator 的完整 normalized helper 与 REST 均含 6 项，job ID roster 一致；此前仅看截断预览而误读为 1 项的判断，已在登记前更正，不声称 connector 丢失 job。

## Linux 原日志的精确范围

| Job | 原始可见结果 | 保留限制 |
|---|---|---|
| Keyring 127581903929 | Cargo metadata、锁文件零 tracked diff、工作流指定的 advisory 包谓词通过、cargo check --locked -p codex-keyring-store 完成 15.98s | 没有测试运行；不等于完整安全或发布资格 |
| Operator Bazel GNU 127581904579 | 原目标 1/1 pass 0.2s，命令含 --nocache_test_results | 未下载 ZIP，不把目标摘要扩成实际 33 case、执行位置或 compact 资格 |
| Operator Ubuntu 127581904974 | 33 条逐 case PASS 与 Summary 33 passed /0 skipped；包含真实 OpenSSH 兼容用例 PASS，原 --retries 0 | 原日志记录 oracle 路径检查和 hash 写入命令；未独立取得 artifact 内 hash/JUnit |
| Owner Ubuntu 127581904493 | UDS 15P、Matrixd 31P、Agentd 242P；Agentd 另有 1 skipped；原 --test-threads 1 / --retries 0，fmt/源未改步骤成功 | console 未展示 skipped 用例名；未下载内层 JUnit |

原完整 UTF-8 job logs（包括 BOM、ANSI 和全部行）在 original/positive/，没有裁切。TRIAGE.json 的位置为对这些完整字符串按 LF 从 1 起计数；observed-nextest-PASS-rows.json 仅是可复核派生 inventory。原 API body 与完整 MCP 回执分别保留，错误回执也完整保存。

本次仅通过 GitHub 只读接口收件；平台执行器不可用，未重试执行器或查询容量，未下载或验证 ZIP，也没有发起 native、dispatch、rerun、cancel、ref 或 PR 修改。后续 create_tree(content) 仅物化无引用不可变对象，并逐对象 full GET 验证。任何对象的实际登记状态以 registry.actual.json 为准。

本包不改变 23 项原始退出条件、不扩展 blocker 关闭范围；历史 Intel drain 根因和这四项 macOS 取消原因都没有因 Linux 正例而得到解释。
