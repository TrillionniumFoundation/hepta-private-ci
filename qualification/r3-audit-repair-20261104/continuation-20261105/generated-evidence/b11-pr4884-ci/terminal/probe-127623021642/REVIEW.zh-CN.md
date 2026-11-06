# B11 native12 原始证据封包

**B11 OPEN。原完整目标和整个 job 仍失败；新增观测 probe 已完成。** 本包保留原分支自动 workflow 的原件，没有重跑、改超时、过滤原失败或修改原断言。

## 实际身份与原件

| 项目 | 实际值 |
| --- | --- |
| Run / attempt | `42135663472` / `1` |
| Job | `127623021642`，`2026-11-06T00:17:05Z`—`00:23:59Z` |
| Head | `87b8603f21e52063ed54ce89cba26756a3efaab7` |
| 实际 checkout | `09960fe697c9c181e4a7d624e29b49360877b687` |
| 实际 tree | `9a804c7b6e0dd554cdb435f41e06c5c689fffaaf` |
| 新观测模块 | `8c16416c185f17871c25139bc16c6fd112b5fd41` |
| Artifact | `13465596874`，2,302,874 字节 |
| ZIP SHA-256 | `b21172467ad92e47439defa6075099cf7ba9fcf56b22221de145f0434bffe4f2` |
| 原始 job log | 511,506 字节，3,277 个 CR 全部保留 |

`archive/manifest.json` 列出 18 个 base64 分片，可逐字节重建官方 digest 对应的原 ZIP。84 个成员的 CRC、长度和 SHA-256 全部验证；ZIP 包含全部 raw logs、XML、7 份 compact 执行日志、完整正反例源码字节和原流程 guard 记录。成员 manifest 的 Git ID 是计算身份，不宣称所有成员分别上传成 Git 对象。

完整 MCP job log 返回对象、decoded log、run/artifact/jobs API、实际 merge GET、初始 in-progress 快照及捕获时钟均保留。MCP 对象是返回值的 JSON 序列化，不是 HTTP wire capture。79 个原流程源叶与 helper 的 11 个 pin 合计 83 条去重路径，使用 18 个完整祖先 tree 节点的 Git Merkle 证明绑定到实际 merge tree。

## 原门与新增观测

| 范围 | 实际结果 | 资格范围 |
| --- | --- | --- |
| 原完整库目标 | 147 通过 / 7 失败 / 2 忽略；Bazel 退出 3 | 原 7 个失败全部保留；整体不通过 |
| 四个原 exact 正例 | 每个 1/0/0，155 filtered，单次 local 执行 | 仅四个原断言子门 |
| 物理 identity 反例 | 0/1/0，155 filtered；XML 101，Bazel 3 | 原 `acl_tests.rs:597:9` 命中：replacement changed / original unchanged |
| 源码恢复 | 整份原始源码字节精确恢复 | 正常 finally 恢复；不保证强制取消恢复 |
| 原 unfiltered setup helper | 21/0/0，0 filtered；退出 0 | helper 子门；完整 read/loader/后代合同尚未资格化 |
| 新观测 probe | 原测试名实际 `ok`，完整 14 条 JSON 和 1 条纯文本 complete | 仅观测；`isolation_qualified=false` |

7 份 compact 全部解析到 EOF，实际 TestRunner 都是 local、非 cache、300,000 ms。whole 退出 1，物理 negative 退出 101，四正例和 helper 退出 0。每份 XML wrapper 单列；actual argv 保留 exact 名称与次数、whole/helper 无新增过滤参数。

实际文件系统为 NTFS。普通直接 token、普通模拟线程 token 的 Neither 组文件/目录都真删除；禁用最大特权的模拟线程对该组收到 OS error 5，物理对象仍存在。其余三个 route 均删除，全部 Rust read 返回原内容。配对线程的实际 token type/level 均为 2/2，用户、groups+attributes、restricted SIDs、integrity/policy、session 和 app-container 相同。普通组启用 Backup/Restore/Debug/ChangeNotify/Impersonate/CreateGlobal，过滤后仅 ChangeNotify 启用。

两个 cmd 子进程实际启动，放行 stdin 前的实际 primary token 与完整 expected record 相等。两者均有单次放行、四次原操作与完成 marker；`work_error=null`、`exit=0`、`terminate_error=null`、`cleanup_wait=0`、`accounted=1`、`active_processes=0`。普通 cmd 的 Neither 真删除，过滤后 cmd 的 Neither 文件/目录均未删，另外三格仍真删除。

**cmd 返回码不是删除成功 oracle。** 过滤后 cmd 对 Neither 打印两条 `Access is denied.`，但 FILE_RC_0 和 DIR_RC_0 仍为 0；两组全部记录的 operation RC 都是 0。本包保留 stdout/stderr 原字节与这项差异，依据保留句柄、释放后路径与身份检查得出的物理后态判断是否删除。

## 证据边界

这次 probe 通过，因此 Rust test harness 未把新五组夹具的 60 个逐对象 `eprintln!` ACL/identity dump 输出到原 log；不能声称已经独立读取了这些不存在的 dump。`executed-observation-module.rs.source.txt` 和 `delete-permission-matrix.rs.source.txt` 完整绑定实际源叶。基于已执行源码与 probe `ok` / complete，可以作出窄范围的源码推断：set_access 保存实际读回 DACL，五组 compare 该字节，release 验证保留对象身份、ACL、文件内容，之后检查释放后的物理后态；最终 ordinary token equality 与 fixture.close 在 complete 前成功。

这是五套不同但 ACL 等价夹具的全特权集合干预，不能单归因于 SeRestore。两次正常 owned cmd 清理不证明任意后代、breakaway、取消或整体产品隔离。旧八行的 row/restoration/finalized 可能有测试输出交错；本包保留完整原行，记录无法解析的行，不修复拼接，也不从残缺 JSON 推断结果。旧 complete 的 descendants_spawned=0 仅描述旧八行阶段，不能用于否认新增的两个 cmd 子进程。

完整 native index/lock 文件字节没有另存，保留的是原流程的稳定指纹。该 verifier 没有执行 rustfmt、产品测试或任何 native 命令，原 7 个失败也没有变成成功。

## 可移植复核

Python 3 与 `zstandard` 已安装后，在登记文件完整的目录内执行：

```sh
python verify-native12.py.source.txt --output new-result.json
```

本地源文件名为 `verify-native12.py`；登记仓库使用 `.py.source.txt`，Python 可直接执行。脚本只从分片重建 ZIP，在临时目录校验全部成员和门，结束后清理，不访问网络、不写 ref、不覆盖已有结果。`VERIFICATION.json` 是已执行成功的确定性结果；`native11-to-native12-verifier.patch` 保留相对于既有 verifier 的全部变化。
