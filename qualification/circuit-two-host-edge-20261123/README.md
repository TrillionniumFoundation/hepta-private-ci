# 两台托管 VM 上的冻结 Circuit 中继

同一条冻结边在两台 GitHub 托管 Linux runner 上产生了与单机相同的两跳结果。第一台只加载 source 并生成 UTF-8 `1`。第二台校验来源、原始字节和权重，在连接条件下输出 `1`。去掉中继后，同一 reader 单独冷加载输出 `0`。这次使用 #7042 的人工数学夹具、固定路由、固定权重和既有测量输入。真实参与者与付款都是 0。[原冻结实验](../paired-consumer-circuit-20261123/README.md) · [本次预登记](PROTOCOL.md)

| 条件与实际加载位置 | 输入 token ID | 输出 token ID（原始文本） | 冷加载 | 生成 | 完整 predict 调用 |
| --- | --- | --- | ---: | ---: | ---: |
| source，Ubuntu 24.04 | `[4,5]` | `7`（`1`） | 2.593 s | 5.171 ms | 8.308 ms |
| reader 有边，Ubuntu 22.04 | `[4,5,0,0,0,7]` | `7`（`1`） | 3.276 s | 5.853 ms | 10.371 ms |
| 相同 reader 去边，独立进程 | `[4,5]` | `6`（`0`） | 2.283 s | 5.451 ms | 9.530 ms |

有边的两个节点与单机原件逐一匹配权重摘要、可见请求、渲染文本、输入 token、输出 token 及答案字节。另一个只读作业直接从冻结的 safetensors、LoRA、词表和配置重算了上述三个贪心输出。去边控制按预登记顺序在相同 reader VM 运行，两个新进程共享主机文件缓存。两次冷加载的耗时差含缓存、环境和顺序因素。[独立核验结果](AUDIT.json) · [核验作业](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45189930917/job/137745274538)

| 传输量或耗时 | 本次观测 |
| --- | ---: |
| 真正中继的答案 UTF-8 字节 | 1 B |
| 绑定运行、任务、模型、路由、源观测和答案的 envelope 文件 | 1,160 B |
| 两个应用文件合计 | 1,161 B |
| GitHub 返回的压缩制品 | 929 B |
| A 端上传动作的本机壁钟区间 | 1.044 s |
| B 端下载动作的本机壁钟区间 | 2.148 s |
| 从 A 上传前至 B 下载后，两台 VM 的壁钟近似值 | 14.219 s |
| 工作流提交至 A 作业启动，GitHub 秒级时间 | 84 s |
| A 作业结束至 B 作业启动，GitHub 秒级时间 | 3 s |
| 工作流提交至 A 的第一个用户步骤 | 85.602 s |
| A 作业结束至 B 的第一个用户步骤 | 6.870 s |

上传与下载动作包括 GitHub 客户端启动、制品打包或解包和平台服务开销。14.219 秒还包括 A 保存原件、收尾、依赖释放及 B 的调度。GitHub 没有提供本次 TLS/HTTP 线路字节数或纯网络单程延迟。环境安装另用 A 的 28 秒和 B 的 37 秒。单次运行只支持这个固定输入的判断，无法估计网络分位数、并发吞吐或最优部署粒度。

A 使用 GitHub runner `1000246474`、Ubuntu 24.04.5、Intel Xeon 6973P-C。B 使用 runner `1000246496`、Ubuntu 22.04.5、AMD EPYC 9V45。工作流指定不同镜像，两侧写下不同 hostname 和 kernel boot ID 哈希，平台作业 ID 与 runner ID 也不同。物理宿主机身份和地理位置没有独立硬件证明。该交付依赖 GitHub 同次工作流的制品服务。两端只解出本跳实际加载的模型文件。B 通过作业依赖取得 A 的制品 ID 和独立传递的 envelope SHA-256，重新校验冻结图、模型身份和答案哈希。[Source 作业](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45189161669/job/137742601657) · [Reader 作业](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45189161669/job/137743888529)

原运行提交 `eba6e3ef8e909f627f0f58e095732fb6b6d2fb3e`。7,339 字节的永久原件包保留三份平台原始压缩制品和平台时间线，SHA-256 是 `6a0f2ee3ee3c23989183940d751b300e4aa275d54b9dae8394d247a26549bdd0`。从仓库根目录执行 `PYTHONPATH=scripts python qualification/circuit-two-host-edge-20261123/audit.py verify qualification/circuit-two-host-edge-20261123/TWO_HOST_ORIGINALS.zip` 可以离线复算。环境使用 Python 3.12 和 NumPy 2.3.5。[三份原始制品与平台时间线](TWO_HOST_ORIGINALS.zip) · [审计程序](audit.py)
