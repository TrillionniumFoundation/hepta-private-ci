# 原生格式失败的完整证据与精确修补候选

此包无损保留 #4936 原提交 2d1137、实际 checkout a0cb0f3 / tree99a 的 repo-checks job127779715942 原失败。完整 log178,931B、MCP decoded原返回、29-job失败切点、0758增量18-run/29-job原API、两个源的原GET与完整pre/postimage、三段实际fmt输出、正反patch和完整两树、独立审阅均在34成员归档中。

候选只重排原formatter指定的三处空白；两文件合计不改任何非空白字节。独审实际7ea9cb737a8c57a215cbf473b2ad100c25ab668b接受该精确候选，全10802叶仅两叶变，候选tree c3e9ddc1799f470ac7c80e117ee953a7232847e0。此包本身不写生产ref，也不声明后继CI已经通过；原fmt exit1仍保留。

archive-manifest.json给完整34成员、XZ CRC64归档与11个ASCII base64分片的三重身份。先将所有分片按原相对路径恢复，再执行：

`python3 restore_evidence.py --root <本包目录> --output <不存在的新目录>`

只读解包全量核对每成员，然后运行归档内的独立Python/Git checker。没有Rust、rustfmt、Cargo、Bazel、产品测试、网络或远端ref操作。实际异目录恢复exit0/stderr0，独审6767B stdout与原f6d35f9逐字节相等。完整作者和独审freeze保留；临时partial Git object库不在归档中。
