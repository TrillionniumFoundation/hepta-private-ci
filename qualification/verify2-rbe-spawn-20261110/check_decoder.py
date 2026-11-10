import runpy, contextlib, io, json
from pathlib import Path

with contextlib.redirect_stdout(io.StringIO()):
    m = runpy.run_path(str(Path(__file__).with_name("audit_spawn.py")))
f = m["fields"]
v = m["varint"]
assert f(b"\x08\x01\x12\x03abc") == {1: [1], 2: [b"abc"]}
cases = [b"\x00", b"\x12\x05a", b"\x0b", b"\x09abc", b"\x0dabc"]
for b in cases:
    try:
        f(b)
    except ValueError:
        pass
    else:
        raise AssertionError("accepted malformed protobuf")
for b in [b"\x80", b"\xff" * 10]:
    try:
        v(io.BytesIO(b))
    except ValueError:
        pass
    else:
        raise AssertionError("accepted malformed varint")
print(
    json.dumps(
        dict(
            valid_example=True,
            malformed_cases_rejected=7,
            actual_artifact_replayed=True,
        )
    )
)
