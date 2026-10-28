"""Trainable shared transitions and dense four-modal emissions around a strong prior.

This model reconstructs a fixed two-second natural segment. Pretrained context
feature extraction is frozen, explicitly costed in each real episode, and feeds
trainable raw-media encoders and projections. It is not open-domain synthesis.
"""
import hashlib
import math

import torch
from torch import nn
from torch.nn import functional as F

LAW = {'schema':'hepta.closure.natural-emission.v1','video_shape':[16,3,112,112],
       'image_shape':[3,112,112],'audio_samples':32000,'audio_sample_rate':16000,
       'image_sigma':0.001,'video_sigma':0.001,'audio_sigma':0.0005,
       'caption':'independent categorical action and sound labels given shared state; exact published template rendering',
       'caption_temperature':0.25,'transitions':2,
       'base':'linear context-boundary video/image interpolation, adjacent context audio concatenation; unavailable boundary repeats the available opposite boundary',
       'residual':'dense trainable spatial/temporal and waveform emission, bounded 0.1*tanh residual',
       'frozen_context_features':['TSM Something-Something V2','PANN MobileNetV2'],
       'density':'normalized joint Gaussian pre-codec actions plus both normalized categorical probabilities',
       'deterministic_routes':'strong fixed interpolation and frozen neural means/argmax are declared separate laws'}


def parameter_hash(model):
    h=hashlib.sha256()
    for name,tensor in sorted(model.state_dict().items()):
        h.update(name.encode());h.update(tensor.detach().cpu().contiguous().numpy().tobytes())
    return h.hexdigest()


class VideoEncoder(nn.Module):
    def __init__(self, hidden):
        super().__init__()
        self.raw=nn.Sequential(nn.Conv3d(4,12,3,stride=(2,2,2),padding=1),nn.SiLU(),
             nn.Conv3d(12,24,3,stride=2,padding=1),nn.SiLU(),nn.AdaptiveAvgPool3d((2,3,3)),
             nn.Flatten(),nn.Linear(432,hidden),nn.Tanh())
        self.pretrained=nn.Sequential(nn.Linear(2222,hidden),nn.Tanh())
        self.fusion=nn.Linear(2*hidden,hidden)

    def forward(self,video,mask,features):
        flags=mask[:,None,:,None,None].expand(-1,1,-1,112,112)
        raw=self.raw(torch.cat((video.permute(0,2,1,3,4),flags),1))
        projected=self.pretrained(features)
        return torch.tanh(self.fusion(torch.cat((raw,projected),1)))


class AudioEncoder(nn.Module):
    def __init__(self,hidden):
        super().__init__()
        self.raw=nn.Sequential(nn.Conv1d(2,12,17,8,8),nn.SiLU(),nn.Conv1d(12,24,9,8,4),
             nn.SiLU(),nn.Conv1d(24,32,9,4,4),nn.SiLU(),nn.AdaptiveAvgPool1d(8),
             nn.Flatten(),nn.Linear(256,hidden),nn.Tanh())
        self.pretrained=nn.Sequential(nn.Linear(1551,hidden),nn.Tanh())
        self.fusion=nn.Linear(2*hidden,hidden)

    def forward(self,audio,mask,features):
        raw=self.raw(torch.stack((audio,mask),1))
        return torch.tanh(self.fusion(torch.cat((raw,self.pretrained(features)),1)))


class SpatialEmission(nn.Module):
    def __init__(self,hidden):
        super().__init__()
        self.condition=nn.Linear(hidden,8)
        self.first=nn.Sequential(nn.Conv2d(18,16,3,padding=1),nn.SiLU())
        self.down=nn.Sequential(nn.Conv2d(16,24,3,2,1),nn.SiLU(),nn.Conv2d(24,24,3,2,1),nn.SiLU())
        self.up=nn.Sequential(nn.Conv2d(40,16,3,padding=1),nn.SiLU(),nn.Conv2d(16,3,3,padding=1))
        nn.init.zeros_(self.up[-1].weight);nn.init.zeros_(self.up[-1].bias)

    def forward(self,left,right,weights,state):
        b=left.shape[0];t=len(weights)
        left=left[:,None].expand(-1,t,-1,-1,-1).reshape(b*t,3,112,112)
        right=right[:,None].expand(-1,t,-1,-1,-1).reshape(b*t,3,112,112)
        times=weights[None,:,None,None,None].expand(b,-1,1,112,112).reshape(b*t,1,112,112)
        base=left*(1-times)+right*times
        condition=self.condition(state)[:,None,:,None,None].expand(-1,t,-1,112,112).reshape(b*t,8,112,112)
        first=self.first(torch.cat((left,right,base,times,condition),1))
        down=F.interpolate(self.down(first),size=(112,112),mode='bilinear',align_corners=False)
        delta=self.up(torch.cat((first,down),1))
        return (base+.1*torch.tanh(delta)).clamp(0,1).reshape(b,t,3,112,112),base.reshape(b,t,3,112,112)


