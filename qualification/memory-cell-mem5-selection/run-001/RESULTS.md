# MEM-5：冻结候选选择器的前瞻性开发验证

固定候选记忆、模型与控制条件后，public rule 的实际完整任务成功数为 **20/54**，frozen neural 为 **11/54**，配对差 **+9/54（+16.67 个百分点）**。54 对全部有终局结果：9 赢、45 平、0 输。该有限样本支持继续使用强确定性选择基线；神经关联的独特收益仍未成立。科学结论保持 **HOLD / NoUpdate**，不采用生产更新。

## 冻结与执行身份

- 源码：`5fa0d0e462cd1393f4f9e95565ff5993e9bad29a`，树 `7b3431e21f604ea5381592c2509db4f26ea91f7d`。
- 一次运行、108 episodes、54 case pairs、14 source groups；每臂54条。10个 development 来源各覆盖五类任务，另4个 retention-validation 来源各覆盖图文互补任务。
- 全部54 case 与执行前 metadata-selected roster 一致；来源、角色、episode、配对、公开包、权重及模型/控制身份检查通过。原训练、调参、隔离与原 MEM 任务来源排除继续保留；仅相对于这些固定记录声明来源分离。
- 两臂均使用 bounded memory（128条、524,288字节）、同一冻结 checkpoint、encoder、OCR、60秒目标和固定动作空间/控制日程；无训练、无按结果重试或调参，至多两个 worker。
- 每次处理观察同时记录两个选择器对同一 ordered roster 和原126维 features 的选择。实际 ROI 轨迹可以不同；shadow 选择不计作反事实交付，也不合并为独立训练重复。
- 所有108个 actor episode 均为 `Completed`；报告原件将108行标为 `VERIFIED`。这表示协议执行和证据检查完成，任务成功仍按完整 rubric 单独计数。

## 完整任务终局及来源

| 任务族 | 配对数 | Frozen neural 成功 | Public rule 成功 | 配对净增 |
| --- | ---: | ---: | ---: | ---: |
| 文本足够 | 10 | 1 | 7 | +6 |
| 图文互补（含4个 retention-validation） | 14 | 0 | 2 | +2 |
| 选择性修正 | 10 | 0 | 1 | +1 |
| 先准备后获益 | 10 | 0 | 0 | 0 |
| 及时停止 | 10 | 10 | 10 | 0 |
| 合计 | 54 | 11 | 20 | +9 |

九个增量分布于九个不同 source groups，各+1；其余五个来源无差异。development 为11/50→18/50，retention-validation 为0/4→2/4。这里仅报告固定样本描述；未估计 sampling uncertainty、未给出预注册之外的 p 值，来源内相关性保留。

两臂各有10个初始完整交付已正确的 no-op success。候选介导的正确 `WRITE_TEXT` 完整交付为1→9，bypass success 为0→1。唯一 bypass 是 `case-18a870e024270af28fa0dd1f`：公包已提交正确文本，但初始缺少必需图片；两臂均执行 PREPARE_ROI→READ_ROI→RENDER_IMAGE→STOP，没有 WRITE_TEXT。public rule 保留文本并交付通过图片检查的 ROI；neural 的既有评分报告图片目标覆盖0且不通过。该+1归于图片补交，不能记成候选文本写入收益。十份相关原件已按 EVIDENCE 中的 bytes/SHA 核对；详见 `bypass-explanation.json`。

## 候选链与缺失界

锚点为最后一次 WRITE_TEXT；若无写入，则取最后实际 actor 决策。每臂34个锚点有已处理候选支持，另20个是未处理 STOP（10个及时停止、10个选择性修正），其候选存在与选择均保留 UNKNOWN，未回填早先候选。

下表为所有54个计划任务上的保守 missing-label bounds，**不是置信区间**。条件未知的20条仍计入界，不能把3/27或19/27直接写成完整样本点估计。

| 指标 | Frozen neural 原始计数 | Public rule 原始计数 | Frozen neural 界 | Public rule 界 |
| --- | --- | --- | --- | --- |
| 正确候选存在 P(C) | 27真、7假、20未知 | 27真、7假、20未知 | [27/54,47/54] = [50.00%,87.04%] | [50.00%,87.04%] |
| 选对 P(S\|C) | 已知C的27条中3选对；另20条C未知 | 已知C的27条中19选对；另20条C未知 | [3/47,23/47] = [6.38%,48.94%] | [19/47,39/47] = [40.43%,82.98%] |
| 候选介导正确交付 P(D\|S) | 已知选对3条中1交付；另20条S未知 | 已知选对19条中9交付；另20条S未知 | [1/23,21/23] = [4.35%,91.30%] | [9/39,29/39] = [23.08%,74.36%] |

