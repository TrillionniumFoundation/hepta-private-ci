# V12：冻结 AV 模型的无 Torch 实际执行包

本轮把 v10 的 **16 个冻结 FP64 模型**导出为纯 NumPy 参数，并实际执行 GRU、SSM、MLP 和有限路径过滤器。每次运行从历史因果事件特征包发起实际 READ，构造当前已接受缓存，重新计算共同内容头、未来正确率读出与调度决策。没有重新训练；所用输入仍是已经暴露的历史低分辨率 AV 特征，不是原始媒体解码或新独立录制。

## 保留的模型与执行语义

GRU 明确按 PyTorch 的 `r/z/n` 门顺序计算，候选态中的 reset 只作用于 hidden 分支，再以 update 门合成新 hidden。SSM 保留实际源时间增量、softplus 的原阈值 20、观察 gain 与 drive。MLP 继续消费完整六槽公开历史；过滤器保留全部有限隐状态路径及晚到源时刻条件化，并同时支持矩阵指数与同律 uniformization-HMM。

原共同缓存、前缀数据服务、内容头特征提取、READ/WAIT/STOP 调度和计费实现继续复用冻结源码。输入、原 `.pt`、导出 NPZ、历史头、calibrator、拟合律和依赖源码分别固定身份。运行入口 `numpy_runtime.py` 的依赖仅为 **NumPy 2.3.5、SciPy 1.17.0**；Torch 只用于独立的本机导出与参照检查。

准备前声明数值门为 `rtol=1e-10, atol=1e-12`。实际类别、动作／计划、请求数和费用必须精确相同，不能放宽近临界动作。对于同机 Torch／NumPy，共同头完整输出与序列化 SHA 还要求完全相同；跨主机概率末位使用同一冻结数值门，真实序列化 SHA 按实际输出字节核验。

## 实际验证

`validation001/` 对全部 16 个冻结模型和两个策略执行 **720 次 fresh Torch／NumPy 双轨 episode**，含过滤器同律两种传播。每次实际读出都比较 logit，每次状态更新都比较 hidden，另逐完整轨迹比较 hidden／路径分布及实际动作和费用。

| 实际检查 | 次数 | 最大绝对差 |
| --- | ---: | ---: |
| 每次实际 hidden 前向 | 3,350 | 4.44089e-16 |
| 完整轨迹 hidden | 3,346 | 4.99600e-16 |
| 完整轨迹路径数组（普通模型为空） | 3,346 | 0 |
| 每次实际 logit 前向 | 3,640 | 8.88178e-16 |
| 全部实际候选概率／score／increment | 3,640 | 2.22045e-16 |

所有本机实际动作、共同头输出、请求数、费用和输出 SHA 完全一致。四个真实 GRU 参数实例的 reset／update 交换负对照均被拒绝，差值为 0.033848–0.134375。上述结果支持登记输入上的推理端口，不作全输入域、训练反向传播或生产采用证明。

`local001/` 又使用**确实没有 Torch 包**的主解释器启动 20 个独立模型进程，随后分别启动已等待的纯标准库审计进程。20/20 模型进程与 20/20 审计通过，共重新执行 720 个 episode；19,141 个退出后语义／数值检查通过，最大数值差 2.22045e-16。环境实测为 NumPy 2.3.5、SciPy 1.17.0、`torch_available=false`，所有 worker 报告 `torch_imported=false`。

跨主机 CI 冻结参考包含全部输出、动作、候选分数、源时间与费用。hidden／路径的逐值双轨门在本机检查；当前 CI verifier 没有把本机 hidden 数组当跨主机逐值参考，不夸大该门范围。

## 封印与 CI 入口

实际模型包为 `export002/`，约 4.6 MiB。`MANIFEST.json` 固定模型／输入／源码，fresh Torch 参考绑定其 SHA；随后 `CI_MANIFEST.json` 对基础 manifest、全部模型数据、`FROZEN_REFERENCE.json.gz` 和 `VALIDATION.json` 再封印，避免引用 SHA 的循环依赖。

每个模型独立运行，`--task`、`--family`、`--seed` 唯一确定 16 个模型；过滤器另运行 uniformization，共 20 个任务。所有输出目录必须是新的：

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 \
python -m experiments.hcsn_v12_followup_20261101.model_runtime.numpy_runtime \
  --bundle experiments/hcsn_v12_followup_20261101/model_runtime/export002 \
  --task async_av --family gru --seed 91101 --implementation expm \
  --out /tmp/v12-model-fresh

python -m experiments.hcsn_v12_followup_20261101.model_runtime.verify_runtime \
  --bundle experiments/hcsn_v12_followup_20261101/model_runtime/export002 \
  --run /tmp/v12-model-fresh --out /tmp/v12-model-fresh-VERIFY.json
```

第二条是模型退出后的独立审计进程，应在测量 cgroup 外执行。其 CPU 单列，不能算进某个模型后称为纯推理成本。CI 的完整 cgroup 峰、单任务族 RSS、no-swap 和能量证据由独立经济性工作流验收；本地本轮不声称已测出这些值。

## 费用、原候选与未闭合项

首导出后，静态独审发现尚未执行的验证路径复用了 `cases` 变量名，会破坏参考列表。原 `source001/`、`export001/` 和 CPU receipt 保留；该版本未运行模型验证，也没有模型验证通过记录。修复后使用全新 `export002/` 与 `validation001/`，没有修改旧 manifest 或旧 source SHA。

| 完整外层执行范围 | CPU 秒 |
| --- | ---: |
| 首导出，静审后退役 | 2.854926 |
| 新封印导出 | 3.099154 |
| 全部 fresh Torch／NumPy 双轨检查与 CI 参考封印 | 34.849161 |
| 20 个无 Torch 实际进程＋各自组外审计＋父进程 | 27.649681 |
| 非重叠合计 | **68.452922** |

最后一项内部模型子进程合计 23.809988 CPU 秒，审计子进程合计 2.323068 CPU 秒，均已包含在 27.649681 中，不再次加总。本账不包括开发实现、后续独立审阅、远端 CI、旧媒体准备或原模型训练，也不把 CPU 秒换算为焦耳。

此端口保持原模型质量结果，未改变 v10 绑定任务的负向核心比较，未补齐原 v6 强头／强音频／独立录制，也未实现 He–Xiong 金融自由边界或生产 Rust 神经核心。完整研究准入继续 HOLD。
