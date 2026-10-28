"""Physical natural-media serialization, reopening and fixed terminal utility."""
from collections import Counter
import hashlib
import io
import math
from pathlib import Path
import subprocess
import wave

import numpy as np
from PIL import Image

SCORE_SPEC={
 'schema':'hepta.closure.natural-terminal-score.v1',
 'task':'same-event two-second missing-segment reconstruction with exact annotation-template caption',
 'text':'multiset token F1 of physically reopened UTF-8 against the official action/sound caption',
 'image':'exp(-10 * mean squared RGB error), reopened 112x112 PNG',
 'video':'exp(-10 * mean squared RGB error), sixteen reopened 112x112 FFV1 frames at 8fps',
 'audio':'exp(-min(10, 0.5*waveform_MSE/(target_power+1e-5) + 0.5*mean_abs(log1p(20*STFTabs(output))-log1p(20*STFTabs(target)))))',
 'stft':'16kHz, Hann nperseg256/noverlap128, scipy boundary=zeros, magnitude rescaled by128',
 'joint':'clip(0.5*min(four qualities)+0.5*geometric_mean(four qualities)-0.1*mean_abs(image-video[8]),0,1)',
 'failure_utility':0.0,
 'semantic_constraint':'separate immutable independent-observer adequacy and generated joint-action/sound/caption gates; reconstruction utility never substitutes for passing them',
 'observer_access':'private targets and semantic reference labels are read only by terminal_score after original owner close',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def ffmpeg(arguments,payload):
    result=subprocess.run(['ffmpeg','-v','error','-threads','1',*arguments],input=payload,capture_output=True)
    if result.returncode:raise ValueError(result.stderr.decode(errors='replace')[:600])
    return result.stdout


def caption(action_id,sound_id,ontology):
    return ontology['action'][str(action_id)].lower().strip()+'; '+ontology['sound'][str(sound_id)].lower().strip()


def encode(values,model,index=0):
    image=values['image'][index].detach().cpu().numpy()
    video=values['video'][index].detach().cpu().numpy()
    audio=values['audio'][index].detach().cpu().numpy()
    if image.shape!=(3,112,112) or video.shape!=(16,3,112,112) or audio.shape!=(32000,):
        raise ValueError('Unregistered emitted dimensions')
    if not all(np.isfinite(x).all() for x in (image,video,audio)):
        raise ValueError('Nonfinite emitted values')
    action=model.action_ids[int(values['action'][index])];sound=model.sound_ids[int(values['sound'][index])]
    encoded={'text':caption(action,sound,model.ontology).encode('utf8')}
    stream=io.BytesIO();pixels=np.uint8(np.clip(image.transpose(1,2,0),0,1)*255+.5)
    Image.fromarray(pixels).save(stream,format='PNG');encoded['image']=stream.getvalue()
    pcm=np.int16(np.clip(audio,-1,1)*32767).astype('<i2')
    stream=io.BytesIO()
    with wave.open(stream,'wb') as out:
        out.setnchannels(1);out.setsampwidth(2);out.setframerate(16000);out.writeframes(pcm.tobytes())
    encoded['audio']=stream.getvalue()
    frames=np.uint8(np.clip(video.transpose(0,2,3,1),0,1)*255+.5)
    first=ffmpeg(['-f','rawvideo','-pix_fmt','rgb24','-s','112x112','-r','8','-i','pipe:0',
                  '-an','-c:v','ffv1','-level','3','-pix_fmt','bgr0','-f','matroska','pipe:1'],frames.tobytes())
    encoded['video']=ffmpeg(['-fflags','+bitexact','-i','pipe:0','-map','0:v:0','-map_metadata','-1',
                             '-c:v','copy','-fflags','+bitexact','-f','matroska','pipe:1'],first)
    return encoded


def reopen(refs):
    if set(refs)!=set(('text','audio','image','video')):
        raise ValueError('Incomplete actual four-media delivery')
    payload={name:Path(path).read_bytes() for name,path in refs.items()}
    image=np.asarray(Image.open(io.BytesIO(payload['image'])).convert('RGB'))
    with wave.open(io.BytesIO(payload['audio']),'rb') as src:
        if (src.getnchannels(),src.getsampwidth(),src.getframerate(),src.getnframes())!=(1,2,16000,32000):
            raise ValueError('Audio format changed')
        audio=np.frombuffer(src.readframes(32000),'<i2').astype(np.float32)/32767
    video=np.frombuffer(ffmpeg(['-i','pipe:0','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],payload['video']),np.uint8)
    if image.shape!=(112,112,3) or video.size!=16*112*112*3:raise ValueError('Media dimensions changed')
    text=payload['text'].decode('utf8')
    if len(payload['text'])>4096:raise ValueError('Caption capacity changed')
    return {'image':image.astype(np.float32)/255,'video':video.reshape(16,112,112,3).astype(np.float32)/255,
            'audio':audio,'text':text},{name:sha(value) for name,value in payload.items()}


def score(delivered,reference,reference_caption):
    from scipy.signal import stft
    tokens=lambda text:Counter(text.replace(';',' ; ').split())
    a,b=tokens(delivered['text']),tokens(reference_caption)
    text=2*sum((a&b).values())/max(1,sum(a.values())+sum(b.values()))
    image=float(np.mean((delivered['image']-reference['image'])**2))
    video=float(np.mean((delivered['video']-reference['video'])**2))
    predicted=delivered['audio'];target=reference['audio']
    waveform=float(np.mean((predicted-target)**2)/(np.mean(target**2)+1e-5))
    spectrum=lambda x:np.abs(stft(x,fs=16000,nperseg=256,noverlap=128,boundary='zeros')[2])*128
    spectral=float(np.mean(np.abs(np.log1p(20*spectrum(predicted))-np.log1p(20*spectrum(target)))))
    qualities={'text':text,'image':math.exp(-10*image),'video':math.exp(-10*video),
               'audio':math.exp(-min(10,.5*waveform+.5*spectral))}
    q=np.asarray(list(qualities.values()));disagreement=float(np.mean(np.abs(delivered['image']-delivered['video'][8])))
    utility=float(np.clip(.5*q.min()+.5*np.prod(q)**.25-.1*disagreement,0,1))
    return {'utility':utility,'qualities':qualities,'image_mse':image,'video_mse':video,
            'normalized_audio_mse':waveform,'audio_spectral_distance':spectral,
            'image_video_disagreement':disagreement,'exact_caption':delivered['text']==reference_caption}
