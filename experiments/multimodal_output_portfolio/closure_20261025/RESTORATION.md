# 恢复证据与复现边界

本目录的源代码、协议和报告由 Git 保存；实际模型、媒体、逐请求记录与执行回执已封入 [EVIDENCE.json](EVIDENCE.json) 指向的本地证据包。当前文件服务上传被自动审批阻止，尚待用户明确授权，不能将本地临时路径视为已完成持久保存。先核对归档字节数和 SHA256，再解包到新的工作目录。不要把重新执行得到的文件覆盖到原始证据上。

## 六个新证据包

| 包 | 内容与用途 |
| --- | --- |
| `hepta-ndu-shared-inputs-20261025.tar.gz` | 200个固定上游输入：MNIST归档、源manifest、五seed实际生成器与teacher/sensor/observer、旧fit/selection数据和成对基础模型 |
| `hepta-ndu-control-runs-20261025.tar.gz` | 全部controller开发、历史新future、256新来源主检验、探索性对照、容量修复和96新来源确认 |
| `hepta-ndu-factorial-runs-20261025.tar.gz` | 新基础训练、三个seed的gate/critic开发、256新来源完整有限树、逐节点输出与最终统计 |
| `hepta-ndu-v6-oracle-runs-20261025.tar.gz` | 原始V6必要checkpoint/forecast/observer、旧dev和新64对枚举、策略实际执行及独立重放；MNIST归档由shared包提供 |
| `hepta-ndu-native-online-20261025.tar.gz` | 主执行binary、真实owner/media/NDU/recovery日志、独立格式化验证、原有模型资格完整输入；通用生成器与MNIST由shared包提供 |
| 媒体包，文件名见 `EVIDENCE.json` | 全部失败、修复、参考与最终媒体证据及所需声学资产；重复的共享输入用精确SHA引用 |

原始V6完整历史包也保留原有下载入口。新V6包已包含这次执行需要的原始参数，不需要重训来猜测历史权重。

## 路径与冻结身份

每项执行协议保留原环境的绝对路径和 SHA。通用包的 `MANIFEST.json` 为每个归档成员记录原路径、大小及摘要；V6和native内嵌包另有各自索引。复现者应先恢复对应字节，再为新环境建立独立的路径映射／登记。不要改写已执行 `PROTOCOL.json`、`FINAL_PROTOCOL.json`、原 `registration.json` 或用新机器摘要替代旧身份。

shared包没有重复保存旧Git工作树。control旧 `DEVELOPMENT.json` 及native旧 `PROTOCOL.json`、`PROSPECTIVE_ADAPTER_PROTOCOL.json` 从基线提交 `07bd949855778b19d3cff6842378814498d40a27` 的原路径恢复；相关大小与SHA在各输入清单中。native包内 `RESTORE_INPUTS.json` 说明另外九个实际权重、校准与资格文件。

当前native活动Rust源经过 `just fmt`，主研究执行使用的原字节位于 `native/frozen-execution-001/SOURCE.tar` 与原始raw包。原主protocol在当前格式化路径上的SHA不再匹配是已记录的版本差异；恢复主研究时用原快照。格式化版本有自己的binary和旧dev验证，不冒充重新做过新64对研究。

## 运行环境与成本

[RUNTIME_VERSIONS.json](RUNTIME_VERSIONS.json) 记录本轮主要Python、Torch、NumPy、Pillow与FFmpeg版本。媒体资产清单另列语音环境、模型、codec可执行文件及SHA。没有复制整个venv或系统共享库，因此证据包不是开箱即用的完整容器镜像；解码和重建仍需匹配的运行依赖。

native包可恢复已执行的研究binary。重新编译需要 `build.json` 中列出的原22-crate依赖与固定产品源码；本轮没有从空环境重建完整Agentd daemon。不能用增量 `rustc` 时间推断完整构建成本。

完整命令在各 `registration.json`、process receipt、training record与build record中。四条研究入口分别为：

- `control`：`development`、`registry`、`process`、`rollout`、`analysis`，补充与修复各有独立入口。
- `factorial`：`train`、`develop`、`evaluate freeze/run`、`process`、`analyze`。
- `v6_oracle`：`registry`、`check_old`、`run`、`analysis`。
- `native`：`build`、`run`、`boundaries`、`freeze`、`process`；media各训练／修复阶段及最终 `evaluate` 命令见媒体报告。

这些名字用于定位已记录命令，不替代原命令行中的模型、source、protocol和输出目录参数。输出目录采用新建而非覆盖，重跑前需明确使用的是开发复核还是历史重放。

## 统计复核与来源使用

可直接在已经保存的输出和评分上复算 CE、来源对bootstrap、计数、时间与SHA；这不会增加统计N。V6、control和factorial的独立复核脚本与结果保存在 `v6_oracle/review`、`native/review`，media审查在 `media/review`。

800对预留来源在本轮已全部分配。再次访问任何已执行来源必须称为重放；不能把相同来源的新视图、future或策略行登记成新来源。若未来改变模型、阈值或观察器，应使用新的独立确认来源；本轮的失败候选和冻结协议继续保留。

`authority=deny_all`、原资格与资源门是实际执行状态。恢复研究证据不会提供生产签名、信任根、Dataset owner身份或模型安装资格；相关未闭合项见 [STATUS.json](STATUS.json)。
