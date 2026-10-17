"""Research-only original frozen Laya/Ettin feature-bank producer (no labels).

A genuine source/weight review and an unmodified original input panel are required
before pretrained import. Never trains, predicts a human label, chooses a model,
grants production use, calls a device, or uploads features. Feature bank remains
private to its source/subject scope until a separate evaluator admits it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import time

import gate
import matched_head
import physical_forward
import review_bytes
import runtime_snapshot
import source_bytes

SCHEMA = "hepta.stem.equal-size.original-input-views.v1"
BANK_SCHEMA = matched_head.FEATURE_SCHEMA
MAX_CASES_PHYSICAL = 96
MAX_TEXT_BYTES = 8 * 1024
MAX_QUESTION_BYTES = 1024
# Independent P1 real physical receipts; both pinned source identities unchanged.
PINNED_ORIGINAL_TENSOR_COUNTS = {"ettin400": 447_458_496,
                                 "laya421": 421_293_827}
OPTIONS = ["not_supported", "supported"]


def check(ok, why):
    gate.require(ok, why)


def manifest_views(panel, views):
    """Fail closed before model import; no answer/target/labels in this process."""
    plan = gate.validate_panel(panel)
    check(type(views) is dict and set(views) == {
        "schema", "panel_sha256", "source_revision", "source_material_sha256",
        "cases", "authority", "production_authorized"},
        "unknown or label-bearing original feature input manifest")
    check(views["schema"] == SCHEMA and views["panel_sha256"] == plan["panel_sha256"] and
          views["source_revision"] == panel["source_revision"] and
          views["source_material_sha256"] == panel["source_material_sha256"] and
          views["authority"] == "DENY_ALL" and views["production_authorized"] is False,
          "original source panel/view provenance mismatch")
    rows = views["cases"]
    check(type(rows) is list and len(rows) == len(panel["cases"]) and
          3 <= len(rows) <= MAX_CASES_PHYSICAL, "original feature view count out of pilot scope")
    validated = []
    for p, item in zip(panel["cases"], rows, strict=True):
        check(type(item) is dict and set(item) == {
            "case_id", "state", "question", "options", "source_sha256", "input_sha256"},
            "unexpected original view fields; labels and extra text forbidden")
        state, question, options = item["state"], item["question"], item["options"]
        check(type(state) is str and state.strip() and 16 <= len(state.encode("utf-8")) <= MAX_TEXT_BYTES and
              type(question) is str and question.strip() and
              4 <= len(question.encode("utf-8")) <= MAX_QUESTION_BYTES and
              type(options) is list and options == OPTIONS,
              "missing/oversized or unordered original evidence/question/options")
        canonical = {"state": state, "question": question, "options": options}
        check(item["case_id"] == p["case_id"] and
              item["source_sha256"] == hashlib.sha256(state.encode("utf-8")).hexdigest() == p["source_sha256"] and
              item["input_sha256"] == gate.digest(canonical) == p["input_sha256"],
              "original source/view bytes or case order changed")
        validated.append(canonical)
    return validated


def _tensor(values, width, tokens):
    """Normalize only dtype, never clip, rescale or silently fabricate features."""
    import torch
    check(type(tokens) is int and 0 < tokens <= gate.MAX_TOKENS and
          type(width) is int and 0 < width <= matched_head.MAX_VECTOR_DIM,
          "invalid pretrained feature geometry or token count")
    check(isinstance(values, torch.Tensor) and values.ndim == 1 and
          values.numel() == width and values.dtype == torch.float32 and
          bool(torch.isfinite(values).all()), "nonfinite or wrong pretrained CLS feature")
    vector = values.detach().cpu().numpy().tolist()
    check(all(type(x) is float and math.isfinite(x) and abs(x) <= matched_head.MAX_ABS_FEATURE
              for x in vector), "real feature beyond registered Head input bound")
    return vector, tokens


class EttinOriginalEncoder:
    def __init__(self, stage):
        import torch
        from transformers import AutoConfig, AutoModelForMaskedLM, AutoTokenizer
        self.torch = torch
        root = str(stage)
        cfg = AutoConfig.from_pretrained(root, local_files_only=True, trust_remote_code=False)
        check(cfg.model_type == "modernbert", "unexpected Ettin original architecture")
        net = AutoModelForMaskedLM.from_config(cfg, trust_remote_code=False)
        weights = torch.load(str(Path(stage)/"pytorch_model.bin"), map_location="cpu",
                             weights_only=True)
        self.tensor_count = physical_forward.safe_state_inventory(net, weights, torch)
        net.load_state_dict(weights, strict=True, assign=True)
        del weights
        net.eval()
        for p in net.parameters():p.requires_grad_(False)
        tok = AutoTokenizer.from_pretrained(root, local_files_only=True,
                                             trust_remote_code=False, use_fast=True)
        check(tok.is_fast, "unregistered Ettin original tokenizer")
        self.net, self.tok = net, tok
        self.feature_width = int(cfg.hidden_size)

    def forward_one(self, view, max_tokens):
        torch = self.torch
        # The same exact fields and order enter Laya's native typed question
        # and Ettin's question-conditioned original text sequence respectively.
        text = ("Evidence: " + view["state"] + " Question: " + view["question"] +
                " Options: not_supported; supported")
        enc = self.tok(text, add_special_tokens=True, truncation=False, return_tensors="pt")
        tokens = int(enc["input_ids"].numel())
        check(0 < tokens <= max_tokens, "Ettin raw original input would be truncated")
        with torch.inference_mode():
            h = self.net.base_model(**enc, return_dict=True).last_hidden_state
            check(tuple(h.shape) == (1, tokens, self.feature_width),
                  "real frozen Ettin hidden layer geometry mismatch")
            out = h[0,0,:].float().contiguous()
        return _tensor(out, self.feature_width, tokens)


class LayaOriginalEncoder:
    def __init__(self, stage):
        import laya
        import torch
        self.torch=torch
        agent=laya.load(str(stage),device="cpu",fast=False)
        check(hasattr(agent,"model") and hasattr(agent.model,"encoder") and
              callable(getattr(agent,"_to_internal",None)) and hasattr(agent,"tok"),
              "native original Laya typed input/encoder unavailable")
        agent.model.eval()
        self.tensor_count=sum(int(x.numel()) for x in agent.model.parameters())
        check(360_000_000 <= self.tensor_count <= 500_000_000,
              "original Laya loaded tensor inventory mismatch")
        self.feature_width=int(agent.model.encoder.config.hidden_size)
        self.agent=agent

    def forward_one(self, view, max_tokens):
        torch=self.torch
        from laya.common import build_sequence
        q=self.agent._to_internal({
            "type":"noul", "instructions":view["question"],
            "criteria":{"false":view["options"][0],"true":view["options"][1]},
        })
        # Reject *silent* Laya state or question truncation, not merely a
        # pre-truncated token count that happens to fit max_tokens.
        ids,markers=build_sequence(self.agent.tok,view["state"],q,
                                   max_len=max_tokens,head_max_len=min(192,max_tokens))
        state_ids=self.agent.tok(view["state"],add_special_tokens=False)["input_ids"]
        head_ids=self.agent.tok("noul question: " + view["question"],
                                 add_special_tokens=False)["input_ids"]
        check(len(markers) == 2 and len(state_ids) > 0 and len(head_ids)>0 and
              len(ids) <= max_tokens and ids[1:len(head_ids)+1] == head_ids and
              ids[-len(state_ids)-1:-1] == state_ids and
              all(0 <= mark < len(ids) for mark in markers),
              "original Laya prompt lost input/option tokens through truncation")
        tok=torch.tensor([ids],dtype=torch.long)
        mask=torch.ones_like(tok)
        with torch.inference_mode():
            h=self.agent.model.encoder(input_ids=tok,attention_mask=mask).last_hidden_state
            check(tuple(h.shape) == (1,len(ids),self.feature_width),
                  "original native Laya encoder shape mismatch")
            out=h[0,0,:].float().contiguous()
        return _tensor(out,self.feature_width,len(ids))


def _load_real_encoder(model, root):
    if model == "ettin400":
        return EttinOriginalEncoder(root)
    if model == "laya421":
        return LayaOriginalEncoder(root)
    raise gate.Denied("model outside original two-way matched feature pilot")


def make_bank(model, panel, views, source_receipt, stage):
    """Original checkpoint→actual frozen features, privately scoped to one panel."""
    check(model in ("ettin400", "laya421"), "unsupported original physical model")
    material=manifest_views(panel,views)
    # All authentic-source-byte checks must pass before a model import.
    proof=physical_forward.checked_receipt(source_receipt,stage,model)
    repo,revision,_,_=gate.MODELS[model]
    source_items=source_receipt["selected_source_inventory"]
    weights=[x for x in source_items if x["is_weight"]]
    tokenizers=[x for x in source_items if "tokenizer" in x["filename"]]
    check(len(weights)==1 and weights[0]["source_identity_type"]=="lfs_sha256" and
          bool(tokenizers) and all(gate.sha(x["source_identity"]) or
          (len(x["source_identity"])==40 and x["source_identity_type"]=="git_blob_sha1")
          for x in tokenizers),"incomplete original original-weight/tokenizer identity")
    weight_sha=weights[0]["source_identity"]
    tokenizer_sha=gate.digest(tokenizers)
    start_cpu=time.process_time_ns()
    start_wall=time.monotonic_ns()
    output=[]
    token_counts=[]
    with runtime_snapshot.isolated_verified_runtime(source_receipt,stage) as frozen:
        encoder=_load_real_encoder(model,frozen)
        check(type(encoder.feature_width) is int and encoder.feature_width==1024 and
              type(encoder.tensor_count) is int and
              encoder.tensor_count==PINNED_ORIGINAL_TENSOR_COUNTS[model],
              "original pretrained model tensor census absent")
        for case,view in zip(panel["cases"],material,strict=True):
            vec,tokens=encoder.forward_one(view,panel["budget"]["max_tokens"])
            check(tokens <= panel["budget"]["max_tokens"], "original tokenizer overflow")
            token_counts.append({"case_id":case["case_id"],"tokens":tokens})
            output.append({"case_id":case["case_id"],
                           "source_sha256":case["source_sha256"],
                           "input_sha256":case["input_sha256"],"values":vec})
    cost={"clock_cpu_ns_self_reported":time.process_time_ns()-start_cpu,
          "clock_wall_ns_self_reported":time.monotonic_ns()-start_wall,
          "peak_rss_kib_linux_self_reported":int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
          "actual_encoder_forwards_observed":len(output),
          "actual_loaded_tensor_elements_reported":encoder.tensor_count,
          "encoder_width":encoder.feature_width,
          "input_tokens_by_case":token_counts,
          "total_real_input_tokens":sum(x["tokens"] for x in token_counts),
          "input_tokenization_nontruncated_reported":True,
          "source_review_receipt_sha256":proof["source_sha256_receipt"],
          "original_issuer_signature_verified":False,
          "production_authorized":False,"authority":"DENY_ALL",
          "disposition":"HOLD_NO_GO"}
    bank={"schema":BANK_SCHEMA,"panel_sha256":gate.digest(panel),
          "model":model,"repo":repo,"revision":revision,
          "source_weights_sha256":weight_sha,"source_tokenizer_sha256":tokenizer_sha,
          "encoder_output_dimension":encoder.feature_width,"precision":"float32",
          "rows":output,"actual_pretrained_forward_reported":True,
          "physical_source_sha256_checked_reported":True,
          "signed_publisher_identity_verified":False,"production_authorized":False,
          "future_window_verified":False,"authority":"DENY_ALL"}
    matched_head.validate_bank(panel,bank)
    return bank,cost


def _save_once(path, obj):
    p=Path(path)
    check(p.parent.is_dir() and not p.parent.is_symlink() and not p.exists(),
          "output must be a fresh private ordinary file")
    raw=json.dumps(obj,sort_keys=True,separators=(",",":"),allow_nan=False).encode()+b"\n"
    check(len(raw)<=16*1024*1024,"oversized private original feature bank")
    fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,"O_NOFOLLOW",0),0o600)
    with os.fdopen(fd,"wb") as out:
        out.write(raw);out.flush();os.fsync(out.fileno())


def main(argv=None):
    p=argparse.ArgumentParser(description="Unlabeled original pretrained bank; no model choice or promotion")
    for key in ("model","panel","views","receipt","stage","bank","report"):
        p.add_argument("--"+key,required=True)
    args=p.parse_args(argv)
    check(args.model in ("ettin400","laya421"),"unregistered original model")
    panel=gate.strict_load(args.panel)
    views=gate.strict_load(args.views)
    receipt=review_bytes.read_sealed(args.receipt)
    check(args.bank != args.report,"cannot alias source and cost outputs")
    bank,cost=make_bank(args.model,panel,views,receipt,Path(args.stage))
    _save_once(args.bank,bank)
    _save_once(args.report,cost)
    print("Private genuine frozen feature bank produced, no held labels or promotion; HOLD_NO_GO")

if __name__=="__main__":
    main()
