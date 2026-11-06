# B11 native11 原始证据封包

整体结论：**B11 OPEN，原目标和任务仍失败**。这是第 11 次原分支自动 workflow 的终态证据，不是重新运行或放宽原断言后的通过记录。

## 绑定与完整性

| 项目 | 实际值 |
| --- | --- |
| Run / attempt | `42130823627` / `1` |
| Job | `127606676952` |
| Head | `2980fa274c599bd07437a2f5915b86d858f89bcc` |
| 实际 checkout | `53766cb836b198e2f928b949f148d7a2a10c0d21` |
| 实际 tree | `9cb7302777ce018dd022086041c2225d1dd5c8dd` |
| Artifact | `13462669785`，2,302,073 字节 |
| ZIP SHA-256 | `b67aa17b107136aa1e934065e671e35b99c1a8b74a82ad7edf40f21c58128ca8` |
| 原始 job log | 509,112 字节，3,334 个 CR 全部保留 |
| Job 完成时间 | `2026-11-05T23:46:15Z`，`failure` |

`archive/manifest.json` 的 18 段标准 base64 可还原完整 ZIP；84 个成员的 CRC、字节长度及 SHA-256 全部核对。所有原始 raw log、XML、7 份 compact 执行日志、精确源码前后像与 guard 回执都在 ZIP 内。成员 manifest 中的 Git blob ID 是计算身份，不能误认为每个成员已单独上传成 Git 对象。

`job-log-tool-response.original.json` 是完整 MCP 返回对象的 JSON 序列化，其 decoded content 与 `job.log` 全字节相等。它不是 HTTP wire capture。终态 run、artifact、根保存的 jobs API，以及最初 in-progress API 快照均单独保留。所保留 79 个源叶和 helper 的 11 个 pin 通过 18 个完整 Git tree 节点的 Merkle 证明绑定到实际 merge tree；83 个去重路径不是完整仓库文件枚举。

## 真实结果

| 范围 | 结果 | 可以得出的结论 |
| --- | --- | --- |
| 原完整库目标 | 146 通过 / 8 失败 / 2 忽略，Bazel 退出 3 | 仍失败，原 7 个失败未消失；观测 probe 新增 1 个前置失败 |
| 原四个 exact 正例 | 各 1/0/0，155 filtered，单次实际执行 | 只资格化四个原断言 |
| 物理 identity 反例 | 0/1/0，155 filtered；XML 101，Bazel 3 | 替换对象实际被错误修改，原对象未改；命中原 `acl_tests.rs:597:9` |
| 源码恢复 | 整份原始字节精确恢复，记录的 index/tests/locks 指纹稳定 | 正常 finally 路径恢复成立；不保证强制取消恢复 |
| 原 setup helper | 21/0/0，0 filtered，命令退出 0 | 原 unfiltered helper 子门通过，不证明完整 read/loader/descendant 契约 |
| 新 Rust 观测 | 3 个 cohort 完成 | 实际 NTFS；直接普通 token 和普通模拟 token 的 Neither 都真删；禁用最大特权的模拟 token 对 Neither 文件/目录都收到 OS error 5 且对象未删 |
| 新 cmd 观测 | 第一子进程创建前失败，0 child marker | 不存在可资格化的 cmd 对照或最终 owned Job 清理结果 |

7 份 compact 全部按完整 framing 解析到 EOF。实际 TestRunner 都是 local、非 cache、300,000 ms：whole 退出 1、物理 negative 退出 101，其余 5 个退出 0；每份独立 XML wrapper 另行记录。actual argv 与四个 exact 名称、negative 同名 exact、whole/helper 无过滤参数相符。

三组 Rust 比较记录了实际线程 token（配对两组均 type 2、level 2），user、groups+attributes、restricted SIDs、integrity/policy、session、app-container 完全相同。普通 token 启用 Backup/Restore/Debug/ChangeNotify/Impersonate/CreateGlobal；过滤后仅 ChangeNotify 启用。36 个保留对象记录显示三组 ACL 字节对应相同、对象 identity 各不相同，Both 等其余三格与全部读取保持正向结果。这是不同但 ACL 等价夹具间的全特权集合干预，**不能单独证明 SeRestore 因果**。

新增 probe 的原错误是 `GetTokenInformation(TokenRestrictedSids) size query failed: 122`，出现在现有 process backend 的 desktop launch 前置检查，早于 child creation。因此 `child_before_release`、`child_finished`、`cmd_physical` 和新 complete marker 均为零。原生产 desktop 的拒绝语义并未被修改或放宽。

## 可移植复核

在本目录布局完整、Python 3 与 `zstandard` 已安装的环境中运行：

```sh
python verify-native11.py.source.txt --output new-result.json
```

本地源文件名为 `verify-native11.py`；仓库封包使用 `.py.source.txt` 以免成为产品构建输入。脚本不访问网络、不运行产品/native 命令、不写 Git ref。它从分片重建 ZIP，检查全部成员，在临时目录复核原件，结束后清理临时目录；拒绝覆盖已有结果。`VERIFICATION.json` 是已执行成功且可确定性复现的完整结果。

完整 native index 和 lock 文件字节没有额外归档，只有原流程记录的稳定指纹。原测试日志中可能交错的旧观测行保持原样；新三组 Rust 的 8 条 JSON 行都完整解析，没有拼接修复。该证据没有运行 rustfmt gate，也没有把原失败转换为成功。
