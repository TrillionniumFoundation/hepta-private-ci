# 空 WAL 的只读快照后处理验收

新增入口为 `scripts/review_hepta_maintenance_snapshot.py`，不修改冻结运行模块或旧 verifier，也不进入 worker 执行 closure。

```bash
python -B scripts/review_hepta_maintenance_snapshot.py SOURCE_DIRECTORY --snapshot-dir NEW_SIBLING_SNAPSHOT --output NEW_REPORT_JSON
```

源目录只读打开，不 chmod、不调用原数据库 SQLite、不 checkpoint；调用前应停止源树写入者。snapshot 与 report 必须都在源树外，snapshot 也不能包含 report；两个输出必须尚不存在，父目录必须存在。

只允许省略 `memory/owner.sqlite-wal`、`predictor/owner.sqlite-wal` 两个明确 0 字节文件。任何非空 `*-wal` 拒绝；其他普通文件逐字节复制，包括 SHM 和无关空 WAL；symlink 与非普通文件拒绝。新副本移除写权限，再调用 SHA 固定为 `899723e…` 的原 `verify_hepta_maintenance_cycle.review()`。

报告保存 copy 前、copy 中、copy 后及 review 后的源文件/目录身份、大小、SHA256、mode、mtime/ctime；同时保存副本 review 前后清单、允许省略的完整关系、旧 verifier SHA 和完整只读检查结果。访问时间不属于不变性口径。PASS 不声称 producer authenticity、实际 runtime transport 或新的任务收益。

## 针对性验收

对已有 local maintenance 原件的精确副本，添加 5 个明确标注的合成空侧文件：两个目标 WAL、两个 SHM 和一个无关 WAL，再将输入树设为只读。

- 正例通过：仅省略两个目标 WAL，61 个其他文件精确复制，两个 SHM 与无关空 WAL保留；旧 verifier 对既有 722 条记录通过；源树与副本前后不变。
- 非空目标 WAL 被拒绝，未创建 snapshot，源树前后不变。
- 源树中的 symlink 被拒绝，未创建 snapshot。
- 没有训练、模型 inference、native call 或夹具 compile；没有修改原 local/remote 证据。
- Ruff 检查通过；测试先执行、最终格式化随后完成。归档保留两版源码及 AST 相等记录，冻结模块和旧 verifier 字节未变。

[validation-records.tar.gz](validation-records.tar.gz) 保留全部验收记录、原始报告和格式前后源码；[RECORDS.json](RECORDS.json) 给出逐文件摘要与压缩包摘要。未重复归档输入/输出中的 58 个既有 campaign payload 文件，它们可与原 [maintenance 原件](../../cell-hia-maintenance-20261116/raw-evidence.tar.gz) 逐 SHA 对照；新增 5 个输入侧文件均为显式空文件。完整本地验收树另保存在 `evidence/maintenance-snapshot-review-001`。

这份验收是后处理方法验证。真实 remote campaign 的后处理报告必须对真实原件另行生成，不能使用本地验收结果替代。
