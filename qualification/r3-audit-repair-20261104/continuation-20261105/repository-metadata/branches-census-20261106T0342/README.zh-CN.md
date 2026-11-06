# 当前全库分支元数据普查

2026-11-06 03:42:06–03:43:26 UTC 的直接 REST 完整分页实际取得5,333个不同branch名称，4,946个不同commit SHA。按API每页100，1–53页满页，第54页33项，第55页为空；批量读取时已请求的56–58空页也原样保留。没有重复名称。首/末/空页1/54/55复读正文全部相等。该窗口不是原子快照，也没有逐个重读全部ref。

实际main为732e934ba496d90fbe042b8d41d479ef901643e5、tree75dc1c1f65375c97da259d947c465a04f030461d，唯一parentf8c9419df6ddeb36ff8b522a50219981fb8d9345。已另取完整commit API。main在API中protected=true；这不是branch-protection/ruleset配置审计或修改。主修复候选67cc仍位于另一整合分支，其base636不能改称main。

包内62份完整UTF-8 API正文包括58页、3锚及main commit。正文按GitHub connector实际返回字符串逐字节保留；不将重复的MCP外包装或HTTP wire计入。SUMMARY和完整VERIFICATION中的每个branch均包含其实际name/commit SHA/protected字段。88个一级名称前缀只表示命名分组，不是Git祖先关系。普查也不表示逐行审完每个分支、该分支已测试通过或产品完成。

此前5,193分支仅是旧报告的固定时间观察。窗口结束后创建或移动的ref在各自发布回执中记录；不能把本文数字称为后续任意时刻的总数。完整PR人口由同时期单独的全分页包记录。

恢复压缩分片后，运行python verify_census.py，结果应与VERIFICATION.json逐字节相等。该脚本只读原JSON，不查询网络、不运行产品、不改变refs。
