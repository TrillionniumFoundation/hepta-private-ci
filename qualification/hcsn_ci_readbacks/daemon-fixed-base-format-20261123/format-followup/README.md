# 原格式候选与 HCSN 签名桥配对

在本目录运行 `python3 verify_followup.py`。核验器仅使用 Python 标准库，从两份原始 Actions ZIP 读取收据。

* [固定基址第一个候选](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45141510085/job/137580371929) 使用原 base `b8e8c6e82abc1479c573f61a5e17d28d581e6cad`，仅资格化两个 #2909 文件。38 项格式守门通过。原来的 4,219 个 Rust 文件顺序一致，其余 4,217 个命令参数及工作目录一致。整门检查在下一份保留的 #2684 材料上确实失败，写入前仓库干净。
* [HCSN 双臂签名训练桥](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45144827402/job/137591403749) 在一台 Ubuntu 机器上从 c12 原文件与 40ea7f9 两处排版更改分别重编 Rust，复用同一 Cargo.lock 签名 worker。三个真实 CPU 后端在每一端均跑完。共同的初态、基线检查点、训练后模型和时钟摘要逐后端相等。两端均拒绝篡改 payload、改动回执、重复写入者、错误 dispatch 和陈旧时钟。完整结果保留了进程标识、恢复、墙钟和各自 ELF；它们覆盖的是原夹具的测试签名与一小段训练。
* [可运行的原宿主配对工作流](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/680d4fa84b10eb4b8af373bf7f66d53c6c99f23d/.github/workflows/hcsn-native-format-pair.yml)。实际命令及解析出的依赖清单也保存在 ZIP 中。
* [37 个归档及 7 个维护源的原固定基址复验](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45146368735/job/137596544154) 在宿主机实跑 41+3 个测试、88 次物理源命令。4,219 项保持原顺序，其余 4,175 个命令参数与工作目录不变，整个 checkout 在检查前后干净。原整门在普通源 hepta-prompt/src/v3.rs 第 319 行失败，完整输出在 `registered-44.zip`。
