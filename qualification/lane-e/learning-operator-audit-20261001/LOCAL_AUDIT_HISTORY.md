# 本地审计历史与远端源码身份

远端源码快照为 `986eae8438285bf6d9a97e5f12ab6a3b1240afea`，其完整 tree `6352a2bdf4785ba1e18ffc9be1124b10b4f871e7` 与本地候选 `a318fec911d96af3ca755fd7c5b7fac8eb03a4fa` 一致。后续提交只更新导航和审计历史元数据。

验证日志中的原本地 revision 属于 `archived-local-audit-history`；原提交、父关系、文件字节和各轮修复保存在 [local-audit-history.bundle](local-audit-history.bundle)。bundle SHA-256 为 `1bce1e3ae966d8808c5be43dde74979ec888605bacebd18523bc25ef045eedc2`，Git blob 为 `3f2d8d244cda60b8616cceb6e2041e146da06468`。它依赖两个原开发分支的 commit，这两个 commit 均保留在远端源码提交的父链中。

在完整 checkout 中可核验并恢复独立审计历史：

```bash
git bundle verify qualification/lane-e/learning-operator-audit-20261001/local-audit-history.bundle
git fetch qualification/lane-e/learning-operator-audit-20261001/local-audit-history.bundle refs/heads/audit/learning-operator-convergence-20261001:refs/heads/audit/learning-operator-local-history-20261001
```

这些记录是各自范围的本地观察；当前 protected/head/synthetic/main qualification 应由工作流对当前实际候选重新生成。不得将本地回归与源码等价提升为产品完整接线、科学接受、部署或发布资格。
