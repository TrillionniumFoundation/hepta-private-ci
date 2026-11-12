"""Offline generation worker and retained model-input verification.

The worker records the exact rendered prompt and tokenizer tensors immediately
before model.generate. This binds observed local inputs without asserting
production-owner authority or the truth of a host-controlled runtime.
"""

from .episodic_provider_handoff import _canonical, _json, _pin


def _document(raw):
    try:
        return _json(raw)
    except (UnicodeError, RecursionError) as error:
        raise ValueError("invalid worker evidence document") from error


def verify_returned_generation(receipt, log):
    """Recheck the same successful execution contract at return and readback.

    Consistency of retained bytes does not authenticate an original host or
    owner. Callers must separately bind this receipt to their frozen admission.
    """
    bootstrap_records, results = [], []
    for line in log.splitlines():
        if line.startswith(b"MEM11_BOOTSTRAP "):
            bootstrap_records.append(_document(line[16:]))
        elif line.startswith(b"MEM11_RESULT "):
            results.append(_document(line[13:]))
    bootstrap = receipt.get("bootstrap")
    result = receipt.get("result")
    execution = receipt.get("execution")
    namespaces = receipt.get("host_namespaces")
    runtime = receipt.get("runtime_before")
    profile = receipt.get("profile")
    if (
        receipt.get("status") != "RETURNED"
        or receipt.get("local_generation_returned") is not True
        or receipt.get("source_unchanged") is not True
        or _pin(log) != receipt.get("combined_log")
        or not isinstance(execution, dict)
        or type(execution.get("returncode")) is not int
        or execution["returncode"] != 0
        or execution.get("timed_out") is not False
        or execution.get("output_limit_exceeded") is not False
        or not isinstance(runtime, dict)
        or not isinstance(profile, dict)
        or runtime != receipt.get("runtime_after")
        or runtime.get("sha256") != profile.get("runtime_sha256")
        or not isinstance(bootstrap, dict)
        or bootstrap_records != [bootstrap]
        or bootstrap.get("empty") is not True
        or not isinstance(namespaces, dict)
        or set(namespaces) != {"mnt", "pid", "net", "ipc", "uts", "user"}
        or not isinstance(bootstrap.get("namespaces"), dict)
        or set(bootstrap["namespaces"]) != set(namespaces)
        or any(not isinstance(namespaces[name], str) for name in namespaces)
        or any(
            not isinstance(bootstrap["namespaces"][name], str) for name in namespaces
        )
        or any(bootstrap["namespaces"][name] == namespaces[name] for name in namespaces)
        or not isinstance(result, dict)
        or results != [result]
        or result.get("request_sha256") != receipt["request"]["sha256"]
    ):
        raise ValueError(
            "returned generation contradicts execution or isolation evidence"
        )
    return read_model_input(log, receipt["request"], result)


