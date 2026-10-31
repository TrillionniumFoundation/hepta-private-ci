# 原生 cell 与完整内容成本：恢复、复验和新实验

本次恢复了此前尚未完整发布的真实 Rust finite-cell owner，并以相同源码重新构建、执行九项 Rust 测试和完整数值资格实验。新增内容成本实验使用已有冻结 FullHX 内容模型实际读取和解码文件。所有实验保持 `DENY_ALL` 与 `production_activation=false`。

## 源码和原始证据

原生源码摘要为 `58c5acd47498d5536293ae8223ed1b28ae8f87a21efd0467c801e46f4298d89b`，新构建的二进制 SHA-256 与此前 tail-fix release 相同：`6cfe7b61662d5c74272594bfc5de0b0aaa2f9cb9b1df3c5ca7dabef7e6298109`。现有 `NeuronRuntime`、独立 witness 和 journal 均实际执行。物理传播、查询、复位及不应期在 Rust 中执行，查询结果进入实际 `NeuronModelPort`，随后由原生 sparse runtime 消费。

`BUILD_REVALIDATION_20261031.json` 保存当前源码重新编译和九项测试输出；`qualification-revalidation-20261031/REPORT.json` 保存本次独立重跑。它复用已注册的同一组种子与协议，因此不增加统计独立样本数。构建复用了核验过的 Cargo 依赖产物，是 fresh direct-rustc build/test，不能计作新的 Cargo/just 全工作区验收。

当前交付索引是 `DELIVERY_MANIFEST_CURRENT.json`。原 `DELIVERY_MANIFEST.json` 原样保留，属于旧 `456a` release，不能用它校验更新后的文件。历史 tail-fix 原始记录现已归档到 `RAW_NATIVE_EVIDENCE_TAILFIX.tar.gz`，逐文件哈希和独立解包读回记录在对应 manifest。本次重跑和新内容实验原始文件另存 `RAW_REVALIDATION_20261031.tar.gz`。

## 数值和恢复复验

九项 Rust 测试全部通过。普通门控、分布 cell、采样 cell 的十二组 event/dense 配对均保持相同终点 native signal；最大独立状态/特征误差 `1.942890293094024e-15`，事件计数误差 `5.329070518200751e-15`。尾概率正通量修复、二万种子的采样分布/重复事件检查亦通过。

恢复仍有明确边界：正常已确认终点可以精确续接；native journal 与物理 checkpoint 两次提交之间的任意中断会检测并拒绝不一致状态，不承诺自动修复。该有限五态生成元的下边界反射，采用既有 upwind 速率；它没有因此获得独立 Brownian 连续模型的收敛结论。

## 新增完整内容成本实验

`qualify_content.py` 在物理资格协议外增加真实文件读取、特征构造、冻结 FullHX 推理、内容输出 fsync、内容 checkpoint 和一次模型/原生进程恢复。每个 public endpoint 只解码一次：dense 版本没有人为重复解码内容。普通门控取得相同事件调度，是同信息的强普通对照。

这里由公开 endpoint 决定 decoder 调用时机，native signal 没有控制内容调用。恢复时重启 native 子进程并重新构造 ContentAdapter，Python 宿主循环仍然存活；不能据此宣称整条 Python 宿主进程崩溃后已自动恢复。

协议在执行前记录源码、二进制、参数、种子和输入身份。共四个种子、四十八份不同 packet；同一 packet 在不同后端重复执行不算新增独立样本。正常任务是已有 marked-first-symbol memory task，32 个符号的真实神经模型推理；这不构成开放语言或多模态内容质量证据。内容任务只检验调度保持已有输出，没有把新的任务价值 head 接入原生 owner。

| Cell | 调度 | 每次完整 CPU（秒） | 每次墙钟（秒） | 正常 packet 准确率 |
| --- | --- | ---: | ---: | ---: |
| 普通门控 | Event | 0.107762 | 0.150669 | 100% |
| 普通门控 | Dense | 0.279603 | 0.626139 | 100% |
| 分布 cell | Event | 0.102695 | 0.135195 | 100% |
| 分布 cell | Dense | 0.271850 | 0.501102 | 100% |
| 采样 cell | Event | 0.101743 | 0.138801 | 100% |
| 采样 cell | Dense | 0.291231 | 0.608079 | 100% |

每行是四个种子的均值。正常事件调度完整 CPU 分别减少 61.46%、62.22%、65.06%，普通门控也得到同类收益。该单主机测量不支持解析 cell 相对强普通 event 调度的稳定独有优势。

正常十二组和另外三组真实缺失文件负例合计十五组配对，内容输出和终点 native signal 全部一致；最大终点特征差 `1.3877787807814457e-15`。三千零六十次实际 native commit、三百六十次读取尝试、三百五十四次成功解码、六次真实读失败，以及三十次已完成动作后的恢复均保存原始记录。失败读取计入时间和读取次数，未被当作成功输出。

报告的 `passed` 只检查输出/信号/数值一致性和成功/失败次数；CPU 下降是另行保留的测量结果，本次十五对差值均为正。

每次执行计入 native 启动、传播/查询/readout、IPC、journal/witness/physical checkpoint、内容读取/特征/FullHX 推理、输出同步、一次恢复和关闭。共享输入生成、评价和汇总不计入单条 rollout；`CONTENT_REVALIDATION_PROCESS.json` 另记录完整实验进程：CPU 6.127609 秒、墙钟 11.255301 秒，含这些共享工作及原生子进程。

## 复现新增内容实验

先按 README 用精确源码构建原生二进制，再从仓库运行：

```bash
OPENBLAS_NUM_THREADS=1 python tools/hcsn/round8_20261031/native_owner/qualify_content.py \
  --binary /path/to/verified/native-owner-final \
  --out /path/to/new-content-evidence \
  --build-sha 58c5acd47498d5536293ae8223ed1b28ae8f87a21efd0467c801e46f4298d89b
```

需要保留冻结 `ContentAdapter` 和其四项 upstream 文件；初始化会逐个核验 SHA-256。新输出目录必须不存在。完整原生部署、任意崩溃的自动原子恢复、校准价值策略在真实 owner 上的任务净收益，以及更开放内容的质量门槛仍需单独验收。
