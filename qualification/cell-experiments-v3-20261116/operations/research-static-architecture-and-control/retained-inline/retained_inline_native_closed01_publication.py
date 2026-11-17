import hashlib,os,pathlib
r=pathlib.Path("/Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a")
p=r/"operations/native_publish_final_v3.py"
assert hashlib.sha256(p.read_bytes()).hexdigest()=="6bce9e3b5e1434ae90a24887ea2a21afeac36792706c560cab0ea74c46c2544e"
os.execv("/opt/homebrew/bin/python3",["/opt/homebrew/bin/python3","-I","-B",str(p),"--archive","publication-closed01-prepared02-input-01.zip","--archive-sha256","49df3af358682cf616f749ac1a23d2b2616958671915d0f1e79f74ab1653593f","--plan-sha256","498b93ec7ea0c6ced1de2850cb3806ab6a5b9b7fb745f19db7b8d702288219bc","--operation","publication-final-operation-04"])