class AudioEmission(nn.Module):
    def __init__(self,hidden):
        super().__init__()
        self.condition=nn.Linear(hidden,4)
        self.encoder=nn.Sequential(nn.Conv1d(6,16,17,4,8),nn.SiLU(),nn.Conv1d(16,24,9,4,4),nn.SiLU())
        self.decoder=nn.Sequential(nn.Conv1d(24,16,9,padding=4),nn.SiLU(),nn.Conv1d(16,1,9,padding=4))
        nn.init.zeros_(self.decoder[-1].weight);nn.init.zeros_(self.decoder[-1].bias)

    def forward(self,base,mask,state):
        features=self.condition(state)[:,:,None].expand(-1,-1,32000)
        encoded=self.encoder(torch.cat((base[:,None],mask[:,None],features),1))
        delta=self.decoder(F.interpolate(encoded,size=32000,mode='linear',align_corners=False))[:,0]
        return (base+.1*torch.tanh(delta)).clamp(-1,1)


class NaturalGenerator(nn.Module):
    def __init__(self,ontology,hidden=96):
        super().__init__()
        self.ontology=ontology;self.hidden=hidden
        self.action_ids=sorted(map(int,ontology['action']));self.sound_ids=sorted(map(int,ontology['sound']))
        self.encoder_video=VideoEncoder(hidden);self.encoder_audio=AudioEncoder(hidden)
        self.encoder_fusion=nn.Sequential(nn.Linear(2*hidden,hidden),nn.Tanh())
        self.initial_states=nn.Linear(hidden,4*hidden)
        self.shared_transition=nn.Sequential(nn.Linear(6*hidden,5*hidden),nn.Tanh())
        self.adapters=nn.ModuleDict({name:nn.Sequential(nn.Linear(2*hidden,hidden),nn.Tanh())
                                    for name in ('text','audio','image','video')})
        self.emissions=nn.ModuleDict({'text':nn.Linear(hidden,len(self.action_ids)+len(self.sound_ids)),
              'audio':AudioEmission(hidden),'image':SpatialEmission(hidden),'video':SpatialEmission(hidden)})

    def forward(self,public):
        video,audio=public['video'],public['audio'];vm,am=public['video_mask'],public['audio_mask']
        v=self.encoder_video(video,vm,public['video_features'])
        a=self.encoder_audio(audio,am,public['audio_features'])
        context=self.encoder_fusion(torch.cat((v,a),1));shared=context
        states=list(self.initial_states(context).tanh().chunk(4,1))
        for _ in range(2):
            update=self.shared_transition(torch.cat((shared,*states,context),1)).chunk(5,1)
            shared=shared+.2*update[0];states=[s+.2*d for s,d in zip(states,update[1:])]
        latents={name:self.adapters[name](torch.cat((shared,state),1))
                 for name,state in zip(('text','audio','image','video'),states)}
        left,right=video[:,7],video[:,8]
        left=torch.where(vm[:,7,None,None,None]>0,left,right)
        right=torch.where(vm[:,8,None,None,None]>0,right,left)
        weights=torch.arange(1,17,dtype=video.dtype,device=video.device)/17
        emitted_video,base_video=self.emissions['video'](left,right,weights,latents['video'])
        emitted_image,_=self.emissions['image'](left,right,weights[8:9],latents['image'])
        audio_base=audio.clone()
        left_ok=am[:,:16000].any(1);right_ok=am[:,16000:].any(1)
        audio_base[:,:16000]=torch.where(left_ok[:,None],audio[:,:16000],audio[:,16000:])
        audio_base[:,16000:]=torch.where(right_ok[:,None],audio[:,16000:],audio_base[:,:16000])
        text=self.emissions['text'](latents['text']);n=len(self.action_ids)
        return {'video':emitted_video,'image':emitted_image[:,0],
                'audio':self.emissions['audio'](audio_base,am,latents['audio']),
                'action_logits':text[:,:n],'sound_logits':text[:,n:],
                'base_video':base_video,'base_image':base_video[:,8],'base_audio':audio_base,
                'shared_state':shared}

    def interpolate(self, public):
        """Strong fixed baseline: compute its trained caption, skip unused decoders."""
        video,audio=public['video'],public['audio'];vm,am=public['video_mask'],public['audio_mask']
        v=self.encoder_video(video,vm,public['video_features'])
        a=self.encoder_audio(audio,am,public['audio_features'])
        context=self.encoder_fusion(torch.cat((v,a),1));shared=context
        states=list(self.initial_states(context).tanh().chunk(4,1))
        for _ in range(2):
            update=self.shared_transition(torch.cat((shared,*states,context),1)).chunk(5,1)
            shared=shared+.2*update[0];states=[state+.2*delta for state,delta in zip(states,update[1:])]
        latent=self.adapters['text'](torch.cat((shared,states[0]),1))
        text=self.emissions['text'](latent);n=len(self.action_ids)
        left,right=video[:,7],video[:,8]
        left=torch.where(vm[:,7,None,None,None]>0,left,right)
        right=torch.where(vm[:,8,None,None,None]>0,right,left)
        weights=torch.arange(1,17,dtype=video.dtype,device=video.device)[None,:,None,None,None]/17
        base_video=left[:,None]*(1-weights)+right[:,None]*weights
        base_audio=audio.clone()
        left_ok=am[:,:16000].any(1);right_ok=am[:,16000:].any(1)
        base_audio[:,:16000]=torch.where(left_ok[:,None],audio[:,:16000],audio[:,16000:])
        base_audio[:,16000:]=torch.where(right_ok[:,None],audio[:,16000:],base_audio[:,:16000])
        return {'image':base_video[:,8],'video':base_video,'audio':base_audio,
                'base_image':base_video[:,8],'base_video':base_video,'base_audio':base_audio,
                'action_logits':text[:,:n],'sound_logits':text[:,n:]}

    def components(self):
        return {**{name:getattr(self,name) for name in ('encoder_video','encoder_audio','encoder_fusion','initial_states','shared_transition')},
                **{'adapter_'+name:module for name,module in self.adapters.items()},
                **{'emission_'+name:module for name,module in self.emissions.items()}}


