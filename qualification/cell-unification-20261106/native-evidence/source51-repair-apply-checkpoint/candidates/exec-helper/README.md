# Exec-server bwrap 夹具修复候选（r24 后）

本候选只改 `codex-rs/exec-server/tests/common/fake_bwrap.rs` 的真实程序发现顺序：在创建 shim、组装子进程 PATH 之前，调用已有的系统 bwrap 发现函数；仅当函数返回 `None` 时才使用已有仓库二进制。**没有在运行失败后改换程序。候选尚未获得原生 Rust 门资格。**

## 原始问题与实测范围

r24 的完整四包门自然退出 100。两项 exec-server 测试在真实受限文件系统 helper 启动时收到同一条 `loopback: Failed RTM_NEWADDR` 错误。原始失败块、命令、raw rc、资源记录与源码后置 guard 均原样保存在 `evidence/r24/`。

单次授权对照对两个已固定身份的 ELF 使用相同原参数：

```text
--unshare-user --unshare-net --ro-bind / / /bin/true
```

系统 `/usr/bin/bwrap`（0.11.1）退出 0，stdout/stderr 均为空；仓库 `target/debug/bwrap` 退出 1，stderr 为61字节，其中不含末尾换行的60字节错误文本与两项原失败一致。生产 helper 对 stderr 调用 `.trim()`，第一项原失败的 Rust debug 字符串因此不保留末尾换行。完整原件在 `evidence/launcher-comparison/`，独立字节、回执、原输出和命令核验在 `PROBE-INDEPENDENT-READBACK.json`。

该结果证明本次两种选择的实际表现不同。它没有确定具体内核 netlink 错误或 LSM 原因，也没有验证完整 helper、全部 bwrap 后端或修复后的 Rust 测试。诊断使用了明确记录的 cwd；原 r24 每个测试的 cwd 没有单独记录。仓库程序身份来自现存 ELF 与其 depfile，原 compiler-artifact JSON 没有被保留。

## 修改为何保持原验收含义

生产 launcher 原本优先尝试 PATH 中的系统 bwrap，并保留自己的 help/capability 资格检查。候选复用现有公共发现 API；它不把路径发现等同于完整资格判定。两个调用方先创建 shim，随后才把其目录放入子进程 PATH，因此不会递归发现本次新 shim。原 shell 其余部分逐字不变：所有隔离参数、argv0、继承描述符、日志、fail-once、退出状态和 stderr 继续传递。两个原测试文件、断言、权限、时间预算均未修改；没有依赖或锁文件变化。

完整正逆改写与原件 pins 在 `source-manifest.json`、`source-input-pins.json`、`STATIC-READBACK.json`。独立静态与 C 初始化顺序审计在 `independent-review/`。`repair-audit.json` 区分原生观察、源码推断与尚未获得的资格。`HANDOFF-MANIFEST.json` 是本目录全部交付文件的最终清单。
