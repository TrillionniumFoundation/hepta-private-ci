# Vendor whitespace 候选的来源与限定核验

准备基准为 4ffa56f6d0be94e68d23d1bfe72aa2cbfd50d479，发布基准为 6ca37caad90259aaad76c89d4f6a5a64715ab041。
发布基准已包含两处完全相同的 Rust 源码字节；本分支只增加两份说明、两份来源 JSON、通知清单四标量校正与三份证据文件，不把已集成源码再次算作新增修复。

## 已有实测

第二次隔离准备的八个登记命令全部 exit 0。官方 just fmt 成功，七路径 git diff --check 成功；二者 stdout/stderr 均为空。95 个前置文件和 60 个准备后文件前后逐字一致，44 个原 formatter guard 保留。准备耗时 0.5343002500012517 秒，其中 formatter 0.2690384581219405 秒。

第一次失败的完整证据仍在档案内：稀疏准备遗漏两个原 Cargo.toml，构造格式化命令时落到虚 workspace 的 manifest，触发 KeyError package。该次未启动 rustfmt。第二次仅从原基准补齐两个 crate manifest；未改候选、原 guard、toolchain 或旧失败结果。两次 DIFF.patch 的 SHA256 相同。

## 具体范围

- Starlark 只删除空文档注释后的两个空格；旧 registry/checksum、78 文件收据及三份 patch.gz 保留。
- Serde 仅把 raw YAML 字面量改为 escaped Rust 字面量，运行时 20 字节、空格与制表符及三个尾 LF 不变；原断言未改，未执行这个 fixture。
- 两份 HEPTA_PATCH.md 仅在原正文后追加来源说明；两份新 provenance 保持准备基准 4ffa，旧五 fixture 成功没有转授给本候选。
- AccessKit 通知清单仅更新两个既有通知文件的 bytes/SHA 四个标量；缺失的 common README hunk 仍未闭合。

## 资格边界与恢复

本次发布器只做字节核验、真实 tar.xz 归档与 Git 数据发布，0 次新增格式化、编译、测试、模型、训练及 optimizer 调用。准备阶段同样 0 次编译、测试、模型或 optimizer 调用。七路径增量检查不等于旧 8ce 来源运行所记录的 183 路径/243 警告门通过，也不提供 Windows/native 运行资格；全仓科学与生产 HOLD 保持。

按 INDEX.json 的 ordered_parts 顺序连接（当前为一个真实 .tar.xz），先核完整 bytes/SHA，再读取档案内 MANIFEST.json 逐成员核验。档案保存 174 份显式原始输入、两个准备尝试的原件、完整 scaffold/guards、原失败与成功命令流、当前七候选、发布输入和发布脚本。读取脚本字节不代表运行脚本；恢复原件后不要自动执行其中程序。
