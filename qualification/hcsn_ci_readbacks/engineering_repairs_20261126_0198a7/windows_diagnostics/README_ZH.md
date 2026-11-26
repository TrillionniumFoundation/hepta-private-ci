# Windows CI 诊断源码候选

本目录与同一提交中的两处源码构成一个已格式化、等待独立 Windows 验证的候选。
它没有取得 Windows 功能资格，也没有闭合整仓科学或生产门。

## 固定来源与修改范围

- 父提交固定为 4ffa56f6d0be94e68d23d1bfe72aa2cbfd50d479。
- 独立分支为 fix/windows-ci-diagnostics-20261126-0198a7；不更新 #6799 或其他分支。
- 原失败记录来自 run 45794035631 / job 139821215079；它不是“最新 head”的测试结论。
- 修改仅涉及 .github/workflows/bazel.yml 和 codex-rs/ext/queue/tests/queue_service.rs。
- Windows shard 新增 --local_test_jobs=1，只限制并行 test actions；
  libtest 线程数、构建并行度、4 个 shards 与原目标选择保持不变。
- Rust 增加有限的失败上下文及 Python fixture 标志，保留原成功条件与业务代码。
- 原 1 秒 / 500 毫秒 / 10 秒 / 20 秒期限、断言、expect_err、wait_for_path、
  entered 条件以及 JobObject / fsync 生产守卫保持原有定义；没有放宽通过判据。

## 诊断局限

每个 marker 最多读取 512 字节，两文件合计最多 1024 字节。
marker 可能陈旧或截断，记录的 pid / prompt 不能证明它属于当前调用。
新增标志写入与失败时读取会增加 I/O，可能影响时序；该候选尚未证明消除原失败。
owner_start.is_finished 仅提供失败时的观察值，不构成新的成功门。

## 已完成的准备

- 原 formatter / manifest / toolchain 与 44 份守卫原件共 51 份逐字节恢复。
- 在独立本地仓库保留原件 baseline 后，一次执行官方 just fmt，返回码为 0。
- 本地准备有 6 个 Git 命令和 1 个 formatter 入口；这不是 formatter 内部子进程总数。
- Rust 216 项关键调用序列、原 wait_for_path 及 raw Python 业务片段通过保留门。
- 两处 Python raw fixtures 删除各自四行新增诊断后，与原业务字节完全一致。
- formatter 前后守卫及其他 baseline 文件未变，原输入前后身份一致。
- 编译、测试、模型、optimizer 均为 0；发布器不创建 PR、不手动 dispatch CI。
- 分支创建后若仓库自动运行 CI，其资格须按实际 head / run 另行读取记录。

## 原件恢复

INDEX.json 给出真实 tar.xz 归档的完整 SHA256、字节数与 ordered_parts。
严格按该顺序连接分片，核对完整归档身份后再读取归档中的 MANIFEST.json。
归档完整保留显式输入清单、原失败日志、原源码与历史候选、formatter scaffold、
审阅记录、格式化原始 stdout / stderr、DIFF、READY / VALIDATION 和准备 / 发布脚本。
manifest 逐项列出成员字节数与 SHA256；读取与打包没有执行归档中的任何内容。
完整大清单保存在归档内，Git 正文只保留本说明与精简索引。
