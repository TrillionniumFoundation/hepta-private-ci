# 连续阈值和一次释放的双运行环境核验

在 CPU Torch 2.10、Python 3.12.16 上，托管作业对 #7015 的确切提交完成两套数值验证与原四个模块中的 12 个测试。在 CPU Torch 2.15、Python 3.12.14 上，独立工作树执行了相同的 12 个用例。两个输出分别有 150 个和 308 个数值叶节点，逐项等值。逐字段比较覆盖概率、相位、存活与重置质量、有符号内容以及梯度。原记录也保留了实际运行时版本和警告。

从本证据提交的项目根目录运行 `python qualification/hcsn_ci_readbacks/halfline-67b04d5/compare.py` 即可使用标准库重新校验源码指纹、原 ZIP、原测试名单和数值。运行数值计算本身的操作说明随[研究实现](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7015)提供。[原生托管作业](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45126290551/job/137531254957)
