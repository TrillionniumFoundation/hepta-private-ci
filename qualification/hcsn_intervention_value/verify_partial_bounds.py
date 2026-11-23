"""Independent exhaustive binary-completion QA for released original-roster intervals."""
import argparse
from collections import Counter
from itertools import product
import hashlib
import json
import math
from pathlib import Path
import numpy as np


def load(p): return json.loads(p.read_text())


def same(a,b): np.testing.assert_allclose(a,b,rtol=0,atol=5e-15)


def qa(data,evidence,original,certificate,report):
    known=load(certificate); output=load(report)['with_certified_prefixes']; rows=load(original)
    group={r['query_id']:r['group'] for r in rows}; groups=sorted(set(group.values())); part=known['partial_frontend']
    direct={}
    for q,r in part.items():
        kk={}
        for act,key in enumerate(('free_probability','paid_probability')):
            kk.update({(t,act):int(np.argmax(prob)==r['target']) for t,prob in enumerate(r[key])})
        cells=list(product(range(6),range(2))); missing=[cell for cell in cells if cell not in kk]
        tables=[]
        for mask in product((0,1),repeat=len(missing)):
            hit={**kk,**dict(zip(missing,mask))}; util={}
            for (t,a),h in hit.items():
                disc=math.exp(-.2*.48*t); util[t,a]=disc*(h-.30*a)-.4/.2*(1-disc)
            tables.append((hit,util))
        direct[q]=tables
    counts=Counter(); sign_groups=[]
    def ranges(roster,rel,other=None):
        # Enumerate one common missing potential-outcome table at a time.
        by={g:[0.,0.] for g in groups}
        for q,g in group.items():
            if q not in part:
                us=[roster['values'][q]-(other['values'][q] if other else 0.)]
            else:
                left=roster['actions'][q]; right=other['actions'][q] if other else None
                us=[]
                for hit,u in direct[q]:
                    if right is None:
                        us.extend((hit if roster['measure']=='r1' else u)[time,action] for time,action in left)
                    else:
                        for t,a in left:
                            for v,b in right:
                                if rel=='same' and (t,a)!=(v,b): continue
                                if rel=='instant' and t==0 and a!=b: continue
                                if rel=='masked' and ((a==0 and (t,a)!=(v,b)) or (a==1 and v<t)): continue
                                us.append(u[t,a]-u[v,b])
            by[g][0]+=min(us)/4; by[g][1]+=max(us)/4
        return by
    def verify_ranges(by,r):
        for g in groups:same(by[g],r['per_source'][g]);counts['group_intervals']+=1
        same(np.mean(list(by.values()),axis=0),r['macro']);same(np.min(list(by.values()),axis=0),r['worst']);counts['macro_and_worst_intervals']+=2
        if 'source_support' in r:
            pos=[int(np.sum(np.array(list(by.values()))[:,i]>1e-12)) for i in (0,1)];p=[sum(math.comb(6,n) for n in range(k,7))/64 for k in reversed(pos)];same(pos,r['source_support']['positive_sources']);same(p,r['source_support']['sign_p']);counts['group_sign_ranges']+=1
    def build(arm,kind,tr,measure='u',table=False):
        vals=tr['episode_hit'] if measure=='r1' else tr['episode_utility']
        obj={'values':dict(zip(tr['query_ids'],vals)),'actions':{},'measure':measure}
        if table:
            legal={'full':list(product(range(6),(0,1))),'refit_no_read':list(product(range(6),(0,))),
                'mask_read':list(product(range(6),(0,))),'always_stop':[(0,0)],'always_read':[(0,1)],'immediate':[(0,0),(0,1)]}[kind]
        else:
            if kind.startswith('immediate_'):
                legal=[(0,a) for a in ((1,) if kind=='immediate_paid' else (0,) if kind=='immediate_free' or arm.startswith('noread') else (0,1))]
            else: legal=list(product(range(6),(0,) if arm.startswith('noread') or kind=='disable_read' else (0,1)))
        for q in part:
            ev=(known['table'][q] if table else known['partial'][q][arm]).get(kind)
            actions=legal if ev is None else [(ev['exit_prefix'],ev['terminal_action'])] if 'exit_prefix' in ev else [v for v in legal if v[0]>=ev['waited_prefixes']]
            obj['actions'][q]=actions
        return obj
    for arm,r in output['read_arms'].items():
        noarm='no'+arm; row=load(evidence/'confirm'/(arm+'.json')); nr=load(evidence/'confirm'/(noarm+'.json')); fit=load(evidence/'fit'/(arm+'.json')); lock=fit['immediate_choice']
        def entity(which,k,typ='u'):
            rr=row if which==arm else nr; tr=rr['immediate_controls'][k] if k.startswith('immediate_') else rr[k];return build(which,k,{**tr,'query_ids':rr['query_id']},typ)
        f=entity(arm,'chosen'); verify_ranges(ranges(f,None),r['absolute']['utility']);verify_ranges(ranges(entity(arm,'chosen','r1'),None),r['absolute']['r1'])
        specs=[('trained_dynamic_noread',noarm,'chosen',None),('dev_locked_immediate',arm,lock,'instant' if lock=='immediate_conditional' else None),('matched_keep',arm,'keep','same' if (fit['theta']==fit['keep_theta'] and fit['head']==fit['keep_head']) else None),('same_scores_disable_read',arm,'disable_read','masked')]
        for label,which,k,relation in specs:verify_ranges(ranges(f,relation,entity(which,k)),r['paired'][label])
        counts['hcsn_and_control_arms']+=1
    table=load(data/'heldout_controls.json')['policy']; result=output['registered_table']; f=build('table','full',table['policies']['full'],table=True)
    for k,tr in table['policies'].items():
        v=build('table',k,tr,table=True); verify_ranges(ranges(v,None),result['absolute'][k]['utility']);verify_ranges(ranges(build('table',k,tr,'r1',True),None),result['absolute'][k]['r1'])
        if k!='full': verify_ranges(ranges(f,'instant' if k=='immediate' else 'masked' if k=='mask_read' else None,v),result['paired'][k])
    return dict(passed=True,exact_binary_completion_tables={q:len(v) for q,v in direct.items()},counts=dict(counts),report_sha256=hashlib.sha256(report.read_bytes()).hexdigest(),scope='Common correctness table enumerated over remaining unobserved time/action outcomes. Group means, macro, worst-group intervals and sign ranges compared for the 33 READ arms and registered table; observed trace data shared as declared input.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('data','evidence','roster','certificate','report'):p.add_argument(key,type=Path)
    p.add_argument('--output',type=Path);a=p.parse_args(); result=qa(a.data,a.evidence,a.roster,a.certificate,a.report)
    raw=json.dumps(result,allow_nan=False,indent=2)+'\n'; print(raw,end='')
    if a.output:
        with a.output.open('x') as f:f.write(raw)
