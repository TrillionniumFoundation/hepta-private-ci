# 历史 Joint 后代回收与普通运行时验收

本轮恢复了真实训练过的 width32 Joint 后代，完成了实际 Cargo
`hepta-joint-propose` 与原始 Torch 模型的独立数值对照，新增普通 Agentd
交付／恢复测试和 admission-cancel 测试。**新增训练更新数为 0。**

原始冻结模型 `9032b075…` 的字节仍然缺失。这次回收对象是它经过历史
16 次 Adam 更新后的完整 Joint 后代，不能沿用原父模型的身份或验收结果。

## 资产与来源

| 对象 | 固定身份与实际检查 |
|---|---|
| 历史源码 | `18dac3ccd30317893ad922792c12400390522f00`，#4442 |
| 已发布归档 | `v3/packaging/bundles/open_text_final_20261030`，8 个原始块，2,887,128 bytes |
| 原始归档 SHA256 | `5ce3179ad1cbab559659eb2f36265dc3071af071ee6cfb27dd5f9640e38693dd` |
| 回收 checkpoint | `payload/adapter.pt`，3,156,046 bytes，SHA256 `33c1aa759bddb5e9b33b906e1796de7a6f89e5b5916711f99033584b3cbafb97` |
| 完整 Joint 状态 | 67 tensors、596,985 参数，全部有限；strict load 通过 |
| Joint tensor digest | `227f25ed9e17fc10cd762dda5739ef3f911a8cf3e0be833a6c8d0ce22e5013dc`，与历史 report 一致 |
| 配置 | width32、depth1、dual、direct、verify_mode=allow |
| 导出 HPS | 4,778,937 bytes，SHA256 `41ce6de8a9095e1ef6b8756c3117a160ed40acfad8b297390de95083664d223e` |
| Public HPS | 78,188 bytes，SHA256 `86c55417fdf2abdd065fc9828c40260aed0ded4a0d607c551e15b2f6b5fd2c00`，与旧数值验收完全一致 |

`adapter.pt` 的名字容易造成误解。历史 `open_domain.py` 实际保存了完整
`hepta.state_dict()` 和 config，此外还有自由文本 prefix 参数和冻结 LM
身份。后两者不属于当前 Joint proposal ABI 的执行范围。checkpoint
不含 optimizer 状态，本轮不声称可恢复训练。

[recover.py](recover.py) 从固定 Git 对象恢复原 8 个块，检查 index、chunk
page、每块、总归档、manifest 和每个成员的 SHA256；以 `weights_only=True`
加载 checkpoint，并对照历史完整 tensor digest 和四个训练源码哈希。
随后调用同一固定来源的 `native_bridge.export_model` 导出全部权重。
前后 tensor digest 相等，没有补张量、随机替代或重训。

完整身份保存在
[joint-trained-v1.json](../../codex-rs/hepta-neuron/tests/fixtures/joint-trained-v1.json)。
权重按 393,216-byte 上限分成 13 个普通 Git fixture；public 单独保留。
`joint_trained.rs` 在编译期 include 每块，在运行期核对完整 weights、public
及 provenance 哈希。缺文件编译失败，身份不符返回错误，没有缺资产跳过或
synthetic fallback。两 crate 的 Bazel compile_data／exports 包含全部文件。

Public 输入是历史 `mechanism_data.batch([3], "v3-native-implementation")`
产生的合成机制案例；权重是真实训练的，输入的来源与范围仍明确为合成任务。
历史自由文本评价中 state／zero_state／shuffled_state 三臂均为 **0/4**。
[原 report](historical-report.json) 和 [原 protocol](historical-protocol.json)
保留原字节；本轮实现一致性不改变该质量结果。

## 实际 Cargo helper 数值结果