在 frozen-neural 实际轨迹的34个已观察支持上，两种 shadow 分别选对3与19条，转换为17个 neural错/rule对、1个 neural对/rule错；在 public-rule 实际轨迹上为18与2，仍各选对3与19条。各层另20条 shadow 未知。它们分别按实际模式报告，不假定两条完整轨迹共享支持。

## 成本及复核范围

整个 run receipt 记录 wall **116.940129 s**、CPU **213.894158 s**。这些是包含并发 episode、校验和评分工作的重叠进程 envelope，不能再与子层计量相加；`energy_joules=null`，`provider_charges=null`，未获得完整物理/生命周期成本。

独立本地算术与 metadata 审计通过3,235项检查、零差异，覆盖完整分母、条件缺失界、来源/模型/角色/配对绑定及逐来源/任务族分解。它以固定 report rows 为输入，**没有独立重演全部原始 sidecar、重新评分 reference 或复验交付像素**。完整 raw 档案保全/出版仍在进行；核心原件及 bypass 有限原件已有字节身份。

| 原件 | 字节数 | SHA-256 |
| --- | ---: | --- |
| REQUEST.json | 16,563 | `cdedbb2f6703be222db1996f6ac76d89e7c6d539dcbb479486f91261d0e875ce` |
| PLAN.json | 215,053 | `e33050d4b01484f8b820730117ed57659476e9e1e922ffdd43673dee7a081f9d` |
| EVIDENCE.json | 419,866 | `68709587e9e66f5fc3cd525b0ab6be089727468d1edd4336ed1e53489ba30c9f` |
| REPORT.json | 197,879 | `8445b7c7644a518999d477da70ca4e12fe5a6ab625db709c4ef8c206cc7a62f7` |
| RUN_RECEIPT.json | 50,921 | `415074ef2b2a7b9500013b7a5f2c55f49c1f77d66f9c9f06f72ebdc33b8de840` |

PLAN 中 canonical request digest 为 `80725130ca2af9fed8fe7c8ee6e1b334a235f8034bdafc735b9e3e78d5026da5`，与上表 pretty-printed REQUEST 原始文件摘要的字节范围不同。

## 保留的验收门槛

本报告为 prospective development validation；sealed confirmation/retention-test 未获准、未执行。原件保持 HOLD、`production_adoption=false`，模型权重执行前后相同。

截至本报告的最后读回，#5643 新 head 的67项 exact-source CI 仍 queued；父 #5631 的52项通过不能移作该 head 的通过证据。required CI 和完整 raw 档案关闭仍需各自证据。跨截图/文档/任务的版本、撤销与有效期记忆，神经关联在干扰/组合任务上的增量，真实独立 provider/完整 exposure 认证、完整 owner 冷恢复、sealed 独立确认和全成本资格均继续开放。先前 replay 结果不由本选择器实验改写，当前保留 uniform。

## 本次出版与复算

`INDEX.json` 绑定两个小于512,000字节的资产。core ZIP 保留15份运行/环境原件及其 member manifest；audit tar.xz 保留29份算术复核、来源分解、冻结输入和 bypass 原件。它们未包含全部4,000份运行输出，也未复制原始 reference 数据集。后续 raw 档案独立出版，不改写本次运行。

在同一新目录下载这些文件及前一阶段的 [final-source-capsule.zip](../execution-preflight/final-source-capsule.zip)，核对资产哈希后，可仅用标准库复算算术审计，不触发 actor、训练或 reference scorer。源码包用于实际输入字节校验，不能省略：

```sh
mkdir run-result published-final
python -m zipfile -e audit-core-5fa0d0e.zip run-result
python -m zipfile -e final-source-capsule.zip published-final
tar -xJf audit-records.tar.xz
python audit-run-result.py --root run-result --output reproduced-audit.json
```

路径字段将反映复算机器的位置；输入字节摘要、3,235项比较及计数应保持一致。`BLOCKERS.json` 区分已验证的执行/选择器增量与仍未成立的记忆本身增量和生产资格。
