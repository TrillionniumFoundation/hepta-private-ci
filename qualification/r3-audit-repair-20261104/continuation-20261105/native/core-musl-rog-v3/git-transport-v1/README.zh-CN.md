# Core / musl 原生验证输入检查点

本目录只保存首次原生启动所需的已审输入。此提交不改变产品代码，不表示构建、测试或发布通过。

- 产品源：`5b6331250ff459033bd44d1a95daec70131277cc`；两文件候选 tree：`e78c819b8b1f435f8b37bea17b4ffdc724961aa2`。
- 完整启用请求：1,261,663 bytes，SHA-256 `148243830f8a8c36ae7fe85822160c4a7dfd19bf5a06d0d3daef7c5ccc8edaaa`。
- gzip：926,608 bytes，SHA-256 `98f1c3e0e36d268659e2522e7d6a82ec71c2855950b815fbb35ae008cd8e5083`；三段严格 base64 在完整重建及 hash 核验后使用。
- V3 loader、776-byte control、原始执行 key 和启用请求均保持原字节。原执行范围及停止条件见 [root-execution-guard.json](root-execution-guard.json)。

此前有序 binary_upload 已确认前六块 393,216 bytes，offset 393216 的第七块及其一次同参数协调均返回工具超时；没有调用 commit 或本 Core 的 process_start。原上传临时分片与响应保留。此检查点支持通过固定 Git commit 在新任务私有目录读取同一输入；后续启动器仍须独立核准、检查原 staging 路径不存在并以 create-only 写入，再进入原 V3 源码与容量守卫。不得借此重放另一个状态未知的 B16 driver。

完整 gzip/raw/分片身份、原 loader/control 与候选绑定见 [transport-manifest.json](transport-manifest.json)。当前综合进度继续以仓库的审计主报告及其明确时间切点为准。
