# 中央源码候选装配：actual-only 初始版本

本目录为独立候选 overlay，提交祖先为 `a96d1b821d10ed3d9e99dd06c5141f9f242ae318`，tree `f96bebefbc1e7d8187efadb62f88d524cdd18451`。没有操作任何正在验证的 checkout、target、远端任务、中央 CALLERS 或 allowlist。

## 已装配内容

严格顺序为 C14 → S12 → C11 → Current13 → Root12 → Root actual UFCS V2 → Version actual40 → diagnostic5 exact `00378c2e33ede95f4a93bf96f6d87b3bd415d337`。全部 Rust incoming postimage 都由各自真实 formatter manifest 的 bytes、SHA256 和 Git blob 核验；不是用 prefmt 源替代 actual after。

随后加入冻结的 7 个 Python QA 文件：Selection／NextUse／Observer 三套迁移、Candidate commands、Current 新旧两套、Root progress/postread 20-case 套件。这里只做 Python AST 解析，未执行这些套件。Root20 的新产品输入仍待 Root3 actual，因此不能从旧单块结果推导当前装配 QA PASS。

最终 `work/` 与 `COMMIT_FILES.json` 一致：**105 个提交文件，98 Rust＋7 QA**。其中 47 个新增 Rust 文件全部在本次已修改源码里找到了真实 `#[path]` 模块挂载。此静态 inventory 不等于 Rust 编译验证。

## 精确应用和共享文件

每次应用都保存 a96 base、incoming base、current-before、incoming-after、实际结果的身份与输入路径，记录在 `LAYER_EVENTS.json`。当 current 等于 incoming base 时按精确字节应用；其它情况使用独立文件的 `git merge-file`，没有通用 prefer-ours/theirs 策略。

| 路径 | 实际处理 | 结果 |
|---|---|---|
| `lib.rs` | Version40 对既有 C14/S12/C11 exports 做 clean 三方合并 | 72167 bytes，SHA256 `76830312435171ae52f85d95be1931d7593c91c3734c7bf1afeae655c905da18`，逐字等先前 actual43 使用的物理文件 |
| `circuit_evaluated_retention_receipt_tests.rs` | 两个新模块同尾部插入点，原三方合并出现一个真实冲突；Root 明确授权精确保留两组 path attrs/mod | 15513 bytes，SHA256 `28c5131f78a1671e4e7ba4b0918a1c9ae825f8d6c87fb2f6ae3540930cfaad1f`，逐字等先前 actual43 使用的物理文件 |

第二个冲突仅为 `command_tests` 与 `version_tests` 的挂载位置，所有既有测试原字节保留。原 conflict markers、三份输入、原 merge return code 和窄 union 结果均保存在 `merge-evidence/07-Version40/`。没有其它内容冲突；**未解决内容冲突数为 0**。

首轮装配脚本在比较共享文件引用时因这个未处理的 fixture 冲突 exit 1。完整首轮 work/base/patch/merge 原件及实际退出记录保存在 `preparation-attempt-01/`；之后按 Root 批准规则重跑成功。这个记录是装配准备失败，不是 source QA 或 native 测试结果。

Diagnostic5 的原祖先是 4ab；已读取完整存档 GitHub compare，确认 4ab→a96 的 180 条变更中不包含这五个路径，因此其 base 与 a96 相同。它与其它本轮输入也没有实际文件交叠。没有为此重新查询 H 或启动任务。

## 独立机械核验

- 从 exact a96 base 生成 `assembled-actual-v1.patch`，在独立 `patch-roundtrip/` 用 `patch --batch --fuzz=0 -p1` 回放，exit 0、无 offset/fuzz，**105/105 结果逐字一致**。
- `SOURCE_INPUT_MANIFEST.json` 保存所有读取的冻结原件身份，装配结束重新核验未变。
- `MODULE_MOUNT_INVENTORY.json` 记录 47 个新增 Rust 文件的实际引用位置，缺失项为 0。
- `QA_SYNTAX_ONLY.json` 记录七个 Python 文件 AST 解析。没有把 AST 解析称为 QA 执行。
- 两个共享文件的结果与此前 actual43 原件再次逐字比较，详见 `SHARED_FILE_COMPARISON.json`。

所有组成块已实际格式化；两个机械合并输出没有在本轮重新执行 formatter，不能将“输入已格式化”写成“整个组装树已重新通过格式化”。本目录也不是完整 Git 工作树；未变文件由 exact a96 checkout 提供。

## 明确待补与交接

1. **Root3 actual after**：progress selection 与两文件 postread 复用。未将 prefmt 代码提前纳入。
2. **Version V4 actual after**：typed progress 与已绑定 evaluated source 的省读改动。收到后按实际 V3 base 做窄三方叠加，lib 不整份覆盖。
3. **Profile 最终四个 QA**：new Version、published-read、evaluated-retention、retained-version-issuer；Profile 正在对实际最终输入封口。未复制旧设计版冒充最终版本。
4. **中央 CALLERS／allowlist**：由 Root／Profile 的 row-level proposal 处理。本目录不创建或修改这两类文件；局部旧 PASS 不代表中央 registry 已正确合流。
5. **Training v3**：按 Root 指令排除，等待它独立审阅及实际格式化。

`UNRESOLVED.json` 区分实际内容冲突与以上待交付项。`COMMIT_FILES.json` 给出每个最终提交路径的 a96 base 和结果身份，可作为 Root 后续中央合流／提交清单的精确输入。后续收到的 actual 层应新增版本记录，不覆盖本轮 raw conflict 或早先失败证据。

**未执行 source suite、fullcaller、native、H 或发布。普通 Adopt、普通 NoUpdate、daemon＋Root 冷恢复资格保持 0。**
