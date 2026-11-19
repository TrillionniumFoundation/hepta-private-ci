# 草稿资产对账结果

两个既有研究资产已完成认证全字节回读、ZIP CRC 与匿名 API/下载地址 404 检查。官方数据资产的唯一新上传尝试失败；随后完整资产列表显示 starter 记录，不能记为成功归档。

| 资产 | 状态 | 标识与字节 |
| --- | --- | --- |
| cloud-p2-diagnostics-20261110-v1.zip | 完整验真；没有重传 | 731802015；17,670,639 B；157 ZIP 成员 |
| hcsn-width16-v6-audit-20261110.zip | 完整验真；没有重传 | 731824485；4,460,517 B；109 ZIP 成员 |
| official-localization-cloud.zip | starter；digest=null；认证下载 HTTP 404 | 732265694；服务端声明 6,290,730 B，不等于成功上传的字节 |

官方上传命令返回 HTTP 408（上传体因不活动超时），耗时 537.948344583 秒。release GET 的内嵌数组只有 17 项，没有显示该 starter；独立 assets 列表有 18 项，明确显示 starter。因此原 main v5 的 still-absent 错误必须按该观测范围理解，不能推导远端完全没有记录，也不能将该脚本复用为通用缺失判断。没有删除、覆盖或再次上传这个资产；草稿状态保持。

原始官方文件仍完整保存在 cloud 和 main：6,290,730 B，SHA-256 为 6660124b4d1fd98963c56a6804bbb0ca0c5ee12edc9b772c8a867148af20d0da。原官方 UCI 下载回执为 HTTP 200，完整来源在 main capsule 中。此后的两个 desktop UCI 下载失败均保留为失败，不改变原始文件来源。

## 新增费用口径

| 阶段 | driver wall（导入后，秒） | driver CPU 采样（秒） | waited child CPU（秒） |
| --- | ---: | ---: | ---: |
| desktop_reconciliation_v1 | 111.995613426 | 0.592835367 | 2.113424000 |
| desktop_official_download_v2 | 36.592069619 | 0.095766957 | 0.940016000 |
| main_source_upload_v3 | 35.384080333 | 0.060820000 | 0.101152000 |
| main_official_upload_v5 | 546.374290750 | 0.065455000 | 0.255088000 |
| desktop_official_readback_v4 | 12.239633030 | 0.093011667 | 0.919475000 |

CPU 采样来自进程启动后的累计时钟，但发生在最终 receipt/manifest 序列化和进程退出之前，不是完整 exit rusage。子命令 wall 嵌套在 driver wall 内，不再相加。五段 driver wall 合计仅用于列清这五个区段，不能冒充端到端时间或全部费用。

原 main uploader 的 1258.598167125 秒包含官方原包下载 639.887319916 秒及其失败回读；该下载不能再次加总。原 width16 成功 uploader 的 92.554298136 秒另行保留。两个 capsule 构建的 wall/CPU 以及不成功的文件传输 RPC 时长单列于 SUMMARY.json。能源、货币费用和完整总账仍未知。

cloud→desktop 的另一路文件传输只确认到 offset 196608；后续 524288 字节块及同 ID/同偏移的精确重放均超时。没有发送 commit，目标没有发布，之后停止传输。不能把超时视为成功字节，也不与本次 GitHub 上传混为一项。

## 复核与复制

两个 ZIP 共 140 个成员，逐成员尺寸/SHA-256、ZIP CRC 和路径安全已在 cloud 再核。原始大读回文件及失败 partial/empty payload 没有重新嵌入小包；PAYLOAD_REFERENCES.json 保留原生路径和完整哈希。原小型 receipt、API 元数据、日志及源代码字节均保留在包内。

复制清单见 COPY_LIST.json；SUMMARY.json 为机器可读结论、每条原始来源和费用作用域。此工作没有新增训练、数值资格或科学收益信用。
