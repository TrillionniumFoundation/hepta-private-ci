# Source53 R30 项目门准备

本目录保存惰性 app-server 项目门执行器及可复核接口。V2 已完成 AST、机械差分和 root／独立静态审阅；当前模板仍为 `FROZEN=False`，15 个实际执行绑定均为 `None`。本组只准备文件，没有 import 或执行 runner、Rust、metadata、lock 更新、fix 或 fmt。

## 运行范围

source53 是 source52 的诊断版本，新增变更清单中的两条既存 Rust 叶；预期 197 条路径为原 195 条加两份 Bedrock 文件。两份文件只增加固定阶段日志和首个测试 child 的窄日志配置。`diagnostic_only=true`、`behavior_repair_claimed=false` 贯穿输入、原回执与完成记录。原 R29 自然失败 100 的事实保持。

只有完整 source53 apply 原件、自然 outer 0、实际 197 条源码／索引／HEAD／双锁检查，以及原 source50 真实 lock 回执和依赖未变证明都通过，已授权的最终执行器才能运行两条原命令：

```text
just clippy --locked -p codex-app-server -- -D warnings
just test --locked --retries 0 -p codex-app-server
```

cwd 是原 source/codex-rs，2 jobs、2 test threads、默认 features、原 profile／内层预算／skip 保持。启动时外层 watchdog 仍为 9,600 秒；前置可用空间须超过 20 GiB。没有新增测试 filter。原 Python runner 源字节没有变化，因此本 runner 没有 Python suite phase；旧证明只按其原始源身份保留。

## 原始证据和结果边界

每个 phase 在读取日志 hash、资源和后置源码守卫之前，先 create-only 写原始 process returncode，并 flush／fsync。后处理失败与真实子进程非零分别记录；任一失败均阻止后续 phase 或成功 complete。原始日志、raw result、资源和 postguard 都保留。

1,345 个 app-server `(binary, name)` 来自完整原 R29 日志，与其 193 包 metadata 和原解析结果独立核对。集合只用于完整原门结束后的验收，不进入命令 selector。V2 显式拒绝 missing、additional、duplicate、非 PASS 或非 app-server 行；Starting、Summary、唯一执行行和 footer 重复行分开处理。单个诊断版本的项目门 PASS 只能说明该版本通过这一次工程门，不证明 Bedrock 原失败已修复，也不替代完整工作区。

`INPUT-CONTRACT.json` 给出完整成功时的 19 个原始文件和额外自然 controller terminal 名称。后继 R31 必须核每份原字节、实际两阶段与 outer 0，再收集 fresh 193 default members 并运行原 no-p 工作区门；不把 R29 失败或历史 R28 通过写成 source53 资格。

## 版本与审阅

V1 保留不变。V2 相对 V1 只增加 `write_json` 的 flush／fsync，并在 `review_tests` 拒绝额外测试身份。两者都不改变命令、schema 或其他源码逻辑。V2 的 15 个绑定只能在真实 apply 闭合后另派生；最终冻结只能在 root 核验具体字节后进行。

本目录的两个机械读回、原始参考、全部差分和 HANDOFF 都保留。source53 apply 第一次输入路径准备失败属于另一组原件，不能据此修改或重跑本项目门。
