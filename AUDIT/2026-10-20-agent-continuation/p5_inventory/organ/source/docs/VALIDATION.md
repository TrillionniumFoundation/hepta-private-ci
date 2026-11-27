# 验证层次、判定器与审计跟踪

版本0.3。模型、codec、内核、设备、Hepta端到端结果严格分层，实际执行状态见STATUS。

## 1. 结果和分母

每项记录not_tested/pass/fail/timeout/skipped/unsupported及执行环境。运行模式native-control/linux_abi/android_runtime/VM与结果分开。报告执行总数、失败、跳过、未支持及原因；不删除失败用例制造全绿。

## 2. 三类接口测试

格式测试（已有 Rust codec 与独立验收）：HOS2/HOSR的64字节header、32字节transport与预算、Query48/Usage64/Install24/Delivery64/Retire16响应及40字节历史引用；截断每一长度、尾随字节、flags/reserved/enum、id全零、generation/target、major/minor、过大payload、输出容量、revision溢出、错误响应无敏感payload。正式入口见下方第9节；格式通过不授予内核权限。

规格模型：K查找后比较digest；D/CapSpace跨boot；revoke/admit两种线性顺序；停止后partial效果；相同预算反复更新保留用量；parent cap共同执行。模型证明选定解释的逻辑，不证明内核采用了该解释。

实际内核测试（部分已有，其余待接合）：主干只读 QueryAbi 和 cgroup CPU 配额有[固定客体收据](../results/organ-backend/2026-10-17/a05-a06-integrated-acceptance.json)。Process / exec_epoch / nonce 的只读身份隔离另有 [单 vCPU 组合收据](../results/kernel/control/a05-main-combined-acceptance-20261017.json)，不能再整体标为未实现。完整 capability 授予与恢复、Linux/Android设备别名、并发CAS/撤销、copyout EFAULT后的原D重取、容量耗尽、最终CPU计费及硬件reset/DMA引用仍按其专用源码与场景验收；不得继承 host 模型或其他候选分支的通过状态。

## 3. 第一个端到端闭环

固定kernel/rootfs/ELF/Hepta和设备身份；先普通客户端，后真实Hepta主工具链。启动两个CPU竞争任务与不随Hepta退出的观察器，取固定策略基线；安装cap并记录K/D、对象generation、revision、时间和内容；核对真实任务完成量与内核用量，而非只读模型文本。

测试同D变内容冲突、相同D丢响应重取、并发旧revision、cap同值刷新、fd跨域及撤销交错。然后停模型/桥/Hepta，核对独立应用、I/O、恢复资源。重启后旧会话无效、原K未决不重放。

独立进程读相同内核计数不是独立证明计数实现正确；用CPU工作量进度、文件实际内容或设备完成交叉校验。不宣称这些能证明已被攻陷内核的全部行为。

## 4. 差分允许集合

确定性字节/errno精确比较；并发用偏序、不丢结果、互斥和最终回收等不变量，而非强制相同调度总序。PID/地址/随机值按明确规范化规则处理。不同安全边界造成的permission_denied单独记录，不能把它当unsupported，也不以兼容名义复制已知漏洞。

## 5. 故障注入分层

应用kill验证进程丢失；客体reset验证内核丢失；VMM退出验证虚拟机进程消失；丢弃指定易失缓存/短写/乱序验证存储假设；实际设备断电另列。尤其kill QEMU不保证host cache被丢弃。

每层记录注入切点、失效范围、重启路径、预期原数据/事务/操作状态。S1原生块存储与host-backed路径分开验收。部分物理效果保留，不能靠取消ACK回写none。

## 6. 性能与AI价值

A：同新内核固定策略/非AI反馈/Hepta策略；B：同硬件Linux等价控制与新内核；C：原生/ABI/VM设备路径差异。固定负载、数据与资源上限，冷/热状态分别测，随机化次序并记录温度及后台负载。

报告成功率、吞吐、p50/p95/p99、样本量与区间；低样本尾分位不作强结论。计入模型推理、观测、策略安装和错误恢复成本。第一cap演示只证明接口有效，不证明AI或新内核更快。实验参数在看结果前固定；无可靠改进则保留基线。

## 7. F01–F22 历史0.2落点（当前契约以0.3为准）

