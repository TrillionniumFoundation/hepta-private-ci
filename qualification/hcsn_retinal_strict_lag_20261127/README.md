# 视网膜事件归属窗口对端口排序的影响

原协议允许突触前后记录在同一毫秒。原有测试中，归入目标候选的下游事件按滞后 0、1、2 毫秒分别为 424、832、38 个。一个候选可接收多个下游事件，因此对应 1,291 个阳性候选。把目标改为最新且严格在前的 1–2 毫秒输入后，1,774 个候选中剩 869 个阳性，共改变 422 个标签。三个划分中，此规则与从原归属中去除零滞后得到完全相同的候选标签。训练阳性由 2,793/3,668 降为 1,922/3,668，开发阳性由 720/1,028 降为 473/1,028。

这是同一记录、相同十个测试试次的事后终点敏感性分析。预先已观察到重标后冻结模型出现排名反转。单独冻结方案 a6c169c56c291957e6fe6cd8b2cf8d22ec5ada6e 明确三组比较，33 个新候选、九个单截距和所有选定读出在冷测前以 c9a9fb5a4c8d138ca18e2d4f9e57ebfd39e11bf0 封存。重新载入原系数，在相同事件上重算九种原概率，最大误差为零。LIF 三列均使用已校正的 1 毫秒时钟。

| 输入或模型 | 冻结旧读出后重标 | 严格训练集只校准一项截距 | 严格标签重新拟合读出 |
|---|---:|---:|---:|
| 边界 | 1.086868 | 0.702751 | 0.584045 |
| 边界与流 | 1.125933 | 0.738065 | 0.582461 |
| 边界、流与价格 | 1.158859 | 0.770290 | 0.578946 |
| 增强端口（四时域） | 1.172857 | 0.781212 | 0.578776 |
| 预测端口 | 1.177586 | 0.785160 | 0.577920 |
| 完整活跃质量 | 1.181522 | 0.779541 | 0.580488 |
| 校正 LIF | 1.229830 | 0.840061 | 0.590501 |
| 历史滤波 GLM | 1.144499 | 0.832924 | 0.634672 |
| 训练基准率 | 0.866697 | 0.695445 | 0.695445 |

表中是十试次等权的平均对数损失，越小越好。单项截距在严格训练标签上调整每个模型的总体概率，保持各事件排序。冻结读出时预测端口减边界的配对差是 +0.090718 [0.061930,0.119311]。只调截距后仍为 +0.082408 [0.057925,0.108042]。允许所有读出重新学习特征的条件效应后，差值变为 −0.006125 [−0.012795,+0.002020]。此时预测端口减增强端口为 −0.000856 [−0.002887,+0.001012]，减校正 LIF 为 −0.012581 [−0.019418,−0.005885]。原冻结排序对端点与概率映射敏感，仅调整总体阳性率未消除逆转。重拟合后端口相对边界的差值区间跨零，预测端口和四时域增强端口仍难区分。

每项不确定度来自十个完整试次的配对重抽。旧标签预测不能直接校准为严格时间因果概率。作为单记录的关联试验，本结果不识别一个视网膜事件的生理因果贡献。原归属、原 2 毫秒 LIF 和此前修正的结果均保留。

独立复算仅需要 NumPy。原始逐事件张量、标签、试次和时间均在本目录。

```bash
python verify.py .
```

Git 独立归档的 source_inputs.zip 含神经核、读出源码、原封存预测和复核用的相对目录。原始生理数据使用公共 CRCNS ch-epfl-2009 Challenge D。将归档解开到新目录并从该目录运行，其中严格终点文件拷贝到 campaign/synapse/strict_lag，校正的 C++ 动态库按下列方式构建。

```bash
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
g++ -O3 -std=c++17 -fPIC -shared campaign/neurons/reservoir.cpp -o /tmp/retina-reservoir.so
g++ -O3 -std=c++17 -fPIC -shared campaign/synapse/trace.cpp -o /tmp/retina-trace.so
g++ -O3 -std=c++17 -fPIC -shared campaign/synapse/clock_correction/lif.cpp -o /tmp/retina-clock.so
s=campaign/synapse/strict_lag
mkdir -p /tmp/retina-strict
python "$s/strict.py" fit /path/to/CRCNS-D core /tmp/retina-trace.so /tmp/retina-reservoir.so /tmp/retina-clock.so campaign/synapse campaign/synapse/clock_correction /tmp/retina-strict/SEAL.json /tmp/retina-strict
python "$s/strict.py" score /path/to/CRCNS-D core /tmp/retina-trace.so /tmp/retina-reservoir.so /tmp/retina-clock.so campaign/synapse campaign/synapse/clock_correction /tmp/retina-strict/SEAL.json /tmp/retina-strict
```
