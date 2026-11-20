### 1a979 的实际源码资格与 NoUpdate13 终态

**C 同步 drain 的四路径修复已成为实际冻结源，但本轮整父在更早的启动阶段失败，尚未运行到新 drain。** 源为 `1a9799686243c2be0ee393ba364e091029cfb944`，tree `931a344b1ea3e2ddf45e917ea4b3ae37c504ed05`，直接 parent `dbd6a00992b60f4b33e8f10c2defda031d123bcb`。源码对象、隔离 HEAD、实际验证和远端分支分别记账；本稿引用的既有 PR/ref 快照没有据此改变。[提交 API][e6-1a979-commit]、[Root 精确提交身份][e6-1a979-identity]、[四路径原 diff][e6-1a979-source-diff]

| 1a979 实际准备阶段 | 原件结果与范围 |
| --- | --- |
| format / compile-list / justfix | **PASS**；format 0.315087 秒，compile 105.773789 秒，justfix 108.922167 秒，整个 owner 218.966524 秒；format / lint 零 delta。当时原 dbd6 ELF 已留存；后续可用性变化在下文另记 |
| 完整源码门 | **53 模块 / 468 项 PASS**，零 failure / error / skip；908 protected records、452 targeted boundaries、完整 1,164-boundary CLI 通过。targeted 166.798642 秒、完整 CLI 473.368007 秒、源码门 owner 705.807639 秒 |
| 库存与源码绑定 | 15,812 文件；实际源码 inventory `1c7782e85a9b79fad6e82c0c5022964299451629d2cb96e55b442f96f0059a7a` 在 compile / lint / sourcegate 前后相符 |
| 原七项 blob 控制与完整 PR source gate | **PASS**；完整 `d83f70f38137a99a86a3afd122199ba9cdae4f79 → 1a979` **156 changed paths**，仍为 512,000 B 原门。七项命令 0.606657 秒，完整门 0.465392 秒，freeze owner 1.886092 秒 |

源码门 RESULT SHA 为 `a3de42e2ec9b4641e31b11eb233a191c678f5ec3d70961bf74cb464b6f1ab6d5`，freeze RESULT 为 `e20af37a9efbfde49e79b4cf1c3084465924fac62f15e23a32f6126c5e1b8763`；均有 Root 独立实际读回。这里复述已执行结果，没有重跑这些门，也没有把 source gate 当作业务通过。[实际编译原件][e6-next-c-compile]、[Root 编译读回][e6-1a979-compile-root]、[源码门 RESULT][e6-1a979-gate]、[Root 源码门读回][e6-1a979-gate-root]、[freeze RESULT][e6-1a979-freeze]、[Root freeze 读回][e6-1a979-freeze-root]

| 1a979 实际 native 范围 | 结果 | 资格边界 |
| --- | --- | --- |
| observation framing | **18 PASS** | 独立协议组件 |
| 原 native11 / retirement16 / delivery5 / Feature ACK2 | **34 PASS** | 原组件控制 |
| Ready-slot2 / completed reader8 + wire3 | **13 PASS** | 与上一行合计原 47 组件；不等于完整接受 |
| 两项 UID0 Root 组件 | **各 1 PASS** | 原 bounded-identity 与 namespace 控制 |
| 原 Root lane 机制父 | **1 PASS** | 机制范围，不是完整学习 ACK 或普通 C |
| 真正 ordinary NoUpdate13 父 | **1 FAIL / 0 error / 0 skip** | 原父报告 `original Q24 publication binding: successor is closed`；没有提升整体资格 |

唯一 native owner 为 `dpty-d86e7367d2132a3a4e1af2c2b212f69d2d655e3d6c7354098733a26b554e07f6`，实际终态 exit 1 / output complete。流水线 RESULT 为 `03b082e8af426d8a73dc8d804038448e9ff62966c6f88da07d5ced92209cb1d7`，owner **273.337733 秒**；wrapper RESULT 为 `186818661a00b7af839d167f70292eb910344b9d106d702561d3d821e30658ab`，owner **131.411846 秒**；原父命令 **66.627302 秒**，JUnit suite **65.905 秒**、case **65.898 秒**。这些窗口互有包含，不能相加为独立成本。source、tracked bytes、compiler inputs、原二进制字节保持和 mount cleanup 均为 true；它们不改变业务 FAIL。[owner 启动][e6-1a979-native-start]、[流水线终态][e6-1a979-pipeline]、[wrapper 原件][e6-1a979-wrapper]、[原父 execution][e6-1a979-parent-execution]、[原父 JUnit][e6-1a979-parent-xml]、[Root 实际终态读回][e6-1a979-native-root]

### NoUpdate13 的 lane_busy：精确归属与尚未执行的 startup 候选

