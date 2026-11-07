# Source53 诊断源码的隔离应用准备

本目录只生成并检查惰性 Python 模板、实际 Git 身份绑定的候选清单及七成员输入包。没有执行该模板、Git 应用、Rust、测试、lock 更新、fix 或 fmt；没有修改 canonical/native 源码、HEAD、分支或报告。

原生基线为 source52 commit `1e0910becc37383e6d17ecf861ea844fd07d8862` / tree `211f15baff19095e8c98bcea2b0ed99ca2270ade`。root 已实际创建的 source53 为 commit `f74be175de66a4b351cd239d39d98cd34fe9cc1b` / tree `440d4a8e09af4009e4d9ea067388826308da8803`，单 parent 是 source52。实际 Git 身份不表示已在 native checkout 或通过工程门。

仅两份既存 Rust 文件有变化：Bedrock setup handler 和原失败 integration fixture。它们原先不在 source52 的 195 条变更清单内，因此候选清单有 197 条：183 Rust＋14 其他。原 195 个对象的全部值及各对象内部 JSON 原字节均保持。依照原实际 R29 metadata 的 193 个成员重新映射后，owner 仍为 26 个；原 workflow 的 27 个 CI selectors 保持。这里没有新跑 source53 metadata。

## 不可执行状态与后续绑定

`native-source53-apply-template.py` 保持 `FROZEN=False`，八个未来执行绑定仍为 `None`。开头的硬检查会拒绝惰性或优化模式 Python。root 审阅候选输入后，只有 native owner 可以按精确常量派生 bound 版本及最终单行冻结版本；本组不授权执行。

`derived/` 内有供 root 审阅的实际 197 行清单、delta 和七成员输入包。其输入成员严格为 delta、source53 全清单、原 3,906 B patch、两份 before 与两份 after。它们保留 ROOT_REVIEW_REQUIRED 的历史状态；root 后续冻结不会倒改本组的准备事实。

## 原失败与应用守卫

执行前置绑定原 R29 的四份完整原件：真实 terminal、raw process result、workspace receipt 和 source postguard。它们证明原无 `-p`、193 default members 的工作区门自然退出 100，source52 的 195 路径、HEAD 和双锁仍匹配。root 已闭合的完整归档报告另作为本地精确 provenance 保存；没有伪造远端 root 报告或声称运行时重读它。

模板在 mutation 前验证完整 195 条原始清单，并从既有 Git tree 与工作区独立验证两条额外 before leaf。七成员 exact-set、双向 patch、after 全清单与旧 195 对象的 JSON 原字节均须匹配。唯一三个 Git 子进程依次为 `apply --check`、`apply`、仅两个声明路径的 `add`。每个真实返回码在日志 hash 或后置检查之前以 create-only、flush、fsync 持久化；失败保留实际索引、工作区和 diff，不 reset、不重试、不运行后续门。

complete 的固定接口使用 plural 字段 `before_existing_repo_leaves_not_in_prior_changed_manifest`，携带 source/fullmanifest/delta/postguard pins、prior195/actual197、两条 `changed_from_source52_paths`，以及明确的 `diagnostic_only:true`、`behavior_repair_claimed:false`。source50 原真实 lock 成功仅在依赖输入与双锁未变的边界内继承；不冒称本次运行了 lock 更新。

## 诊断资格边界

本候选只增加九个固定阶段事件，并给原失败用例的第一个 child 设置窄日志过滤器。没有改变任何原请求、await、错误、断言、10 秒响应预算、60 秒初始化预算或重试策略。

未来若 source53 的完整 app-server 项目门真实 PASS，可以记录该诊断版本的项目门结果；这不证明原 Bedrock 失败的根因已修复，也不能替代完整工作区门或科学资格。当前 R29 FAIL100 保持；科学 HOLD、authority DENY_ALL 保持。

## 可复核入口

- `BUILD-READBACK.json`：模板生成及八个未绑定 literal。
- `STATIC-READBACK.json`：12 个共用函数逐字保留、AST、原回执绑定和 mutation 顺序审查。
- `MANIFEST-DERIVATION-READBACK.json`：18 份实际 Git tree payload 重新 hash、16 个父子引用、两 leaf overlay、scope 与七成员包。
- `ROW-PRESERVATION.json`：原 195 条 JSON 对象切片的精确 pins。
- `references/`：原模板、source52 manifest、四份 R29 原件、root 归档闭合、实际 Git 原件及 prior metadata。
- `HANDOFF-MANIFEST.json`：本新目录的完整冻结原文清单。

构建和验证脚本只处理本地数据。它们不会 import 或执行 native apply 模板。
