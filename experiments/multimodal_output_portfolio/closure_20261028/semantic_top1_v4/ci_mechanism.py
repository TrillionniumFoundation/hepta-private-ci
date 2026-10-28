"""Fixed eight-source mechanism and resource probe; never fit or read holdouts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
import wave
import zipfile

from .registration import load_registration, digest
from .ci_runtime import resources




def cpu_seconds():
    return sum(getattr(resource.getrusage(kind),name) for kind in (resource.RUSAGE_SELF,resource.RUSAGE_CHILDREN)
               for name in ('ru_utime','ru_stime'))


def write_json(path, value):
    with path.open('x') as stream:stream.write(json.dumps(value,indent=2,sort_keys=True)+'\n')


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):h.update(block)
    return h.hexdigest()


def roundtrip(directory, video, audio, text):
    import numpy as np
    from PIL import Image
    directory.mkdir(parents=True,exist_ok=False)
    if video.shape!=(16,112,112,3) or audio.shape!=(32000,):raise ValueError('Wrong codec dimensions')
    (directory/'text.txt').write_text(text,encoding='utf-8')
    Image.fromarray(video[8]).save(directory/'image.png')
    pcm=np.rint(np.clip(audio,-1.,1.)*32767).astype('<i2')
    with wave.open(str(directory/'audio.wav'),'wb') as stream:
        stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(16000);stream.writeframes(pcm.tobytes())
    command=['ffmpeg','-v','error','-threads','1','-f','rawvideo','-pix_fmt','rgb24','-s','112x112','-r','8',
             '-i','pipe:0','-an','-c:v','ffv1','-threads','1',str(directory/'video.mkv')]
    subprocess.run(command,input=video.tobytes(),capture_output=True,check=True)
    raw=subprocess.run(['ffmpeg','-v','error','-threads','1','-i',str(directory/'video.mkv'),
                        '-f','rawvideo','-pix_fmt','rgb24','pipe:1'],capture_output=True,check=True).stdout
    read_video=np.frombuffer(raw,np.uint8).reshape(16,112,112,3).copy()
    with wave.open(str(directory/'audio.wav'),'rb') as stream:
        if (stream.getnchannels(),stream.getsampwidth(),stream.getframerate(),stream.getnframes())!=(1,2,16000,32000):
            raise ValueError('Invalid physical WAV readback')
        read_audio=np.frombuffer(stream.readframes(32000),'<i2').astype(np.float32)/32767.
    with Image.open(directory/'image.png') as image:
        read_image=np.asarray(image.convert('RGB'))
    if not np.array_equal(video,read_video) or not np.array_equal(video[8],read_image):
        raise ValueError('Lossless visual codec failed byte equality')
    if (directory/'text.txt').read_text(encoding='utf-8')!=text:raise ValueError('Text readback differs')
    if not np.array_equal(read_audio,pcm.astype(np.float32)/32767.):raise ValueError('PCM readback differs')
    files={name:{'bytes':(directory/name).stat().st_size,'sha256':sha(directory/name)}
           for name in ('text.txt','audio.wav','image.png','video.mkv')}
    if sum(item['bytes'] for item in files.values())>4*1024*1024:raise ValueError('Mechanism bundle exceeds fixed delivery cap')
    return read_video,read_audio,files


def probe(registration_path, output, assets_override=None):
    wall=time.monotonic();registration=load_registration(registration_path,assets_override)
    spec=registration['specification'];assets=Path(registration['parent_assets']) if assets_override is None else Path(assets_override)
    output.mkdir(parents=True,exist_ok=False)
    observed=resources();space=os.statvfs(output)
    initial={'schema':'hepta.closure.top1-v4-mechanism-entry.v1','registration_sha256':registration['registration_sha256'],
             'resources_before_model_import':observed,'free_disk_bytes':space.f_bavail*space.f_frsize,
             'fixed_source_ids':registration['mechanism_source_ids'],'actual_assets_root':str(assets),
             'torch_imported_before_gate':'torch' in sys.modules,'fitted_models':0,'new_training_updates':0,
             'new_holdout_media_or_predictions':0}
    write_json(output/'ENTRY.json',initial)
    if (observed['effective_headroom_bytes']<spec['budget']['initial_process_headroom_minimum_bytes']
            or initial['free_disk_bytes']<spec['budget']['mechanism_minimum_free_disk_bytes']):
        result={**initial,'status':'resource_gate_blocked','torch_imported':'torch' in sys.modules,'sources_downloaded':0,
                'total_process_self_children_cpu_seconds':cpu_seconds(),'wall_seconds_since_entry':time.monotonic()-wall}
        write_json(output/'RESULT.json',result);return result
    from importlib.metadata import version
    if sys.version.split()[0]!=spec['runtime_versions']['python']:raise ValueError('Registered Python runtime differs')
    for name,expected in spec['runtime_versions'].items():
        if name!='python' and version(name)!=expected:raise ValueError('Registered package runtime differs: '+name)
    import numpy as np
    import torch
    from ..data_prepare import decode
    from ..data_prepare_v2 import window
    from ...unified_20261028.natural_data import RemoteZip
    from .features import TemporalFeatures
    torch.set_num_threads(2)
    plan=json.loads((assets/'SOURCE_PROTOCOL.json').read_text())
    selected={row['source_id']:row for row in plan['selected'] if row['role']=='observer_train'}
    models=TemporalFeatures(assets/'pretrained')
    observations=[resources()];records=[];remote=None;archive=None
    try:
        for sid in registration['mechanism_source_ids']:
            before=resources();observations.append(before)
            if before['effective_headroom_bytes']<spec['budget']['source_boundary_headroom_minimum_bytes']:
                raise RuntimeError('Resource reserve exhausted at a completed source boundary')
            source=selected[sid];old_dir=assets/'prepared/observer_train'/sid
            old_receipt=json.loads((old_dir/'RECEIPT.json').read_text())
            if sha(old_dir/'FEATURES.npz')!=old_receipt['retained_files']['FEATURES.npz']:
                raise ValueError('Frozen training comparison features changed')
            if source['source_bytes']>spec['budget']['maximum_original_member_bytes']:raise ValueError('Source exceeds registered bound')
            if archive is None:
                identity=plan['archive']['train'];remote=RemoteZip(identity['url'])
                if (remote.generation,remote.etag,remote.length)!=(identity['generation'],identity['etag'],identity['length']):
                    raise ValueError('Official archive identity changed')
                archive=zipfile.ZipFile(remote)
            payload=archive.read(source['member'])
            if len(payload)!=source['source_bytes'] or digest(payload)!=old_receipt['original_source_sha256']:
                raise ValueError('Original training video bytes changed')
            source_dir=output/'sources'/sid;source_dir.mkdir(parents=True,exist_ok=False)
            raw=source_dir/'source.mp4';raw.write_bytes(payload);del payload
            frames,audio=decode(raw)
            with np.load(old_dir/'FEATURES.npz') as old:
                for index,event in enumerate(source['events'][:source['retained_event_count']]):
                    video,waveform,_,_=window(frames,audio,event)
                    video,waveform=video[8:24],waveform[16000:48000]
                    before_codec=models(video[None],waveform[None])
                    errors={}
                    for name,reference in [('video_pooled','video'),('sound_pooled','audio'),('tsm_pooled_check','video_tsm')]:
                        observed_row=before_codec[name][0];expected=old[reference][index]
                        error=float(np.max(np.abs(observed_row-expected)));errors[name]=error
                        if not np.allclose(observed_row,expected,atol=spec['mechanism_checks']['precodec_pooled_reference_atol'],rtol=spec['mechanism_checks']['precodec_pooled_reference_rtol']):
                            raise ValueError('Pre-codec pooled feature parity failed')
                    text=f"Action: {plan['ontology']['action'][str(event['action_id'])]}. Sound: {plan['ontology']['sound'][str(event['sound_id'])]}."
                    directory=source_dir/f'event-{index:03d}'
                    actual_video,actual_audio,files=roundtrip(directory,video,waveform,text)
                    delivered=models(actual_video[None],actual_audio[None])
                    np.savez_compressed(directory/'FEATURES.npz',**{k:v for k,v in delivered.items() if k!='tsm_pooled_check'})
                    row={'source_id':sid,'event_index':index,'original_video_sha256':old_receipt['original_source_sha256'],
                         'artifacts':files,'feature_sha256':sha(directory/'FEATURES.npz'),
                         'feature_shapes':{k:list(v.shape) for k,v in delivered.items()},
                         'precodec_pooled_max_abs_error':errors,
                         'source_audio_clipped_fraction':float(np.mean(np.abs(waveform)>1.)),
                         'pcm16_max_absolute_error_to_clipped_source':float(np.max(np.abs(actual_audio-np.clip(waveform,-1,1))))}
                    write_json(directory/'RECEIPT.json',row);records.append(row);observations.append(resources())
            raw.unlink()
        status='passed'
        error=None
    except Exception as exception:
        status='incomplete_or_failed';error=type(exception).__name__+': '+str(exception)
    result={**initial,'status':status,'error':error,'torch_imported':True,'event_records':records,
            'expected_events':registration['mechanism_events'],'events_completed':len(records),'resource_observations':observations,
            'range_receipts':remote.receipts if remote is not None else [],
            'total_process_self_children_cpu_seconds':cpu_seconds(),'wall_seconds_since_entry':time.monotonic()-wall,
            'native_owner_called':False,'generator_called':False,'semantic_accuracy_evaluated':False,
            'scope':'Fixed training-source feature/physical-codec and resource mechanism only; no observer fitting, policy or held-out access.'}
    if status=='passed' and len(records)!=registration['mechanism_events']:raise ValueError('Mechanism event count changed')
    write_json(output/'RESULT.json',result);return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--registration',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--assets',type=Path)
    args=parser.parse_args()
    try:
        result=probe(args.registration,args.output,args.assets)
    except Exception as error:
        if args.output.is_dir() and not (args.output/'RESULT.json').exists():
            write_json(args.output/'FAILURE.json',{'status':'failed_before_source_loop','error':type(error).__name__+': '+str(error),'total_process_self_children_cpu_seconds':cpu_seconds(),'torch_imported':'torch' in sys.modules})
        raise
    print(json.dumps({k:v for k,v in result.items() if k in ('status','error','events_completed','torch_imported','total_process_self_children_cpu_seconds')}))
    if result['status']!='passed':raise SystemExit(3 if result['status']=='resource_gate_blocked' else 1)
