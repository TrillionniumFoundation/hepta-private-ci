# main67 CI 01:04 状态切点：完整只读原件包

本切点含 19 个 run、53 个 job 和完整 20 次 API 原响应。状态为 19 success、23 queued、9 cancelled、2 skipped。23 个 queued job 无 runner、无步骤，两个额外 pending run 的 job 数为零。两个新终态 V8 job 的 raw log 与完整 MCP 解码内容相同，保留 CR 字节。ARM 取消原因未确定：elapsed 时间及取消消息都不能证明超时或操作者；不可用 check-run 的 400 原响应也完整保留。

## 归档与重放

本包 29 份完整原件保留 `root/` 下的 workspace 相对层级。`member-manifest.json` 逐份列出原字节数、SHA-256、Git blob SHA；`archive-transport.json` 绑定无损 gzip/tar 和全部 base64 分片。相同依赖可能曾由另一证据包登记，本包仍实际包含全部所需原件，不依赖工作目录之外的历史包。

在 Python 3 环境运行：

```sh
python restore_readonly_evidence.py
```

程序验证完整分片及每份成员，将所有原字节保存于新临时目录后执行未修改的原只读 verifier。实际 stdout 必须与归档内原冻结 stdout 完整 `bytes ==`；每一成员在恢复前后也做直接完整字节比较，且不得产生额外文件。不会重新查询 API、dispatch/rerun/cancel、查询 native 容量、编译或运行原生测试。

`offline-roundtrip.stdout.json` 与 `.execution.json` 记录此次离线恢复的实际回执。Git 实际登记采用 `create_tree(content)`、实际递归 tree 对照、每个 blob 的完整 full GET 字节比较；不更新任何 ref。最终实际清单见 `registry.actual.json` 和独立 self receipt。

## 结论范围

Frozen current-head metadata and two complete V8 original logs only; not a new native/product/artifact qualification.

证据封存和静态重放不改变原 blocker 状态，不替代 AGENTS 所要求的项目 test/fix/fmt；这些命令在本封包中保持 NOT_RUN。
