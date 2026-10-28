"""Frozen pretrained temporal features; original modules and weights stay unchanged."""
import numpy as np
import torch
from torch.nn import functional as F

from ..semantic_backbones import SemanticBackbones
from ..semantic_tsm import TsmObserver


class TemporalFeatures:
    def __init__(self, root):
        self.models=SemanticBackbones(root)
        self.tsm=TsmObserver(root)

    @torch.no_grad()
    def __call__(self, video, waveform):
        from scipy.signal import resample_poly
        video=np.asarray(video,np.uint8)
        waveform=np.asarray(waveform,np.float32)
        if video.shape!=(1,16,112,112,3) or waveform.shape!=(1,32000):
            raise ValueError('Expected one exact original-task target window')
        x=torch.as_tensor(video[:,1::2].copy()).permute(0,1,4,2,3).float()/255
        x=F.interpolate(x.reshape(8,3,112,112),size=(256,256),mode='bilinear',align_corners=False)
        x=x[:,:,16:240,16:240]
        mean=torch.tensor((.485,.456,.406))[None,:,None,None]
        scale=torch.tensor((.229,.224,.225))[None,:,None,None]
        video_tokens=self.tsm.base_model((x-mean)/scale).reshape(1,8,2048)
        hidden=video_tokens.mean(1)
        tsm_pooled=torch.cat((hidden,self.tsm.new_fc(hidden).softmax(1)),1)
        audio=self.models.audio
        x=torch.from_numpy(resample_poly(waveform,2,1,axis=1).copy())
        x=F.pad(x[:,None],(512,512),mode='reflect')
        stft=audio.spectrogram_extractor.stft
        power=(stft.conv_real(x).square()+stft.conv_imag(x).square()).transpose(1,2)
        mel=10.*torch.log10((power@audio.logmel_extractor.melW).clamp_min(1e-10))
        x=audio.bn0(mel[:,None].transpose(1,3)).transpose(1,3)
        local=audio.features(x).mean(3)
        pooled=F.relu(audio.fc1(local.amax(2)+local.mean(2)))
        sound_pooled=torch.cat((pooled,torch.sigmoid(audio.fc_audioset(pooled))),1)
        sound_tokens=F.adaptive_avg_pool1d(local,8).transpose(1,2)
        result={'video_pooled':self.models.video_features(video),
                'video_tokens':video_tokens.cpu().numpy(),
                'sound_pooled':sound_pooled.cpu().numpy(),
                'sound_tokens':sound_tokens.cpu().numpy(),
                'tsm_pooled_check':tsm_pooled.cpu().numpy()}
        if not all(np.isfinite(value).all() for value in result.values()):
            raise ValueError('Nonfinite frozen feature value')
        return result
