# E2 bounded runtime recovery: BLOCKED before encoding

本次交付完成了当前学生纠错代码、数据冻结、真实父模型恢复与执行前验证。**正式 CPU 编码和训练尚未开始**。原 3,600 秒运行环境恢复窗口已到期，官方依赖未形成完整、校验通过且可安装的闭包。此结果属于依赖获取与执行环境阻塞，不能解释为优化器、监督数据或模型能力失败。

## 冻结身份与实际完成内容

- Draft #6833: https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6833
- Published commit: `dc3397c9e09e29861a0a4fe2267e8ef19e55db01`。
- Candidate: `dc96ad0c29223dc0fbf0e6165854d8e7cf25331c3f77d57ad30c4f30fc6cf678`。
- Protocol SHA256: `6a8405ee33dc26dd365de5ea17907a756ae4afaa7ec860338a10eb2c43d65efc`。
- 已发布源代码在最终回读时保持原字节；未调整框架、tokenizer 身份、模块 hash gate 或训练参数。
- 从两个当前父学生各自的 A 失败状态装配 4 条纠错；保留 16 calls / 12 native / 4 admission refusals 原分母。只将已验证的最终修复标为正例，失败动作与反馈保留在 masked prefix。只有一个正确 assistant target，因此 `all_actions` 和 `final_only` 退化为同一目标，不能作为不同监督方案比较。
- 7 项离线测试真实通过；原命令、合并输出、exit0、1.068262737 秒外层 wall、0.970 秒 unittest wall 与源码 SHA 全部保留。它们验证真实 A 档案、序列化与拒绝条件，不等同于正式 tokenizer CPU 编码或 GPU 训练。未为补日志重跑测试。
- 原 `just fmt` 的实际结果是没有匹配需格式化文件，不能把它改称 Ruff 验证；其冻结回执位于已发布提交中。

## 运行环境恢复与计时

原窗口从 **2026-11-21 03:24:26.254009 UTC** 到 **04:24:26.254009 UTC**。所有官方源切换、ROG relay 和一次剩余范围续传共用此截止时间，没有重置窗口。

运行环境固定为 Python 3.12.3，torch 2.9.1+cu128、transformers 4.57.3、tokenizers 0.22.2、safetensors 0.7.0、peft 0.18.0。目标 Torch wheel 为 900,881,648 bytes，官方 SHA256 为 `7cb4018f4ce68b61fd3ef87dc1c4ca520731c7b5b200e360ad47b612d7844063`。官方 URL 和每个已验证依赖的 URL/SHA 均在原回执中。

初始 desktop 安装在 NVIDIA 分发上非常缓慢；原 SSH 调用在自身 3,500 秒上限失败，desktop 原 pip 仍存活。随后限定的 source switch、ROG 同一官方文件的 8 个不重叠范围下载、一次精确尾部续传和直接依赖预取均保留各自成本、输出和终态。未下载任何模型。

ROG 的 1 MiB 首包探针为 4.246/4.778 秒，desktop 对应为 63.186/41.438 秒；长下载没有维持该速度，不能据首包推算已恢复 runtime。首次 relay read timeout；依赖预取的 NCCL 322.3 MB 只收到约 5.8 MB 后超时，显式 0 retry。尾段续传到预算结束仍不完整。

截止时 watchdog 以确切 argv、PPID、start ticks 与 cmdline SHA 识别原 pip PID 1679780，并 SIGTERM 后确认 `still_running=false`。预算终态 JSON 的 elapsed 为 **3600.350175 秒**，fsync 后 stdout 采样为 **3600.552161 秒**。ROG socket 清理尾部至 **04:24:41.857 UTC** 才由持久 supervisor 确认 cancelled/exit -15，即从原开始算 **3615.602991 秒**。这额外约 15.603 秒必须作为清理成本披露，不能隐去或称严格在 3,600 秒内已停止所有 socket。尾段应用未自行写完 BLOCKED JSON；其权威终态是保留的持久 job exit。

只读证据收集另外耗时 19.573239 秒。复制、探针、下载等区间存在重叠，不应将其嵌套 wall time 相加成新的端到端训练时间。

## 保留材料与模型不变性

完整复制了原有 base 的 9 个文件、3,098,972,269 bytes，以及两父 adapter 各 3 个文件、2,200,035 bytes，复制和 SHA 验证耗时 18.179432 秒。收尾再次计算原始及保留副本全部 base 共 18 项、adapter 共 12 项 SHA，全部与冻结身份一致。

官方完整 SHA 已核对的不同 wheel 材料共 **10 份**：desktop 原件 9 份，ROG 上追加的 cusparselt 1 份。已传到 ROG 的那 9 份副本没有在本次末尾再次完整 hash，因此不把这项搬运称为该主机全部重新验证。完整依赖闭包仍不存在。

ROG 保留首次 Torch 范围 364,923,806 bytes，加上一次尾段 353,127,326 bytes；desktop 保留 13 份完整或部分 wheel 的硬链接，其中 Torch 的 167,587,840 bytes 前缀与 ROG 有重叠，不能简单相加为独立完成量。部分字节不构成整轮 SHA 成功。大 wheel、模型权重不包含在本证据包；其位置、大小、预期身份与资格边界均保留。

最终现场证据为：`ENCODING.json` 不存在，fit `CLAIM-*` 为空，新训练 artifact 目录不存在，本次 desktop runtime 活进程清单为空；14 个相关持久恢复 job 均有终态，另只读收集器也成功结束。

## 科学执行状态与后续边界

| 项目 | 本轮真实数量 |
|---|---:|
| 正式 CPU 编码运行 | 0 |
| 模型生成调用 | 0 |
| Native task 执行 | 0 |
| Optimizer update started/completed | 0 / 0 |
| 新模型下载 | 0 |
| 已冻结科学更新 cap | 每父 8，总计 16 |

16 次科学更新没有消耗，也没有生成 child 权重或性能结果。这不构成自动重试或扩展窗口的授权；后续恢复/编码/训练须在明确审核的执行 scope 下推进，并保留本轮失败与所有成本。旧 #6778 的 32+32 updates、56 calls 和已经曝光的 4 个 future 都未重开。

## 证据布局

`RESULT.json` 提供机器可读结论；`EVIDENCE_MANIFEST.json` 为每一成员提供字节数和 SHA256。压缩档 `EVIDENCE.tar.gz` 包含：

- `local/validation/`：7 项原离线测试日志和 source hashes。
- `local/published-source/`、`local/published-prepared/`：已发布代码与冻结纠错数据；早期候选保留在独立目录。
- `remote/desktop/`：部署、复制、官方依赖身份、partial 留存、停流身份和 budget terminal，以及最终模型/源代码回读。
- `remote/rog/`：官方探针、Range/续传/依赖预取的原协议、精确 launch 脚本、输出与失败。
- `remote/jobs/`：14 个持久 job 的原 request/start/exit/stdout/stderr。`COLLECTOR_TERMINAL.json` 补充只读收集器终态。

本包没有删除或覆盖失败，没有合成实验结果，也没有将环境恢复失败重新命名为训练失败。
