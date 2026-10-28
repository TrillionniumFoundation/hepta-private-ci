"""Natural callback port for the same fully metered native episode executor."""
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import torch

from .control_episode import MediaFailure
from .data_sources import digest
from .natural_media import caption,encode,reopen,score
from .natural_model import draw,parameter_hash,sampled_log_density


def array_hash(values):
    h=hashlib.sha256()
    for name,value in sorted(values.items()):
        if isinstance(value,torch.Tensor):value=value.detach().cpu().numpy()
        h.update(name.encode());h.update(np.ascontiguousarray(value).tobytes())
    return h.hexdigest()


def public_tensors(data,tsm,pann):
    frames=np.asarray(data['context_video'],np.uint8);audio=np.asarray(data['context_audio'],np.float32)
    vm=np.asarray(data['context_video_mask']) if 'context_video_mask' in data else np.ones(16,bool)
    am=np.asarray(data['context_audio_mask']) if 'context_audio_mask' in data else np.ones(32000,bool)
    vf=tsm.features(frames[None]);af=pann.audio_features(audio[None])
    public={'video':torch.tensor(frames.transpose(0,3,1,2)[None].copy(),dtype=torch.float32)/255,
            'audio':torch.tensor(audio[None].copy()),'video_mask':torch.tensor(vm[None].copy(),dtype=torch.float32),
            'audio_mask':torch.tensor(am[None].copy(),dtype=torch.float32),
            'video_features':torch.tensor(vf),'audio_features':torch.tensor(af)}
    return public


