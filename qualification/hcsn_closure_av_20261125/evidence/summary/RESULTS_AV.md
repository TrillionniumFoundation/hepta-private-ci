# 新演员真实 AV 确认

三臂各3 seeds；统一32步离线低层特征、归一化模型时间、32维embedding和联合CE/InfoNCE。真实片长仅为审计元数据，不进入任何模型。

| Model | Fused accuracy | Audio→video paired R@1 | Cross-actor emotion R@1 | Cross-actor mAP | 256-update completion |
|---|---:|---:|---:|---:|---:|
| hcsn | 31.424% ± 1.591% | 0.868% ± 0.301% | 23.958% ± 10.838% | 22.670% ± 3.388% | 3/3 |
| transformer | 30.208% ± 2.387% | 1.042% ± 0.902% | 22.396% ± 0.521% | 23.297% ± 0.930% | 3/3 |
| lif | 32.465% ± 1.084% | 1.215% ± 1.203% | 20.486% ± 7.298% | 20.654% ± 1.244% | 3/3 |

均值/SD跨训练seed，8位演员是另一条来源轴；不把192个clip视为192个独立演员，也不据3个seed作普遍显著性结论。所有失败/CPU截尾记录保留在3-seed分母；上表只对实际可评估模型聚合，完整计数、初始模型、每actor、两个检索方向及校准指标在JSON。

Paired R@1寻找同一条记录；跨actor语义检索剔除查询演员的所有gallery记录，再以相同acted emotion判相关。二者不能替代彼此。输入特征来自固定音频log-mel/视频低分辨率DCT与全片重采样；此实验不能代表原始媒体端到端预训练、语言理解或全模态生成。

同width并非同参数量：HCSN接收端物理特征为20维，其projection与8维baseline不同。完整结构活跃参数、概率/标记/phase状态、token或膜电位逻辑状态及进程峰RSS分开报告，不能把局部状态byte直接当总训练显存。

费用见SUMMARY.costs和完整worker/stage回执。更新CPU、body、worker与stage相互包含，禁止相加。获取/解码/预检/失败和等待费用另留原件；能量未测。
