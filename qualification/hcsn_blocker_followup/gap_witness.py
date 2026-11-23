"""Counterfactual raw PCM witnesses for one missing TEST prefix in the original frozen task.

No completion is an observation. Only the 412 absent mono samples are changed within
an alignment. A changed output certifies ambiguity of that concrete frozen policy
under the declared completion class; agreement of a finite list cannot certify identity.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from unittest.mock import patch

import numpy as np
import torch
from qualification.hcsn_intervention_value import frontend,run
from qualification.hcsn_intervention_value.media import coverage,recording_features as media

QID='commons-112833470-w01'
MEDIA_SHA1='34916381e520d40dc23b494ee552d8c749057fd2'
CAMERA_SHA='7c2b058dda65d5595ce46d0744fc98c40f9d49e6bf5200996593032d992c19e0'


def digest(x):return hashlib.sha256(np.ascontiguousarray(x).tobytes()).hexdigest()


def candidates(n,rate):
    rng=np.random.default_rng(17); t=np.arange(n)/rate;freqs=[0,98,220,440,880,1400,1800,2400,3000,4200,5500,7200,10600]
    waves={'zero':np.zeros(n),'ramp':np.linspace(-1,1,n),'noise':rng.uniform(-1,1,n)}
    for hz in freqs:
        for amp in (.1,1.):waves[f'tone-{hz}-{amp}']=amp*np.cos(2*np.pi*hz*t)
    for j in range(12):
        y=sum(np.sin(2*np.pi*f*t+rng.uniform(0,2*np.pi)) for f in rng.choice(freqs,3,False));waves[f'mix-{j}']=y/abs(y).max()
    if len(waves)!=41 or max(abs(v).max() for v in waves.values())>1:raise ValueError('changed completion family')
    return waves


def timelines(path,start):
    with path.open('rb') as f:
        if hashlib.file_digest(f,'sha1').hexdigest()!=MEDIA_SHA1:raise ValueError('original Commons file SHA-1 mismatch')
    args=['ffmpeg','-hide_banner','-nostdin','-v','info','-threads','1','-i',str(path),'-map','0:a:0','-af','asettb=expr=1/sr,ashowinfo','-ac','1','-f','f32le','-']
    proc=subprocess.run(args,capture_output=True,check=True);pcm=np.frombuffer(proc.stdout,dtype='<f4');b=np.array([[int(v) for v in a] for a in re.findall(coverage.PATTERN,proc.stderr)]);rate=int(b[0,2]); begin=round(start*rate);count=round(2.88*rate);end=begin+count
    if rate!=44100 or not np.array_equal(b[:,0],np.arange(len(b))) or (b[:,2]!=rate).any() or b[:,3].sum()!=len(pcm):raise ValueError('changed decoded stream')
    offsets=np.r_[0,np.cumsum(b[:,3])];included=np.flatnonzero((b[:,1]<end)&(b[:,1]+b[:,3]>begin));first=included[0];gap=int(b[first,1])-begin
    if not (first>0 and b[first-1,1]+b[first-1,3]<=begin and gap==412):raise ValueError('expected single missing leading interval')
    anchored=np.full(count,np.nan);anchored[gap:]=pcm[offsets[first]:offsets[first]+count-gap];earliest=np.full(count,np.nan);latest=earliest.copy();overlaps=0
    for j in included:
        pts=int(b[j,1]); l=max(begin,pts);r=min(end,pts+int(b[j,3])); dest=slice(l-begin,r-begin); source=pcm[offsets[j]+l-pts:offsets[j]+r-pts];overlaps+=int(np.isfinite(earliest[dest]).sum());
        earliest[dest]=np.where(np.isfinite(earliest[dest]),earliest[dest],source);latest[dest]=source
    timelines={'anchored_decoded_order':anchored,'literal_pts_earliest':earliest,'literal_pts_latest':latest}
    for v in timelines.values():
        if not np.isnan(v[:gap]).all() or not np.isfinite(v[gap:]).all():raise ValueError('unexpected interior missing samples')
    reported=b[included,1]-(b[first,1]+offsets[included]-offsets[first]); sr,frame_tb=rate,json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','a:0','-show_entries','stream=time_base','-of','json',str(path)]))['streams'][0]['time_base']
    info=dict(rate=rate,time_base=frame_tb,start_seconds=start,start_sample=begin,end_sample_exclusive=end,first_observed_sample=int(b[first,1]),
         missing_samples=gap,missing_seconds=gap/rate,within_query_overlap_positions=overlaps,within_query_pts_minus_contiguous=[int(reported.min()),int(reported.max())],
         ffmpeg=subprocess.check_output(['ffmpeg','-version'],text=True).splitlines()[0],source_media_sha1=MEDIA_SHA1)
    return timelines,info


def evaluate(path,row,clock_data,pcm,waves,camera,weights,meta,teachers,fitroot):
    rate,frames,clock,offset=clock_data; variants=[];suffix=pcm[len(next(iter(waves.values()))):].copy();n=len(pcm)-len(suffix)
    for w in waves.values():
        filled=np.concatenate((w,suffix)); assert np.array_equal(filled[n:],suffix)
        with patch.object(media,'make_frames',return_value=(filled,rate,frames,clock-offset,0.)):
            variants.append(media.extract(path,row['start_seconds']))
    visual=np.stack([r['visual'] for r in variants]);assert all(np.array_equal(a,visual[0]) for a in visual)
    s={'audio':np.stack([r['audio'] for r in variants]),'visual':visual};m=len(variants)
    for k in ('label','group','recording','query_id','split'):s[k]=np.repeat(row[k],m)
    s['dt']=np.full((m,6),.48);s['start_seconds']=np.full(m,row['start_seconds']);names=list(waves)
    state=frontend.candidate(frontend.render(s,weights['final'],weights['reference'],np.broadcast_to(camera,(m,6,2))),'imagenet_visual')
    if not np.all(state['read_scores']==camera):raise ValueError('paid sensor changed across counterfactual completions')
    result={}
    for availability in run.AVAIL:
        paid=availability=='read'; inp=run.frontend(state.copy(),meta,teachers[availability]);
        for seed in run.SEEDS:
            for mode,method in run.ARMS:
                key=f'{availability}-{mode}-{method}-{seed}';f=run.load(fitroot/'fit'/(key+'.json'));model=run.representation(mode,seed,len(meta['mu']));theta=torch.tensor(f['theta'],dtype=torch.float64);head=torch.tensor(f['head'],dtype=torch.float64)
                with torch.no_grad():q=run.predict(run.features(model,mode,paid)(theta,inp),head).numpy()
                score=run.score(q,inp,paid); actions0=[];outcomes=[];computed=[]
                for j in range(m):
                    choices=q[j].copy(); choices[-1,2]=-np.inf
                    if not paid:choices[:,1]=-np.inf
                    decision=np.argmax(choices,1);t=next(k for k,a in enumerate(decision) if a!=2);a=int(decision[t]);hit=int(np.argmax(state['read_scores' if a else 'scores'][j,t])==row['label']);u=float(np.exp(-.2*.48*t)*(hit-.3*a)+2*np.expm1(-.2*.48*t));
                    if (t,a,hit)!=(score['exit_prefix'][j],score['terminal_action'][j],score['episode_hit'][j]) or abs(u-score['episode_utility'][j])>1e-12:raise ValueError('independent first/exit law disagreement')
                    actions0.append(int(decision[0]));outcomes.append((t,a,hit));computed.append(u)
                signatures={str(tuple(k)):names[outcomes.index(k)] for k in sorted(set(outcomes))}
                result[key]=dict(first_actions=sorted(set(actions0)),terminal_witness=signatures,utility_range=[min(computed),max(computed)],
                                 first_action_changes=len(set(actions0))>1,terminal_changes=len(signatures)>1,utility_changes=np.ptp(computed)>1e-12)
                result[key]['utility_changes']=bool(result[key]['utility_changes'])
    return dict(recorded_suffix_f32_sha256=digest(suffix.astype('<f4')),image_frames_f64_sha256=digest(frames),image_pts_f64_sha256=digest(clock),visual_features_sha256=digest(visual[0]),
        first_free_class_probability_range=[float(state['scores'][:,0,1].min()),float(state['scores'][:,0,1].max())],
        counts={k:sum(v[k] for v in result.values()) for k in ('first_action_changes','terminal_changes','utility_changes')},completed_policies=result)


def main():
    c=argparse.ArgumentParser(description=__doc__)
    for k in ('roster','media','camera','frontend','policies','output'):c.add_argument(k,type=Path)
    a=c.parse_args();seal=run.check_test_receipt(a.frontend,a.policies);fs=run.load(a.frontend/'frontend_seal.json');
    if fs['selected']!='imagenet_visual' or run.sha(a.camera)!=CAMERA_SHA:raise ValueError('frozen pure camera required')
    row=next(r for r in run.load(a.roster) if r['query_id']==QID); timelines_,info=timelines(a.media,row['start_seconds']);run.init(); _,rate,frames,clock,offset=media.make_frames(a.media,row['start_seconds']);
    with np.load(a.camera,allow_pickle=False) as cam:camera=cam['probability'][cam['query_id'].astype(str).tolist().index(QID)]
    waves=candidates(info['missing_samples'],rate);teachers={k:run.load(a.policies/'prepare'/(k+'.json')) for k in run.AVAIL};meta=run.load(a.policies/'prepare/metadata.json');weights=run.load(a.frontend/'front_weights.json');result={}
    for name,pcm in timelines_.items():result[name]=evaluate(a.media,row,(rate,frames,clock,offset),pcm,waves,camera,weights,meta,teachers,a.policies)
    summary={k:{'all_alignments':sorted(set.intersection(*[{n for n,v in r['completed_policies'].items() if v[k]} for r in result.values()])),
                  'any_alignment':sorted(set.union(*[{n for n,v in r['completed_policies'].items() if v[k]} for r in result.values()]))} for k in ('first_action_changes','terminal_changes','utility_changes')}
    run.write(a.output,dict(query=QID,source_roster=run.sha(a.roster),fit_seal=seal,frontend_seal=run.sha(a.frontend/'frontend_seal.json'),camera_sha=CAMERA_SHA,
        clock=info,scenario_sha={k:digest(v.astype('<f8')) for k,v in waves.items()},frozen_camera_probability=camera.tolist(),alignments=result,across_alignments=summary,
        interpretation='Alternative bounded digital signal completions, not measurements or imputations. Within each convention all recorded suffix samples as represented, source camera frames, labels, clock, prices, and frozen weights are identical. Anchored decoded order preserves all original decoded samples in sequence; literal timestamp policies drop only physically overlapping timestamp slots, taking the first or last value. Finite agreement is inconclusive. Results identify ambiguity for these deployed policies and this completion set; they do not recover original audio or certify an arbitrary biological or acoustic signal model.'))


if __name__=='__main__':main()
