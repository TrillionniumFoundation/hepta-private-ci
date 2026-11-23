from pathlib import Path, PurePosixPath
from zipfile import ZipFile
import sys
target = Path(sys.argv[1])
root = target / "raw"
root.mkdir()
with ZipFile(target/"ORIGINAL.zip") as z:
    for f in z.infolist():
        n=PurePosixPath(f.filename)
        if not n.parts or n.is_absolute() or ".." in n.parts or "\\" in f.filename:
            raise ValueError(f.filename)
        p=root.joinpath(*n.parts)
        if f.is_dir():
            p.mkdir(parents=True,exist_ok=True)
        else:
            p.parent.mkdir(parents=True,exist_ok=True)
            with p.open("xb") as out: out.write(z.read(f))
