# a471 生产上下文接线：独立源码审查包

**本包是静态源码审查，不是新增执行资格。** Objective 的真实入口可复用；NDU 认证 owner 库存在，但 Agentd 挂载、当前读取证明和 native 生产工厂尚未完成。

- 源提交：`a47190bb84714cb1262fcd85ebb723081fdb0581`。
- 审查者：`/root/tick_shadow_recovery`；原审查时间保留在包内。
- 原始 MD/JSON、27 个精确源码文件、4 组引用搜索、方法、旧调查身份均完整保留。
- 不改写旧审查，也不把先前 33c CI 成功推定到本提交。
- 草稿审查只保留原 receipt、原 SHA 和六处修正说明，不复制完整草稿。

## 文件与校验

| 文件 | 字节数 | SHA-256 |
| --- | ---: | --- |
| `production-context-a471.tar.xz` | 99256 | `17d5bd63dd22f67469547e9bf567186f1b3d6e1895ce24701ee587b129744261` |

外部 `production-context-a471.manifest.json` 列出来源、规模、关键原始文件 SHA 与验证范围。
包内 `inventory.json` 为每个 payload 文件列出 SHA、字节数和归档 mode。

## 内容

- `review/`：原始 a471 MD/JSON，字节不变。
- `source/`：从精确 Git 提交读取的 27 个 Rust 文件，逐项匹配 review pins。
- `searches/`：四组实际 rg 输出及完整参数；否定搜索重现仍需要完整精确 checkout。
- `provenance/`：原始 commit object、源码清单、原审查身份。
- `prior-investigation/`：较早调查的原字节与原提交归属。
- `draft-review/`：旧草稿审查 receipt、原 SHA，以及六处已核对修正。
- `METHOD.md`：捕获与校验方法、复现要求和局限。

## 验证与边界

27 个 source pins、Git blob 身份和主工作树字节逐项一致；四组搜索匹配集合与原审查一致。
归档逐成员读回，原始审查输入及主仓库保持不变。
只运行只读 Git/rg 与标准库文件、哈希、归档操作；没有执行仓库源码、Rust、测试、模型或 SQLite。
当前 provider、生产 owner 安装、跨进程时钟与授权新鲜度仍是未实施/未资格化部分。
八个完整研究 blocker 仍为 false；本包不获取或认证后续 CI 状态。
