# 2026-11-06：真实 V13 来源重放验收

## 身份和结论

实现基线为 #4930 的 `dd1adf3defc5f1b1bcf3358419e23490e24b9a6a`。
本地是 **16 个精确 Git blob 的组件/formatter projection**，不是整个仓库 clone。
执行资格绑定 [`source-before.json`](evidence/20261106-cpu/real-campaign/source-before.json)
中的逐文件 SHA-256；相同 `source-after.json` 证明本次执行期间这些字节未改变。
这里不声明完整仓库或后续远端 commit 的原生资格。

真实材料来自固定 #4532 的 `aeedeee98a5f7472f11b88ef7b869fc5a6d3d8e1`：原
`sources.sqlite`、frontier-0 checkpoint/release、原始 120 行训练数据和原 feature NPZ。
[`MATERIALS_MANIFEST.json`](evidence/20261106-cpu/MATERIALS_MANIFEST.json) 记录原 Git
路径/blob/SHA-256/长度。source snapshot 从该只读 SQLite 中按原 release cut 的精确
scope/source ID/revision 导出；没有伪造 source body 或修改原数据库。

MiniLM 八文件按原 `download_model.py` 的正式 URL/revision/pins 获取，随后再次验证。
实际 NumPy/ONNX Runtime/tokenizers 为 `2.3.5`/`1.23.2`/`0.21.4`。
所有结果继续 `DENY_ALL`。

## 实际结果

| 验收 | 实际观察 | 资格边界 |
| --- | --- | --- |
| Python 行为控制 | 25 run / 25 passed / 0 failed / 0 skipped | 11 原内容控制、5 fd 控制、9 feature/controller 控制 |
| 固定真实原始材料 | 120 × 384 float32，4 个真实 ONNX batches | 每个完整原 dataset 的 C-order float32 bytes 与原 NPZ 完全一致 |
| 原纯计算参考 | 1 次原 Adapter.predict，120 次原 tasks.execute，保留 120 个输出，0 执行异常 | 不等于独立质量 120/120；没有使用 held-out 质量门 |
| 完整参数状态 | before/after 均为 `8a03519dff1585b1b49c808371c7e143dac2f91e5cd6a2bef5da5fdceb9f0654` | 冻结推理状态不变；不声明 recurrent Cell 状态更新 |
| 原材料变异 campaign | 11/11 预声明控制符合预期 | 1 正例 VERIFIED、8 内容漂移 REJECTED、2 不可用/资源控制 HOLD |
| 独立新进程冷回执 | exit 0，完整 retained receipt 相等 | computation import / model read / external operation / write 尝试均为 0；不是下一任务采用 |

最终实现的真实正例观察为 wall **2.471801056 s**、父子总 CPU **2.444958170 s**，child
峰值 RSS **215,437,312 bytes**。此成本包括该调用的材料冻结、检查、模型加载、编码、
分类、纯 executor 和 child 退出；模型获取和调用方保存结果另计。

11 次执行尝试全部保留，合计 wall **10.348413257 s**、父子总 CPU **10.434924410 s**。
没有从分母中删除 REJECTED/HOLD、CPU 信号退出或其已耗成本；能耗未知，保持 `null`。
这些不是强硬件比较、最优矿工优势或 Chain 出块延迟的证明。

## 具体拒绝控制

[`SUMMARY.json`](evidence/20261106-cpu/real-campaign/SUMMARY.json) 和每案 JSON 保留完整
状态、进程退出、stdout/stderr 捕获状态、实际成本和已观察执行进度：

- source body 改动而原 cut/hash 不变：REJECTED。
- 原始 text 改动、同类别两行顺序交换：REJECTED。
- 聚合训练 NPZ 单个 float32 特征变化、source feature archive 变化：REJECTED。
- tokenizer 字节变化、max-length/mask profile 变化：REJECTED。
- 训练 checkpoint 参数变化但原 release 身份不变：REJECTED。
- 缺真实 encoder：HOLD，未执行任何 encoder/adapter/executor；没有 synthetic fallback。
- 将原执行的 CPU 配置收紧至 1 秒：worker exit **-9**、HOLD，wait4 实测 child CPU
  **1.047516 s**。保留内核计时/调度粒度产生的全部已耗成本，没有把它截断写成 1 秒。

另有真实 OS child 生命周期夹具，实际启动 Python 子进程并验证 wall/output 超限、父
KeyboardInterrupt 和 wait4 异常的 kill/reap。其 sleep/write command 是明确夹具，
不是另一次 MiniLM 模型成功。catchable interrupt 原样传播；不可捕获父死亡/宿主故障
没有被宣称闭合。

## 原始记录与格式门

- [汇总机器记录](evidence/20261106-cpu/RESULT.json)
- [25 项完整测试日志](evidence/20261106-cpu/stage2-tests.stderr.log)
- [真实 campaign 原始 stdout](evidence/20261106-cpu/real-campaign.stdout.log)
- [真实正例完整结果](evidence/20261106-cpu/real-campaign/original.json)
- [新进程冷读回完整结果](evidence/20261106-cpu/real-campaign/cold-readback.stdout.json)
- [逐文件证据库存](evidence/20261106-cpu/INVENTORY.json)
- [格式范围](evidence/20261106-cpu/formatter-scope.json)

初始 stage1 的 16 tests / 1 error 保留在 `stage1-tests.stderr.log`。错误是新测试错误地
期待路径替换后的成功；实现已经因 ctime 变化拒绝。修正测试为“只读到原 fd 字节且最终
拒绝”，没有放宽实现。随后全部 25 项实际通过。

原仓库 `just fmt` 在真实非空组件 diff 上 exit 0，但原 formatter **不覆盖 qualification
Python**，其零 formatter-group 输出没有被当作 Python 格式资格。11 个 Python 文件由
真实 Ruff `0.15.13` format/check 验证，全部通过；原 `.py.source` 字节未修改。

## 仍为 HOLD 的工作

普通 Hepta Cell/Agentd 路径、Joint 生成模型、跨 manifest 更新、live SourceOwner
frontier/发布采用、独立 held-out 质量门、冷恢复后下一任务使用新版本、Windows 原生，
以及 Chain 的完整 W1 证明和原资源服务门均未由本次结果闭合。冷回执只是读取旧事实，
不能把它改名为下一次模型采用，也不能隐藏 `incumbent/no-update`。
