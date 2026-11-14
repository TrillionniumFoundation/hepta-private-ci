"""Independent transcription of #2085 original numeric MiniLM BERT probe; source-only diagnostic."""
import json,math,hashlib
from pathlib import Path
import torch
import torch.nn.functional as F
from safetensors import safe_open

def reference(root):
    path=Path(root)/'encoder/model.safetensors'
    with safe_open(str(path),framework='pt',device='cpu') as s:
        g=lambda k:s.get_tensor(k).to(torch.float32)
        cfg=json.loads((path.parent/'config.json').read_text())
        h,nheads=int(cfg['hidden_size']),int(cfg['num_attention_heads'])
        ids=torch.tensor([101,2023,2003,1037,3231,102])
        count=len(ids)
        x=g('embeddings.word_embeddings.weight')[ids]
        x=x+g('embeddings.position_embeddings.weight')[:count]
        x=x+g('embeddings.token_type_embeddings.weight')[0]
        norm=lambda x,w,b:F.layer_norm(x,(x.shape[-1],),weight=w,bias=b,eps=cfg['layer_norm_eps'])
        x=norm(x,g('embeddings.LayerNorm.weight'),g('embeddings.LayerNorm.bias'))
        for i in range(int(cfg['num_hidden_layers'])):
            pre=f'encoder.layer.{i}.'
            a=pre+'attention.self.'
            q,k,v=(F.linear(x,g(a+name+'.weight'),g(a+name+'.bias')) for name in ('query','key','value'))
            q=q.reshape(count,nheads,h//nheads).transpose(0,1)
            k=k.reshape(count,nheads,h//nheads).transpose(0,1)
            v=v.reshape(count,nheads,h//nheads).transpose(0,1)
            attn=(q@k.transpose(-1,-2)/math.sqrt(h//nheads)).softmax(-1)
            y=(attn@v).transpose(0,1).contiguous().reshape(count,h)
            w=pre+'attention.output.'
            y=F.linear(y,g(w+'dense.weight'),g(w+'dense.bias'))
            x=norm(x+y,g(w+'LayerNorm.weight'),g(w+'LayerNorm.bias'))
            f=pre+'intermediate.dense.'
            y=F.gelu(F.linear(x,g(f+'weight'),g(f+'bias')))
            f=pre+'output.'
            y=F.linear(y,g(f+'dense.weight'),g(f+'dense.bias'))
            x=norm(x+y,g(f+'LayerNorm.weight'),g(f+'LayerNorm.bias'))
        pool=torch.tanh(F.linear(x[0],g('pooler.dense.weight'),g('pooler.dense.bias')))
        def digest(y):return hashlib.sha256(y.detach().cpu().float().contiguous().numpy().astype('<f4',copy=False).tobytes()).hexdigest()
        return {'cls':digest(x[0]),'pooler':digest(pool)}
