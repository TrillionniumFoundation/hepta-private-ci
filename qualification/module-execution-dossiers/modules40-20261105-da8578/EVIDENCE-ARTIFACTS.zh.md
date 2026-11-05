# 原始证据与完整重建入口

最终执行源码为 `8658210499706130788c216ff14fd342809b45a4`，tree `6bc86196d10cf83b010f9917e5e9cb471b5f6b68`。当前文件所在提交是证据文件载体；不是另一个已执行的源码候选。完整结论见[执行总览](EXECUTION-OVERVIEW.zh.md)，逐模块事实见[40 模块正文](MODULES40-DEVELOPMENT-BODY.zh.md)。

| 归档 | 内容范围 | 字节数 | SHA256 前缀 |
| --- | --- | ---: | --- |
| [native-final-bb55-checkpoint.tar.gz](native/native-final-bb55-checkpoint.tar.gz) | bb55 历史原生执行与此前失败 | 1,026,914 | `28424496bd400d6c` |
| [native-797-file-read-checkpoint.tar.gz](native/native-797-file-read-checkpoint.tar.gz) | 797 原始执行；逐文件版本固定的非原子采集 | 313,492 | `6e95dfc4723db20a` |
| [native-775-checkpoint.tar.gz](native/native-775-checkpoint.tar.gz) | 775 Windows 引用修复后的独立 Linux 执行 | 217,229 | `1c59a87b3802c3a6` |
| [native-865-checkpoint.tar.gz](native/native-865-checkpoint.tar.gz) | 最终固定合并候选的独立原生执行 | 325,679 | `ba0299e0531d3a3f` |
| [native-audits-through-865.tar.gz](audit/native-audits-through-865.tar.gz) | 历史及最终独立审计、读取与归档 custody、审计工具 | 488,338 | `b384992ba6230e2a` |
| [platform-and-merge-checkpoint.tar.gz](platform-and-merge-checkpoint.tar.gz) | 全部保留的平台日志、快照及 3a39 源码合并审计 | 3,124,274 | `2d461eb2ac9522d4` |
| [source-report-rebuild.tar.gz](source-report-rebuild.tar.gz) | 完整历史及最终 40 模块报告、原始输入与重建工具 | 1,931,138 | `a7a9102bc6e8ce8e` |

完整 SHA256、Git blob 与各候选身份见[EVIDENCE-ARTIFACTS.json](EVIDENCE-ARTIFACTS.json)。上述档案保留原始失败、各提交自己的成功、未执行的平台快照及可复核脚本。它们不相互替代，也不把 Linux 或 Python 回执控制测试变成 Windows 原生验收。

原 f581 七包失败仍封存在[原始不可变检查点](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/acf11067530fc12386b090e7e067e518b182088f/qualification/module-execution-dossiers/modules40-20261105-da8578)。所有 40 个生产标记仍为 false，公共拓扑保持 DENY_ALL；完整外部门槛见[操作与门槛附录](MODULES40-OPERATIONS-AND-GATES.zh.md)。