class NaturalPort:
    def __init__(self,*,model,event_directory,tsm,pann,seed,route='stochastic',fault_first=False,actor_features=True):
        self.model=model;self.directory=Path(event_directory);self.tsm=tsm;self.pann=pann
        self.rng=torch.Generator().manual_seed(seed);self.route=route;self.fault_first=fault_first
        self.emission_count=0;self.public=None;self.metadata=None
        self.compute_actor_features=actor_features;self.sampled_actions=[];self.prepared_binding=None;self.input_binding=None

    def prepare(self):
        self.metadata={'event_id':self.directory.name+'-closure-0',
                       'source_id':self.directory.name,'role':self.directory.parent.name}
        # Lazy NPZ reads select public inputs only. Target arrays stay untouched
        # until terminal_score is invoked after the original native owner stops.
        with np.load(self.directory/'EVENT.npz') as data:
            self.public=public_tensors(data,self.tsm,self.pann)
        self.prepared_binding=parameter_hash(self.model);self.input_binding=array_hash(self.public)
        return {'event_id':self.metadata['event_id'],'source_id':self.metadata['source_id'],
                'split':{'generator_train':'train','policy_calibration':'calibration'}.get(self.metadata['role'],self.metadata['role']),
                'allocation_role':self.metadata['role'],'public_input_sha256':self.input_binding,
                'current_parameter_sha256':self.prepared_binding,'emission_route':self.route}

    def emit(self,action,public,output_dir,register_sample,write_file):
        if array_hash(self.public)!=public['public_input_sha256']:
            raise ValueError('Prepared public inputs changed')
        before=digest(self.rng.get_state().numpy().tobytes())
        output=self.model.interpolate(self.public) if self.route=='interpolation' else self.model(self.public)
        values,logp=draw(output,self.rng,self.route)
        after=digest(self.rng.get_state().numpy().tobytes())
        if parameter_hash(self.model)!=self.prepared_binding:
            raise ValueError('Generator parameters changed inside actual delivery')
        if self.route=='stochastic':
            self.sampled_actions.append({'values':{name:value.detach().clone() for name,value in values.items()},
                'sampled_sha256':array_hash(values),'joint_log_probability':float(logp[0]),
                'mean_sha256':array_hash({name:output[name] for name in ('image','video','audio','action_logits','sound_logits')})})
            register_sample(logp[0],{'sampled_sha256':array_hash(values),
                'rng_before_sha256':before,'rng_after_sha256':after})
        self.emission_count+=1
        try:
            payload=encode(values,self.model)
            if self.fault_first and self.emission_count==1:
                payload['video']=payload['video'][:31]  # A real bounded-write transport fault.
            suffix={'text':'.txt','audio':'.wav','image':'.png','video':'.mkv'}
            refs={name:write_file(name,suffix[name],payload[name]) for name in ('text','audio','image','video')}
            delivered,hashes=reopen(refs)
        except (ValueError,OSError,RuntimeError) as exc:
            raise MediaFailure(str(exc)) from exc
        if not self.compute_actor_features:
            return {'artifact_refs':refs,'artifact_sha256':hashes,'terminal_kind':'delivered',
                    'stochastic':self.route=='stochastic','public_feedback':1,'public_features':[0.]*16,
                    'final_state_digest':digest({'action':action,'artifacts':hashes,'draw':self.emission_count})}
        image=delivered['image'];audio=delivered['audio'];video=delivered['video']
        entropy=[]
        # Frozen public-context statistics, never current trainable logits.
        # Thus a fixed actor has no explicit generator-parameter path outside
        # the actually sampled and registered delivered-media actions.
        for probabilities in (self.public['video_features'][:,-174:],self.public['audio_features'][:,-527:]):
            probabilities=probabilities.detach().clamp_min(1e-30)
            probabilities=probabilities/probabilities.sum(1,keepdim=True)
            entropy.append(float(-(probabilities*probabilities.log()).sum()/math.log(probabilities.shape[1])))
        public_features=[len(delivered['text'].encode('utf8'))/4096,len(delivered['text'].split())/128,float(self.public['video_mask'][:,:8].mean()),float(self.public['video_mask'][:,8:].mean()),
            float(self.public['audio'].square().mean().sqrt()),
            float((self.public['video'][:,1:]-self.public['video'][:,:-1]).abs().mean()),
            float(np.sqrt(np.mean(audio**2))),float(np.max(np.abs(audio))),*image.mean((0,1)).astype(float).tolist(),
            float(np.mean(np.abs(np.diff(video,axis=0)))),*entropy,
            float(np.mean((image-video[8])**2)),float(abs(np.mean(audio)))]
        return {'artifact_refs':refs,'artifact_sha256':hashes,'terminal_kind':'delivered',
                'stochastic':self.route=='stochastic','public_feedback':1,'public_features':public_features,
                'final_state_digest':digest({'action':action,'artifacts':hashes,'draw':self.emission_count})}

    def replay_score(self):
        """Training-only likelihood evaluation; no draw, decision or media write."""
        if array_hash(self.public)!=self.input_binding:
            raise ValueError('Actual public tensors changed before likelihood replay')
        if parameter_hash(self.model)!=self.prepared_binding:
            raise ValueError('Parameters changed before the actual sampled-action score replay')
        rng_before=digest(self.rng.get_state().numpy().tobytes())
        result=torch.zeros((),dtype=torch.float64);checks=[]
        with torch.enable_grad():
            # Every retry in this frozen law starts from the same public state
            # and theta. Share its deterministic replay forward, but verify the
            # mean identity separately against every actual emission receipt.
            output=self.model(self.public) if self.sampled_actions else None
            mean_sha=(array_hash({name:output[name] for name in ('image','video','audio','action_logits','sound_logits')})
                      if output is not None else None)
            for trace in self.sampled_actions:
                if array_hash(trace['values'])!=trace['sampled_sha256']:
                    raise ValueError('Actual pre-codec sampled action changed before replay')
                if mean_sha!=trace['mean_sha256']:
                    raise ValueError('Gradient replay means differ from actually executed no-grad law')
                score=sampled_log_density(output,trace['values'])[0]
                error=abs(float(score.detach())-trace['joint_log_probability'])
                tolerance=1e-5+1e-10*abs(trace['joint_log_probability'])
                if error>tolerance:raise ValueError('Actual normalized joint log density changed in replay')
                result=result+score
                checks.append({'sampled_sha256':trace['sampled_sha256'],'mean_sha256':mean_sha,
                               'log_probability_absolute_error':error,'registered_tolerance':tolerance})
        if digest(self.rng.get_state().numpy().tobytes())!=rng_before:
            raise ValueError('Score replay must not advance the actual sampling RNG')
        return result,{'draws_replayed':len(checks),'replay_forward_evaluations':int(bool(checks)),
                       'shared_forward_only_after_all_actual_means_match':True,'checks':checks,'no_resampling':True,
                       'no_replanning_or_delivery':True,'same_parameter_sha256':self.prepared_binding}

    def terminal_score(self,final):
        delivered,actual=reopen(final['artifact_refs'])
        if actual!=final['artifact_sha256']:raise ValueError('Terminal artifact identity changed')
        with np.load(self.directory/'EVENT.npz') as data:
            reference={'image':data['target_image'].astype(np.float32)/255,
                       'video':data['target_video'].astype(np.float32)/255,'audio':data['target_audio']}
        reference_metadata=json.loads((self.directory/'RECEIPT.json').read_text())['events'][0]
        if any(reference_metadata[key]!=self.metadata[key] for key in ('event_id','source_id','role')):
            raise ValueError('Private reference belongs to another public input')
        text=caption(reference_metadata['action_id'],reference_metadata['sound_id'],self.model.ontology)
        return score(delivered,reference,text)
