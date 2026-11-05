# H4 实际内容引用归档计划与压缩传输独立审查

## 结论与范围

对冻结的实际计划 `c917633ed8b22fa7a97455ea06c4a96fecc4a208375899bd3afededebf007619`、请求 `23aab51a4e4802c75d75712e955f3558d28b187e4243d4e68a88bf3e92a3b452` 及新增有界传输解码器的只读审查，**未发现具体执行阻断或接受错误内容的路径**。独立本地核对实际传输字节、原 inventory、父包索引、release 证明和已有三项 utility 的原 receipt/log，结果全部一致。

这份审查只确认输入与协议绑定。没有 dispatch、读取远端 ELF、重新运行 native、执行归档或运行消费端。因此它不授予归档完成、二进制持久化、下载闭合或联合发布资格。H1 bulk 保持暂停。

## 实际输入绑定

| 输入 | 独立核对结果 |
| --- | --- |
| H4 原运行 | `1a1ade2970f-fc05-5b5c`，源码 `6db78eca53a5acdda0d96873d3f4cd65863426f0` / tree `e91f5994017fc5d2cfe58d405a20ee6ad9376772` |
| 原 inventory | 525,002 字节，SHA `a1e42612d6a89337144b00335da2fa690dc7f503b46532ff795f0c92198bdd9c`；plan 内 base64 解出后逐字相同 |
| 原观察 | 11 个镜像、32 个 aliases、597 条 observations；每一列表、顺序、实际路径和原 outcome 字段均与 inventory 相同 |
| 选定原文件 | 每个镜像明确选择原 `retained_aliases[0]`；另外 21 个 alias 只保留观察，不冒称本次重读 |
| 表示方式 | 11 个 `referenced-complete-image`、0 个 embedded ELF；逻辑内容 1,674,575,368 字节 |
| 后置预算 | 请求实际 `timeout_seconds=900`；这是独立归档预算，不改变 H4 原 native 5,400 秒或单例 60 秒 |
| 幂等键 | `93bfc-hepta-h4-actual-reference-images-export-01` |
| release | `dcdd164eb680465a440bf9dc4e11ab68c5598d8cb86a4d99320784d0a5b68107`，同一 H4 job，权威终态 1793919910435、exit 0、未超时，精确 owned 进程已清空且没有杀进程 |

源代码、旧运行的资格和当前归档表示没有混合：FinalUse 辅助 child 仍没有 case 信用；ordinary 第二代仍是 held-object reuse，未变成第二次完整 SHA；H3 的失败状态没有被改写。原 inventory 之前已独立核对全部 301 FD、294 live、两代 daemon 与原 raw。本次仅复核这些原字段没有在计划组装或压缩过程中被替换。

## 唯一父依赖

固定父包仍是已经审查的完整 H3 包：

- archive 283,427,280 字节，SHA `5365fcf900781044108e9642ae02a110e4ac8d031d9ee516c4f0b0e471e1e773`。
- index 294,654 字节，SHA `b023aca6ab2dccf4324dccab2e5319a00ef9b32773e0dc73127efc9af3caa002`。
- completion SHA `93d7bf08914054e4bcf05f17eea3cd5ef36fac9bbf0d1e601dda59084e758cd3`。
- 完整父索引含 11 个 ELF 与 16 个实际归档成员；每个 H4 reference 的 member、字节数和 SHA 精确命中父索引。

计划中的父身份逐字段等于未改动 `ce96…` exporter 的唯一 `PINNED_PARENT`。没有 partial、第二父包或传递引用。11 个同内容镜像只是索引元数据匹配；实际运行时仍必须完整重验父包字节与所有成员。

## 新传输解码器

`transport_payload.py` 为 1,205 字节，SHA `6160a7dc42e570ae51b49ae8c5f44fc59c4eba60b1333577a1c51c0ce4063b84`。本次实际压缩数据 190,197 字节，解出 bundle 1,706,220 字节，二者均在 4 MiB 固定上限内。

解码顺序先核声明长度和 base64 长度，再核完整压缩字节 SHA；`decompress` 使用声明原文长度加一作为输出上限。必须同时满足原文精确长度及 SHA、流已结束、无未消费输入、无尾随输入且无缓冲输出。截断、追加字节和第二个 zlib 流都被拒绝。原文较大并不会通过无限解压申请绕过上限。

独立审查程序没有导入或运行 bootstrap/exporter。它以 AST 读取冻结 literal，独立解码实际 payload，核对 bundle 恰含两个唯一成员：

| 成员 | 字节数 | SHA-256 |
| --- | ---: | --- |
| `archive_reference.py` | 43,223 | `ce96de09dc981311753d37312c1b254751cce3b40c4f950f603303a523508425` |
| `H4-reference-export-plan.json` | 1,236,214 | `c917633ed8b22fa7a97455ea06c4a96fecc4a208375899bd3afededebf007619` |

两成员的实际内容逐字等于本地冻结原件。请求 stdin 逐字等于 bootstrap；bootstrap 又逐字等于原 decoder、固定 literal 和已读 builder 模板，未附带其他代码。原成员 base64 在有限 bundle 内，并在落盘前再次核精确名字、长度和 SHA。

bootstrap 使用新建 0700 输入目录、独占新文件、文件 fsync、实际只读重开后的内容核对、目录 fsync，最后以同一进程 `execv` 进入固定 `/usr/bin/python3 -B` 和原 exporter；目录已存在会失败，不覆盖旧结果。exporter 仍自核它自己的原字节与 plan SHA。此核对不将本地模板生成等同于远端 Python 的实际执行。

## 已有三项 utility

原 receipt 为 exit 0，外层 0.075066033 秒，unittest 原文为三项通过、0.001 秒。stdout 是实际 0 字节，stderr 543 字节，两者与 receipt 哈希相同。测试文件及 decoder 字节也与 receipt 一致。三项分别覆盖：

1. 精确字节 roundtrip。
2. 截断、尾随字节、第二个压缩流拒绝。
3. 声明长度、原文哈希和展开上限拒绝。

这些是已执行的本地字节控制；本审查没有重跑，也没有将它们算为 native、实际 H4 ELF 或实际父包验证。

## 仍须由实际执行和消费完成的条件

未修改的 `ce96…` 协议要求本次对全部 11 个选定 H4 原文件各完整读取两次，稳定检查文件对象、长度、SHA 和元数据，包括那些只作 reference 的文件；不能因 11/11 同内容就跳过本次读取。执行还须验证唯一 H3 父包完整 SHA、所有实际成员，再生成 H4 child 的完整 logical views。

发布并非多个文件之间的原子事务。后续 IO 或 fsync 失败可能留下 final 命名的 archive 或部分 parts；这与已经接受的 publication amendment 一致。只有权威归档成功、哈希绑定的 `COMPLETE_WITH_REFERENCED_PARENT` completion、完整 H3/H4 两包与全部原分片和成员、以及消费端 logical view 校验全通过，才能给完整字节交付信用。

原 exporter 顶部保留了 draft 时“inputs 尚未 frozen”的说明，因为这次按原字节复用；它没有改变实际 plan/request 已冻结的事实或任何验证逻辑。该说明不作为执行成功证明。

## 交付

`input-binding-verification.json` 记录独立计算、所有输入 SHA、准确请求和范围；`verify_actual_inputs.py` 可复现本地只读核对。`delivery-manifest.json` 冻结本报告、验证结果、脚本和逐字输入副本。原 ce96 协议审查与 publication amendment 保留，不重写旧审查或历史运行状态。
