# 独立复核：H2 来源容器 API 的机械修复

复核者：`control_next`。只读比较三个 v2 文件与保留的原文件，并检查来源 loader、容器定义、第一次失败日志和身份记录；没有执行模型、重新读取来源数据或查看新结果。

`v6.data.SourceCorpus` 明确定义 `splits` 和 `manifest` 两个字段。`h2_sources.load_registered` 校验实际协议、来源分配、候选依赖、XNIST archive、实际元数据和像素身份，以及 pair/writer census 后，返回 `SourceCorpus(..., record)`；`record` 就是经过校验的完整 allocation。

| 文件 | 唯一变更 | 新 SHA256 |
| --- | --- | --- |
| `collect_qualification_v2.py` | 接收 `corpus`，再读取 `corpus.manifest` | `4bfdc729f34aff0a1c1e861f7665bdf05667a60b3e4dff3cf6307977666fab3a` |
| `run_v2.py` | 同样修正容器读取方式 | `4b3b1cd0795493d4a5139e0bdabe4abc00e6ccc7bc5bd1fb6b3b4b9e510c62b2` |
| `prospective_v2.py` | 资格连续性读取 `CALIBRATION_PROTOCOL_V2.json` | `4331a8f78953cd966cd0042c982e1e51dac7326dd5cafd9cc6eca8898bf10e3b` |

逐字 diff 没有其他变化。collector 的角色名、100/1000 pair 检查、逐请求 source ID、所有五种决策状态和生成/计分顺序不变；执行器仍使用同一经过校验的 allocation。模型、teacher、概率 cuts、bins、来源列表和统计门槛均未修改。

首次 `calibration-001` 的实际 traceback 在 tuple unpack 处报 `TypeError: cannot unpack non-iterable SourceCorpus object`。该目录只有 `access-registration.json`，模型加载位于失败点之后；第一次确实已经读取来源像素，但未生成或评分输出。失败进程记录和日志 SHA 均与 [修复登记](SOURCE_CONTAINER_AMENDMENT_V2.json) 一致；登记 SHA 为 `e46c383c70a6ec9c18aead3552bd3c8114e08d1de6f957f4f9ba7673cb6bb5a6`。原 `CALIBRATION_PROTOCOL.json` 的 72 项 pins 全部保持一致。

结论：这是修复已验证对象的读取接口，不是因模型结果而更换来源或调整科学候选。可以在明确保留首次来源访问、失败和零输出事实的独立 v2 协议下，重试同一已登记的 100-writer calibration role。静态复核不预判重试是否通过校准或后续资格。
