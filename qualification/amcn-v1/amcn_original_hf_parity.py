"""Mandatory ORIGINAL Hugging Face parity gate for archived offline AMCN models.

Run only with independently installed *official* transformers/tokenizers. If
those modules, checkpoint files, actual source data or tensor agreement are
missing, fail closed; never substitute a manual/synthetic model result.

Research-only. Numerical and tokenizer parity do not authorize Cell selection,
answer correctness, three-axis gains, FinalUse or deployment.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
import time

import torch
import torch.nn.functional as F
from safetensors import safe_open

from amcn_original_numeric_probe import EXPECTED as EXPECTED_WEIGHTS, ENCODER_IDS, READER_IDS
from amcn_original_text_reader import (ArchivedLlama, ArchivedByteLevelBPE, file_sha,
                                       format_archived_chat)

ENCODER_TOKENIZER_SHA = "be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037"
READER_TOKENIZER_SHA = "9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c"
ENCODER_CONFIG_SHA = "953f9c0d463486b10a6871cc2fd59f223b2c70184f49815e7efbcab5d8908b41"
READER_CONFIG_SHA = "8eb740e8bbe4cff95ea7b4588d17a2432deb16e8075bc5828ff7ba9be94d982a"


def pinned_origin(root: Path):
    expected = {**EXPECTED_WEIGHTS,
                "encoder/tokenizer.json": ENCODER_TOKENIZER_SHA,
                "reader/tokenizer.json": READER_TOKENIZER_SHA,
                "encoder/config.json": ENCODER_CONFIG_SHA,
                "reader/config.json": READER_CONFIG_SHA}
    checks = {}
    for name, sha in expected.items():
        p = root / name
        if not p.is_file() or p.is_symlink() or file_sha(p) != sha:
            raise RuntimeError("missing or tampered ORIGINAL HF material: " + name)
        checks[name] = sha
    return checks


def original_bert_tensors(directory: Path):
    """Numerical reference from original BF16 weights; no HF implementation."""
    path = directory / "model.safetensors"
    with safe_open(str(path), framework="pt", device="cpu") as sf:
        g = lambda name: sf.get_tensor(name).to(torch.float32)
        cfg = json.loads((directory / "config.json").read_bytes())
        ids = torch.tensor(ENCODER_IDS, dtype=torch.long)
        n, heads, hidden = len(ids), cfg["num_attention_heads"], cfg["hidden_size"]
        ln = lambda z, weight, bias: F.layer_norm(
            z, (z.shape[-1],), weight, bias, cfg["layer_norm_eps"])
        x = g("embeddings.word_embeddings.weight")[ids]
        x = x + g("embeddings.position_embeddings.weight")[:n]
        x = x + g("embeddings.token_type_embeddings.weight")[0]
        x = ln(x, g("embeddings.LayerNorm.weight"),g("embeddings.LayerNorm.bias"))
        for i in range(cfg["num_hidden_layers"]):
            p = f"encoder.layer.{i}."
            q, k, v = (F.linear(x,g(p+"attention.self."+name+".weight"),
                                g(p+"attention.self."+name+".bias"))
                       for name in ("query", "key", "value"))
            q = q.reshape(n,heads,hidden//heads).transpose(0,1)
            k = k.reshape(n,heads,hidden//heads).transpose(0,1)
            v = v.reshape(n,heads,hidden//heads).transpose(0,1)
            logits = q @ k.transpose(-1,-2) / math.sqrt(hidden//heads)
            z = (logits.softmax(-1) @ v).transpose(0,1).contiguous().reshape(n,hidden)
            w = p + "attention.output."
            z = F.linear(z,g(w+"dense.weight"),g(w+"dense.bias"))
            x = ln(x+z,g(w+"LayerNorm.weight"),g(w+"LayerNorm.bias"))
            w = p + "intermediate.dense."
            z = F.gelu(F.linear(x,g(w+"weight"),g(w+"bias")))
            w = p + "output."
            z = F.linear(z,g(w+"dense.weight"),g(w+"dense.bias"))
            x = ln(x+z,g(w+"LayerNorm.weight"),g(w+"LayerNorm.bias"))
        pooled = torch.tanh(F.linear(x[0],g("pooler.dense.weight"),g("pooler.dense.bias")))
        return x[0], pooled


def _require_close(ours, official, label, *, atol=0.002, rtol=0.001):
    if ours.shape != official.shape or not torch.isfinite(ours).all() or not torch.isfinite(official).all():
        raise RuntimeError("nonfinite or mismatched original model tensors: " + label)
    max_err=float(torch.max(torch.abs(ours-official)).item())
    if not torch.allclose(ours,official,atol=atol,rtol=rtol):
        raise RuntimeError(f"original HF {label} parity FAIL: max_abs={max_err}")
    return max_err


def run(root: Path, output: Path):
    if output.exists() or output.is_symlink():
        raise RuntimeError("no overwrites of original HF parity receipts")
    root=Path(root)
    origin = pinned_origin(root)
    # The imports are intentionally deferred. Missing official packages MUST
    # raise; a hand-written fallback would defeat the independent comparison.
    import transformers
    from transformers import AutoTokenizer, AutoModel, AutoModelForCausalLM
    import tokenizers

    torch.set_num_threads(2)
    prior=torch.is_grad_enabled()
    torch.set_grad_enabled(False)
    started=time.monotonic()
    try:
        enc_tokenizer=AutoTokenizer.from_pretrained(str(root/"encoder"),use_fast=True,
                                                   local_files_only=True,trust_remote_code=False)
        read_tokenizer=AutoTokenizer.from_pretrained(str(root/"reader"),use_fast=True,
                                                    local_files_only=True,trust_remote_code=False)
        if not enc_tokenizer.is_fast or not read_tokenizer.is_fast:
            raise RuntimeError("real HF fast tokenizers required")
        candidate=ArchivedByteLevelBPE(root/"reader",expected_tokenizer_sha256=READER_TOKENIZER_SHA)
        probe_text=["Hello world!", "When did Caroline attend the support group?",
                    "Session date: 8 May 2023. [E1] Caroline went yesterday.",
                    "English 中文 français 😀\n punctuation-12345",
                    "<|im_start|>user\nWhat happened?<|im_end|>\n<|im_start|>assistant\n"]
        expected_manual=[]
        for passage in probe_text:
            manual=candidate.encode(passage)
            actual=read_tokenizer(passage,add_special_tokens=False)["input_ids"]
            if manual != actual:
                raise RuntimeError(f"ORIGINAL GPT-2 ByteLevel BPE <> HF fast parity FAIL: {passage!r}; "
                                   f"manual={manual[:35]}, original_hf={actual[:35]}")
            expected_manual.append(manual)
        # Numeric-model calculations are isolated from all publisher QA gold.
        ref_encoder_cls, ref_encoder_pool=original_bert_tensors(root/"encoder")
        bert=AutoModel.from_pretrained(str(root/"encoder"),torch_dtype=torch.float32,
                                       local_files_only=True,trust_remote_code=False).eval()
        with torch.inference_mode():
            hf_out=bert(input_ids=torch.tensor([ENCODER_IDS],dtype=torch.long),return_dict=True)
        e_cls=_require_close(ref_encoder_cls,hf_out.last_hidden_state[0,0],"encoder CLS")
        e_pool=_require_close(ref_encoder_pool,hf_out.pooler_output[0],"encoder pooler")
        del bert,hf_out

        ref_reader=ArchivedLlama(root/"reader")
        with torch.inference_mode():
            ref_logits=ref_reader.forward(READER_IDS,reset=True)
        reader=AutoModelForCausalLM.from_pretrained(
            str(root/"reader"),torch_dtype=torch.float32,attn_implementation="eager",
            local_files_only=True,trust_remote_code=False).eval()
        with torch.inference_mode():
            hf_logits=reader(input_ids=torch.tensor([READER_IDS],dtype=torch.long),
                             use_cache=False,return_dict=True).logits[0,-1].cpu().float()
        r_logits=_require_close(ref_logits.cpu().float(),hf_logits,"reader logits")
        if ref_logits.topk(5).indices.tolist()!=hf_logits.topk(5).indices.tolist():
            raise RuntimeError("HF numeric top-5 token ranking mismatch")
        # Independently compare actual natural-language ORIGINAL Reader token
        # continuations, rather than passing known numeric IDs only.
        input_text=format_archived_chat(
            "When did Caroline go to the LGBTQ support group?",
            ["Session date: 8 May, 2023. Caroline: I went to an LGBTQ support group yesterday."])
        manual_ids=candidate.encode(input_text)
        hf_ids=read_tokenizer(input_text,add_special_tokens=False)["input_ids"]
        if manual_ids != hf_ids:
            raise RuntimeError("actual LoCoMo prompt tokenizer parity FAIL")
        if len(manual_ids)+16>1024:
            raise RuntimeError("natural Reader context bound exceeded")
        with torch.inference_mode():
            manual_cont=ref_reader.generate(manual_ids,max_new_tokens=16)
            generated=reader.generate(input_ids=torch.tensor([hf_ids],dtype=torch.long),
                                      max_new_tokens=16,do_sample=False,num_beams=1,
                                      use_cache=True,eos_token_id=2,pad_token_id=2)
        hf_cont=generated[0,len(hf_ids):].tolist()
        if manual_cont != hf_cont:
            raise RuntimeError(f"ORIGINAL natural Reader greedy tokens differ: manual={manual_cont}, "
                               f"HF={hf_cont}")
        result={"schema":"hepta.amcn.original-hf-parity.shadow.v1",
                "source_model_and_tokenizer_sha256":origin,
                "transformers_version":transformers.__version__,
                "tokenizers_version":tokenizers.__version__,
                "torch_version":torch.__version__,
                "encoder_cls_max_absolute_difference":e_cls,
                "encoder_pooler_max_absolute_difference":e_pool,
                "reader_logits_max_absolute_difference":r_logits,
                "real_official_fast_tokenizer_parity":True,
                "real_official_model_forward_parity":True,
                "real_official_greedy_token_parity":True,
                "natural_language_prompt_sha256":sha256(input_text.encode()).hexdigest(),
                "manual_hf_greedy_continuation_sha256":sha256(
                    json.dumps(hf_cont,separators=(",", ":")).encode()).hexdigest(),
                "tokenizer_probe_count":len(probe_text)+1,
                "new_independently_scored_answers":0,
                "nine_arm_executions":0,
                "true_future_calendar_windows":0,
                "strong_rag_outperformed":False,
                "production_accepted":False,
                "wall_seconds":time.monotonic()-started}
    finally:
        torch.set_grad_enabled(prior)
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open("x") as f:
        f.write(json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+'\n')
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--archive-root",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args()
    print(json.dumps(run(args.archive_root,args.output),sort_keys=True))
