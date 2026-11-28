"""Report true three-seed common-budget retrieval outcomes and constructor-inclusive sensitivity."""
import json,sys
from pathlib import Path
import numpy as np
from compare_long import BUDGETS,SEEDS,mean_hits,paired_interval


def main(root,dest):
    joint=json.loads((root/'time_matched_long_comparison.json').read_text());dest.mkdir(exist_ok=True,parents=True)
    lines=['# RSICD 图文实例检索的完整三种子长时曲线','','每种子分配 2、10、30、60、120 分钟单线程活跃墙钟预算。物理 BP 采用短实验只按开发集选中的宽度 12 构造器。常规对照采用像素卷积塔、文本注意力塔与两个学习率。全部结果来自 964 对图像和原作者字幕，同一图库先前已用于短时间比较。下列百分比为三种子及两个检索方向的均值。','','| 每种子预算 | 冻结字面 R@1 | 平滑 R@1 | 单层 CCA R@1 | 物理 BP R@1 | 常规 BP R@1 | 物理 BP − 常规 BP，pp [95%] |','|---:|---:|---:|---:|---:|---:|---:|'];charged={}
    bpath=root/'long'/'cold_ranks.npz'
    with np.load(bpath) as base:
        for budget in BUDGETS:
            entry=joint[str(budget)];r=entry['r1'];contrast=entry['contrasts']['hybrid-conventional'];lo,hi=contrast['paired95']
            lines.append(f"| {budget//60} 分钟 | {100*r['literal']:.4f}% | {100*r['smooth']:.4f}% | {100*r['linear']:.4f}% | {100*r['hybrid']:.4f}% | {100*r['conventional']:.4f}% | {100*contrast['strict_R1_difference']:+.4f} [{lo*100:+.4f}, {hi*100:+.4f}] |")
            rec=json.loads((root/'hybrid_long'/f'cost-outcome-{budget}.json').read_text());sel=json.loads((root/'hybrid_long'/f'cost-seal-{budget}.json').read_text())
            with np.load(root/'hybrid_long'/f'cost-ranks-{budget}.npz') as physical:
                p=[physical[str(s)] for s in SEEDS];c=[base[f'conventional/{s}/{budget}'] for s in SEEDS];delta=mean_hits(p,1)-mean_hits(c,1)
                csort={'same_incremental':{s:v['same_as_incremental'] for s,v in rec['seeds'].items()},'selector':sel,'matched_R1':float(mean_hits(p,1).mean()),'matched_R5':float(mean_hits(p,5).mean()),'matched_R10':float(mean_hits(p,10).mean()),'R1_minus_conventional':float(delta.mean()),'paired95':paired_interval(delta)}
                charged[str(budget)]=csort
    lines+=['','物理 BP 的增量时钟从已建好的初始化参数开始。单列的完整初始化敏感性把每个种子的四候选开发选择与解析表成本一并扣除。正向构造、平滑与 CCA 在候选穷尽后没有用空闲时间重复训练。图库配对区间固定这三组训练状态和 964 张图片；它不测量新任务、新地点或新种子组的变动。','', '| 每种子预算 | 计入初始化的物理 R@1 | 计入初始化相对常规 pp | 与增量时钟状态相同的种子 |','|---:|---:|---:|---:|']
    for t in BUDGETS:
        s=charged[str(t)];lines.append(f"| {t//60} 分钟 | {s['matched_R1']*100:.4f}% | {s['R1_minus_conventional']*100:+.4f} | {sum(s['same_incremental'].values())}/3 |")
    lines+=['','严格 R@5、R@10 和其他主要对比见 joint.json。由于视觉与文本主任务是实例检索，本表的准确率没有语言建模含义。所有选模均在开发集进行；前向构造和后续物理 BP 的两个阶段须分别计费。'];(dest/'README.md').write_text('\n'.join(lines)+'\n');(dest/'joint.json').write_text(json.dumps(joint,indent=1));(dest/'charged.json').write_text(json.dumps(charged,indent=1))
if __name__=='__main__':main(Path(sys.argv[1]),Path(sys.argv[2]))
