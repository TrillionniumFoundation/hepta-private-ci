"""Bounded reader of Bazel 9.3.0 ExecLogEntry records; no protobuf execution."""

import json, zipfile, zstandard, hashlib, pathlib
from io import BytesIO


def varint(stream, eof=False):
    value = 0
    for i in range(10):
        b = stream.read(1)
        if not b:
            if i == 0 and eof:
                return None
            raise ValueError("truncated varint")
        value |= (b[0] & 127) << (i * 7)
        if b[0] < 128:
            if value >= 2**64:
                raise ValueError("varint overflow")
            return value
    raise ValueError("varint overflow")


def fields(data):
    stream = BytesIO(data)
    out = {}
    while True:
        key = varint(stream, True)
        if key is None:
            return out
        num, wire = key >> 3, key & 7
        if num == 0:
            raise ValueError("zero field")
        if wire == 0:
            v = varint(stream)
        elif wire in (1, 2, 5):
            n = varint(stream) if wire == 2 else 8 if wire == 1 else 4
            if n > len(data) - stream.tell():
                raise ValueError("truncated field")
            v = stream.read(n)
        else:
            raise ValueError("unsupported wire type")
        out.setdefault(num, []).append(v)


def value(f, n, default=b""):
    return f.get(n, [default])[-1]


def text(f, n):
    return value(f, n).decode("utf-8")


expected_sha = "75f0d66a9bed98b735a0149e6f097dafedbf146b0201616d23d13c85092ed33b"
with pathlib.Path("bazel-linux-e4.zip").open("rb") as source:
    artifact = source.read(15851173 + 1)
if len(artifact) != 15851173 or hashlib.sha256(artifact).hexdigest() != expected_sha:
    raise ValueError("source artifact identity mismatch")
results = []
entries = 0
decoded = 0
with zipfile.ZipFile(BytesIO(artifact)) as z:
    if z.namelist() != ["execution-log-test-test-3273.zst"]:
        raise ValueError("unexpected archive roster")
    with z.open(z.namelist()[0]) as compressed:
        with zstandard.ZstdDecompressor().stream_reader(compressed) as stream:
            while True:
                n = varint(stream, True)
                if n is None:
                    break
                if n > 16 * 1024 * 1024:
                    raise ValueError("record cap")
                decoded += n
                entries += 1
                if decoded > 256 * 1024 * 1024 or entries > 1000000:
                    raise ValueError("stream cap")
                data = stream.read(n)
                if len(data) != n:
                    raise ValueError("truncated record")
                entry = fields(data)
                if 7 not in entry:
                    continue
                spawn = fields(value(entry, 7))
                label, mnemonic = text(spawn, 7), text(spawn, 8)
                if (
                    "hepta-operator-acceptance-tests" not in label
                    or mnemonic != "TestRunner"
                ):
                    continue
                platform = {}
                for prop in fields(value(spawn, 3)).get(1, []):
                    p = fields(prop)
                    platform[text(p, 1)] = text(p, 2)
                environment = {}
                for env in spawn.get(2, []):
                    e = fields(env)
                    if text(e, 1) in [
                        "PATH",
                        "SystemRoot",
                        "SYSTEMROOT",
                        "TESTBRIDGE_TEST_ONLY",
                        "TEST_SHARD_INDEX",
                        "TEST_TOTAL_SHARDS",
                        "TEST_RUN_NUMBER",
                        "RUST_TEST_THREADS",
                        "CODEX_BAZEL_TEST_SKIP_FILTERS",
                    ]:
                        environment[text(e, 1)] = text(e, 2)
                args = [v.decode("utf-8") for v in spawn.get(1, [])]
                kind = (
                    "xml-generation"
                    if args and args[0].endswith("/generate-xml.sh")
                    else "test-execution"
                )
                results.append(
                    dict(
                        kind=kind,
                        target=label,
                        mnemonic=mnemonic,
                        args=args,
                        exit_code=value(spawn, 9, 0),
                        runner=text(spawn, 11),
                        cache_hit=bool(value(spawn, 12, 0)),
                        platform=platform,
                        environment=environment,
                    )
                )
if not results:
    raise ValueError("missing requested target")
report = dict(
    schema="verify-bazel-spawn-observation-v1",
    bazel="9.3.0",
    artifact_id=13739510839,
    artifact_sha256="75f0d66a9bed98b735a0149e6f097dafedbf146b0201616d23d13c85092ed33b",
    source_head="e4ba7c89eee20062d33303c95162e9796490d853",
    entries=entries,
    decoded_record_bytes=decoded,
    spawns=results,
    tool_visibility_proved=False,
    root_cause_closed=False,
)
open("spawn-observation.json", "w").write(json.dumps(report, indent=2) + "\n")
print(json.dumps(report))
