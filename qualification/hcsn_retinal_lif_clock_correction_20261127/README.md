# 视网膜事件关联的 LIF 时钟修正

原分析沿用 2 毫秒皮质记录的指数泄漏系数，而视网膜输入每 1 毫秒推进一次。修正版以真实的 1 毫秒计算膜泄漏和适应衰减。保留原有试次、标签归属、六个因果滤波器、门限、重置、初始状态、四个候选及读出，其他模型使用已封存预测。原 LIF 分值作为参照单列。修正登记提交 e519fae333cd58715aea798052da9745374a1836，选定参数在冷测前封存于 9d5dab6115d736dbe0a9cb3f936b9298d336493d。

在 3,668 个训练事件和 1,028 个开发事件中，原规则选中尺度 0.6、岭系数 0.0001。另进程评估十个完整保留试次共 1,774 个输入，1,291 个符合下游脉冲关联规则。旧模式使用原始封存系数逐点重现旧 LIF 概率，最大绝对差为零。

| 项目 | 平均试次 log loss 或配对差 | 95% 试次重抽区间 |
|---|---:|---:|
| 修正 1 毫秒 LIF | 0.291434 | [0.256765, 0.320388] |
| 修正 LIF 减原 2 毫秒 LIF | +0.006786 | [−0.001889, +0.015876] |
| 修正 LIF 减预测端口 | +0.010475 | [+0.004359, +0.016579] |
| 修正 LIF 减四时域增强端口 | +0.010143 | [+0.003437, +0.016894] |
| 修正 LIF 减单边界 | −0.006293 | [−0.017655, +0.005652] |

正差表示修正 LIF 的对数损失较大。原 LIF 的平均试次损失为 0.284648。修正的总体事件加权对数损失为 0.290903，平均试次 Brier 为 0.085629。该事后敏感性分析只涉及一个视网膜至外侧膝状体的在体记录，试次之间共享同一记录条件。预测端口与四时域增强端口的原始主比较未重新拟合。

在当前目录执行。legacy 为原 synapse 目录，包含 cold.npz、seal.json.gz；单独的 Git 归档中的 legacy_evidence.zip 提供同样两个文件。编译时使用 GCC 和 C++17。原始神经数据为 CRCNS ch-epfl-2009 Challenge D。

```bash
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
python verify.py . ../
g++ -O3 -std=c++17 -fPIC -shared lif.cpp -o /tmp/lif1ms.so
mkdir -p /tmp/lif1ms-run
python correct.py fit /path/to/raw/D /tmp/lif1ms.so ../ /tmp/lif1ms-run/SEAL.json /tmp/lif1ms-run
python correct.py confirm /path/to/raw/D /tmp/lif1ms.so ../ /tmp/lif1ms-run/SEAL.json /tmp/lif1ms-run
python verify.py /tmp/lif1ms-run ../
```