首轮实测记录在 [numerical-cargo-01](evidence/numerical-cargo-01/RESULTS.json)。
使用实际 Cargo 构建的 helper，大小 1,145,208 bytes，SHA256
`f0c813b016c895f4a1b333cf2012b248ab84db275227ca6c0c6dd0972b5a769c`。
[HELPER-TRANSFER.json](HELPER-TRANSFER.json) 保留不可变版本、分块读回和完整
重组校验。Cargo 来源由统一候选的构建回执与同一二进制 SHA 关联；脚本中的
文字说明本身不是构建证明。helper 源文件与 `7391c3dc…` 的固定实现一致。

| 实际观察 | 结果 |
|---|---|
| 实际 helper 进程 | 39 个新进程，39 个不同 PID，全部 exit 0 |
| 完整状态比较 | 8 个主线状态、28 个 Commit 分支、3 个 Auto 分支，共 39 组 |
| FP64 最大绝对误差 | `7.771561172376096e-16`，严格小于预冻 `1e-9` |
| FP32 最大绝对误差 | `1.8493976472466755e-07`，严格小于预冻 `5e-5` |
| 媒体 | 每个非终态的四种 mean 输出与 Torch FP64 独立量化字节完全一致；Stop 完整 flush 一致 |
| Auto | Init→Stop；Shared 后→Video；Verify 后→Stop；FP32／FP64选择、后继状态和输出一致 |
| 最终 prefix SHA256 | `db8938ed1a26c84c16b1043b579e9682d7e640387903e3a5fac610971c96e6ee` |
| 实测 wall | 39.659837226 s |
| 父进程 CPU 计量区间 | 2.949014145 s |
| helper 完整进程 CPU 合计 | 37.176769 s |

完整 context、shared、slots、feedback 和四种 core 状态均逐元素比较；离散
状态、资产绑定、prefix tensors 和 cursor 精确比较。媒体量化独立使用
Torch FP64 heads、sigmoid／tanh、ties-to-even 取整和首个最大值标签。
图像 PNG 和音频 WAV 写出后再次解码核对原字节；四帧视频和文本也保留。

**误差上限只适用于完整可恢复状态。** proposal ABI 没有返回原始 actor、
critic 或 emission-head 浮点向量；当前观察是量化媒体字节和 Auto 后继行为。
没有执行冻结 LM／learned text prefix，也未测试 splitmix 采样器。

首轮执行前冻结的协议 SHA256 为
`7c663a753517a14cb1790dd85a242d4f8489cb8b91413e892d965e28d3565300`。
该轮目录保留了原 `differential.executed.py`、`recover.executed.py` 和协议
原字节，均与 REGISTERED.json 的哈希一致。它们是这 39 次实测的执行来源。

之后只读审阅发现失败记录边界：预检异常缺回执，Popen 失败缺调用记录，
响应错误缺原始 stdout，以及比较已成功后清理异常可能未重置 passed。
当前 [differential.py](differential.py) 已修复这些失败路径，开始时保存执行
源码与协议，解析前保存原始 response，任何异常强制失败；没有放宽阈值、
改变输入、模型或比较算术，也没有为此重复 39 次成功扫。

[verify_failure_boundaries.py](verify_failure_boundaries.py) 定向验证错误 helper
身份、启动失败、坏响应保存，以及成功之后清理异常必须 exit 1。这些测试
不执行实际 Cargo 模型；其中一个受控 shell stub 只用于返回非法响应，模拟
成功的比较只用于验证异常门。它们不构成模型或普通 owner 的资格证据。
这四项检查均通过，见
[failure-boundaries-01/RESULTS.json](evidence/failure-boundaries-01/RESULTS.json)：
实际 Cargo helper 执行数 0，受控非法响应进程 1，新增训练更新数 0。
首轮原始 response 未全部保存这一局限保留；该轮有完整调用记录、状态、
输出、哈希与正常通过结果，后续 harness 加固没有覆盖它。

## 普通 Agentd owner 验收

以下两个 trained 测试与原 synthetic 测试独立存在，均使用实际
`hepta-joint-propose`、完整训练权重、Fleet 身份、原 control 文件 owner、
Cell journal 和外部 anchor witness。执行结果由统一固定候选的原生门保存，
此处的数值结果不能替代该原生门。

