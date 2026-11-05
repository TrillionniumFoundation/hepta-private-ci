# 跨主机中继验证材料的独立审查

## 结论

**限定通过：两个已配置主机上的这次有限生命周期运行，其源码、组件、签名、请求绑定、状态变化和整数计算结果相互一致。** 本次审查只读取已有材料并在本地离线验签，没有重新执行远端阶段、安装依赖或写入远端状态。

已有记录包含 9 个控制阶段和 1 个只读日志导出阶段，10 个 job 全部具有退出码 0 的完整终态。离线验证了 16 个不同的签名对象：6 个成功请求及对应权威回执、1 个被拒绝请求及其权威回执，以及接收方的落盘声明和冷计算声明。7 对请求和回执的全部 `command_hash` 均由原始签名请求重新计算通过。

可复现验证器为 [verify_receipts.py](verify_receipts.py)，结果为 [review_checks.json](review_checks.json)。运行以下命令只检查本地已记录材料，直接输出 JSON；任一检查失败时退出码非零：

```bash
python qualification/memory-cell-v15/device_qualification/verify_receipts.py
```

需要另存结果时可使用 `--output <结果文件>`。本次验证器退出码为 0、`passed=true`。它同时核对原 53 项测试 receipt 中的八个 Python 文件，确认这些源码未被本次新增材料修改。原 53 项同主机自动化套件与本次跨主机记录是两个范围，不能互相替换或累加为模型效果样本。

| 材料 | SHA-256 |
| --- | --- |
| `receipts.json` | `8412c030ed18f95e4e2b97939beebb35570881d981550390223b7b2e0cd9f17b` |
| `costs.json` | `752ecbffc158480c765659571d1020d509be10332ad20e9aec705feb13cdf326` |
| 两端 `authority.py` | `7e5a2016347718e87df147f2ae96f2e56b9813d2c11e705bf88c8649a16bbe68` |
| 两端 `host_worker.py` | `e71df378426d8eb6c7afd8e75938741943fbdb482ec15de17c45b3f74ca12160` |
| 离线验证器 | `013f16a1776de6c7f3c78668f9e484ec9bfedb77db94a24b3ec7c79e15a2e4ef` |

## 实际核对的链

源码摘要在两端每个 worker 阶段一致，解析后的 observation 与保存的原始 stdout 一致。主机观察为：

| 配置主机 | 角色 | 观察到的运行环境 |
| --- | --- | --- |
| mac | 唯一权威、初始 owner | Darwin / arm64，Python 3.9.6，cryptography 46.0.5，SQLite 3.51.0 |
| pocket4 | 组件接收方、新 owner | Linux / x86_64，Python 3.14.4，cryptography 46.0.5，SQLite 3.46.1 |

配置别名、SSH 认证、job 身份、平台观察和 node digest 支持本次两端关联；它们不构成独立物理硬件的远程证明。x230 只出现在能力探测记录中，没有参与本次迁移。

| 状态 | 核对结果 |
| --- | --- |
| 创建 | source 管理员签名，cell 位于 epoch 1，所有组件摘要与实际字节一致 |
| prepare | source owner 签名指定接收方，权威进入 epoch 2 的 prepared 状态 |
| 目标落盘与冷计算 | 接收方签名声明与原 bundle 一致；`persist` 和 `cold_ready` 为不同 job、不同 PID；冷阶段 stdin 为 `{}`，从目标持久文件读取模型及记忆 |
| ready / commit | 原始请求由目标公钥验签通过，控制器转交的请求与导出的权威日志完全一致；目标成为 epoch 3 owner |
| 旧 owner 写入 | 被拒绝请求由旧 owner 签名，使用当时正确的 epoch 3 和当前 bundle；权威拒绝原因是 `not current owner`，因此不只是旧代次拒绝 |
| 参数版本更新 | 目标签名发布新的 model 组件，其他组件及来源依赖保持一致；权威进入 epoch 4，owner 仍为目标 |

独立验证器从实际组件字节解析权重、bias 和输入，重新计算矩阵结果，没有调用 worker 的计算函数。源端结果与目标新进程冷计算均为：

```text
[[11, 10], [1, -10], [14, 22]]
```

修改第一项 bias 后，目标计算与权威端计算均为：

```text
[[13, 10], [3, -10], [16, 22]]
```

这次只改变了 model 组件，memory 组件身份没有变化。它证明本次参数版本改变实际影响了计算，未提供“更好”的质量标签。更新后的计算来自当次加载的候选字节；不能额外宣称又完成了更新后目标进程的第二次冷恢复实验。

还有一个必须保留的权限区别：旧 source owner 被撤销的是写入所有权；它仍列在本次 bundle 的读取 ACL 中。本次没有撤销它的全部读取权限，不能把写入拒绝表述为全部权限撤销。

## 密钥、来源与可公开内容

审读 `host_worker.py` 确认，目标私钥由目标进程本地随机生成并写入本机 key 文件；本运行路径向控制器输出的是公钥、签名请求和签名声明，没有输出私钥序列化结果。源端各角色也在源端生成 key。记录的目录权限为 `0700`、key 文件权限为 `0600`。

`export_requests.py` 以 SQLite `mode=ro` 只读取得本 run 的成功与拒绝记录，不读取 key 文件。导出的 source 注册请求内容摘要与实际 memory 组件一致，create/prepare/ready/commit/publish 的 signer 和请求绑定完整闭合。

对 receipts 和成本文件进行字段、私钥 PEM 标记、个人及私有绝对路径检查，未发现私钥、密码/token 字段或个人目录路径；同时审读了脚本输出路径。这个结论限定于检查到的代码路径与材料，不是密钥硬件不可导出、宿主无恶意行为或所有潜在编码均可识别的证明。

## 成本与仍未建立的结论

`costs.json` 的十个阶段测量已逐条与原始 job/observation 绑定。原三次入口参数拒绝和本地证据写入错误均保留，没有改写为成功。完整成本缺失项仍为 `null`，`full_cost_comparison_complete` 和 `product_net_benefit_qualified` 均为 false。

- 408 bytes 是组件的逻辑字节合计，2,276 bytes 是 bundle JSON 大小；两者都不是完整磁盘占用、网络 wire 流量或模型部署成本。
- worker 的 elapsed 计时在 imports 之后开始，不能当作解释器启动、库导入、传输和控制器等待的总耗时。CPU 是进程累计值；各进程 RSS 峰值不能相加成为整机峰值。
- source 一直保有唯一权威数据库，通信经过控制器中继；没有验证 P2P、复制共识、权威主故障恢复或网络分区自动接管。
- 目标本次成功的文件/目录 fsync、新进程读回和实际计算加强了此次持久性观察；没有验证断电、磁盘失效、恶意接收者或未来长期保留。
- 本次只运行 authority 的限定操作与整数矩阵夹具；没有在 Mac 上完成整个 V15 评估器兼容性套件，没有训练 Transformer/LoRA，没有运行真实 Meta Network 的联合收益门，也没有验证语言记忆长期稳定性。
- 未测得能源、完整训练摊销、全部失败与基础设施成本、网络 wire 流量、物理存储及整机资源，因此没有完整成本后的净收益结论。

可以据此报告“经控制器中继，在 mac 与 pocket4 两个配置主机上完成了有限模型组件冷读取、签名所有权迁移及新 owner 参数版本发布，并独立验签通过”。不能据此报告“小设备已经获得大模型通用能力”“节点增长改善了智能”或“生产分布式 Memory Cell/Meta Network 已全部验收”。
