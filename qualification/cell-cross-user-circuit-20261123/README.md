# 两个 Cell 的冻结、双冷启动与去边对照

本次用自建的一层 GPT-2 复核了带路由器的候选能否直接取代单模型，走相同的冻结与前瞻评测接口。发送 Cell 的低秩适配器经历一次真实 SGD 更新。模型在训练输入 `train` 上原先生成 `0`，纠正目标为 `1`，保存后的适配器重新加载生成 `1`。`train` 与模拟后续输入 `later` 在夹具中人为共享一个特征。本次训练数据、模拟后续题与旧能力题均为开发夹具。

评测侧先核对两臂绑定的所有模型文件、路由系数、拓扑、分词器、预算与执行器版本，再冻结模型和旧任务。随后用冻结摘要组装仅供评测的后续记录。两个新的 OS 进程各自从磁盘加载冻结图、路由器和两个实际生成模型，先答 `later`，再答 `keep`。每个节点保留实际传给模型的 token ID 和实际输出 token。两臂完成后，父进程用冻结的分词器重新编码消息、复核节点间传递的内容、路由得分和计分器的结果。未来输入若与任一已冻结路由器拟合时见过的输入 token 完全相同，评测在生成前结束。

| 等调用预算的对照 | 后续题 `later` | 旧题 `keep` | 每题调用 | 每题累计输入 / 输出 token |
| --- | --- | --- | ---: | ---: |
| 冻结父 Circuit，学习路由 | 失败 | 通过 | 2 | 6 / 2 |
| 候选 Circuit，学习路由 | 通过 | 通过 | 2 | 6 / 2 |
| 同一候选，始终采用固定连通图 | 通过 | 通过 | 2 | 6 / 2 |
| 同一候选，移除答案传递边 | 失败 | 通过 | 2 | 2 / 2 |

在这个夹具上，发送 Cell 的更新和答案传递共同使 `later` 的结果发生变化。学习路由与固定连通图在两题的通过数之差为 0。接收上游内容增加了 4 个输入 token。两臂的断网复跑均只有回环接口，收发计数始终为 0。真实用户、独立业务确认和生产采用数均为 0。本实验只覆盖固定的两节点图。

## 原件与复跑

- `SOURCE_UPDATE.json` 保存前后参数摘要、实际损失和训练目标。`PARENT_CONTROLS.json` 和 `CANDIDATE_CONTROLS.json` 保存固定拓扑实验及其逐题原件位置。
- `PAIRED_RESULT.json` 和 `NETWORK.json` 分别来自第二遍双冷执行和该次 Linux 网络命名空间的原始读回。
- `CIRCUIT_FIXTURE.zip` 含两个路由拟合搜索、实际基座与两个适配器、逐节点生成、两次完整配对输出等 72 个文件。压缩包 SHA-256 为 `9ca95174be3f7e24e55164cfc41df15c26a6d17f91357af8ae6d37f986d29aa6`。候选 bundle 为 `32ee053d020918d0a694c8b9a3a3bcaec3dfd93eed5bb7f98e0b33e46352dac4`，配对请求为 `7d60577d12d49a10a6896cdef6c9762f7dd40e8d831cdeaf0597c3d626d50276`。

在仓库的固定 CPU 测试环境中，从项目根目录运行下列命令可重载归档内的原始权重和路由。在单独的新目录中从头训练及拟合可运行 `PYTHONPATH=scripts python -m cell_experiments.test_paired_circuit --fixture NEW_FIXTURE`。

```sh
unzip qualification/cell-cross-user-circuit-20261123/CIRCUIT_FIXTURE.zip -d NEW_EXTRACT
PYTHONPATH=scripts python qualification/cell-cross-user-milestone-20261123/replay_offline.py \
  NEW_EVALUATION --fixture NEW_EXTRACT/fixture
```
