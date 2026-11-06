# 独审原件与便携重放

这里的 14 个原件逐字节复制自独立审阅目录，不包含重复的 author-frozen 副本。REVIEW.json 实际 Git blob 为 a146f5e5faf1c0b4ea0f07b51f3d29dc80734902，结论仅为静态/离线接受，旧139份XML仍缺。

恢复时先把本包 manifest.json、12个 parts/ 分片和 restore_packet.py 放到同一目录。用原恢复器将作者快照恢复为本目录的 author-frozen 子目录：

    python3 ../restore_packet.py ../manifest.json author-frozen
    python3 verify_independent.py --root .

如果作者快照已恢复，可将该完整快照原字节复制到 author-frozen；需保留空目录，不加入后续 delivery/ 对象。原 verify_independent.py 与 static_helpers.py 不需修改。stdout 应与 INDEPENDENT_VERIFICATION.json 逐字节相等，exit0、stderr为空。

PORTABLE_ASSEMBLY.json 记录本次从作者不可变ZIP实际异地还原后，与这里的原14文件组合并重放的结果：6673字节 stdout 全等。Python静态验证器与 git apply 的正反检查属于离线核验，没有执行 Bazel、cargo、产品测试或新原生作业。

作者的1010冻结数据文件及 freeze-manifest.json 已在 manifest.json 的完整快照中；本独审增量原件独立登记，避免覆盖作者或审阅者的冻结原件。
