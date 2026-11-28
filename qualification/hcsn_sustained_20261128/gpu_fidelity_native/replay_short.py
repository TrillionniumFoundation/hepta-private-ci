"""Independently recover the exceptional public FLV into both exact original arrays."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import numpy as np


def sha(b):return hashlib.sha256(b).hexdigest()

def main(root,out):
    pos=6186;name='1076_MTI_NEU_XX';flv=root/'data/raw'/(name+'.flv');sha_media=sha(flv.read_bytes());assert sha_media=='5152cf0f07dd16c3df3a088855a47b51258cfc23c2fc42826e1c2fdd3051acaf'
    ffmpeg=root/'env/ffmpeg';assert sha(ffmpeg.read_bytes())=='e7e7fb30477f717e6f55f9180a70386c62677ef8a4d4d1a5d948f4098aa3eb99'
    pre=[str(ffmpeg),'-nostdin','-loglevel','error','-threads','1','-filter_threads','1','-i',str(flv)]
    v=np.frombuffer(subprocess.check_output(pre+['-map','0:v:0','-vf','scale=28:28:flags=area','-pix_fmt','gray','-f','rawvideo','pipe:1']),np.uint8).reshape(-1,28,28)
    a=np.frombuffer(subprocess.check_output(pre+['-map','0:a:0','-ac','1','-ar','8000','-f','s16le','pipe:1']),'<i2')
    w=a.astype('float32')/32768;sw=np.lib.stride_tricks.sliding_window_view(w,256)[::80];p=np.abs(np.fft.rfft(sw*np.hanning(256),axis=1))**2;features=np.log1p(.5*(p[:,1:129:2]+p[:,2:129:2]))
    def ix(n):return np.minimum(n-1,((np.arange(12)+.5)*n/12).astype(int))
    vid=v[ix(len(v))];sound=features[ix(len(features))].astype('float32')
    with np.load(root/'data/data.npz',allow_pickle=False) as z:
        assert z['ids'][pos]==name and z['split'][pos]==1
        assert np.array_equal(vid,z['images'][pos]) and np.array_equal(sound,z['audio'][pos])
    ans={'id':name,'global_row':pos,'fold':'development','media_sha256':sha_media,'ffmpeg_sha256':sha(ffmpeg.read_bytes()),'frames':len(v),'samples':len(a),'unfilled_stft_windows':len(sw),'video_indices':ix(len(v)).tolist(),'spectral_indices':ix(len(features)).tolist(),'images_sha256':sha(vid.tobytes()),'audio_sha256':sha(sound.tobytes()),'exact_array_bytes':True}
    out.write_text(json.dumps(ans,indent=1)+'\n');print(json.dumps(ans))

if __name__=='__main__':main(Path(sys.argv[1]),Path(sys.argv[2]))
