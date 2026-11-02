# V11：真实 Linux cgroup 收费计量验证结果

已完成固定源码上的真实 GitHub runner 执行、下载与原始回执核验。
源码 PR #4593；最终源码 head `4283ce4e1eced302c5b22d0dcffcc07949ef10ea`。
有效 run **41371357603 / attempt 1**，事件为 pull_request。

**限定的无 swap、可信 fork/exec 夹具计量验证通过；完整进程族 RSS、设备能量及实际模型部署经济性仍未验收。**

| 真实场景 | 内存收费峰（字节） | 组 CPU（秒） | 业务成功 | 删除与排空验证 |
| --- | ---: | ---: | --- | --- |
| waited | 115777536 | 0.309269 | true | true |
| adopted | 81457152 | 0.303161 | true | true |
| nonzero | 5939200 | 0.050756 | false | true |
| timeout | 9408512 | 0.073025 | false | true |

正常及收养场景均实际产生 root/child/grandchild/短命 leaf，后者在 root 退出后实际执行。
新自有空 parent 明确开启 cpu/memory、设置并读回 memory.swap.max=0；
fixture 触碰的 48 MiB 私有分配下界获得内核计数支持。非零退出和超时是预定负例，
业务必须失败，但计量有效与清理成功必须成立；没有将这些负例改写成业务成功。
CI 端独立标准库审核 **122/122**，根下载后核对 ZIP digest、8/8 源快照、
Git blob、实际 parent profile、四组计量/退出/排空回执，通过。

最终四个不重叠 payload 组 CPU 共 **0.736211 秒**，不包含 checkout、排队、
父计量器、pre-join 启动或 GitHub runner 其他工作。取消尝试及完整 CI CPU 未知，
不填零。内存收费峰不等于 RSS/PSS 或物理唯一页，也没有测实际 AV 模型峰值。

## 归档问题与原始尝试

首有效 run **41370810857** 的四场景及 122 项审核也通过，但其 ZIP 缺少
以点开头的 workflow 源快照。根完整下载核验实际报 FileNotFoundError；
该原 ZIP、原记录、日志和 gap review 完整保留，未回填文件或重写旧 ZIP。
仅将受控 evidence 目录的 upload-artifact 设置 include-hidden-files:true 后，
在新固定源码 head 重跑。最终 ZIP 包含全部八个快照，包括隐藏 workflow。

两次更早的同 head push 运行被 PR 并发规则取消。全部 run observations 保留；
取消不计作业务实验失败，也不虚构零费用。

- 第一份原 ZIP SHA256：`0ddf77a04a2c41cc25ae75464dca1aab16fae43f370d1af0af4f6bbe07df3ee4`。
- 完整原 ZIP SHA256：`b623390d228a3724d99beafe4f8ab39f9fa881e9ffe87347adcee82dd1d20917`。

## 与科学准入的关系

本结果关闭“该 cgroup 计量器从未完成真实内核成功路径”的限定验证缺口。
它没有关闭 V10 前端质量、原 v6/历史排除账本/新独立录制、稳定解析核心增益、
完整金融神经网络训练、实际模型全成本、完整族 RSS 或可归因设备焦耳门。
`all_blockers_closed=false`，`production_activation=false`。

结果单独放在 evidence 分支，源码分支保持固定，避免保存回执再次触发源码 CI。
