# bf6d 原门与构建缓存读回：cold 仍未执行

本增量沿原 E6 证据候选追加，不更改源码、历史结果、原预算或任何资格标志。2026-11-24 经已配置的 HeptaRuntime `ai395` 主机只读取回 2026-11-23 的原门结果，并重新检查同一工作区的执行产物是否仍存在。没有新编译、原生测试、cold、Adopt、FinalUse 或模型调用。

## 固定源码和已有的真实结果

执行源仍为 `bf6d51904c8bcda5d50f3782c85ece84cb73a78f`，tree 为 `03f7135e2c060422f9dbd51bb38c5701cfaefe24`，单亲为 `61503a7d3bc87a5584cd2f20b8b17ea3838fdcfd`。本次读回时同一源码 checkout 的 HEAD 未变、工作树干净。

| 原门 | 已保存的执行结果 | 适用范围 |
| --- | --- | --- |
| 原 `just fmt --base 61503...` | exit 0，0.265170447 s；源码前后相同 | 原 bf6d 的格式范围；不代表 cold |
| CALLERS self-test / verify | 两项 exit 0 | 原源码保护门；没有授予执行权限 |
| 完整 b4 discovery / execution | 原结果记录 1,014 项，执行 exit 0，136.697286551 s | 该原源码门；本次没有重跑 |
| 两个原 neuron boundary 用例 | 原始日志、JUnit 和 recorder 均记录 2 passed，0 failed | 其余 237 项 nextest 筛出；不是完整 neuron 包资格 |
| 三包 library 构建 | `cargo nextest list` 在 623.692257727 s 超时，exit -9 | 没有获得完整 agentd 测试产物，也没有执行 cold |

构建原累计为 **1,798.0039511984214 / 1,800 秒**，剩余 **1.9960488015785813 秒**。原准备、失败、边界测试与本次库构建成本均保留；本次没有重置或扩张该额度，也没有把预处理或嵌套墙钟相加。更早的 Cold01 仍是 0 pass / 1 fail，NoUpdate19 的已通过范围保持不变。

## 2026-11-24 的新只读观察

新作业 `1a20d97df65-ffbe-3938` 已由 HeptaRuntime 确认 succeeded / exit 0，原始 stdout 347 B、stderr 0 B，输出完整且持久。它只读取既有 Cargo metadata、检查文件存在性及 Git 状态；没有运行目标 ELF 或编译器。

该 metadata 指定的 target 目录 `e6-bf6d-private-neuron-validation-20261123/target` **已不存在**，matching agentd executables 为 0。另一次只读观察确认原 `e6-lifecycle-qualification-v1/target` 中两份历史 agentd ELF 路径也不存在。存在旧 RESULT 或编译日志不等于当前具有可执行产物。新观察完整保存在 [CURRENT_OBSERVATION.json](CURRENT_OBSERVATION.json)。

因此，本次不能从原剩余额度与现存缓存执行完整 cold 父用例。不能把两个 boundary 单测、离线 publication 谓词验证或其他模型族的冷启结果替换为原 Q24 生命周期验收。原 cold/Adopt/FinalUse/独立新任务改善继续开放。

## 原件和校验

[originals.tar.gz](originals.tar.gz) 保存 13 份实际读回原件，包含 source gate 结果、两项 neuron boundary 的 recorder/完整日志/JUnit、构建准备和失败结果、完整 91,949 B 编译 stderr，以及原离线 warm/cold 比较。所有 UTF-8 原字节先按远端返回的完整 SHA-256 和字节数逐项核验，编译 stderr 以同一不可变 version 的两个连续分片读回。

[MANIFEST.json](MANIFEST.json) 列出 13 个成员的路径、字节数、SHA-256 和完整容器 SHA-256。新容器通过标准 tar/gzip 写入，mtime 为 0；本地复读全部成员再次核验。容器不是旧运行当时生成的原始归档；各成员原字节未重序列化。未修改旧归档或删去失败证据。

这是一份执行准备缺口的可复核记录，不是新学习样本、新支付、生产资格或科学收益。没有修改 main、既有工作区、服务、权限、构建策略或重试规则。
