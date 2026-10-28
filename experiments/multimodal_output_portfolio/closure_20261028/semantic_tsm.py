"""Official fine-grained TSM action features, registered before development scores.

The temporal shift follows MIT HAN Lab's MIT-licensed implementation. Publisher
source and license bytes are retained with this study's pinned checkpoint.
"""
import hashlib
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

TSM_FILE = "TSM_somethingv2_RGB_resnet50_shift8_blockres_avg_segment8_e45.pth"
TSM_SHA = "74bb90d6ecf5b03ed78ac6572d2ced7cd3d0f8dc7fdba0bd6ce11400a5908d38"


class TemporalShift(nn.Module):
    def __init__(self, net):
        super().__init__()
        self.net = net

    def forward(self, value):
        n,c,h,w=value.shape
        x=value.reshape(n//8,8,c,h,w)
        fold=c//8
        shifted=torch.zeros_like(x)
        shifted[:,:-1,:fold]=x[:,1:,:fold]
        shifted[:,1:,fold:2*fold]=x[:,:-1,fold:2*fold]
        shifted[:,:,2*fold:]=x[:,:,2*fold:]
        return self.net(shifted.reshape(n,c,h,w))


class TsmObserver(nn.Module):
    def __init__(self, root):
        super().__init__()
        from torchvision.models import resnet50
        path=Path(root)/TSM_FILE
        if hashlib.sha256(path.read_bytes()).hexdigest()!=TSM_SHA:
            raise ValueError("Official TSM checkpoint identity changed")
        self.base_model=resnet50(weights=None)
        self.base_model.fc=nn.Identity()
        for name in ('layer1','layer2','layer3','layer4'):
            for block in getattr(self.base_model,name):
                block.conv1=TemporalShift(block.conv1)
        self.new_fc=nn.Linear(2048,174)
        state=torch.load(path,map_location='cpu',weights_only=True)['state_dict']
        self.load_state_dict({k.removeprefix('module.'):v for k,v in state.items()},strict=True)
        self.eval().requires_grad_(False)

    @torch.no_grad()
    def features(self, frames):
        frames=np.asarray(frames)
        if frames.ndim!=5 or frames.shape[1:]!=(16,112,112,3):
            raise ValueError('Expected actual sixteen-frame 112px RGB target')
        x=torch.as_tensor(frames[:,1::2].copy()).permute(0,1,4,2,3).float()/255
        b,t,c,h,w=x.shape
        x=F.interpolate(x.reshape(b*t,c,h,w),size=(256,256),mode='bilinear',align_corners=False)
        x=x[:,:,16:240,16:240]
        mean=torch.tensor((.485,.456,.406))[None,:,None,None]
        scale=torch.tensor((.229,.224,.225))[None,:,None,None]
        hidden=self.base_model((x-mean)/scale).reshape(b,8,2048).mean(1)
        return torch.cat((hidden,self.new_fc(hidden).softmax(1)),1).cpu().numpy()