WORKER = r"""
import hashlib, json, os, resource, sys
from pathlib import Path
os.environ.pop("PWD", None)
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
resource.setrlimit(resource.RLIMIT_FSIZE, (1048576, 1048576))
print("MEM11_BOOTSTRAP " + json.dumps({
 "namespaces": {n: os.readlink("/proc/self/ns/"+n)
 for n in ("mnt", "pid", "net", "ipc", "uts", "user")},
 "empty": all(not os.listdir(p) for p in ("/home/provider", "/cache", "/work"))
}, sort_keys=True), flush=True)
sys.path.insert(0, "/runtime/site")
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
torch.set_num_threads(4)
torch.manual_seed(0)
raw = Path("/input/request.json").read_bytes()
request = json.loads(raw)
tokenizer = AutoTokenizer.from_pretrained("/model", local_files_only=True,
 trust_remote_code=False)
model = AutoModelForCausalLM.from_pretrained("/model", local_files_only=True,
 trust_remote_code=False, use_safetensors=True, dtype=torch.float32).eval()
prompt = tokenizer.apply_chat_template([{"role":"user", "content":request["input"]}],
 tokenize=False, add_generation_prompt=True)
inputs = tokenizer(prompt, return_tensors="pt", truncation=False)
if inputs["input_ids"].shape[1] > 1024:
 raise ValueError("input token budget exceeded")
model_input = {"schema":"hepta.mem12.model-input.v1",
 "request_sha256":hashlib.sha256(raw).hexdigest(), "rendered_prompt":prompt,
 "tensors": {name:{"dtype":str(value.dtype), "shape":list(value.shape),
 "values":value.tolist()} for name,value in inputs.items()}}
model_input_raw = json.dumps(model_input, sort_keys=True,
 separators=(",", ":"), allow_nan=False).encode()
print("MEM12_MODEL_INPUT " + model_input_raw.decode(), flush=True)
with torch.inference_mode():
 result = model.generate(**inputs, do_sample=False,
  max_new_tokens=request["max_output_tokens"], use_cache=True,
  pad_token_id=tokenizer.eos_token_id)
tokens = result[0, inputs["input_ids"].shape[1]:].tolist()
usage = resource.getrusage(resource.RUSAGE_SELF)
print("MEM11_RESULT " + json.dumps({"request_sha256":hashlib.sha256(raw).hexdigest(),
 "model_input":{"bytes":len(model_input_raw),
 "sha256":hashlib.sha256(model_input_raw).hexdigest()},
 "text":tokenizer.decode(tokens, skip_special_tokens=True), "tokens":tokens,
 "prompt_tokens":int(inputs["input_ids"].shape[1]),
 "user_cpu_seconds":usage.ru_utime, "system_cpu_seconds":usage.ru_stime,
 "max_rss_kib":usage.ru_maxrss}, sort_keys=True), flush=True)
"""


def read_model_input(log, request_pin, result):
    """Recover one complete canonical input record bound to this generation."""
    marker = b"MEM12_MODEL_INPUT "
    records = [
        line[len(marker) :] for line in log.splitlines() if line.startswith(marker)
    ]
    if len(records) != 1 or not 1 <= len(records[0]) <= 1048576:
        raise ValueError("one bounded model input record required")
    raw = records[0]
    document = _document(raw)
    if (
        not isinstance(document, dict)
        or set(document) != {"schema", "request_sha256", "rendered_prompt", "tensors"}
        or document["schema"] != "hepta.mem12.model-input.v1"
        or document["request_sha256"] != request_pin["sha256"]
        or _canonical(document) != raw
        or _pin(raw) != result.get("model_input")
        or not isinstance(document["rendered_prompt"], str)
        or len(document["rendered_prompt"].encode()) > 262144
    ):
        raise ValueError("model input does not bind exact request and generation")
    tensors = document["tensors"]
    count = result.get("prompt_tokens")
    if (
        type(count) is not int
        or not 1 <= count <= 1024
        or not isinstance(tensors, dict)
        or not {"input_ids", "attention_mask"} <= tensors.keys()
        or not tensors.keys() <= {"input_ids", "attention_mask", "token_type_ids"}
    ):
        raise ValueError("bounded original tokenizer tensors required")
    for name, tensor in tensors.items():
        if (
            not isinstance(tensor, dict)
            or set(tensor) != {"dtype", "shape", "values"}
            or tensor["dtype"] != "torch.int64"
            or tensor["shape"] != [1, count]
            or any(type(size) is not int for size in tensor["shape"])
            or not isinstance(tensor["values"], list)
            or len(tensor["values"]) != 1
            or not isinstance(tensor["values"][0], list)
            or len(tensor["values"][0]) != count
            or any(
                type(value) is not int or not 0 <= value < 2**31
                for value in tensor["values"][0]
            )
            or (
                name == "attention_mask"
                and any(value not in (0, 1) for value in tensor["values"][0])
            )
        ):
            raise ValueError("tokenizer tensor content or shape mismatch")
    return raw