| 审计项 | 0.2规格落点 | 尚需真实验证 |
| --- | --- | --- |
| F01 | ARCHITECTURE/DECISIONS/upstream-lock：完整内核派生 | 已有固定构建/启动；裸机与跨宿主可复现仍待验证 |
| F02 | NATIVE_ABI §2：同对象策略、会话绑定、root边界 | 内核别名/fd/credential |
| F03 | NATIVE_ABI §7：admit/revoke同锁及桥TCB | 并发/硬件切点 |
| F04 | NATIVE_ABI §8：K与D、摘要不入查找键 | 持久owner/重启/copyout |
| F05 | NATIVE_ABI §10：执行、取消、效果、观测分离 | partial/reset/DMA |
| F06 | NATIVE_ABI §3–6：有限三操作完整wire | codec与驱动接入 |
| F07 | NATIVE_ABI §9：固定周期不充值、祖先与内存 | 真实调度/SMP/计费 |
| F08 | HEPTA_INTEGRATION：源码符号/profile | 实际owner装配/主链 |
| F09 | PROJECT/LINUX_COMPATIBILITY：W0–W5/rootfs | ELF和应用分场景 |
| F10 | ANDROID_COMPATIBILITY：product/VINTF/MAC/页/代理 | manifest锁定/AOSP/CTS |
| F11 | ARCHITECTURE/HARDWARE：锁/IRQ/DMA所有权 | 源码锁分析/设备测试 |
| F12 | ROADMAP/HARDWARE：并行风险调查 | 选定GPU/VMM路径 |
| F13 | SECURITY：S0输送/S1原生Ext2候选 | 存储与SQLite故障 |
| F14 | SECURITY：熵/时钟/boot/更新 | entropy/clone/休眠/回滚 |
| F15 | HEPTA/VALIDATION：有界控制器/三基线 | 净收益与稳定性 |
| F16 | HEPTA/VALIDATION：K/D/对象/完成关联 | 权限观测/计数交叉 |
| F17 | DESKTOP_UX：Wayland/分域Xwayland/Android面 | 实际UI/IME/共享 |
| F18 | PROJECT：原生控制≠独立用户态ABI | 当前定义无独立ABI承诺 |
| F19 | ROADMAP/upstream-lock：输入和缺项 | 容器/rootfs/firmware锁定 |
| F20 | VALIDATION：允许集合/故障层/独立性 | 实际差分与掉电 |
| F21 | ROADMAP：M1a/b/c -> M2a/b/c | 按依赖逐项交付 |
| F22 | INDEX/STATUS：共同原则与单一状态页 | 链接/状态一致维护 |

“规格已修订”不等于“问题在运行实现中已关闭”。本表是审计追踪，不是新的审批或授权数据库。

## 8. 最小证据

一次运行保留run_id、source/build/hash、host/guest、配置/镜像/设备、命令/退出码、日志hash、预期和实际。凭据/用户内容不进入公开日志。大镜像不入Git，仓库放复现入口与准确摘要。文档验证只检查文件/链接/字段算术，不冒充CI、kernel boot或兼容通过。

## 9. 0.3复审落点与实际测试

[tests/spec/test_recovery_contract.py](../tests/spec/test_recovery_contract.py)是仅用Python标准库的**顺序规格模型**，不解析wire、不调用设备，不实现Rust库或真实权限。运行 `python3 tests/spec/test_recovery_contract.py /tmp/hos-spec-results.json` 可复现14个场景。结果基线在[spec-recovery-v03.json](../results/spec-recovery-v03.json)。其中10,000次写在同一模型窗口中，每64条终局确认一次，验证旧序列不能重新执行；不是内核吞吐或并发测试。

[tests/golden/hos2.json](../tests/golden/hos2.json)包含12份独立生成的固定十六进制请求/响应样本，包括降额后consumed>cap与错误响应。实际 [no_std Rust codec](../libs/os-abi/src/lib.rs) 已消费独立固定样本，并由 [run_acceptance.py](../tests/abi/run_acceptance.py) 执行黄金、语义边界、负例及编译型错误变异验收。使用以下正式入口，保留其生成的原始日志与源码/工具链身份；独立 expected 数据仍须与同一 codec 的 round-trip 分开：

```bash
python3 tests/abi/run_acceptance.py --help
```

精确执行命令、结果与边界见 [A02 验收说明](../tests/abi/A02_REVIEW_CLOSURE_2026-10-17.md) 和 [证据完整性修复](../tests/abi/A02_EVIDENCE_INTEGRITY_2026-10-17.md)。当前 #147 的累计CPU/历史投递语义仍待 A00 统一决策，不能把验收脚本修复写成语义已定案。

| 复审项 | 本轮落实 | 尚未完成 |
| --- | --- | --- |
| V201 | 最终exec后可信激活与启动页；顺序场景 | init/exec真实接合 |
| V202 | CapSpace级D预约、目标锁提交；跨目标冲突模型 | 实际锁序/抢占/并发 |
| V203 | DeliveryView与QueryDelivery；独立观察模型 | 内核身份与重启观察授权 |
| V204 | 历史未知与新目标分离；等观测历史场景 | 原Hepta未决前驱/收敛接缝 |
| V205 | 按原因回退、恢复域不可被管理；暂停场景 | 实际timer/进程失效/恢复资源 |
| V206 | ClassScheduler公共gate、TSC换算与计费点 | 内核调度/真实误差界 |
| V207 | 有序sequence+连续退役；模型10,000写 | 常驻内核/持久owner确认 |
| V208 | 五操作Rust codec、独立golden/负例/编译变异已执行 | 真实效果路径的用户copy/权限/恢复接合 |
| V209 | 持久OperationIntent逐字段映射 | 真实owner调用/事务边界 |
| V210 | 提交前时效重验；局部观测限制 | 父域/等待原因与实际控制收益 |
| V211 | 内核初始时钟域，N0不支持活跃快照恢复 | 时钟/恢复失效实现 |
| V212 | 残留charge对象的范围 | 内存回收与共享压力量化 |
| V213 | shell/compositor/GPU分别承诺 | UI与客户端实际恢复 |
| V214 | Direct Boot/DE/CE/密钥列入后续 | AOSP product及真实解锁 |
| V215 | DMA所有CPU映射别名要求 | 实际驱动/设备验证 |
| V216 | 官方ISO下载失败保留历史；Rust源码构建与QEMU启动已有独立证据 | 完整构建输入、跨宿主复现与裸机资格 |
| V217 | 当前版本测试源码、固定样本与结果入库 | 从模型迁移到实际内核测试 |

14个模型断言通过不表示17个实现问题已经关闭。测试中的布尔观察授权是明确的模型前提，不是可用于生产的授权机制。
