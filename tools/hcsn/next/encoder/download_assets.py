"""Explicit public downloads with pinned revisions and verified byte hashes."""
import argparse
import hashlib
from pathlib import Path
import urllib.request

AG="https://huggingface.co/datasets/fancyzhx/ag_news/resolve/eb185aade064a813bc0b7f42de02595523103ca4/data/"
CIFAR="https://huggingface.co/datasets/uoft-cs/cifar10/resolve/0b2714987fa478483af9968de7c934580d0bb9a2/plain_text/"
MINILM="https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/1110a243fdf4706b3f48f1d95db1a4f5529b4d41/"
MOBILE="https://huggingface.co/onnxmodelzoo/mobilenetv2-12/resolve/23a2a25eaaa6fcd61865414c8a1acf13dda66b7a/mobilenetv2-12.onnx"
ASSETS={
    "ag_train.parquet":(AG+"train-00000-of-00001.parquet","fc508d6d9868594e3da960a8cfeb63ab5a4746598b93428c224397080c1f52ee"),
    "ag_test.parquet":(AG+"test-00000-of-00001.parquet","71de87ec66bc5737752a2502204dfa6d7fe9856ade3ea444dc6317789a4f13fb"),
    "cifar_train.parquet":(CIFAR+"train-00000-of-00001.parquet","8428b53a88a11ac374111006708df51469e315a22ac6d66470afd9c78d2ae883"),
    "cifar_test.parquet":(CIFAR+"test-00000-of-00001.parquet","841389e6f2d64f28bf17310e430aebac20ec3ba611a3c5e231dc93c645ce84de"),
    "mobilenetv2-12.onnx":(MOBILE,"c0c3f76d93fa3fd6580652a45618618a220fced18babf65774ed169de0432ad5")}
TEXT_ASSETS={
    "model.onnx":(MINILM+"onnx/model.onnx","6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452"),
    "tokenizer.json":(MINILM+"tokenizer.json","be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037")}


def download(url,path,expected):
    if not path.exists():
        temporary=path.with_suffix(path.suffix+".partial")
        with urllib.request.urlopen(url,timeout=60) as source,temporary.open("wb") as target:
            while block:=source.read(1024*1024):
                target.write(block)
        if hashlib.sha256(temporary.read_bytes()).hexdigest()!=expected:
            raise ValueError("Download SHA mismatch: "+str(path))
        temporary.replace(path)
    actual=hashlib.sha256(path.read_bytes()).hexdigest()
    if actual!=expected:
        raise ValueError("Cached SHA mismatch: "+str(path))
    print(path.name,actual,path.stat().st_size,flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--cache",type=Path,default=Path("/tmp/hcsn-next-encoder-assets"))
    parser.add_argument("--text-cache",type=Path,default=Path("/tmp/hcsn-encoder-assets"))
    args=parser.parse_args()
    for folder,items in ((args.cache,ASSETS),(args.text_cache,TEXT_ASSETS)):
        folder.mkdir(parents=True,exist_ok=True)
        for name,(url,expected) in items.items():
            download(url,folder/name,expected)
