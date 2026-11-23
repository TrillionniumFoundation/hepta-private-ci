# 两套 CPU 环境的连续算子复核

最终源码 `610f91087b598656f7f3913e600c705b95bf071f`、Git 树 `e7b3615a8eb989b6df6970ea0c42262811f480ce`。托管 CPU Torch 2.10 独立重算参照、有限多代空间和标记、双源连续传播、串联的两个内生 QVI 神经元，并通过全部 12 个既有具名测试。其原 60,163 字节 ZIP 保留首达正积分、产品输出、Git 状态与标准测试日志。[官方原作业](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45162302799/job/137650500461) · [原件](hosted.zip)

与 CPU Torch 2.15 的四份结果对照了 1,011 个数值，其中 202 个有浮点差异。最大绝对差 1.481×10⁻¹¹ 出现在独立程序的有限差分。双神经元报告中两环境的数值最大绝对差 2.23×10⁻¹⁶。每套环境分别在原验收条件下通过。托管侧两个分割时刻的连续传播最大误差分别为 1.56×10⁻¹⁵ 和 2.67×10⁻¹⁵，概率及有符号通量的最大误差 4.45×10⁻¹⁶。[逐文件差异和本次各项误差](agreement.json)

将本目录的 `verify.py` 和 `hosted.zip` 放在一起，执行 `python verify.py /path/to/checkout-at-610f9108`。复核器会检查原始摘要、Git 提交和树、12 个测试名称与结果，并逐项比较四份文件。[复核程序](verify.py) · [物理模型、公式与测量](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/610f91087b598656f7f3913e600c705b95bf071f/qualification/hcsn_halfline_transport/FINITE_MARKED_ZH.md)
