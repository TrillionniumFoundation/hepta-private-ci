"""Aggregate the locked three-seed comparison and paired held-block diagnostics."""
import argparse,json,math
from pathlib import Path
import numpy as np


def run(root):
    results=root/'results';seeds=(137,311,557);kinds=('hx','sdpa','smooth','lif')
    runs={(k,s):json.loads((results/f'{k}-{s}.json').read_text()) for k in kinds for s in seeds}
    if len(set(d['metadata']['parameter_count'] for d in runs.values()))!=1:raise ArithmeticError('parameter mismatch')
    clocks=set.intersection(*(set(c['clock'] for c in v['timed']) for v in runs.values()))
    budget=max(clocks)
    final={};seedwise={};blocks={};shift={}
    for k in kinds:
        usd=[runs[k,s] for s in seeds]
        cvs=[next(r for r in q['timed'] if r['clock']==budget) for q in usd]
        final[k]=dict(mean_nll=np.mean([q['test']['nll'] for q in usd]),mean_test_ppl=np.mean([q['test']['ppl'] for q in usd]),
            sd_test_ppl=np.std([q['test']['ppl'] for q in usd],ddof=1),mean_val_ppl=np.mean([q['epochs'][q['selected_epoch']-1]['valid']['ppl'] for q in usd]),
            mean_cut_ppl=np.mean([q['cut_test']['ppl'] for q in usd]),mean_tok_s=np.mean([q['tok_per_training_second'] for q in usd]),
            mean_clock_ppl=np.mean([q['test']['ppl'] for q in cvs]),clock_targets=[q['tokens'] for q in cvs],
            clock_overshoot_seconds=[q['actual_seconds']-budget for q in cvs],selected_epochs=[q['selected_epoch'] for q in usd])
        seedwise[k]=[q['test']['ppl'] for q in usd]
        blocks[k]=np.stack([np.load(results/f'{k}-{s}-blocks.npz')['metrics'] for s in seeds])
        diff=(blocks[k][:,:,3]-blocks[k][:,:,2]).sum(1)/blocks[k][:,:,4].sum(1)
        shift[k]=dict(mean_excess_nll=diff.mean(),per_seed=diff.tolist(),scored_targets=int(blocks[k][0,:,4].sum()))
    # Conditional on the same three fitted seeds. Chronological macroblocks of
    # 16 consecutive scoring blocks are sampled with their actual target counts.
    boot={};rng=np.random.default_rng(913)
    for k in kinds[1:]:
        by_seed=blocks['hx'][:,:,0]-blocks[k][:,:,0]
        cnt=blocks[k][0,:,1]
        start=np.arange(0,len(cnt),16)
        sums=np.add.reduceat(by_seed.mean(axis=0),start)
        nums=np.add.reduceat(cnt,start)
        draw=rng.integers(len(start),size=(5000,len(start)))
        obs=sums[draw].sum(1)/nums[draw].sum(1)
        boot[k]=dict(mean_nll_hx_minus_comparator=float(sums.sum()/nums.sum()),
             macroblock_resample_95_percent=np.quantile(obs,[.025,.975]).tolist(),macroblocks=len(start),
             per_seed=(by_seed.sum(1)/cnt.sum()).tolist())
    return dict(full_training_target_presentations=sum(v['epochs'][-1]['cumulative_targets'] for v in runs.values()),
                seeds=seeds,common_training_seconds=budget,models=final,seed_test_ppl=seedwise,
                paired_chronological_macroblock=boot,early_history_perturbation=shift)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);z=p.parse_args()
    (z.root/'summary.json').write_text(json.dumps(run(z.root),indent=2)+'\n')
