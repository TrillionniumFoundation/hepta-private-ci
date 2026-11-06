# Source53 最终整理：惰性准备稿

此目录只提供静态可审阅的 finalizer。**FROZEN=False，35 个执行绑定仍为 None**；没有 import 或运行此脚本，没有运行 Rust、Cargo metadata、fix、fmt、工具版本查询或上传。

已知登记身份为 source53 f74be175de66a4b351cd239d39d98cd34fe9cc1b / tree 440d4a8e09af4009e4d9ea067388826308da8803。这是 197 个相对框架变更路径（183 Rust + 14 其他），包括两个 Bedrock 诊断增量；diagnostic_only=true、behavior_repair_claimed=false 始终保留。登记对象不等于 native HEAD 已 checkout 到该 commit。

## 必须先闭合的证据

| 输入 | 独立要求 | 当前准备稿边界 |
| --- | --- | --- |
| R30 | 当前 source53、原 app-server strict 与完整测试，19 原件和自然 outer 0；完整 1,345 身份恰好相等并全部 PASS | Future pins 全部未绑定，不记录终态 |
| R31 | 同源、原无 -p 工作区门、fresh 193 members/defaults；18 原件和自然 outer 0；完整 20,228 身份恰好相等并全部 PASS | Future pins 与 metadata 均未绑定 |
| R28 | 原 source52 的 26 原件和自然终态单独复核 | 历史门禁，不能替代 R30/R31 |
| 原失败 | R24、R26、R29 原 raw/receipt/guard/failed terminal 保留 | 不改成当前源码通过 |
| 最终范围 | 从真正 R31 metadata 重算 26 owner、183 Rust、2 Python、27 CI selectors | 当前作用域审计只用了明确标记的历史 R29 metadata，不能当 fresh scope |
| 工具清单 | source53 新只读 inventory 与当前源/manifest 绑定，再逐字核实际可执行文件、PATH shim、venv 和锁定版本 | 原 source51 的 8,083 B inventory 只作参考；新 inventory 尚未取得 |

测试身份集合仅用于完整执行后的验收，从未作为 selector、过滤或重试输入。四份最终 scope 输入和新工具清单必须由实际闭合原件派生、独立审阅后绑定；此目录没有预造其成功字段。

## 获准绑定后的原顺序

全部原门、源码、双锁、native HEAD、工具和范围守卫通过后，脚本才可执行 26 owner 的原 **just fix --locked -p …**，然后执行默认 **just fmt**。默认基准仍为 native HEAD bef6fa7645df9df12b69fda499e97eed25de6c75；不改 HEAD，不使用 --all、--base 或新增 --allow-staged。CI 独有的 codex-hepta-control-plane 不扩展 fix 的 26 owner。

Fix 只允许修改这 183 个 Rust 路径；fmt 只允许同一组 Rust 加 scripts/run-nextest.py、scripts/test_run_nextest_helpers.py。原 Python formatter 命令为 **uv run --frozen --project scripts ruff format ./scripts/run-nextest.py ./scripts/test_run_nextest_helpers.py**。相同 34 个 Cargo/formatter 原始输入、两个锁文件、原环境和文件模式均受保护。

实际子进程自然结束后先 create-only 写入原 raw result 并 flush/fsync，再解析日志/resources 和源码守卫。非零退出、额外修改、依赖/配置变化或后续审计异常会保留现场并停止，不自动回退、补跑或继续 fmt。只有成功的获准路径变化可以按原机制显式暂存，再导出实际新树；失败状态中观察到的旧 index 不会被冒称为完整 post-command 源码。

最后不运行测试，不把已测试 source53 的资格转移到发生修改的最终树。任何后续发布都需要 root 审阅真实输出；本准备稿不提供最终资格。

## 已完成的本地静态核验

- [作用域与依赖风险审计](SCOPE-DEPENDENCY-RISK-AUDIT.json)：原 195 条保持、2 个新增诊断 leaf、历史 metadata 的最长目录 owner 计算、34 个不变输入及工具待采样边界。
- [机械读回](MECHANICAL-READBACK.json)：44 个 R31 共用函数和 6 个旧 finalizer helper 逐字保留。
- [合同读回](STATIC-CONTRACT-READBACK.json)：8 类 R31 producer/consumer 字段相容、18/19/26 原件合同、raw-first 持久化、无 after-tests；mutation 分支去除源码标签与诊断输出字段后与旧 v2 AST 相同。
- [未来绑定合同](FUTURE-INPUT-CONTRACT.json)：35 个待绑定项、fresh scope 和新工具 schema、每个门的独立身份与原件清单。
- [源码精确差分](source52-source53-finalizer.patch)：对旧 129,529 B finalizer v2 的完整文本差分，已重新生成比对。
- [模板](native-finalize-source53-template.py)及[交接清单](HANDOFF-MANIFEST.json)：绑定本准备稿的精确原字节。

preparation-history/ 保留首次本地文本生成器的失败回执、原失败生成器和窄修说明。该失败发生在模板及 reference 写出之前，与任何 native 或 Rust 门无关；第二次生成和静态读回实际退出 0。旧文件没有被改写。

所有新文件均为准备材料，没有任何未来 R30/R31/工具成功记录被构造出来。历史工具版本是待核对的要求，不是对当前工具可用性的声明。
