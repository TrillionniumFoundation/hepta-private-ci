# source50：原生锁更新闭合证据

本组保留实际 just bazel-lock-update 返回0、原始资源/日志/外层终态，以及两份锁更新前后完整字节相同的证据。实际 source50 commit 为 1fdd647b0ecb235530e8b88bbea45b3d3762906f，tree 为 ea48acf562499192a25e05ae28926a32632dee62；原生成快照的 source_commit:null 和当时待冻结标记均原样保留。

Bazel 工具下载的早期失败、成功第4次准备、六条原始 Bazel warning、锁归档导出第1次失败均保留。77 MB 工具及分块二进制不进入本组；本次只复核原始工具回执，不冒称重新读取工具本体。完整锁归档包含29件，28行 INDEX；INDEX 是原文件权限，tar 运输权限独立记录。四份 raw lock 以 mtime=0 gzip 无损保存。

INDEPENDENT-READBACK.json、CLOSURE-MAPPING.json 和 ATTACHMENT-MANIFEST.json 定义完整范围及缺件。该锁前置条件通过不表示 Rust、r24、r25 或科学资格通过。旧 source50-provisional-repair 是历史准备快照，未被改写。
