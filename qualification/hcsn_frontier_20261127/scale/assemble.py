"""Assemble the authorized offline script from auditable code, calibration law and public data."""
import argparse
import base64
import hashlib
from pathlib import Path

def assemble(core,pack,cap):
    law=(core/'he_xiong.py').read_text()
    pop=(core/'population.py').read_text().replace('from he_xiong import Published','')
    main=Path(__file__).with_name('train.py').read_text()
    encoded=base64.b85encode(pack.read_bytes()).decode('ascii')
    return ('# Standalone UCM-Captions scaling task\n'+law+'\n'+pop+'\n'+f'CAP={cap}\nPACK={encoded!r}\n'+main).encode('utf-8')

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('core','pack','out'):p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--cap',type=int,required=True,choices=(15,60,120,360))
    a=p.parse_args();b=assemble(a.core,a.pack,a.cap);a.out.write_bytes(b)
    print(len(b),hashlib.sha256(b).hexdigest())
