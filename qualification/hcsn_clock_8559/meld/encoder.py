"""Tri-modal raw frontends and comparable temporal encoders."""
from pathlib import Path
import sys
import torch
from torch import nn
from torch.nn import functional as F
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from model import WIDTH, Population, Lif, Classifier

ARMS=('literal','smooth','lif','attention','gru','text_attention')
class FusionPopulation(Population):
    def forward(self,x,port='normal'):
        drive=self.inp(x);z=torch.zeros_like(drive[:,0]);wall=signal=refr=z
        price=z[...,None].expand(-1,-1,2);mass=self.reset.expand(*z.shape,4);outputs=[]
        for frame in drive.unbind(1):
            fb=(torch.tanh(price)*self.feedback).sum(-1)
            u=frame+self.recurrent(signal)+fb;bounded=u.tanh();rel=.21*bounded
            w=torch.log1p(self.beta*rel);mu=-.10+.25*bounded
            kernel,j,frac=self.transition(w-wall,mu);arrival=(mass[...,None]*kernel).sum(-2)
            mass=arrival[...,:4]+refr[...,None]*self.reset;refr=arrival[...,4]
            price=(mass[...,None]*(self.coeff[0]+rel[...,None,None]*self.coeff[1])).sum(-2)
            probes=(mass[...,None]*torch.lerp(self.probes[j],self.probes[j+1],frac)).sum(-2)
            coords=torch.cat([w[...,None],refr[...,None],price,probes],-1)
            signal=(coords*self.emitter).sum(-1);wall=w
            if port=='no_wall':cross=signal-w*self.emitter[:,0]
            elif port=='shuffle_wall':cross=signal+(w.roll(1,0)-w)*self.emitter[:,0]
            elif port=='no_prices':cross=signal-(price*self.emitter[:,2:4]).sum(-1)
            else:cross=signal
            outputs.append(cross)
        return torch.stack(outputs,1)
class Encoder(nn.Module):
    def __init__(self,arm):
        super().__init__();self.arm=arm
        self.words=nn.Embedding(4096,24,padding_idx=0)
        self.visual=nn.Sequential(nn.Conv2d(3,12,5,4,2),nn.GELU(),nn.Conv2d(12,24,3,2,1),nn.GELU(),nn.AdaptiveAvgPool2d(1))
        self.acoustic=nn.Sequential(nn.Conv1d(1,12,33,16,16),nn.GELU(),nn.Conv1d(12,24,9,4,4),nn.GELU(),nn.AdaptiveAvgPool1d(1))
        self.fusion=nn.Sequential(nn.Linear(72,WIDTH),nn.LayerNorm(WIDTH))
        if arm in ('literal','smooth'):
            self.one=FusionPopulation(WIDTH,arm);self.two=FusionPopulation(WIDTH,arm)
        elif arm=='lif':self.one=Lif(WIDTH);self.two=Lif(WIDTH)
        elif arm=='gru':self.one=nn.GRU(WIDTH,WIDTH,batch_first=True);self.two=nn.GRU(WIDTH,WIDTH,batch_first=True)
        else:
            self.pos=nn.Parameter(torch.randn(1,8,WIDTH)*.02)
            self.one=Classifier.attention();self.two=Classifier.attention()
        self.out=nn.Linear(2*WIDTH,7)
    def forward(self,video,audio,text,view='natural'):
        b=len(text)
        word=(self.words(text).sum(-2)/(text!=0).sum(-1,keepdim=True).clamp(min=1))
        if self.arm=='text_attention':
            pic=snd=torch.zeros_like(word)
        else:
            pic=self.visual(video.reshape(-1,32,32,3).permute(0,3,1,2).float().div(255.)-.5).reshape(b,8,24)
            snd=self.acoustic(audio.reshape(-1,1,2048).float()/32768.).reshape(b,8,24)
        x=self.fusion(torch.cat([(torch.zeros_like(pic) if view=='no_video' else pic),
                                (torch.zeros_like(snd) if view=='no_audio' else snd),
                                (torch.zeros_like(word) if view=='no_text' else word)],-1))
        if self.arm in ('literal','smooth'):h=self.two(self.one(x,port=view if view in ('no_wall','shuffle_wall','no_prices') else 'normal'))
        elif self.arm=='gru':h=self.two(self.one(x)[0])[0]
        elif self.arm=='lif':h=self.two(self.one(x))
        else:h=self.two(self.one(x+self.pos))
        return self.out(torch.cat([h.mean(1),h[:,-1]],-1))
