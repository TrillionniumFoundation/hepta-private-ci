# E6 completion / namespace 原件独立归档核验

本包是 **9df 历史执行的完整原件归档与独立完整性验证**，没有新增模型、训练、native、普通父、cold 或 Adopt 执行，也不授予这些资格。source 身份固定为 `9dfded9cecc74e39a19bccd14b9de9dc46c02c63`，tree `d07a8a95a2f0921387446063a1a51661cbd62df7`。527e 的 namespace fixture 失败、9df 的 ordinary NoUpdate11 失败，以及归档前的 source/组件结果都保留在原件中。

## 实际核验范围

| 归档 | 原件数 | 原件总字节 | tar 实际 regular 成员 | 压缩包大小 | 原分片 |
|---|---:|---:|---:|---:|---:|
| 宿主原始归档 | 791 | 222,686,491 | 793：原件 + MANIFEST + NUL 路径清单 | 4,156,344 B | 9，最大 480,000 B |
| 本云准备/审查原件 | 516 | 25,904,697 | 517：原件 + MANIFEST | 2,255,488 B | 5，最大 480,000 B |

两个原件数分别属于两套归档，不能相加后声称是无重复的独立执行或独立数据。每个 tar 的成员名称唯一、路径安全、全部为 regular file，无符号链接、硬链接或特殊文件；所有成员长度和 SHA-256 与完整 manifest 一致。核验使用流式读取，没有把 tar 成员展开到文件系统。

- 宿主完整 archive SHA-256：`9d6848aa4145952dbd7b889a76b1f41f67de659ab90c045006c8585c43670341`。
- 宿主 manifest SHA-256：`85403eefe5ea729681d3a0bb6750ebf7ed56fc81b5d09016d87647d2917b04ac`。
- 本云完整 archive SHA-256：`119695fed1e1684dcb7a5b6d9b4350c120c923db863ed0301460d51dbc003127`。
- 本云 manifest SHA-256：`7bfb33e3e8c5145183bdbe1a25a47a96e5db52fa0dfd7a4f1b7ef376a1898571`。

全部原始归档分片在 `host/` 与 `cloud/`。完整压缩包留在本云；Git 发布准备稿不重复包含整个 4 MB 或 2 MB archive。两套 manifest 和 RESULT 均按原字节保留。宿主 `RESULT.json`、`archive-parts.json` 是 tar 外 sidecar，已单独从固定宿主路径读回并保留，不能仅靠 tar 内材料推定它们存在。本云 archive 的分片元数据原在其 RESULT，随包的 `cloud/archive-parts.json` 是从原 RESULT 确定性导出，来源见 `cloud/PARTS_DERIVATION.json`，不冒称它是原宿主文件。

## 交叉绑定

宿主归档内的两批物理输入为 **58 + 36 = 94 件，1,421,946 B**。每件已与 `PHYSICAL_ORIGINALS.json`、两份 `CAPTURED_INPUTS.json`、总 manifest 以及实际成员 bytes/SHA 交叉核对。

三份私钥只保留原元数据；其原路径不出现在归档 body 成员和 94 件非密钥物理输入中。没有读取或提取这些私钥 body。另对 94 件非密钥输入重新检查了原方案规定的 PEM 私钥标记与明确的 JSON 私钥 body 字段。这是有界检查，不声称覆盖所有可能的秘密编码。

11 件 `source-9df/` 文件的真实 bytes、SHA-256 和 Git blob OID 均与独立准备的 9df Git 对象相符。这里是本次完整变更源文件组，不声称复制整个 15,812 文件仓库。还核对了 **27 个结果 SHA 绑定、16 份宿主 driver、28 份有明确 `original-cloud-inputs/` 命名空间的本云提供材料，以及 13 份实际终态 PTY 日志**。

原 manifest 明确排除了两份大型 retained test ELF 和四份生成的 `.pyc`；其原身份和保留位置均留在 manifest，未将缺省打包说成已下载二进制。原 SUMMARY 中的 66 项物理路径库存和 149 项 runtime 元数据库存是原执行现场的有界库存，不是整个宿主的目录扫描。

## 独立验证及保留的失败

- [宿主第二次验证 RESULT](verification/host-v2/RESULT.json)：实际 PASS；SHA `9bb03e6b30500a8078890036028a318113dc0d13af642575606b6ec0e1a06983`。
- [本云验证 RESULT](verification/cloud-v1/RESULT.json)：实际 PASS；SHA `8faf0a2b2c1ebb8aabaecf63dee91de0de1cde10434116907ea8b1c575298348`。
- [完整物理、源文件与终态交叉核对](verification/host-v2/PHYSICAL_SOURCE_TERMINAL_CROSSCHECK.json)；两套 `ALL_MEMBERS_VERIFIED.json` 列每个成员的实际长度/SHA。
- [第一次宿主验证失败](verification/host-v1/RESULT.json) 及 traceback、原验证器均完整保留。初版验证器把本云提供材料查作 `drivers/...`，而真实 `ARCHIVE_OWNER.py` 明确写入 `original-cloud-inputs/drivers/...`。第二版仅修正该实际命名空间并使用新输出目录；[完整修改](verification/VERIFIER_REVISION_2.diff) 保留。archive、manifest 和原执行结果未改。

## 固定版本传输与可逆回执

宿主 archive 用 64 个 `h_binary_read` 块读取，manifest 用 6 块读取。全部 70 块绑定各自首次固定版本，检查 offset、长度、next_offset、eof、块 SHA，并在拼接后再次核完整 SHA。9 个原分片还单独调用只读 file-info 核对原长度、SHA 和版本。没有启动宿主 shell、PTY、编译、测试、下载 owner 或重试模型任务。

70 份完整 MCP 结果的本云 JSON 原件仍保留。Git 准备稿采用可逆编码：`verification/transport/RECEIPT_TEMPLATES.json` 保存每份原回执的完整 prefix/suffix、原始长度/SHA 和 donor offset/length；只有 base64 数据字符串由同一 archive/manifest 的精确字节区间重建。没有丢弃其他字段。这不表示 Git 中存有未经编码的原 RPC 文件。

`verification/transport/RECONSTRUCTION_RESULT.json` 记录实际重建结果：**70/70 与本云保留原件逐字节及 SHA 相等**。重建器只在新的本云目录写输出，不访问远端。

## 从分片重建

在本包目录执行，输出目录必须尚不存在：

```sh
python reassemble_archives.py --package . --output /absolute/new/archive-output
python verification/tools/restore_download_receipts.py \
  --templates verification/transport/RECEIPT_TEMPLATES.json \
  --archive /absolute/new/archive-output/original-evidence.tar.xz \
  --manifest host/MANIFEST.json \
  --output /absolute/new/receipt-output
```

第一个工具只拼接并核对两套压缩包，不提取 tar。第二个工具重建原回执序列并核对各自原长度/SHA。保留的 `verify_archives.py` / `verify_archives_v2.py` 是本次实际本云审计源程序，包含与独立本云 Git source shadow 的比对路径；不是删除这些依赖后即可运行的简化验收。

本包只准备提交文件，没有创建 Git blob/tree/commit，也没有更新 ref。原报告和研究附录按 Root 要求冻结；对后续 source 的结果，不从本次 9df 历史归档迁移资格。