1. `historical_trained_joint_control_service_preserves_real_output_cost_and_owner_on_reopen`：
   Init、Shared、16-sample 音频 prefix、真实消费者 ACK、Stop 全模态 flush，
   然后重开终态且仍有待 ACK 输出的服务。逐字比较 snapshot、outbox、cost 和
   control 文件；相同 Stop 请求重试只读回原回执，最终 ACK／drain 完成。
   每步 7 条、交付前 29 条、最终 30 条成本断言与原 synthetic 测试相同。
2. `historical_trained_joint_admission_cancel_retains_predecessor_cost_and_receipt_on_reopen`：
   先真实 Init，再对已 admission 的 Shared 立即持久化取消意图。要求
   Cancelled、整个前驱 snapshot 仅 revision 加 1、无 outbox／pending，重开
   后原取消回执、成本和 control 文件不变。未进入 worker、进程中断、迟到
   成功三种真实路径分别允许 2／3／7 条实际成本，不虚构已经执行的计算。

取消测试不保证 Shared 子进程已启动。它发生在空 prefix 的 Shared 请求上，
Shared 本身不发布媒体，因而不覆盖已有媒体 prefix 下的取消或输出生成期间
的强制中断。主生命周期覆盖终态 outbox 恢复，未覆盖进程死亡后继续生成。

测试总会运行，不依赖可选环境变量跳过。成功证据保留在
`HEPTA_JOINT_TRAINED_EVIDENCE_DIR` 指定父目录下的新子目录；未指定时保留新的
临时证据目录并打印路径。包括 state、prefix、control 原字节、媒体、完整
回执与成本。失败时原生门保留 nextest 的原始失败日志。

## 成本与仍未完成的条件

这里证明的是实际状态／媒体计算和现有 owner 生命周期的可验收接入；完整
成本仍没有闭合，独立任务收益与采用也没有资格结论。

- helper 四阶段 wall 是互斥的子区间；CALLS 的完整进程 wall 包含这些区间，
  不可重复相加。父 orchestration wall 也包含子进程等待。
- 数值脚本的父 CPU 区间始于标准库导入之后；helper child CPU 覆盖整个
  已启动进程。Cargo 构建、二进制传输、基座获取、历史训练和 energy 未包含。
- 普通 owner 的 30 条 ledger 不等于全部当前 wall 成本：控制计时在 worker
  启动前截取，后续 collect／结果编码／settle、Cell journal fsync／witness、
  ACK 持久化、服务重开／重放、资产加载和证据复制没有被完整计入。
- `deliver()` 只测消费者内存复制，不能称为完整 ACK 路径计时。CPU 和 energy
  缺测保持未知，不转成零。
- 原父模型仍未找回；后代缺 optimizer；自然任务能力、分化收益、完整历史
  成本以及是否应采用这一后代均未证明。

## 重现

在含 Torch、NumPy、Pillow 的 CPU 环境中，使用可读到固定 `18dac3cc…` Git
对象的仓库，以及固定身份的实际 Cargo helper。两个输出目录都要求事先不存在。

```sh
python qualification/joint-trained-recovery-v1/recover.py \
  --source-repository /path/to/pinned-source-repository \
  --work-directory /path/to/new-recovery-directory

python qualification/joint-trained-recovery-v1/differential.py \
  --source-repository /path/to/pinned-source-repository \
  --checkpoint /path/to/new-recovery-directory/adapter.pt \
  --helper /path/to/cargo-built/hepta-joint-propose \
  --expected-helper-sha256 f0c813b016c895f4a1b333cf2012b248ab84db275227ca6c0c6dd0972b5a769c \
  --output /path/to/new-numeric-evidence
```

重建后的 helper 若字节身份不同，必须登记实际 Cargo 来源和新的完整 SHA，
不能沿用这里的二进制身份。普通 Agentd 的 Rust 测试通过仓库 `just test`
原生门执行；本回收脚本不代替 Cargo／Bazel 门。
