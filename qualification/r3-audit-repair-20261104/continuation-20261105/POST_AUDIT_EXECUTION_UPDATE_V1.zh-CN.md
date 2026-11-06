# 审计发布后的执行增量 V1

**原 23 项账本保持 16 项限定范围闭合、6 项开放、1 项科学验证保留。此增量没有新增 blocker 闭合。** 完整项目方向、原退出条件及后续路线以 [方向与执行计划 V7](PROJECT_DIRECTION_AND_EXECUTION_PLAN_V7.zh-CN.md) 和 [机器台账 V8](continuation-blocker-progress-v8.json) 为准；本文补充实际发布回执及随后取得的原生结果。

## 审计已实际发布

完整审计提交为 `fc10fbef82ec8e1a7db511c06d865c147200f1fc`，tree `3cbdfada435378fb080f1e5f9359e4f34d70f74c`，parent `46fd74d98c1cef42e1439920f9ca83361481b3d8`。创建、完整 GET、带 expected SHA 的 ref 更新与更新后 GET 均成功。14,670 叶与 2,276 个非根目录已重算 Git tree；23 个原 ID/exit 字面保留，只有 B23 相对前一账本新增 CLOSED_SCOPED。

主修复 [PR #4797](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4797) 和 Windows 机制诊断 [PR #4884](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4884) 已同步上述审计链接与限定结论，完整旧正文保留为后缀，head/base/merge/Draft 状态不变。

[本增量实际证据 registry](reviews/post-audit-publication-native-20261106/registry.actual.json) 记录 34 个实际 payload 路径及其完整 GET 字节核对。26 个编码分片可恢复 7,778,538 B 原 ZIP、96 个原件、15,092,732 B 原始 payload；[可重放说明](reviews/post-audit-publication-native-20261106/README.zh-CN.md) 与 [root 实际复验结果](reviews/post-audit-publication-native-20261106/verification.stdout.json) 一并保留。

## 新增的原生结果

### B23：新采集器成功，完整原目标再次通过

[PR #4910](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4910) head `2ac89eaf`、merge `652ff4a8` 的自动 run `42164668625` / job `127718228723` 整体成功。原 Bazel exit 与 console-copy exit 均为 0；全部 10,582 个产品叶、14 个 pin 以及前后 tree 关系不变。

两个官方 ZIP 保留完整八分片的 8 log + 8 XML；原日志计数为 **307 通过、0 失败、1 个由父测试调用的忽略入口**。三项单信号父测试与两项原 drain 测试通过。compact 的 93,986 个记录证明八个实际产品 TestRunner 在固定 Linux/amd64 远端运行、cache_hit=false、预算 300,000 ms；XML 辅助动作中六个非缓存、两个缓存，单独列示。每份 log 与自己的 XML helper 输入摘要相等，每份 XML 与自己的输出摘要相等。产品 spawn 未直接记录 test.log output digest，不据此声称直接产品输出摘要绑定。

新 collector complete，errors 为空；重复 Fetch 的两个 payload 仍完整保留。此前 e63 运行的整体失败与八份缺 XML 保持历史事实，新产物不回填旧运行。**B23 已在完整审计中按原条件闭合；此处补强新运行和采集器资格，不关闭 B15 或 B21。** [独立审阅](reviews/b23-v3-native-independent-20261106/REVIEW.json) 与作者冻结输入逐字节相符，隔离重放 11,262 B stdout 全等。

### Windows：格式门禁成功，原生库范围仍待验收

[PR #4913](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4913) 当前 head `18bbef4f`、merge `eefd4467` 的原 repo-check job `127731162050` 成功，完整日志证明原 `just fmt-check` 执行通过。原错误原因保留修复的两项测试仅在较早 `340fbc06` 来源取得通过；不会转授为当前 head 的全 Windows 资格。该工作流仍有其他失败或运行中的 job。

### Windows state EOF：拒绝引入可被先占的无限等待锁

[固定源码可行性审阅](reviews/windows-state-eof-feasibility-20261106/ASSESSMENT.zh-CN.md) 保留 75 个固定源文件和 4,832 个 Rust 文件的完整字面扫描。原 EOF 被呈现两次但只是一例；ACL error 5 为另一失败。原地截断写入存在源码支持的竞态窗口，但没有实际 writer/PID/时序来证明原 EOF 唯一根因。

拟议锁文件位于 sandbox 主体可写目录，阻塞 `File::lock()` 会新增先占后无限等待的路径；故正式 **REJECT_PUBLICATION**。包内保留草稿、原失败、替代设计义务和 root 对 117 成员的独立恢复。下一设计必须先建立可信稳定私有锁对象，或定义兼容的 setup deadline/cancellation；没有用忽略错误、跳过 ACL 或猜测超时来换取绿色结果。

## 新观察窗口与原全量切面分开解释

2026-11-06 **05:52:07–05:52:12 UTC** 只读取四个指定 run，完整取得 73 个 latest-attempt jobs：

| 来源 | Run | 成功 | 失败 | 运行中 | 跳过 |
|---|---:|---:|---:|---:|---:|
| B21 collector `84cc7345` | 42164663819 | 0 | 0 | 1 | 0 |
| B23 collector `2ac89eaf` | 42164668625 | 1 | 0 | 0 | 0 |
| Windows fmt `18bbef4f` | 42166252146 | 23 | 3 | 5 | 4 |
| PTY `8075eb36` | 42167168039 | 25 | 5 | 2 | 4 |

该窗口非原子、非全 workflow 普查，不替换前次七 head、46 run、214 job 完整切面。主候选 `67cc5c28` 的 19 run / 93 job 已全终态：68 成功、9 失败、10 取消、6 跳过；九条失败含七个执行失败及两个汇总门禁，仍不能合入为全合格产品。

## 接续工作

当前继续审阅固定四 crate 的 `pin-utils` 最小回补与真实 Cargo/Bazel 双锁生成提案，以及 holdout 文件锁生命周期候选。二者需各自源码身份、原生执行和原门禁验收；目前没有在本增量中授予资格。随后将已验证修复收敛到单一整合候选，重新运行其原必需 CI。

B02、B11、B15、B16、B19、B21 继续 OPEN，B18 继续 SCIENTIFIC_HOLD；原测试预算、严格 token/文件系统契约、真实 Root/Current/FinalUse 外部效果和外部接口接受要求均保留。[前一完整进度 V9](CONTINUATION_PROGRESS_V9.zh-CN.md) 及 [主证据包独立审阅](reviews/root-followup-independent-20261106/REVIEW.json) 可核对各项界限。
