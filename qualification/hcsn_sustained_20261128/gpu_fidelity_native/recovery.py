"""Select an already-installed native decoder using exact public-media pilots."""
import hashlib
import json
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import numpy as np
from reference import stages
import prepare_original as original


def sha(b):return hashlib.sha256(b).hexdigest()


def choose(root,fetch,report,save):
    report['fsize_soft_hard_bytes']=list(resource.getrlimit(resource.RLIMIT_FSIZE))
    paths=[]
    try:
        import imageio_ffmpeg
        paths.append(Path(imageio_ffmpeg.get_ffmpeg_exe()))
    except (ImportError,OSError,RuntimeError):pass
    if shutil.which('ffmpeg'):paths.append(Path(shutil.which('ffmpeg')))
    for j in (Path('/usr/bin/ffmpeg'),Path('/usr/local/bin/ffmpeg')):
        if j.exists():paths.append(j)
    original.download=fetch
    with np.load(root/'meta.npz',allow_pickle=False) as z:names=z['ids'];tiers=stages(z['split'])
    refs=json.loads((root/'reference.json').read_text());ptr=(root/'pointers.bin').read_bytes()
    pointers={int(j):ptr[20*i:20*i+20].hex() for i,j in enumerate(tiers[-2])}
    rows=tiers[0][[0,11,23,32,39,47]];report['decoder_pilots']=[];seen=set();save()
    for f in paths:
        if not f.is_file():continue
        with f.open('rb') as b:h=hashlib.file_digest(b,'sha256').hexdigest()
        if h in seen:continue
        seen.add(h);entry={'name':str(f),'sha256':h,'bytes':f.stat().st_size,'version':subprocess.check_output([str(f),'-version'],text=True).splitlines()[0],'pilots':[]}
        report['decoder_pilots'].append(entry);save()
        link=root/'env/ffmpeg';link.unlink(missing_ok=True);link.symlink_to(f);correct=True
        for j in rows:
            name=str(names[j]);clip=root/'data/clips'/(name+'.npz');clip.unlink(missing_ok=True)
            try:
                original.extract_one((root,int(j),{'path':'VideoFlash/'+name+'.flv','sha':pointers[int(j)]}))
                with np.load(clip,allow_pickle=False) as z:vc=sha(z['video'].tobytes());ac=sha(z['audio'].tobytes())
                ref=refs['first48'][name];row={'id':name,'video_match':vc==ref['image_sha256'],'audio_match':ac==ref['audio_sha256'],'image_sha256':vc,'audio_sha256':ac}
            except Exception as exc:row={'id':name,'video_match':False,'audio_match':False,'error':type(exc).__name__+': '+str(exc)[:300]}
            entry['pilots'].append(row);correct=correct and row['video_match'] and row['audio_match'];save()
        entry['qualifies']=correct;save()
        if correct:return entry['sha256']
    raise RuntimeError('No installed native decoder produced exact reference images and audio on all six pilots.')
