"""Create a verified-shape positive-multiple listing from an explicit file request."""
import ast
import hashlib
import itertools
import os
from pathlib import Path
import re
import tempfile

import cell

MODEL_SHA = "adc690f5f70aa9505c9f24baafdbbb90cfcf6cf3172a09ad6566a6b8696dd9ba"
MAX_RECORDS = 12_000_000
MAX_BYTES = 128 * 1024**2
FILE = re.compile(r"""\b(?:text\s+)?file\s+(?:named\s*:?\s*|called\s+)?(["'])([^"']+)\1""", re.I)
EXCLUSIVE = re.compile(r"\b(?:strictly below|under|less than|below|before)\s+(?=\d)",re.I)
START = re.compile(r"\b(?:starts? at the number|starts? at|starting with|beginning at)\s+(?=\d)",re.I)


def materialize(source, arm):
    if arm == "rule":
        return None
    if arm != "direct" or cell.file_sha(source) != MODEL_SHA:
        raise ValueError("Unknown frozen Cell")
    material = cell.read(source)
    # The optimized loop below implements only this exact archived filter.
    pattern = ast.parse("for i in range(1, 101):\n    if i % 7 == 0:\n        print(i)")
    proto = ast.parse(material["actions"][1])
    def shape(tree):
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and type(node.value) is int:
                node.value = 0
        return ast.dump(tree, include_attributes=False)
    if shape(proto) != shape(pattern) or material["offsets"] != [0,0,1]:
        raise ValueError("Unsupported donor program")
    return material


def binding(query, material, arm):
    matches = list(FILE.finditer(query))
    if len(matches) != 1:
        raise ValueError("Expected one quoted destination")
    match = matches[0]
    name = match.group(2)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\.txt", name):
        raise ValueError("Unsupported file name")
    # Keep file names out of the numeric binding, including year/version digits.
    text = query[:match.start()] + " " + query[match.end():]
    text = text.lower()
    if not cell.IN_SCOPE.search(text) or cell.OTHER.search(text):
        raise ValueError("Unsupported list request")
    if re.search(r"(?<!\w)-\d|\d{14,}", text):
        raise ValueError("Number outside supported range")
    if len(EXCLUSIVE.findall(text)) > 1:
        raise ValueError("Conflicting upper bounds")
    exclusive = bool(EXCLUSIVE.search(text))
    normalized = START.sub("from ", EXCLUSIVE.sub("to ", text))
    bound = cell.bind(normalized, material, arm)
    if bound is None:
        raise ValueError("Missing numeric binding")
    d, lo, hi = bound
    if not (1 <= d <= 10**12 and 0 <= lo <= 10**12 and 0 <= hi <= 10**12):
        raise ValueError("Unsupported numeric domain")
    stop = hi if exclusive else hi+1
    first = (-lo % d) + lo
    seq = range(first,stop,d)
    return name, seq


def byte_count(seq):
    if not seq:
        return 0
    total = 0
    # Count canonical decimal digits and one newline without allocating rows.
    for n in range(1,len(str(seq[-1]))+1):
        lower = max(seq.start, 0 if n == 1 else 10**(n-1))
        upper = min(seq[-1], 10**n-1)
        if upper >= lower:
            total += (upper//seq.step - (lower-1)//seq.step) * (n+1)
    return total


def execute(query, source, arm, work):
    material = materialize(source, arm)
    name, seq = binding(query, material, arm)
    size = byte_count(seq)
    if len(seq)>MAX_RECORDS or size>MAX_BYTES:
        raise ValueError("Listing exceeds output quota")
    target = work/name
    if target.exists():
        raise FileExistsError(name)
    tmp = None
    count = 0
    digest = hashlib.sha256()
    try:
        with tempfile.NamedTemporaryFile(dir=work, prefix=".listing-", delete=False) as stream:
            tmp=Path(stream.name)
            it=iter(seq)
            while True:
                batch=list(itertools.islice(it,8192))
                if not batch:
                    break
                data=("".join(f"{v}\n" for v in batch)).encode("ascii")
                stream.write(data)
                digest.update(data)
                count+=len(data)
            stream.flush()
            os.fsync(stream.fileno())
        if count!=size:
            raise ValueError("Published length would differ from quota")
        # Atomic create-only publication, even when another writer won the race.
        os.link(tmp,target)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
    return dict(name=name, records=len(seq), bytes=count, sha256=digest.hexdigest())
