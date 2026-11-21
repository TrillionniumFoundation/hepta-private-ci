# E6 NoUpdate18：完整失败原件与独立 shell 诊断

本追加包保留一次真实失败的 native NoUpdate18、其后一次成功的只读收证，以及一次独立 shell 环境探针。原件、传输响应与后续复核分开标明来源。原有 137 个 blob 的证据提交 `45cb05764454be5386488dc689d7dc65c182e629` 保持不变；本目录不包含 NoUpdate19 候选，也不包含新的可执行验证器、allowlist 或 ignore 变更。

## 已经发生的结果

| 作用域 | 真实结果 | 证据边界 |
| --- | --- | --- |
| Native NoUpdate18 | H job `1a1fd80ebdb-ffbe-1f71`，failed / exit 1 | 四个 nextest `--list` target runner 在环境检查处拒绝，原 nextest 命令 exit 104；当前 canonical 用例通过 0、失败 0，ordinary 未执行。 |
| 原件收证 v3 | H job `1a1fd9f4090-ffbe-1fb6`，succeeded / exit 0 | 完整读取 83 份原件共 13107210 B；原始 main、62 项输出库存、每个成员 SHA 与字节数均匹配。 |
| 独立 shell 探针 | H job `1a1fd92a5fb-ffbe-1f90`，succeeded / exit 0 | 13 份原件共 55292 B 及 H → POST_FSYNC → RESULT → stdout / inputs 的对应关系已独立复核；执行 native / cargo / nextest 次数均为 0。 |

Native NoUpdate18 的首错是 `CARGO_BIN_EXE_codex-hepta-agentd` 在 runner 环境中不符合封存输入。四份 refused 原 JSON 发生在目标 ELF 打开前，不能作为四个 Rust 测试失败，也不能证明 same-FD ELF 执行身份。完整首错 log 为 42299 B，SHA-256 `93ce299218e67ecad9be9342c06f21dbc0ec9d50085d5bbb64a1f803a8c22a77`；配套 execution stdout 为 44043 B，均保存在原容器中。

原 main 的 `native_build_mode_restored` 为 false，并保留原原因 “Original terminal sealing/cleanup prerequisites were not complete.” 两个 retained ELF 的复制与回读收据成功，复制品 mode 为 0o444、donor chmod/write 为 0；这不表示 native source mode 已恢复。原 prior/excluded JUnit 属于历史记录，不计为当前 18 用例。此前 descriptor `--list` 预检及构建仍保留在工作记录中，不能把当前 canonical 用例为零写成没有计算工作。

独立探针实际 shell 为 `/usr/bin/dash`。14 个显式报告的环境键中，三个名称含连字符的 CARGO_BIN_EXE 键在原 just-shell → sh → reporter 路径后缺失，另外 11 项保持相同。这是新的诊断观测，不回填 NoUpdate18 当时的 actual environment，也未覆盖 just CLI exports、CI recorder、run-nextest、cargo、nextest 环境构建或产品 / 测试二进制执行。

## 容器与逐成员索引

`CONTAINERS.tsv` 给出容器长度、SHA、成员数与分片顺序；`CHUNKS.tsv` 给出每个原始二进制分片的偏移、长度与 SHA；`MEMBERS.tsv` 给出两个容器的每个成员 SHA。`SUMMARY.json` 提供机器可读结果及全部资格标志。

- `native18-originals`：原 `74v3_noupdate18_rebuilt_originals.tar.gz`，2177942 B，SHA-256 `d6ae47ae7f380c247346e7e1a33dc90880d7df9940d53da870ff39e880d12c9e`。原压缩字节未改，共 84 个成员：83 原件加原 READBACK_MANIFEST。
- `native18-sidecar`：新建 sidecar，保存 root 原始 launch / H / transport / review，完整 core 与精确解码的日志，所有 43 次分片读取原响应和核验收据，冻结的收证候选及 v3 执行输入，独立 probe 的 13 原件、传输记录和新复核。sidecar 内 `SIDECAR_MANIFEST.json` 逐项记录来源路径、角色、长度与 SHA。

未重复打包 native 归档的展开目录或已重建的分片二进制副本。原 MCP text / base64 内容保留在原响应快照中；纳秒整数由原 text / base64 字节或 Python 整数解析保留，没有用 JavaScript Number 重序列化原件。准备稿中的“未执行”是当时的原始状态，后续真实执行另由 root H 记录与结果文件证明。

分片为真实二进制，每个不超过 350000 B。按文件名顺序拼接到新路径即可恢复容器，先核整包 SHA，再查看或按安全路径规则解包：

```sh
cat payloads/native18-originals/part-*.bin > /tmp/hepta-noupdate18-originals.tar.gz
sha256sum /tmp/hepta-noupdate18-originals.tar.gz
cat payloads/native18-sidecar/part-*.bin > /tmp/hepta-noupdate18-sidecar.tar.gz
sha256sum /tmp/hepta-noupdate18-sidecar.tar.gz
```

这些是人工恢复步骤，不是新增可执行门禁或测试。若目标临时文件已有内容，应改用新的路径，避免覆盖其他证据。

## 收证、传输与资格

v3 在冻结 v2 基础上只为三个新增自有传输日志加显式 fsync，并 fsync 输出目录；失败会强制 unsuccessful。原远端只读归档逻辑除 schema 版本外字节相同。实际收证的三日志 fsync、H 完整 / durable / confirmed、H → launch → capture → archive / core 均已核验。读取为逐文件稳定检查，不能称为原子快照。

42 个有效分片覆盖两份原件，发生了 43 次读取请求。一次 archive offset 262144 读取返回 SSH helper exit 255，原响应为 “Connection closed by 10.77.0.1 port 22”；只补取了同一版本的缺失范围，随后整包 SHA 与所有成员 SHA 匹配。超出返回消息的连接关闭原因仍为 UNKNOWN。失败原响应没有删除，也没有重跑 collector 或 native 来掩盖该错误。

收证成功、诊断成功与 native 失败分别保留。source qualification、完整 NoUpdate、cold/restart、Adopt、next-task improvement 与联合科学资格均为 false；本追加包不新增独立科学样本。它为下一次严格限定的工程修正提供可重放的失败依据，不证明训练有效、在线学习改善或 BP / 编辑方法的速度优势。
