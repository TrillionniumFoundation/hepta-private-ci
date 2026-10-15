"""Read-only numerical probe of ORIGINAL immutable pretrained archive weights.

Strictly NOT HF/Reader-tokenizer parity, scored answers, Task success, final
use, independent model issuer, HNMF authority, or production acceptance.
Exercises BF16 original physical tensors on deterministic numeric token IDs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import resource
import time
from pathlib import Path

import torch
import torch.nn.functional as F
from safetensors import safe_open

EXPECTED = {
    'reader/model.safetensors': '5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c',
    'encoder/model.safetensors': '53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db',
}
READER_IDS = [1, 420, 35, 177]
ENCODER_IDS = [101, 2023, 2003, 1037, 3231, 102]


def filehash(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def numeric_digest(v):
    raw = v.detach().cpu().float().contiguous().numpy().astype('<f4', copy=False).tobytes()
    return hashlib.sha256(raw).hexdigest()


def norm(x, weight, bias, eps):
    return F.layer_norm(x, (x.shape[-1],), weight=weight, bias=bias, eps=eps)


def bert_probe(path):
    t0 = time.perf_counter()
    with safe_open(str(path), framework='pt', device='cpu') as source:
        g = lambda name: source.get_tensor(name).to(torch.float32)
        cfg = json.loads((path.parent / 'config.json').read_text())
        heads = int(cfg['num_attention_heads'])
        hidden = int(cfg['hidden_size'])
        ids = torch.tensor(ENCODER_IDS)
        n = len(ids)
        x = g('embeddings.word_embeddings.weight')[ids]
        x = x + g('embeddings.position_embeddings.weight')[:n]
        x = x + g('embeddings.token_type_embeddings.weight')[0]
        x = norm(x, g('embeddings.LayerNorm.weight'),
                 g('embeddings.LayerNorm.bias'), cfg['layer_norm_eps'])
        for i in range(int(cfg['num_hidden_layers'])):
            pre = f'encoder.layer.{i}.'
            a = pre + 'attention.self.'
            q, k, v = (F.linear(x, g(a+name+'.weight'),g(a+name+'.bias'))
                       for name in ('query','key','value'))
            q = q.reshape(n, heads, hidden//heads).transpose(0,1)
            k = k.reshape(n, heads, hidden//heads).transpose(0,1)
            v = v.reshape(n, heads, hidden//heads).transpose(0,1)
            attn = (q @ k.transpose(-1,-2) / math.sqrt(hidden//heads)).softmax(-1)
            y = (attn @ v).transpose(0,1).contiguous().reshape(n,hidden)
            w = pre + 'attention.output.'
            y = F.linear(y, g(w+'dense.weight'), g(w+'dense.bias'))
            x = norm(x + y, g(w+'LayerNorm.weight'),g(w+'LayerNorm.bias'),cfg['layer_norm_eps'])
            f = pre + 'intermediate.dense.'
            y = F.gelu(F.linear(x,g(f+'weight'),g(f+'bias')))
            f = pre + 'output.'
            y = F.linear(y,g(f+'dense.weight'),g(f+'dense.bias'))
            x = norm(x + y,g(f+'LayerNorm.weight'),g(f+'LayerNorm.bias'),cfg['layer_norm_eps'])
        pooled = torch.tanh(F.linear(x[0],g('pooler.dense.weight'),g('pooler.dense.bias')))
        return {'token_ids':ENCODER_IDS,'dtype':'float32_compute_on_original_bf16_tensors',
                'hidden_width':hidden,'layers':cfg['num_hidden_layers'],
                'cls_sha256':numeric_digest(x[0]),
                'pooler_sha256':numeric_digest(pooled),
                'cls_l2':float(x[0].norm()),'pooler_l2':float(pooled.norm()),
                'physical_wall_s':time.perf_counter()-t0}


def llama_probe(path):
    t0=time.perf_counter()
    with safe_open(str(path),framework='pt',device='cpu') as source:
        g=lambda name:source.get_tensor(name).to(torch.float32)
        cfg=json.loads((path.parent/'config.json').read_text())
        ids=torch.tensor(READER_IDS)
        x=g('model.embed_tokens.weight')[ids]
        n=len(ids)
        heads=cfg['num_attention_heads']
        kvheads=cfg['num_key_value_heads']
        head_dim=cfg['hidden_size']//heads
        repeat=heads//kvheads
        theta=float(cfg['rope_theta'])
        pos=torch.arange(n,dtype=torch.float32)
        freqs=torch.outer(pos,theta**(-torch.arange(0,head_dim,2,dtype=torch.float32)/head_dim))
        cos=torch.cat([freqs.cos(),freqs.cos()],dim=-1).unsqueeze(0)
        sin=torch.cat([freqs.sin(),freqs.sin()],dim=-1).unsqueeze(0)
        def rotate(y):
            lo,hi=y.chunk(2,dim=-1)
            return torch.cat([-hi,lo],dim=-1)
        def rms(y,w):
            eps=cfg['rms_norm_eps']
            return y*torch.rsqrt(y.square().mean(-1,keepdim=True)+eps)*w
        for i in range(int(cfg['num_hidden_layers'])):
            p=f'model.layers.{i}.'
            z=rms(x,g(p+'input_layernorm.weight'))
            a=p+'self_attn.'
            q=F.linear(z,g(a+'q_proj.weight')).reshape(n,heads,head_dim).transpose(0,1)
            k=F.linear(z,g(a+'k_proj.weight')).reshape(n,kvheads,head_dim).transpose(0,1)
            v=F.linear(z,g(a+'v_proj.weight')).reshape(n,kvheads,head_dim).transpose(0,1)
            q=q*cos+rotate(q)*sin
            k=k*cos+rotate(k)*sin
            k=k.repeat_interleave(repeat,dim=0)
            v=v.repeat_interleave(repeat,dim=0)
            attn=q@k.transpose(-1,-2)/math.sqrt(head_dim)
            mask=torch.full((n,n),float('-inf'),dtype=attn.dtype).triu(1)
            attn=(attn+mask).softmax(-1)
            out=(attn@v).transpose(0,1).contiguous().reshape(n,heads*head_dim)
            x=x+F.linear(out,g(a+'o_proj.weight'))
            z=rms(x,g(p+'post_attention_layernorm.weight'))
            m=p+'mlp.'
            x=x+F.linear(F.silu(F.linear(z,g(m+'gate_proj.weight')))
                         *F.linear(z,g(m+'up_proj.weight')),
                         g(m+'down_proj.weight'))
        final=rms(x,g('model.norm.weight'))
        if 'lm_head.weight' in source.keys():
            embed=g('lm_head.weight')
        else:
            embed=g('model.embed_tokens.weight')
        logits=F.linear(final[-1],embed)
        top=torch.topk(logits,5)
        return {'token_ids':READER_IDS, 'dtype':'float32_compute_on_original_bf16_tensors',
                'layers':cfg['num_hidden_layers'],'hidden_width':cfg['hidden_size'],
                'lm_head_tied_to_embeddings':cfg['tie_word_embeddings'],
                'last_hidden_sha256':numeric_digest(final[-1]),
                'logits_sha256':numeric_digest(logits),
                'top5_ids':top.indices.tolist(),
                'top5_logits':[float(x) for x in top.values],
                'physical_wall_s':time.perf_counter()-t0}


def main():
    args=argparse.ArgumentParser()
    args.add_argument('--archive-root',type=Path,required=True)
    args.add_argument('--output',type=Path,required=True)
    a=args.parse_args()
    if a.output.exists() or a.output.is_symlink():raise RuntimeError('create-only result')
    torch.set_num_threads(2)
    result={'schema':'hepta.amcn.original-numeric-weight-probe.shadow.v1',
            'reader_hf_model_parity_verified':False,
            'text_tokenizer_parity_verified':False,
            'reader_natural_language_task_answers':0,
            'real_model_numeric_forward':True,
            'strong_rag_compared':False,
            'independent_future_windows':0,
            'production_accepted':False,
            'source_file_sha256':filehash(Path(__file__)),
            'model_files':{}}
    for name,expected in EXPECTED.items():
        p=a.archive_root/name
        if filehash(p)!=expected:raise RuntimeError('model SHA mismatch: '+name)
        result['model_files'][name]=expected
    with torch.inference_mode():
        result['encoder']=bert_probe(a.archive_root/'encoder/model.safetensors')
        result['reader']=llama_probe(a.archive_root/'reader/model.safetensors')
    result['peak_rss_bytes']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x') as o:
        o.write(json.dumps(result,sort_keys=True,ensure_ascii=False,allow_nan=False)+'\n')
    print(json.dumps(result,sort_keys=True))

if __name__=='__main__':
    main()
