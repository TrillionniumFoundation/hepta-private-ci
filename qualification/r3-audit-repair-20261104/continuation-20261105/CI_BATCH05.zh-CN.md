# 原 0e139 CI：主测试取消的最后增量

本批 API 截止 **2026-11-05 08:25:35 UTC**。产品作业仍为原 `0e139b599f0fe451f80fb7db4b2913bb9c679dce`、`run_attempt=1`，没有重跑、取消、dispatch 或 ref 更新操作。

原 GNU 主测试 job `127089469040` 在 08:20:31 被取消，完整日志 674,404 字节，SHA256 `583b9dd9feb27984952f953eddb06213d5fe517ffd1da7cbff618cd3aedafdc6`；最后只到 186/435 的动态目标进度。原 musl-label job `127089469218` 在 08:17:42 被取消，完整日志 98,616 字节，SHA256 `d491d9caee170ea363634bd3a02097d4d9f8e81bdf060065150d63c7c9902896`；最后只到 114/325 的动态目标进度。两者都没有最终目标总结或完整案例名单。这些进度分母会随着 Bazel 分析改变，不能作为固定测试总数。

SDK job `127089468286` 同样取消。三份完整日志只出现通用取消信息，不能据此确定操作者或机制。主矩阵 08:22:41 快照没有 running job；08:25:35 的 architecture 与 V8 原作业快照也没有 running job。部分 run 仍显示 queued，不能把 run 层状态当作正在执行的证明。

当前主 run 的工件列表只存在 Mac ARM Clippy 执行日志元数据；没有主测试 collector ZIP。不能据此恢复未保留的成功案例，也不能借旧 head 的结果关闭本轮缺证。musl-label 主矩阵仍使用已核 GNU/RBE 配置，独立真实 musl 产品门保持单列。

[原件清单](generated-evidence/batch-05/original-files-manifest.json) 和 [传输清单](generated-evidence/batch-05/transport-manifest.json) 绑定 14 个原件、2,127,456 原始字节。2 个严格 Base64 分片重建 220,528 字节 gzip，SHA256 `b60ab3cf3284d2539d95bd5cb39202cbd71057a76e09b3fe7d3db0924762372d`；[校验程序](generated-evidence/batch-05/verify_archive.py) 已实际核对全部成员及身份。未执行任何产品测试，未改变原 23 项退出条件或闭合数。
