# 一条历史 Agent 轨迹能适应哪些参数变化

冻结的历史示范能提供创建、写入、运行、结束四个动作，以及循环和整除条件。这个实验为数值输入增加了显式绑定。系统从唯一示范中对齐除数、下限和上限，识别 Python `range` 停止值相对原问题多 1；运行时将新请求的数值写入同一程序。英语提示词、语法支持和候选的一对一分派是工程设计。研究源为前一轮公开的 OpenHands 历史会话。[原研究](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7034)

## 冻结后冷评

七个候选在单独的 Linux 断网进程中收到相同请求。每题最多四个动作，各臂共有 132 题，七臂合计 924 份逐题回执。旧题是共享的单项输出 0 回退，七臂均为 1/1。拒绝项是预先设计的求和、计数、倒序等相邻需求。

| 方法 | 上轮改参 /12 | 显式 /24 | 调序 /24 | 隐含下限 /24 | 无关数字 /24 | 正确拒绝 /16 |
|---|---:|---:|---:|---:|---:|---:|
| 顺序回放原动作 | 0 | 0 | 0 | 0 | 0 | 16 |
| 依原位置代入 | 8 | 24 | 0 | 12 | 0 | 16 |
| 直接岭回归绑定 | 12 | 24 | 24 | 24 | 24 | 16 |
| 同模型梯度拟合 | 12 | 24 | 24 | 24 | 24 | 16 |
| 直接绑定，去掉语义提示 | 6 | 24 | 0 | 0 | 0 | 16 |
| 手写规则和手写程序 | 12 | 24 | 24 | 24 | 24 | 16 |
| 删除示范的轨迹候选 | 0 | 0 | 0 | 0 | 0 | 16 |

直接解在 96 道新题上比按位置替换多通过 60 道、比去掉语义提示多通过 72 道。与手写解相比，新增和丢失均为 0。预登记的受控参数迁移门槛通过，超越手写解的门槛未通过。前三个参数角色与模板高度匹配。这里的配对结果不能估计跨用户收益。[冻结前协议](./PROTOCOL.md) · [七臂成绩及配对](./result/scores.json)

直接解与梯度法拟合同一份 3 行、9 维输入和相同正则项。51 轮交错 CPU 计时中，直接解中位 24.947 微秒，梯度法 545.969 微秒，后者做 46 步，最终参数最大绝对差 3.95×10⁻¹⁰ 以下。两种方法解出的动作与受控质量相同。计时区间只覆盖已备好矩阵的拟合，源材料读入、角色对齐、三种拟合及模型写盘合计 9.44 毫秒。这一结果适用于小型线性绑定层。[逐次计时](./result/timing.json)

## 独立作者的历史问题

事先锁定 Stack Overflow 上两个关键词各自最早的 30 道 Python 问题，合计 60 个不同问题。阅过所有原始正文，保留每题 ID、原文摘要与排除理由。在盲评模型前锁定数值和验收条件。59 题涉及求和、多个除数、运行期变量或不同任务。一题要求从 99 起列举小于十亿的所有 99 的倍数，并写入指定文件。严格限定原有标准输出接口的匹配数为 0；数值列举的匹配数为 1。[来源筛选](./result/external/selection.json) · [原始提问](https://stackoverflow.com/questions/18205390/)

七臂首次均为 **0/1**。直接解、梯度法、按位置、去提示和去示范五臂弃权。回放和规则各自生成了错误范围。原执行器限制整数到 299，也没有写指定文件的接口。该题来自历史公共语料，未参与权重训练，两次读取的是同一批 ID，60 份正文摘要一致。[首次结果](./result/external/scores.json)

## 流式文件输出的事后修复

发现问题后，在保持角色权重不变的条件下，扩展了大整数区间、严格上限语义和只创建新文件的有界流式输出。直接绑定和手写规则都实际生成了 `Blank.txt`，分别独立逐行验证所有记录、换行、总长度和文件哈希。两个输出均为 **10,101,010 行，99,887,766 字节**，SHA-256 为 `0cd37251aafe355936f2865533daf43331bc84968337588b445b27896496927c`。新登记的 24 个文件任务两臂全部通过，包含空区间、边界重排和重复数值。每臂另做 3 个拒绝测试，既有文件内容保持完整。两条路径共实际生成并核验 50 个文件。[修复前登记](./STREAM_PROTOCOL.md) · [直接绑定原件](./result/stream-direct.json) · [规则原件](./result/stream-rule.json)

原问题已参与诊断。这次成功是工程修复验收，迁移、真实 B、生产采用和客户付款均按各自原始登记。生成器、全量原始动作、模型及验证程序均已提交。公开问题原文保留在原作者页面，重放脚本检查其正文哈希和实际送入模型的段落摘要。独立托管复跑还用 GNU seq 核对最终完整文件摘要。

## 重现

从此 PR 的仓库根目录执行。需要 Python 3.12、NumPy 和能创建新网络命名空间的 Linux。研究材料位于 qualification 下，并依赖前一研究的原始模型和有界语法解释器。公开源的读取发生在冷工作进程启动前。

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python qualification/trace-binding-controls-20261123/verify.py \
    qualification/historical-four-arm-transfer-20261123 --retain-known /tmp/hepta-verified-listing.txt
```

时间顺序可从提交核对：[预登记](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/72913b97180824ebd97183587d82346b30e72529) → [实现](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/9869533bc6cf4ac41b1d6087b1c3148d04e97309) → [拟合权重](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/55bbe16b59a80090fd7dff512b5d8a12536d4372) → [新题冻结](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/0ff890965ab01f15fee1da6ca9a93a672f29619d) → [七臂结果](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/0ee4f675603b4c71ad52823b221dd519e1f44a0a)。外部来源的[筛选协议](./PUBLIC_PROTOCOL.md)、[冻结标注](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/7b8e53338af301c050abf24ee8d1ee0bda8e7c93)、[首次冷评](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/e2488d57a7270a19d5ef27d31cc5141c6ccf21f2)、[修复实现](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/b0264a0643e19da04b1ce129d6f2b4a661187c68)与[新文件面板](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/1d836eef51be1d288c9ceeb1dd510a5103da9c2c)均另行保留。
