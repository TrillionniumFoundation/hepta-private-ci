# R18 实际生产 journal／witness API 接入

新 Rust 二进制实际调用仓库既有 `SparseJournal`、`JournalScope` 和 `FileAnchorWitnessStore`，将有持久账单副作用的 provider 收据字节绑定到真实神经元 journal tick，并保留独立 witness CAS。生产 crate 源码未修改；57 个 Rust 源文件的 Git blob 身份与固定 R17 提交逐项匹配。隔离三 crate workspace 用 Rust 1.95、锁定依赖离线构建成功，`build.py` 可从同一源码重建。

远端源码冻结为 `3ce16e80211d6ae3db1daa736babb89cefda10e2`；本地 `SOURCE_FREEZE.json` 在最终检查前绑定 Rust、检查器、构建器、计量器、Cargo.lock、生产来源身份与外部收据输入。`RESULTS_V2.json` 是权威记录，固定其实际测试二进制 SHA256。二进制位于复现构建的 `target/debug/hcsn-production-bridge-r18`，不能用另一个构建目录的可执行文件哈希替代。

## 已执行范围

- 40 个主要进程记录包括 36 次 ACK 和 4 次在 journal 已持久追加、witness 尚未确认时的真实 SIGKILL；恢复后的完整 journal／witness 文件字节等于不中断执行。
- 12 项拒绝检查通过：冲突重试、前驱错误、scope／objective／generation 漂移、截断、已确认历史回退、超界收据，以及三个未确认追加之后直接跳到下一序列的请求。失败不改变既有文件字节。
- 六份实际原生外部服务的 `EFFECT` 收据通过生产 API，逐项核对输入 SHA256。`requires_calibration=true` 和 `DENY_ALL` 始终保留。
- 独立审阅核对冻结身份、实际二进制、全部保存记录与收据，见 `INDEPENDENT_REVIEW.json`。

`RESULTS_V2.process.json` 记录 Python 检查解释器和其已等待 Rust 后代的完整 CPU **0.184375 秒**、墙钟 **0.230345 秒**。编译、开发和独立审计另计，不能把该数称完整项目成本。早期 V1 探针及可精确复原的旧检查源码保留。

输入清单最初指向原生服务 run01 的实际账单收据。修正 LEASE 原子提交后的 run02 产生相同六条 EFFECT 字节，`PROVIDER_V2_EQUIVALENCE.json` 保存此事后字节核对；该核对不冒称已经运行生产模型与服务的在线联合生命周期。

## 资格边界

接入的是实际生产 journal／witness API。数值 CTMC／解析金融核仍由冻结 Python 参照执行；此 Rust tick 绑定收据，不计算新的金融状态，不提供内容能力或 D−B 证据。收据哈希不认证远端服务，目录私有性及 witness 独立可信存储仍由 host 负责。本轮未验证断电、网络传输、并发敌对主机、全神经元模型端口准入、GPU 或能耗。

生产主路径采用与校准资格仍开放，`production_activation=false`。复现用新的构建和结果目录；原结果均不可覆盖。

```sh
python build.py CHECKOUT NEW_BUILD RUST_BIN CARGO_HOME
python meter.py NEW_BUILD/target/debug/hcsn-production-bridge-r18 NEW_RESULT.json
```
