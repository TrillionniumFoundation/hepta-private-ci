# 五组普通历史合并的证据

本批以 `87b141833f2a43e0e87fdb3d4a168e1dacde7a0f` 为起点，包含五个顺序双亲 merge。所有 merge 的完整树均为 `477005584144e1f9cd9c4e9e280e0a7f7706a487`，59,426 个叶条目未变；随后只添加本批 QA 记录。

各组先实际执行默认合并并审查差异。组合时实际运行 Git `merge-tree --write-tree`，核对三方 mode/OID、原始冲突全文与确切解决路径，再通过独立 index 和 `commit-tree` 形成双亲对象。GitHub 对象使用其实际 parent 重算默认合并，证据单独保留。没有使用合并策略覆盖来丢弃另一方历史。

| 记录 | 内容 |
| --- | --- |
| [HISTORY-BATCH.json](HISTORY-BATCH.json) | 精确对象、每组范围、快照计数、归档成员来源与摘要 |
| [history-1bc.tar.gz](history-1bc.tar.gz) | 一份原 Rust 格式提交，四个同 tip 分支 |
| [history-047.tar.gz](history-047.tar.gz) | 七份原提交、十三文件三十六块冲突 |
| [history-438.tar.gz](history-438.tar.gz) | 二十四份原历史、十六文件四十九块冲突与独立复核 |
| [history-a5a.tar.gz](history-a5a.tar.gz) | 四十一份原历史、三十八文件七十四块冲突及自动重放核对 |
| [history-c6e.tar.gz](history-c6e.tar.gz) | 四十六份原历史、四十八文件一百零六块冲突及两处自动重放修正 |
| [sequence-proof.tar.gz](sequence-proof.tar.gz) | 五步真实默认合并输出、两个独立复核、GitHub parent/tree 读回与实际 parent 合并证明 |
| [refs-and-protection-7831.tar.gz](refs-and-protection-7831.tar.gz) | 7,831 refs 的固定快照、已知 HIA 保护集合、精确 tip 核对及可重建父图增量 |
| [ci-87-observations.tar.gz](ci-87-observations.tar.gz) | 原 head 87 的 103 项 CI 快照、原 coverage 失败日志及实际步骤边界 |
| [platform-review-observations.tar.gz](platform-review-observations.tar.gz) | AppContainer 与 Windows 私有目录后端的只读审查；没有把旧分支当作已完成 AuthBus 修复 |

每个归档只包含普通文件，`ARCHIVE-INDEX.json` 列出原始来源、大小与 SHA-256。打包后已逐成员回读，完整字节等于冻结原文件；原补丁和日志的空白未清理。可用 `tar -tzf 文件名.tar.gz` 查看清单，用 `tar -xOzf 文件名.tar.gz ARCHIVE-INDEX.json` 直接读取索引。

父图增量以上一批已保存的 `complete-known-parent-graph-7812.tsv.gz` 解压原文为基线；该基线的片段重组说明见上级目录。`COMMIT-GRAPH-DELTA.json` 记录精确新增行、移除键、基线和结果摘要，已实际重建完整 79,123 节点图并逐字相等。其中五个节点是本地合并对象；远端对象映射单独保存，不把这些节点冒充快照时已存在的远端 refs。

本审查不声明所有中间补丁逐行审完，也不继承新 head 的测试资格。`main` 尚未更新；没有删除任何分支，已知 HIA 保护只增加。原第 551 个历史保护 pin 的身份缺口仍保留。
