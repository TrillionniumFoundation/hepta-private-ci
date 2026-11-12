# cc22 原生失败与 4ab 修复记录

这是独立的失败证据快照。实际原生执行绑定 `cc22a69972d029d3ef28d49096f396eb5214c616` / tree `827fb70ed75d30c48d4693cbd0d23ea04f5744da`：**109 例，78 PASS、24 例栈溢出、5 例显式 FAIL、2 例 TIMEOUT**。原 hepta/nextest 命令 exit 100，外层 driver exit 1；整条 driver 没有超时。原始错误、日志、JUnit 和前后源状态均保留。

当前修复源已发布为 **4ab34bbd3ca803213b6eecbaba81af719630f5d0** / tree `f947d38de96534b3882fba023e51ecd0476c809d`，仅修改七个测试或 fixture 文件。这个快照没有 4ab 原生验收结果。六文件和另一个诊断文件的真实 Rust 1.96 格式化 exit 0，只证明这些精确输入的格式化完成，不是整棵 checkout 的维护或测试通过。

## 已执行结果与边界

| 项目 | 实际绑定 | 结果与限制 |
|---|---|---|
| 完整 focused native | cc22 | 109 例 / 78 PASS / 31 未通过；其中 2 例是 TIMEOUT |
| 新增九例 coverage | cc22 | 每例恰好执行一次；S 三例、C 四例均栈溢出，intake V2 两例通过 |
| Helper build / verify | cc22 | 两项 exit 0，仅是执行前提，不能使失败 suite 合格 |
| GDB 单例诊断 | cc22 原二进制 | 原 8 MiB 栈、60 秒预算；SIGSEGV 后自然 SIGABRT，单例失败，没有人工 kill |
| 静态反汇编尝试 | 预定同一 cc22 二进制 | 首次 `BINARY.stat` 即 FileNotFound，exit 1，没有反汇编或新帧结论 |
| 单 caller 边界 proof | cc22 + 一个 registry overlay | 6,595 个 Rust 源索引：before FAIL、after PASS、三种未登记 caller 攻击拒绝；不是 fullcaller |
| 修复发布 | 521 草稿基线 → 639 证据父提交 → 4ab | 七个精确 postimage 与格式化原件及发布 Git blobs 相同；native 尚未验证 |
| 完整 source closure | 仅 cc22 | 397 PASS / 0；原件在已冻结的 153 文件包，不能倒绑给 521、639 或 4ab |
| 完整 caller gate | 修复后的共同源 | 本快照尚无执行或 PASS；旧 8faf 的真实失败留在此前包 |

普通 Adopt、普通 NoUpdate、完整 daemon + Root 冷恢复、多代改进器四项资格计数均为 **0**。本次没有修改冻结的 PUBLICATION，也没有改写此前 93 文件或 153 文件证据包。

## 对失败采取的修改

`FAILURE_RESPONSE_MAP.json` 将所有 31 个失败 testcase 映射回完整原始日志的字节区间及后续修改。Provider 的非规范 candidate 顺序现在在实际 Cell/registry/Source 建立前绑定；原签名和 ledger 没有事后重写。Provider expiry v1 的错误诊断和 hunk 在集成前撤回，v1 原件仍保留，实际采用 v2：原签名在 `now == expires_at` 时合法，只有严格大于它才应得到 `Evidence(ValidityWindow)`。

S/C expiry 测试保留原签名、完整 journal/witness 字节比较、custody 与 frame 断言，并等待到原始有效期结束之后。Provider 的独立场景拆分保留原分支断言和预算。C publication-withdrawal 原测试在撤回之前的 positive read 已失败；这次只加入原 client/server 诊断，不声称已解决。Deep timeout 也只加入阶段计时标记，没有延长预算或宣称修复。

24 例栈溢出对应两个共同 fixture 文件的三个 child-future heap cuts。真实 GDB 第一个信号发生在初始 preregistration Admission 的 poll 链，尚未到 `completed_member`。未来尺寸和逐帧栈尺寸没有测量，因此不能把 crash site 解释为 flume/SQLx 缺陷，也不能据此断言三个切分已经足够。静态尝试失败没有补充这些缺失数据。

## 原件位置与复核

- `native-cc22-focused-review/`：完整 183,732 B 原日志、139,423 B JUnit、完整 31 例失败、九例 coverage、前后源记录、helper 原件及传输证据。
- `native-cc22-stack-diagnostic-v1/`：完整 GDB 与 runner 日志、九份执行 JSON、诊断报告和取回回执。
- `native-stack-fixtures-521-v2/static-failure/`：静态尝试的实际 FileNotFound 结果；原 PTY 终态也在 `root-native-sevenfile-review/`。
- `candidate-sourcebound-caller-cc22-v1/`：单边界实际 proof 的九份原件、原执行输入和已发布 patch。
- 各修复目录、`native-failures-sixfile-formatted-v1/`、`native-deep-stage-markers-521-v1/actual-format/`：保留修复历史、完整 patches、真实格式化原件和精确 postimage 身份。
- `root-native-sevenfile-review/PUBLISHED.json`：实际 4ab 七文件 GitHub compare 和全部基线/目标 Git blob。

`ARTIFACTS.json` 索引每个物理文件的 bytes、SHA-256、Git blob、原件或派生类别以及实际 source 归属；索引自身不递归包含自身哈希。`PACKAGE_MAP.json` 保留复制来源，所有复制按原始字节执行，没有 CRLF 归一化。运行 `python3 verify_package.py` 仅核验证据包完整性，不运行 Rust、source gate 或 caller gate。

完整 focused/GDB/runner 日志在回收时由连续原 h.view 行恢复，且已分别匹配原执行记录中的完整 bytes/SHA；这不冒充独立的完整 binary-read。XML 采用固定 immutable version 分块回收后核完整 SHA。有关未回收、刻意排除的源码/大二进制及历史相对路径，参见 `PACKAGING_NOTE.md` 和 `UNPACKAGED_REFERENCES.json`。
