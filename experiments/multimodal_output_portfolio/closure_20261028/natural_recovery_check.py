"""Small numerical checks of per-example reduction and exact optimizer recovery.

This verifies the actual proxy loss reduction on an independent-example fixture;
it is not a claim of bit-identical dense and microbatch production trajectories.
"""
import argparse
import copy
import io
from pathlib import Path

import torch
from torch import nn

from .data_sources import digest, save
from .natural_model import NaturalGenerator, parameter_hash, proxy_loss


class Fixture(nn.Module):
    def __init__(self):
        super().__init__()
        self.shared = nn.Sequential(nn.Linear(7, 24), nn.Tanh())
        self.output = nn.Linear(24, 3*8*8 + 2*3*8*8 + 512 + 7)

    def forward(self, x):
        value = self.output(self.shared(x))
        image, video, audio, action, sound = value.split((192, 384, 512, 4, 3), dim=1)
        return {"image": image.sigmoid().reshape(-1, 3, 8, 8),
                "video": video.sigmoid().reshape(-1, 2, 3, 8, 8).repeat_interleave(8, dim=1),
                "audio": audio.tanh(), "action_logits": action, "sound_logits": sound}


def check(output):
    torch.set_num_threads(2);torch.manual_seed(8931)
    full, micro = Fixture(), Fixture()
    micro.load_state_dict(full.state_dict())
    public = torch.randn(4, 7)
    target = {"image": torch.rand(4,3,8,8), "video": torch.rand(4,16,3,8,8),
              "audio": .1*torch.randn(4,512), "action": torch.tensor([0,1,2,3]), "sound": torch.tensor([0,1,2,0])}
    opt_full = torch.optim.AdamW(full.parameters(), lr=.0003, weight_decay=.0001)
    opt_micro = torch.optim.AdamW(micro.parameters(), lr=.0003, weight_decay=.0001)
    whole = proxy_loss(full(public), target).mean()
    whole.backward()
    parts = []
    for index in range(4):
        part = proxy_loss(micro(public[index:index+1]), {key:value[index:index+1] for key,value in target.items()}).mean()
        (part/4).backward();parts.append(float(part.detach()))
    errors = [float((a.grad-b.grad).abs().max()) for a,b in zip(full.parameters(),micro.parameters())]
    scale = max(float(p.grad.abs().max()) for p in full.parameters())
    torch.nn.utils.clip_grad_norm_(full.parameters(),2.)
    torch.nn.utils.clip_grad_norm_(micro.parameters(),2.)
    opt_full.step();opt_micro.step()
    update_error = max(float((a-b).detach().abs().max()) for a,b in zip(full.parameters(),micro.parameters()))
    # Exercise all checkpoint states, including dropout's global RNG, rather
    # than assuming model weights alone recover a stochastic optimizer path.
    torch.manual_seed(9012)
    model = nn.Sequential(nn.Linear(7,16), nn.Dropout(.15), nn.Tanh(), nn.Linear(16,3))
    optimizer = torch.optim.AdamW(model.parameters(),lr=.001)
    rng = torch.Generator().manual_seed(9013)
    def step(model,optimizer,rng):
        ids=torch.randint(4,(3,),generator=rng)
        loss=model(public[ids]).square().mean()
        optimizer.zero_grad();loss.backward();optimizer.step()
    for _ in range(3):step(model,optimizer,rng)
    buffer=io.BytesIO()
    torch.save({'model':model.state_dict(),'optimizer':optimizer.state_dict(),
                'sampler_rng':rng.get_state(),'global_rng':torch.get_rng_state()},buffer)
    for _ in range(2):step(model,optimizer,rng)
    expected=copy.deepcopy(model.state_dict());expected_optimizer=copy.deepcopy(optimizer.state_dict())
    restored=nn.Sequential(nn.Linear(7,16),nn.Dropout(.15),nn.Tanh(),nn.Linear(16,3))
    restored_optimizer=torch.optim.AdamW(restored.parameters(),lr=.001)
    state=torch.load(io.BytesIO(buffer.getvalue()),map_location='cpu',weights_only=True)
    restored.load_state_dict(state['model']);restored_optimizer.load_state_dict(state['optimizer'])
    restored_rng=torch.Generator();restored_rng.set_state(state['sampler_rng'])
    torch.set_rng_state(state['global_rng'])
    for _ in range(2):step(restored,restored_optimizer,restored_rng)
    exact_model=all(torch.equal(value,restored.state_dict()[key]) for key,value in expected.items())
    exact_optimizer=all(torch.equal(value,restored_optimizer.state_dict()['state'][index][key])
                        if isinstance(value,torch.Tensor) else value==restored_optimizer.state_dict()['state'][index][key]
                        for index,item in expected_optimizer['state'].items() for key,value in item.items())
    # The production model is inspected without allocating production pixels.
    production=NaturalGenerator({'action':{str(i):str(i) for i in range(63)},'sound':{str(i):str(i) for i in range(17)}})
    batch_coupled=[type(module).__name__ for module in production.modules()
                   if isinstance(module,(nn.modules.batchnorm._BatchNorm,nn.Dropout,nn.Dropout1d,nn.Dropout2d,nn.Dropout3d))]
    result={'schema':'hepta.closure.microbatch-recovery-check.v1',
            'actual_proxy_loss_dense':float(whole.detach()),'actual_proxy_loss_micro_mean':sum(parts)/4,
            'maximum_gradient_absolute_difference':max(errors),'gradient_scale':scale,
            'maximum_gradient_relative_to_global_scale':max(errors)/max(scale,1e-20),
            'maximum_one_adam_update_parameter_difference':update_error,
            'model_and_optimizer_resume_bit_exact_on_stochastic_fixture':exact_model and exact_optimizer,
            'production_batchnorm_or_dropout_modules':batch_coupled,
            'production_parameter_count':sum(p.numel() for p in production.parameters()),
            'qualification_or_development_data_access':False,
            'limits':'independent-example proxy fixture and architecture inspection; production floating-point trajectories need not be bit-identical under a different reduction order',
            'source_sha256':{name:digest((Path(__file__).parent/name).read_bytes()) for name in
              ('natural_recovery_check.py','natural_train_microbatch.py','natural_model.py','semantic_observer.py','natural_proxy_data.py')}}
    result['passed']=(max(errors)/max(scale,1e-20)<2e-5 and update_error<2e-6
                      and exact_model and exact_optimizer and not batch_coupled)
    if not result['passed']:raise ValueError(result)
    save(output,result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    print(check(p.parse_args().output))
