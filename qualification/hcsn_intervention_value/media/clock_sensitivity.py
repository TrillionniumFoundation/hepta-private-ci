"""Quantify source PCM clock transitions and conservative fixed-panel price-gate sensitivity."""
import argparse
from collections import Counter
from fractions import Fraction
import json
from pathlib import Path
import re
import subprocess

import numpy as np

if __package__:
    from . import build, coverage
else:
    import build,coverage


def timings(path):
    src=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','a:0','-show_streams','-of','json',path]))['streams'][0]
    rate=int(src['sample_rate']);tol=max(1,int(np.ceil(rate*Fraction(src['time_base']))))
    p=subprocess.run(['ffmpeg','-nostdin','-v','info','-threads','1','-i',path,'-map','0:a:0',
                      '-af','asettb=expr=1/sr,ashowinfo','-f','null','-'],check=True,capture_output=True)
    f=np.array([(int(n),int(t),int(sr),int(sz)) for n,t,sr,sz in re.findall(coverage.PATTERN,p.stderr)])
    assert np.array_equal(f[:,0],np.arange(len(f))) and np.all(f[:,2]==rate)
    start=f[:,1];end=start+f[:,3]
    prev=end[:-1];cur=start[1:];jumps=cur-prev
    drift=start-np.r_[0,np.cumsum(f[:-1,3])]
    return rate,tol,start,end,prev,cur,jumps,drift


def survey(path):
    roster=json.loads(path.read_text());sources={};rows=[]
    for recording in dict.fromkeys(r['recording'] for r in roster):
        subset=[r for r in roster if r['recording']==recording]
        rate,tol,l,h,a,b,d,drift=timings(subset[0]['local_media'])
        src=dict(rate=rate,packet_quantization_tolerance_samples=tol,
                 positive_transitions_entire_source=int((d>tol).sum()),
                 negative_transitions_entire_source=int((d< -tol).sum()),
                 net_timeline_minus_emitted_samples=int(d.sum()),
                 largest_transitions_samples=dict(Counter(map(int,d)).most_common(7)),
                 max_minus_min_clock_offset_samples=int(np.ptp(drift)))
        for r in subset:
            lo=round(r['start_seconds']*rate);hi=round((r['start_seconds']+2.88)*rate)
            edge=(np.maximum(np.minimum(a,b),lo)<np.minimum(np.maximum(a,b),hi)) & (np.abs(d)>tol)
            pos=np.where(edge&(d>0),np.maximum(0,np.minimum(b,hi)-np.maximum(a,lo)),0)
            neg=np.where(edge&(d<0),np.maximum(0,np.minimum(a,hi)-np.maximum(b,lo)),0)
            outer=max(0,min(hi,l[0])-lo)+max(0,hi-max(lo,h[-1]))
            active=(l<hi)&(h>lo)
            strict=not edge.any() and not outer
            rows.append(dict(query_id=r['query_id'],group=r['group'],recording=recording,reference_label=r['label'],
                             strict=bool(strict),positive_jump_samples=int(pos.sum()),negative_jump_samples=int(neg.sum()),
                             original_endpoint_uncovered_samples=int(outer),max_abs_clock_transition_samples=int(np.abs(d[edge]).max(initial=0)),
                             local_peak_to_peak_clock_offset_samples=int(np.ptp(drift[active])) if active.any() else None))
        sources[recording]=src
    return {'works':sources,'query':rows,'n':len(rows),'strict':sum(r['strict'] for r in rows)}


def gate(panel,query_rows):
    groups={r['query_id']:r['group'] for r in query_rows}
    good={r['query_id'] for r in query_rows if r['strict']}
    def summary(kind,threshold):
        values=panel[kind+'_gain_by_query'];assert set(values)==set(groups)
        all_groups=sorted(set(groups.values()))
        lower={};observed={}
        for g in all_groups:
            ids=[k for k,v in groups.items() if v==g]; keep=[k for k in ids if k in good]
            lower[g]=float(sum(values[k] for k in keep)/len(ids))
            if keep:observed[g]=float(np.mean([values[k] for k in keep]))
        lb=float(np.mean(list(lower.values())));n_pos=sum(v>1e-12 for v in lower.values())
        return {'original_macro':panel[kind+'_gain_mean'],'lower_bound_original_denominators':lb,
                'lower_by_group':lower,'groups_positive_at_lower':n_pos,
                'passes_fixed_threshold_at_lower':bool(lb>=threshold-1e-12 and n_pos>=2),
                'strict_only_macro_available_groups':float(np.mean(list(observed.values()))) if observed else None,
                'strict_only_groups':len(observed),'all_groups':len(all_groups)}
    return {'paid':summary('paid',.03),'wait':summary('wait',.015)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw',type=Path,required=True);parser.add_argument('--discovery',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    seal=json.loads((args.discovery/'frontend_seal.json').read_text());selected=seal['selected']
    panels=json.loads((args.discovery/'panels.json').read_text());assert build.digest(args.discovery/'panels.json')==seal['sha256']['panels.json']
    out={}
    for name in ('gallery','train','dev','retain','test'):
        out[name]=survey(args.raw/'roster'/(name+'.json'))
        if name in ('train','dev'):out[name]['fixed_selected_sensitivity']=gate(panels[selected][name],out[name]['query'])
    report={'frozen_selected_method':selected,'source_sha256':build.digest(Path(__file__)),
            'panels_sha256':build.digest(args.discovery/'panels.json'),'full_source_redecode':True,
            'definition':'Strict windows contain neither internal positive nor negative decoded-frame PCM timestamp transitions exceeding one original stream time-base tick, and lie entirely within the emitted endpoint interval. Positive jump totals can be counterbalanced by overlaps: they are timing flags, not automatically missing waveforms.',
            'sensitivity':'Keep original frozen gallery, heads, selected frontend, episodes and group weights; replace every gain on a timing-flagged episode by its mathematical lower bound zero. Conditional on frozen scores on strict episodes, this bounds the gain for every possible set of outcomes on flagged episodes. It does not retrain the observed gallery/heads on new clocks.',
            'scope':out}
    build.save_json(args.output,report)
    for k,item in out.items():print(k,item['strict'],item['n'],item.get('fixed_selected_sensitivity',{}),flush=True)
if __name__=='__main__':main()