def draw(output,rng,route='stochastic'):
    if route not in ('stochastic','deterministic','interpolation'):
        raise ValueError('Unregistered generation law')
    values={};logp=torch.zeros(len(output['audio']),dtype=torch.float64)
    for name in ('image','video','audio'):
        mean=output[('base_'+name) if route=='interpolation' else name]
        sigma=LAW[name+'_sigma']
        sample=mean.detach() if route!='stochastic' else mean.detach()+sigma*torch.randn(mean.shape,generator=rng)
        values[name]=sample
        if route=='stochastic':
            density=-.5*((sample.double()-mean.double())/sigma).square()-math.log(sigma)-.5*math.log(2*math.pi)
            logp+=density.flatten(1).sum(1)
    for kind in ('action','sound'):
        logits=output[kind+'_logits']/LAW['caption_temperature']
        if route=='stochastic':
            chosen=torch.multinomial(logits.detach().softmax(1),1,generator=rng)[:,0]
            logp+=logits.log_softmax(1).gather(1,chosen[:,None])[:,0].double()
        else:chosen=logits.argmax(1)
        values[kind]=chosen
    return values,logp



def sampled_log_density(output, values):
    """Same normalized law, evaluated at already sampled pre-codec actions."""
    result=torch.zeros(len(values['audio']),dtype=torch.float64)
    for name in ('image','video','audio'):
        sigma=LAW[name+'_sigma'];sample=values[name].detach();mean=output[name]
        density=-.5*((sample.double()-mean.double())/sigma).square()-math.log(sigma)-.5*math.log(2*math.pi)
        result+=density.flatten(1).sum(1)
    for kind in ('action','sound'):
        logits=output[kind+'_logits']/LAW['caption_temperature']
        result+=logits.log_softmax(1).gather(1,values[kind].detach()[:,None])[:,0].double()
    return result


def proxy_loss(output,target):
    rgb=20*((output['image']-target['image']).square().flatten(1).mean(1)+
            (output['video']-target['video']).square().flatten(1).mean(1))
    audio=(output['audio']-target['audio']).square().mean(1)/(target['audio'].square().mean(1)+1e-4)
    window=torch.hann_window(256,device=output['audio'].device)
    pred=torch.stft(output['audio'],256,128,window=window,return_complex=True).abs()
    truth=torch.stft(target['audio'],256,128,window=window,return_complex=True).abs()
    spectrum=(torch.log1p(20*pred)-torch.log1p(20*truth)).abs().flatten(1).mean(1)
    text=F.cross_entropy(output['action_logits'],target['action'],reduction='none')+F.cross_entropy(output['sound_logits'],target['sound'],reduction='none')
    consistency=(output['image']-output['video'][:,8]).square().flatten(1).mean(1)
    return rgb+.15*audio+.15*spectrum+text+.5*consistency
