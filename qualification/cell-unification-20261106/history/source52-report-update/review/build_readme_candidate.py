#!/usr/bin/env python3
"""Build README candidate; preserve the complete maturity and scientific sections."""
import hashlib,json
from pathlib import Path
B=Path('/workspace/scratch/08f5efd48967');P=B/'source52-report-update-preparation'
old=(P/'references/README.md').read_text()
def section(n,m):return old[old.index('## '+str(n)+'. '):old.index('## '+str(m)+'. ')]
maturity=section(1,2);implementation=section(2,3);science=section(4,5)
implementation=implementation.replace('源码来源与 51 个登记记录','源码来源与 52 个登记记录').replace('固定在 source51','固定在 source52')
text="""# Cell 统一集成：当前源码、验证与采用边界

**当前状态：DRAFT；科学结论 HOLD；权限 DENY_ALL。** source52 的 GitData commit ¤1e0910becc37383e6d17ecf861ea844fd07d8862¤、tree ¤211f15baff19095e8c98bcea2b0ed99ca2270ade¤ 已登记，并已由唯一原生 apply 任务应用到隔离 staged tree。实际 apply-check、apply、精确 stage 与外层任务均自然退出 0；195 个变更路径、HEAD 与双锁守卫通过。原生 HEAD 仍是 framework 基线，不能把 commit 对象登记写成 checkout、分支发布或 PR 已创建。[当前状态][status]／[源码身份][identity]／[source52 精确修复与应用原件][apply52]

source52 的 **r28 原四包项目门已完整通过**：原 Python **32/32、0 skip**，strict 退出 **0**；完整 Rust 测试 **1,564 个唯一结果全部 PASS、0 FAIL、0 TIMEOUT，另报 3 skipped**，原 tests 与外层任务均自然退出 **0**。四包范围为 CLI、exec-server、network-proxy、external-agent-migration；原 1,564 个基线 ID 完整保留，没有新增筛选。r29 已实际启动同源默认工作区原命令，新 metadata 的 **193 members＝193 defaults** 已独立核验；本快照没有 nextest 开始或最终计数证据，完整工作区结果仍为 ¤null¤。最终 fix/fmt、最终源码 CI、分支与 Draft PR 均未完成。[r28 闭合原件][r28]／[r29 启动与 metadata 快照][r29-start]

上一轮 source51 的 r26 **失败结论原样保留**：1,562 PASS、2 FAIL、0 TIMEOUT，另报 3 skipped，tests／outer 均为 100。两个实际失败用例在 r28 均已通过；此前 source50/r24 的三个失败用例已在 r26 全部通过，在 r28 继续通过。旧 r25、r27 工作区准备没有执行。[r26 完整闭合证据][r26]／[逐例转换][r28-facts]

本目录是工程证据与成熟度索引，不是生产采用批准。每个门绑定其原始 staged tree；历史 PASS、静态审查、应用成功和工具准备成功分别记录，不转授给其他源码、完整工作区或真实模型采用。

"""
text+=maturity+implementation
text+="""## 3. 实际门状态：分别绑定源码，禁止相加

当前 source52 清单有 **195 个变更路径：181 个 Rust、14 个其他文件**，对应 **26 个 Rust owner 包**。既有五个 CI lane 保留 **27 个包选择项**，额外保留 control-plane。source51→52 只改变已有仓库文件 ¤network-proxy/src/runtime.rs¤ 的四个测试初始配置；该文件原本不在 source51 的 194 项变更清单中，其余 194 项原字节不变。依赖、双锁和 CI 输入均未改变，scoped fix/fmt 尚未执行。[源码范围准备快照][scope52]

原 source50 ¤just bazel-lock-update¤ 的退出 0 仅按未改变的依赖输入继承；source51 和 source52 没有重新执行锁更新。当前 26 个 owner 已按实际 195 路径和 r29 新执行的 Cargo metadata 重新映射；其 193 默认成员、包名、manifest 路径、edition 与默认 formatter 选择均有独立只读读回。没有执行 fix/fmt。[当前范围读回][fresh-scope]

| 原始门 | 绑定源码 | 实际结果及范围 |
| --- | --- | --- |
| r20：app-server＋linux-sandbox | source48 / ¤e65356f¤ | strict 与 tests 均退出 0；**1,495 PASS、0 FAIL、0 TIMEOUT，2 reported skipped**；原七项失败和新增四项 owner／FD 回归全通过。[入口][r20] |
| r21：默认 193 成员 workspace | source48 / ¤e65356f¤ | **编译退出 101**；nextest 未启动，执行与结果计数为 ¤null¤。[入口][r21] |
| r22：app-server-client | source49 / ¤be34ab1¤ | strict 与 tests 均退出 0；**30 PASS、0 FAIL、0 TIMEOUT、0 skip**。[入口][r22] |
| r23：默认 193 成员 workspace | source49 / ¤be34ab1¤ | **自然失败，退出 100**；**20,228 unique＝20,220 PASS＋7 FAIL＋1 TIMEOUT，130 reported skipped**。[入口][r23] |
| 原 Bazel lock 更新 | source50 / ¤ea48acf¤ | 原命令与外层均退出 0；两锁完整前后原字节相同。它是锁更新门，不是 Rust 资格。[原件][lock50] |
| r24：四包项目门 | source50 / ¤ea48acf¤ | Python **32/32**；strict **0**；完整测试 **1,561 PASS、3 FAIL、0 TIMEOUT，3 reported skipped**；tests／outer **100**。[入口][r24] |
| source51 apply-only | source51 / ¤763c8d2¤ | 原三条 Git 命令与外层均 **0**；194 路径、两处 delta 与双锁守卫通过；该任务未运行 Rust、锁更新或 fix/fmt。[原件][apply51] |
| r26：四包项目门 | source51 / ¤763c8d2¤ | Python **32/32、0 skip、0**；strict **0**；完整测试 **1,562 PASS、2 FAIL、0 TIMEOUT，3 reported skipped**；tests／outer **100**。原 r24 三个失败用例均 PASS。[入口][r26] |
| source52 apply-only | source52 / ¤211f15b¤ | 原三条 Git 命令与外层均 **0**；195 路径、唯一 runtime.rs delta、HEAD 与双锁守卫通过。没有新锁更新或 Rust 执行。[原件][apply52] |
| r28：四包项目门 | source52 / ¤211f15b¤ | Python **32/32、0 skip、0**；strict **0**；完整 **1,564 PASS、0 FAIL、0 TIMEOUT，3 reported skipped**；tests／outer **0**，源码守卫通过。[入口][r28] |
| r29：默认工作区 | source52 / ¤211f15b¤ | 唯一任务已启动；新 metadata **193 members＝193 defaults、退出 0**，原 no-p 工作区命令开始。本快照没有 nextest 开始或 tests／outer 终态；计数 ¤null¤，不记为 PASS。[启动快照][r29-start] |
| 旧 r25、r27 | 各自旧源码 | 惰性历史准备，均未执行；不累计为工作区结果。 |

默认工作区原命令保持 ¤just test --locked --retries 0¤，不新增测试筛选。各门 skip 数保持原日志口径，不凭总数补造跳过身份；不同阶段和源码的执行数量不相加。193 默认成员范围也不等于所有 feature、平台或外部服务均已验证。

### r26 两项实际失败与 source52 四处测试配置

r26 的两个实际失败均在 network-proxy 的 wildcard policy 测试中。source52 在四个直接配置 policy 的测试内显式设置已有 ¤allow_local_binding=true¤，让这些测试的 allowlist／denylist oracle 不依赖其不打算验证的主机解析前置。另两个用例在 r26 本来就是 PASS，保留其历史状态，不把它们列为新增失败。

| 原测试 | r26 原结果 | r28 原结果 |
| --- | --- | --- |
| ¤host_blocked_subdomain_wildcards_exclude_apex¤ | FAIL | PASS |
| ¤host_blocked_global_wildcard_allowlist_allows_public_hosts_except_denylist¤ | FAIL | PASS |
| ¤host_blocked_requires_allowlist_match¤ | PASS | PASS |
| ¤add_allowed_domain_removes_matching_deny_entry¤ | PASS | PASS |

四个测试的原断言、命令、时限与 oracle 全部保留；生产代码、默认配置、专门的 DNS／private／localhost 防护测试与注入解析测试均未修改。原失败块不包含实际 DNS 答案或解析耗时，不能仅凭约五秒的用例耗时推断 DNS 超时、私有地址或特定系统调用原因。[source52 修复与原件][apply52]／[r26 原结果][r26-readback]／[r28 完整结果][r28]

source51 的两处修复也有明确边界：bwrap 测试 helper 先使用既有生产 PATH system-bwrap 查找入口，缺失时保留仓库 binary fallback；DetectTls policy 测试只增加局部 ¤allow_local_binding=true¤。同主机、同受控参数的诊断中 system bwrap 退出 0、repo bwrap 退出 1；这不证明全部后端可用，也没有测出具体内核或 LSM 根因。对应两个 exec-server 用例与 DetectTls 用例在 r26、r28 均实际通过，原权限／计数／FD／PID 1 防护没有放宽。[source51 有限诊断与修复][registration51]／[原转换][r26-readback]

r28 三条原命令的实际耗时分别为：Python **4.025784969 秒**、strict **89.192417145 秒**、完整 tests **347.584490299 秒**。Python unittest 自报 **3.921 秒**；nextest 自报执行 **52.852 秒**。包含构建／fixture 准备的命令总时长与测试框架内部时长分别保留，不能互换。[闭合原回执][r28]

"""
text+=science
text+="""## 5. 剩余采用与发布门槛

1. 保留 source52 r28 原 Python／四包严格／完整项目门的真实通过结果，并完成同源、无新增筛选的完整默认工作区 r29。原两个 wildcard 失败及更早三个用例都已在 r28 实际通过，但不能据此推定完整工作区通过。旧 r25、r27 准备件继续保持未执行。
2. 只有工程门满足后，才执行约定的 scoped fix/fmt、精确最终差异和源码导出，再由最终发布 SHA 的 CI 验证。最终执行器必须重绑实际 native HEAD／tree、双锁、实际工具与非空默认 fmt 选择：**181 个 Rust 文件＋2 个 Python 文件**；不沿用 source49／51 的旧准备件，不改成 ¤--all¤。当前 fix 与 fmt 均 **NOT_EXECUTED**。
3. 把真实后端、真实 Encoder receipt 与产品 owner 接到共同合约；补齐完整状态、unknown 恢复、当前来源／scope／撤销和最终消费校验。
4. 按具体任务完成独立保留、校准、强检索／精确 KV／固定策略对照与完整生命周期成本验收。历史训练、fixture 回归和测试数量均不能代替这些结果。
5. 形成可分层审阅的 Draft PR；当前分支未创建、PR 未发送，最终 CI 与生产采用均未获资格。

## 6. 历史快照、恢复与证据阅读

本页、[STATUS.json][status] 和 [SOURCE_IDENTITY.json][identity] 是当前 source52 报告。修改之前，source51 三报告的原字节已保留在 ¤history/source51-report-update/*.candidate¤，并由不可变 artifact checkpoint ¤e904dc657d8f511380178d32f8563175ce7bfaa8¤ 固定。该 checkpoint 的代码仍是 source51，报告只记录当时 r26 Python 闭合与 strict 开始的快照，不能解释为当前 source52 或后来的完整 gate 结果。[前版原文与精确 pins][prior52]

本次登记列表逐项复用固定 [checkpoint5 ledger 快照][ledger52]中的 **52 个源码对象登记记录**；该次观察有 **185 个已登记二进制路径、5 个 artifact checkpoint**。后续附件登记不改写这些历史数字，本报告不把它们声明为永久的当前附件总数。ledger、源码与已有 formal 组均未被报告编辑器修改。

更早 source49 三报告、其原 native INDEX 与全部失败记录保存在[旧历史快照][history49]；source47／r19 的历史也继续保留。[更早历史][history] r20、r21、r22 的原 archive、日志、raw rc、receipt、资源与源码原件已精确恢复；三个 ¤*-recovered-checkpoint¤ 的读回是恢复后新审计，没有重跑 Rust，也没有伪造失去的旧审计字节。[r20][r20]／[r21][r21]／[r22][r22]

r23 完整失败、source50 实际锁更新、r24 和 r26 完整项目失败分别封存；读回成功没有改变任何原始失败结果。source52 的登记、单文件 apply 与 r28 完整项目通过另行绑定当前 tree。新的文档、静态审查和 artifact 保存都不等于完整工作区、真实模型或科学采用资格。[r23][r23]／[lock][lock50]／[r24][r24]／[r26][r26]／[source52][apply52]

[status]: STATUS.json
[identity]: SOURCE_IDENTITY.json
[maturity]: MATURITY.zh-CN.md
[assets]: HISTORICAL_ASSETS.json
[study]: study-evidence/README.md
[history]: history/published-r19-b14c3288/MANIFEST.json
[history49]: history/source49-r23-checkpoint/MANIFEST.json
[prior52]: history/source52-report-update/PRIOR-REPORTS.json
[ledger52]: history/source52-ledger-snapshot/MANIFEST.json
[r20]: native-evidence/r20-recovered-checkpoint/RECOVERY-CLOSURE.json
[r21]: native-evidence/r21-recovered-checkpoint/RECOVERY-CLOSURE.json
[r22]: native-evidence/r22-recovered-checkpoint/RECOVERY-CLOSURE.json
[r23]: native-evidence/r23-workspace-checkpoint/CLOSURE.json
[r24]: native-evidence/r24-project-checkpoint/CLOSURE.json
[r24-readback]: native-evidence/r24-project-checkpoint/INDEPENDENT-READBACK.json
[transitions]: native-evidence/r24-project-checkpoint/readback/R23-FAILURE-TRANSITIONS.json
[r26]: native-evidence/r26-project-checkpoint/CLOSURE.json
[r26-readback]: native-evidence/r26-project-checkpoint/INDEPENDENT-READBACK.json
[r28]: native-evidence/r28-project-checkpoint/CLOSURE.json
[r28-facts]: native-evidence/r28-project-checkpoint/INDEPENDENT-READBACK.json
[r29-start]: history/source52-r29-start-checkpoint/MANIFEST.json
[fresh-scope]: history/source52-scope-preparation/fresh/READ-ONLY-AUDIT.json
[baseline]: native-evidence/baseline/native-first-receipt.json
[registry]: native-evidence/registry-a/native-registry-a-receipt.json
[projection-source]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1e0910becc37383e6d17ecf861ea844fd07d8862/codex-rs/hepta-neuron/src/cell_feature_projection.rs
[registry-source]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1e0910becc37383e6d17ecf861ea844fd07d8862/codex-rs/hepta-neuron/src/cell_registry.rs
[lock50]: native-evidence/source50-lock-update-checkpoint/INDEPENDENT-READBACK.json
[lock-control]: native-evidence/source50-lock-control-recovery-addendum/INDEPENDENT-READBACK.json
[registration51]: history/source51-registration/MANIFEST.json
[apply51]: history/source51-apply-checkpoint/MANIFEST.json
[apply52]: native-evidence/source52-repair-apply-checkpoint/CLOSURE.json
[scope52]: history/source52-scope-preparation/SCOPE.json
"""
text=text.replace(chr(164),chr(96))
assert maturity==text[text.index('## 1. '):text.index('## 2. ')]
assert science==text[text.index('## 4. '):text.index('## 5. ')]
p=P/'README.candidate.md';p.write_text(text)
raw=p.read_bytes();print(json.dumps({'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'maturity_and_science_sections_byte_preserved':True}))

