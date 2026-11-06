# B11 严格边界独立机制审阅：完整只读原件包

完整保留六份原独审文件及原 verifier 精确引用的依赖：v3 source-map、published 完整树、14 份 actual source；旧 boundary source-manifest、其中 11 份在 9cb 树仍 unchanged 的原件和旧 token；elevated/ipc_framed；native10/11 完整 test.log 与 XML；root 独立重放完整 stdout。未纳入 native12/13。原交错 JSON 保留原文，不补拼、修复或推断缺失值。finite explicit-read 控制不证明 ambient-read、loader、IPC 或后代产品合同；host privilege-set 干预不单归因某个 privilege，也不修复本来就 DISABLE_MAX_PRIVILEGE 的 strict token。

## 归档与重放

本包 41 份完整原件保留 `root/` 下的 workspace 相对层级。`member-manifest.json` 逐份列出原字节数、SHA-256、Git blob SHA；`archive-transport.json` 绑定无损 gzip/tar 和全部 base64 分片。相同依赖可能曾由另一证据包登记，本包仍实际包含全部所需原件，不依赖工作目录之外的历史包。

在 Python 3 环境运行：

```sh
python restore_readonly_evidence.py
```

程序验证完整分片及每份成员，将所有原字节保存于新临时目录后执行未修改的原只读 verifier。实际 stdout 必须与归档内原冻结 stdout 完整 `bytes ==`；每一成员在恢复前后也做直接完整字节比较，且不得产生额外文件。不会重新查询 API、dispatch/rerun/cancel、查询 native 容量、编译或运行原生测试。

`offline-roundtrip.stdout.json` 与 `.execution.json` 记录此次离线恢复的实际回执。Git 实际登记采用 `create_tree(content)`、实际递归 tree 对照、每个 blob 的完整 full GET 字节比较；不更新任何 ref。最终实际清单见 `registry.actual.json` 和独立 self receipt。

## 结论范围

Frozen static strict-boundary mechanism review with existing native10/native11 originals; no native12/native13, new execution, or qualified product repair.

证据封存和静态重放不改变原 blocker 状态，不替代 AGENTS 所要求的项目 test/fix/fmt；这些命令在本封包中保持 NOT_RUN。
