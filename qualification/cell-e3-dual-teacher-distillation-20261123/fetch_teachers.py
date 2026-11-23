from pathlib import Path
import concurrent.futures, requests, json, sys, hashlib

base = Path(sys.argv[1])
base.mkdir(parents=True, exist_ok=True)
expected = json.loads(
    (Path(__file__).parent / "evidence" / "upstream.json").read_bytes()
)


def model(name):
    rev = expected[name]["revision"]
    meta = requests.get(
        "https://huggingface.co/api/models/" + name + "/revision/" + rev, timeout=35
    )
    meta.raise_for_status()
    j = meta.json()
    assert j["sha"] == rev
    d = base / name.rsplit("/", 1)[-1]
    d.mkdir(exist_ok=True)
    (d / "identity.json").write_text(
        json.dumps(
            {
                "id": name,
                "revision": rev,
                "license": j.get("cardData", {}).get("license"),
            }
        )
    )
    files = [
        p["rfilename"]
        for p in j["siblings"]
        if p["rfilename"]
        in [
            "config.json",
            "generation_config.json",
            "tokenizer.json",
            "tokenizer_config.json",
            "special_tokens_map.json",
            "spiece.model",
            "vocab.json",
            "merges.txt",
            "model.safetensors",
            "LICENSE",
            "README.md",
        ]
    ]

    def download(f):
        for attempt in range(3):
            try:
                with requests.get(
                    "https://huggingface.co/" + name + "/resolve/" + rev + "/" + f,
                    stream=True,
                    timeout=(15, 80),
                ) as r:
                    r.raise_for_status()
                    with (d / (f + ".part")).open("wb") as o:
                        for chunk in r.iter_content(1024 * 1024):
                            o.write(chunk)
                (d / (f + ".part")).replace(d / f)
                print(name, f, (d / f).stat().st_size, flush=True)
                return
            except Exception as e:
                print(str(e)[:180], flush=True)
        raise ValueError(f)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(download, files))
    with (d / "model.safetensors").open("rb") as f:
        if (
            hashlib.file_digest(f, "sha256").hexdigest()
            != expected[name]["upstream_lfs_sha256"]
        ):
            raise ValueError("Teacher weights mismatch")
    if (
        hashlib.sha256((d / "tokenizer.json").read_bytes()).hexdigest()
        != expected[name]["tokenizer_sha256"]
    ):
        raise ValueError("Teacher tokenizer mismatch")
    print(name, rev, flush=True)


with concurrent.futures.ThreadPoolExecutor() as pool:
    list(
        pool.map(model, ["google/flan-t5-small", "HuggingFaceTB/SmolLM2-135M-Instruct"])
    )
