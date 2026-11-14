"""P3 auditable LOCAL four-modality bytes: integrity, decodability and pairing.

No encoder is trained/evaluated. Even perfect byte validation does not imply
cross-modal semantic alignment, legal permission or independent holdout scores.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import subprocess
from PIL import Image
import soundfile as sf
from multimodal_gate import check_pairs,MODALITIES


def digest_file(path:Path,cap=150*1024*1024):
    if path.stat().st_size>cap or path.stat().st_size==0:
        raise ValueError('empty/over-limit asset')
    h=hashlib.sha256()
    with path.open('rb') as f:
        for data in iter(lambda:f.read(1024*1024),b''):
            h.update(data)
    return h.hexdigest()


def _probe_video(path):
    res=subprocess.run(['ffprobe','-v','error','-show_entries',
                        'format=duration:stream=codec_type,width,height,nb_frames',
                        '-of','json',str(path)],text=True,capture_output=True,
                        timeout=8,check=False)
    if res.returncode:
        raise ValueError('ffprobe failed to decode video metadata')
    payload=json.loads(res.stdout)
    streams=[s for s in payload.get('streams',[]) if s.get('codec_type')=='video']
    if not streams or not all(int(s.get(k,0))>0 for s in streams for k in ('width','height')):
        raise ValueError('no decodable video stream/dimensions')
    duration=float(payload.get('format',{}).get('duration',0))
    if not math.isfinite(duration) or duration<=0:
        raise ValueError('nonpositive video duration')
    return duration


def check_bytes(records,root):
    """Fail closed on path escape, SHA mismatch, invalid media, time mismatch."""
    root=Path(root).resolve()
    failures=[]
    for i,r in enumerate(records):
        if not isinstance(r,dict) or not isinstance(r.get('files'),dict):
            failures.append(f'row {i}: invalid files map')
            continue
        times=(r.get('t_start_sec'),r.get('t_end_sec'))
        if (not all(isinstance(x,(float,int)) and math.isfinite(x) for x in times)
                or times[0]<0 or times[1]<=times[0]):
            failures.append(f'row {i}: invalid aligned window')
            continue
        for mod in MODALITIES:
            asset=r['files'].get(mod)
            if not isinstance(asset,dict) or 'path' not in asset or 'sha256' not in asset:
                failures.append(f'row {i}: missing {mod} bytes/digest');continue
            try:
                relative=Path(asset['path'])
                if relative.is_absolute() or '..' in relative.parts or not relative.parts:
                    raise ValueError('unsafe absolute/traversal asset path')
                candidate=root
                for component in relative.parts:
                    candidate=candidate/component
                    # Resolving the final path before testing for symlinks
                    # loses the evidence that a symlink was used.
                    if candidate.is_symlink():
                        raise ValueError('symlink component is forbidden')
                path=candidate.resolve(strict=True)
                path.relative_to(root)
                if not path.is_file():
                    raise ValueError('not regular safe file')
                digest=digest_file(path)
                if digest!=asset['sha256']:
                    raise ValueError('sha256 does not match file bytes')
                if mod=='text':
                    s=path.read_text(encoding='utf-8')
                    if not s.strip():raise ValueError('empty UTF-8 transcript')
                elif mod=='image':
                    with Image.open(path) as pic:
                        pic.verify()
                    with Image.open(path) as pic:
                        if min(pic.size)<16:raise ValueError('undersized image')
                elif mod=='audio':
                    info=sf.info(str(path))
                    if info.samplerate<8000 or info.frames<1 or info.channels<1:
                        raise ValueError('invalid decoded audio')
                    if times[1]>info.duration+0.03:
                        raise ValueError('audio shorter than aligned window')
                elif mod=='video':
                    duration=_probe_video(path)
                    if times[1]>duration+0.03:
                        raise ValueError('video shorter than aligned window')
            except Exception as exc:
                failures.append(f'row {i} {mod}: {str(exc)[:140]}')
    # Subset validator independent of file-specific metadata.
    records_for_meta=[]
    for r in records:
        if not isinstance(r,dict):continue
        meta={key:r[key] for key in
              ('sample_id','entity_id','scene_id','split','t_start_sec','t_end_sec','provenance')
              if key in r}
        meta['asset_sha256']={k:v.get('sha256') for k,v in r.get('files',{}).items()
                              if isinstance(v,dict)}
        records_for_meta.append(meta)
    m=check_pairs(records_for_meta)
    failures.extend(m['failures'])
    return {'byte_integrity_metadata_valid':not failures,'failures':failures,
            'samples_checked':len(records),
            'verified_real_world_provenance':False,
            'four_modality_encoder_executed':False,
            'semantic_alignment_verified':False,
            'production_evidence_accepted':False}