原 JUnit 保留的 B daemon stderr 记录到 request 32。结合精确 1a979 调用链，request 30 / 31 属于 delivery 的原 claim；随后 **request 32 属于 continuation 在等待 Decision 前执行的 `require_current_historical_source`**。这条直接 source 检查没有取得 Q24 aggregate semaphore。另一条 delivery 已经 Submit，runtime 调度的 **Restore** 取得 aggregate permit 后，在其 Prepared 操作的前观察上竞争同一个私有 Historical client，记录 `historical_client.lane_busy`，继而 fence 该 client。原 request 32 的持有者返回时记录 `fenced_after_exchange`，后继出现 original-result 错误和 `successor is closed`。[精确调用链审查][e6-1a979-lane-review]、[审查源码 pins][e6-1a979-lane-pins]、[从原 XML 派生的 B stderr][e6-1a979-derived-b-stderr]、[原 JUnit][e6-1a979-parent-xml]

这里不是仅凭 `Unavailable` 猜测，也不是把 `original training material` 错误包装当作 C 的 `actual_model` 已执行。`try_lock` 的单独 `lane_busy` 标签也可能涵盖 poison；本次定位还依赖 request 32 已进入交换、Restore 的确切调用标签、共享 receipt 的 `Arc` 身份及随后原持有者的 `fenced_after_exchange`。原 `tokio::join!` 让 delivery 与 continuation 各自等 readiness，二者没有固定先后；aggregate 的 permit 没有覆盖 continuation 的直接 source 路径。[Historical client 原实现][e6-1a979-client-source]、[continuation 原实现][e6-1a979-continuation-source]、[delivery / startup 原实现][e6-1a979-historical-source]、[Restore 原 owner][e6-1a979-stage-source]

**本次尚未到 Evaluation、真实新 C 或新增同步 drain，不能评价 C-drain 修复成败。** NoUpdate12 的两步 Training、独立 B NoUpdate、首次 acceptance / ACK 只属于 dbd6 的既有物证，不转给本轮 1a979。原 NoUpdate13 request 1…32 也不是 Adopt 超出 64 的证据，更不是 32 次成功接受。[实际失败范围读回][e6-1a979-actual-readout]、[原父完整日志][e6-1a979-parent-log]

**15:51:50 UTC 的后续复现环境观察另记。** 对 16 个固定路径的实际只读 `lstat` 终态 exit 0：原 `native-target`、其中的实际 1a979 ELF、另存的 dbd6 ELF 在该次观察均为 ENOENT；BASE、source、两份 BASE owner 锁和 NoUpdate13 result 仍在。此前拟提取 12 份 child log 的 capture 在检查第三份 target 锁时已因 ENOENT 退出，尚未读取任何日志。本稿的相应 B stderr 是由原 JUnit 派生的文本，不能冒称这次已经回收了完整 12 份原 child log。[实际 16 路径 lstat][e6-1a979-target-lstat]、[lstat 原终态][e6-1a979-target-lstat-terminal]、[child capture 原失败][e6-1a979-child-capture-terminal]

这项观察不确定谁使路径消失，也不把目录 mtime 当成删除时间。它不抹去此前 compile / gate / native 的原始执行事实，但增加了当前复现环境缺件的限制：不能直接凭旧 ELF 资格继续执行。独立 target 恢复和新的只读日志提取还须另有实际结果；本报告没有执行恢复或重跑。

后继 startup 候选目前只有本云两份产品源码草稿：拟先由同一个 continuation owner 完成其原有 readiness / admission / 完整 source preflight，成功后才进入旧 joined delivery 与 Decision 等待。它不把 preflight 变成后续 effect 的持续授权；原后续 Source / Current / trust / expiry、原 try-lock / fence、原 64 上限与时限都必须保持。此稿固定的 PRODUCT_MANIFEST 明确 format、compile、sourcegate、native、model、host actions 均为 **0**。Root 与独立 peer 随后只完成静态审查，未发现该产品草稿的新增阻断；精确 CALLERS / protection / QA 接线及实际 compile、lint、sourcegate、native 仍待执行，没有新的执行通过结论。[startup 草稿原清单][e6-startup-cloud-manifest]、[startup 草稿 diff][e6-startup-cloud-diff]、[Root 静态产品复核][e6-startup-root-static-review]、[独立静态 peer][e6-startup-peer-static-review]

**截至本稿，最新实际完整普通父为 1a979 NoUpdate13 FAIL。** bfea NoUpdate9 的 ENOENT、527e namespace 控制失败 / 父 0、9df NoUpdate11 的 Root 退出失败、dbd6 NoUpdate12 的 C drain 失败均继续保留。尚无 native Adopt、cold D 或完整 FinalUse / settlement 资格。
