# P0 共同候选与本轮实际结果

本轮把原恢复链、普通 Q24 LEARN、原始 Generator 训练回执和已复现的联合消费者修复收敛到同一候选。**P0 尚未完成验收**：缺少完整的原始 StageOwner 产品装配，以及同一冻结运行的 A→学习→独立 B→C 使用→冷恢复证据。这里不把组件测试或源码检查改称完整运行链。

## 已落实的代码

- 继承并保留 `source_sha` 与实际 checkout/tested SHA 的绑定。原修复来自 `dbb3bce393685469bd5587bb591d01099f1df697`，不是待重新修复的缺口。
- 合并 `0c99a30d` 的完整 CURRENT 恢复、`f97f3c90` 的普通 Q24 LEARN 和 `c7633658` 的原生 CI 维护修复。普通执行与只读恢复共享 canonical evaluation key，执行前身份核验保留。
- 新增原始 Generator 回执 owner：只从 typed 原训练 owner 读取完成结果；固定 Dataset、scope、已有角色和信任、签名 journal 与独立 witness。原 receipt、签名及签发时间一次持久化，冷读取不训练、不续签。Candidate、NoUpdate、错误绑定、Pending 和 lost-ACK 路径都有行为测试。
- RMCP 3.9 的 source-bearing discovery 错误恢复原分类与明确的有界重定向诊断，同时保留原错误链。
- 修复 unified exec 把有界历史交给可能落后的广播订阅者的问题：原进程先保留历史，再发送实时增量；轮询读取与历史分开。新回归覆盖慢订阅、两次轮询、退出后的 stderr 尾字节、关闭后订阅及精确省略计数。
- 两处现有失败测试保留原始 auth refresh / Matrix reopen 错误；没有放宽超时或验收断言。

固定候选源码为 `6ecfa504d2132f3682ffb01f8c9d65346b26cf5b`，tree 为 `9184583f3842d90a560436f279c753f15792e3ab`，集成 PR 为 [#5865](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5865)。代码身份、组件证据和未完成门槛见 [INTEGRATION.json](INTEGRATION.json)。后续证据保存于单独的证据分支，保持受测源码身份不变。

普通 LEARN 合并版的完整调用边界检查通过，覆盖 6,298 个 Rust 文件、213 个边界和 215 个受保护条目。新增训练回执的 138 项来源/变异检查与 217 边界、216 个受保护条目的静态检查另行保存，不把重叠测试相加，也不转称最终共同源的原生测试通过。

上一候选 `4073268e…` 的原生 CI 在 helper 构建阶段实际失败：旧 generation-use readback 未显式覆盖新增 `TrainingNoUpdateV2`，普通与 Root 测试均未执行。当前候选增加了明确拒绝分支及普通 actor 的回归用例；[原始失败记录](NATIVE_FAILURE_4073268.json)和完整 helper 输出已保留，新的 source-head CI 才能确认修复。

此外，同一旧候选的 Windows 原日志确认了另一项错误：恢复测试引用不存在的 `pending`。合并还残留同一 intent 的第二次 claim；仅改变量名会继续触发失败。当前源码恢复原 `claimed` 快照并复用原 coordinator，保留 backpressure、owner loss、readback-only 与不再训练的全部断言。两项修复都等待新源码的实际原生验证。

### 历史源码的实际原生通过

[原始 CI 读回报告](ci-readback/RESULTS.md)保存 5 个 artifact 的成员索引、77 个原始文件及 6 份完整 job log。仅维护集成版本 `8c9c51e…` 实际通过 daemon ordinary 1,104 项、独立 Root parent 7 项和 shared 1,134 项；对应 nextest 排除/忽略数为 72、908、71。三个执行集合不能相加为独立测试或研究样本。daemon 的 fmt、fix、bins 均返回 0，六份源码 inventory 完整字节相同。

后继 `0b13…` 与 `407…` 的 Linux helper 失败由各自原 stderr 独立确认，不能用上述通过记录替代。新的 `6ecfa504…` CI 另行等待。最终源码上 scoped Clippy/fix 和完整 native 门禁仍未宣告通过。

训练回执重开测试的范围是有效凭证/签名窗口内的文件对象重开，尚不是完整 daemon/Root 进程冷启动。过期签名拒绝续签，genesis witness 写入未确认时保持阻塞；两项限制均有新增回归代码。四个新 public 回执接口的产品调用者仍为空，不能据此称全链已装配。本目录不授予模型采用或生产权限。

## CTRL：本轮真正执行并读回的冻结诊断

[完整结果与原始文件](ctrl-gap/RESULTS.md)绑定既定源码、9,496,351 字节原训练记录、前后基线和原生回执。160 个状态来自 40 个既有训练来源；原覆盖 86，冻结的当前文本探针后为 87，即描述性增加 0.625 个百分点。

74 个原缺口中，1 个由固定数字格式投影补回，73 个只在同来源、同字段的其他历史状态中存在 scorer match。后者尚未证明普通 READ 可达、信息获取因果作用或最终选择成功。13 个状态受到本次探针预算截尾；历史生成器截尾仍全部未知。字段级统计保留 40 来源完整分母，缺少来源时保持 null。

原生文件回执记录 child exit 0，所有输入/源码前后哈希一致；远程 API 的两次同 key 请求仍是 transport timeout，durable job ID/权威进程终态未读回。二者分开保存。新模型调用、OCR、训练和新独立任务均为 0，采用仍为 NoUpdate。

## P1 的现有证据已更新

[RESEARCH_STATUS.json](RESEARCH_STATUS.json)分别引用各实验原发布身份，不能把它们当成共同候选的验收结果。

| Cell | 当前可用观察 | 尚未成立的结论 |
| --- | --- | --- |
| MEM6 | retention 30/84 对 28/84；selector 21/54 对 13/54；来源分别为 20 和 14 组 | retention 的单侧 95% 下界为 0；没有独立封存的新来源确认 |
| CTRL | 当前候选覆盖 86/160→87/160，40 个既有训练来源 | 73 个历史状态差异尚未转为可达的信息获取与任务收益 |
| PERC | 30 个合成任务×3 seeds；rules 90/90，global 49/90，dense 63/90 | 已有真实在线编码与普通文件 CLI，但未证明真实来源净收益或生产 daemon 接入 |
| ACT3 | 16 次拟合，640 个受控文件系统 episode；各 arm 均 96/128，1,600 primitive calls | 重复 16 个已暴露 probe 与 8 seeds 不增加独立任务数；未超过固定技能 |
| VERIFY4 | 226 项工程测试，72 条受控 confirmation row | 新独立真实任务仍为 0，不能替代独立终态裁定 |
| PRED | 159 项测试；12 train/6 dev 合成工程样本 | 原 owner 实际数据与独立 effect observer 未接通；189 fits 仍是开发执行量 |

P2、P3、P4 的实验顺序与准入条件保留，尚不开放机制优胜、拓扑收益或 RSI 主张。训练、搜索、失败、验证、恢复与通信成本只报告已测部分，未知项保持未知。
