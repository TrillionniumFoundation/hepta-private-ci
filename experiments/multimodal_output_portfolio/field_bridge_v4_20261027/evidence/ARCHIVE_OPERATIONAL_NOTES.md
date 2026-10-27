# V4 归档操作记录

本地完整原始证据包已建立并通过全部校验；原资格失败结果得到精确重复。归档/恢复成功没有改变科学结论。

- 第一次 collector 正确拒绝 RESTORATION 清单中的 19 个历史 0B 占位文件。实际用于 V4 的 9 个原数据、模型及 observer 文件全部匹配；没有生成 archive 或 partial，没有科学重试，没有修改五个归档模块。首次失败日志、回执、工具及配置快照均进入最终包。
- 从既存 Library 原始包作只读恢复。整个原包 SHA、manifest 及 gzip EOF/CRC 通过后，严格补齐 19 件（62,146,791 字节），9 个研究输入不写，前后身份一致，原 RESTORATION 不变。28 个原资产现全部按原 bytes/SHA 精确匹配。历史原包本身不嵌套；Library ID、SHA、manifest、读取及恢复回执已保存。读取 helper 的第一次网络失败由原读取回执保留；这不是上传重试。
- 第二次 collector 成功固定 945 个成员、487,105,575 字节。唯一实际 build 成功，压缩包 415,960,474 字节。完整读取校验了全部成员 SHA、外层 gzip CRC/物理 EOF、119 个内层 gzip 的 CRC/EOF，无异常白名单。
- 实际恢复 280 件、15,622,988 字节。新进程执行恢复目录中的归档脚本及冻结 analyzer，唯一统计验证精确重复所有注册统计及 bootstrap 身份，结论仍为 QUALIFICATION_FAILED；没有新 outcome look、方法选择、模型或 observer 调用。
- 完成后重新核对全部 945 个输入 bytes/SHA，以及 run、science、review、freezes、assets 五棵树成员集合，均与打包前一致。
- build 前按精确 tar、匹配 libz 的 deflateBound、实际恢复量、回执预算及 32 MiB 余量要求 538,781,749 字节，当时可用 846,438,400 字节；没有删减独有证据或依赖经验压缩率。

归档 SHA：716b1291ee2fe1271f50589222fec9793b87a5bcae156c7af8e498c6c80f9df7。
Manifest SHA：fd05cac4184a7c468b4da057ea0f84e7ffe0e8978dd25287840f6117fb215cd0。

ARCHIVE_AND_RESTORE_VERIFICATION.json 与 EVIDENCE_ARCHIVE.json 绑定完整操作回执。它们是明确的 postpackage、自身不入包回执，避免 hash 自引用。发布时无需把 3.45 MB 原 manifest 或原资产 raw 重复放入 Git；其完整字节已经在包内。旧 V2/V3 大 tar、临时 Torch 和旧研究全部生成史均未嵌套，范围及原包 SHA 引用明确列出。

此链没有上传新文件。完整 raw archive 目前只有已验证本地文件；未确认另有持久副本。原资产包的已存 Library 只读下载与这个 raw V4 包的持久化是不同操作。
