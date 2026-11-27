"""Preserve the matched three-seed cold rankings and weights at one fixed horizon."""
import argparse, hashlib, io, json, lzma, zipfile
from pathlib import Path
import numpy as np

def digest(b):return hashlib.sha256(b).hexdigest()
def write(data,budget,dest):
    root=data/"hybrid_long";dest.mkdir(parents=True,exist_ok=True);files={}
    for name in [f'seal-{budget}.json',f'cold-{budget}.npz',f'outcome-{budget}.json']:
        files[name]=(root/name).read_bytes()
    seals=json.loads(files[f'seal-{budget}.json']);outcomes=json.loads(files[f'outcome-{budget}.json'])
    paired=[]
    with np.load(io.BytesIO(files[f'cold-{budget}.npz'])) as arr,np.load(data/'short'/'cold_ranks.npz') as base:
        for seed,selected in sorted(seals.items()):
            state=(root/seed/selected["state"]).read_bytes();assert digest(state)==selected["hash"]
            files[f'{seed}/'+selected["state"]]=state
            history=[json.loads(l) for l in (root/seed/'history.jsonl').read_text().splitlines()]
            eligible=[row for row in history if row["time"]<=budget]
            expected=max([r for r in eligible if r["state"]],key=lambda r:(r["dev_r1"],r["dev_r5"],-r["time"]));assert expected==selected
            files[f'{seed}/eligible.json']=json.dumps(eligible,separators=(',',':')).encode()
            files[f'{seed}/cost.json']=(root/seed/f'budget-{budget}.json').read_bytes()
            r=arr[seed];assert r.shape==(2,964,3)
            for rank in (1,5,10):
                metric=float((r[:,:,0]<=rank).mean())
                assert abs(metric-outcomes["scores"][seed][f"strict_R{rank}"])<1e-14
            paired.append(((r[:,:,0]==1).astype(float)-(base[f'literal/{seed}/60'][:,:,0]==1)).mean(0))
    delta=float(np.mean(paired));assert abs(delta-outcomes['delta_vs_frozen'])<1e-14
    mem=io.BytesIO()
    with zipfile.ZipFile(mem,'w',zipfile.ZIP_STORED) as z:
        for name,b in sorted(files.items()):z.writestr(zipfile.ZipInfo(name,(2026,11,27,0,0,0)),b)
    raw=mem.getvalue();transport=lzma.compress(raw,preset=4);chunks=[]
    for i in range(0,len(transport),360000):
        b=transport[i:i+360000];name=f'part{i//360000:03d}.bin';(dest/name).write_bytes(b);chunks.append(dict(file=name,size=len(b),sha256=digest(b)))
    manifest=dict(delivery_encoding='xz',zip_sha256=digest(raw),delivery_sha256=digest(transport),delivery_bytes=len(transport),zip_bytes=len(raw),chunks=chunks,files={n:digest(v) for n,v in files.items()});(dest/'manifest.json').write_text(json.dumps(manifest,indent=1))
    (dest/'outcome.json').write_text(json.dumps(outcomes,indent=1));(dest/'seal.json').write_text(json.dumps(seals,indent=1))
    title=f"# 前向构造后物理 BP 的 {budget//60} 分钟曲线"
    lines=[title,"",f"三个父种子先按开发集封存了当期状态，再冷测 964 幅遥感图片与对应原作者说明。初始网络是原短期开发选中的宽度 12、岭参数 0.1 的字面双价格编码器。每种子最多 {budget} 累计活跃墙钟秒，种子在同一核上轮转，等待其他种子的时间单列。","",
           "| 种子 | 入选学习率 | 单率更新数 | 实例 R@1 | 实例 R@5 |","|---:|---:|---:|---:|---:|"]
    for s in ("109","271","463"):
        row=seals[s];metrics=outcomes['scores'][s]
        lines.append(f"| {s} | {row['rate']} | {row['step']} | {100*metrics['strict_R1']:.4f}% | {100*metrics['strict_R5']:.4f}% |")
    mean=np.mean([x["strict_R1"] for x in outcomes["scores"].values()])*100
    ci=np.array(outcomes['paired95_vs_frozen'])*100
    lines+=["",f"三种子均值 R@1 为 {mean:.4f}%。相对同一冻结解析初值的配对差为 {100*delta:+.4f} 个百分点，条件于这份图库的 95% 配对区间为 [{ci[0]:+.4f}, {ci[1]:+.4f}]。各做法共用先前已经检验的图库。本时点的发布覆盖物理网络和其冻结父模型。常规深度对照须等三个种子的相应预算都达到后再独立比较。","",
            f"归档含 {len(files)} 个文件。逐个从所有在预算内实际完成的开发候选重选，所有入选权重 SHA 和逐例严格检索指标均匹配。按 manifest.json 顺序连接 {len(chunks)} 段、解开 XZ 及 ZIP，可得到全部当期选择、三份完整权重、每个项目的双向排名与资源回执。"]
    (dest/'README.md').write_text("\n".join(lines)+"\n")
    print(budget,delta,len(chunks),len(transport))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('data',type=Path);p.add_argument('budget',type=int);p.add_argument('dest',type=Path);args=p.parse_args();write(args.data,args.budget,args.dest)
