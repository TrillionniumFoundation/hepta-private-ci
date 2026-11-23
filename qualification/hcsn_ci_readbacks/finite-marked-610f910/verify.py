"""Compare portable scientific outputs with the original hosted archive at the same Git tree."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from zipfile import ZipFile

HERE=Path(__file__).resolve().parent
SOURCE="610f91087b598656f7f3913e600c705b95bf071f"
TREE="e7b3615a8eb989b6df6970ea0c42262811f480ce"
DIGEST="b1bcaeb231266d79f378d45cfe2d8fe25223943286256403441505b0486a3b31"


def leaves(value,prefix=""):
    if isinstance(value,dict):
        for k,v in value.items():
            yield from leaves(v,prefix+"/"+str(k))
    elif isinstance(value,list):
        for i,v in enumerate(value):
            yield from leaves(v,prefix+"/"+str(i))
    else:
        yield prefix,value


def main(science_root):
    reference=science_root/"qualification/hcsn_halfline_transport"
    assert hashlib.sha256((HERE/"hosted.zip").read_bytes()).hexdigest()==DIGEST
    pairs={"finite-marked-reference.json":"finite_marked_reference/result.json","finite-marked.json":"FINITE_MARKED_RESULT.json",
           "mixed-continuum.json":"MIXED_CONTINUUM_RESULT.json","qvi-finite-bridge.json":"QVI_FINITE_BRIDGE.json"}
    with ZipFile(HERE/"hosted.zip") as z:
        assert z.read("source.txt").decode().splitlines()==[SOURCE,TREE]
        original=z.read("upstream.log").decode()
        assert re.search(r"^Ran 12 tests in [0-9.]+s\n\nOK\s*$",original,re.MULTILINE)
        starts=list(re.finditer(r"\b(test_\w+) \(qualification\.[\w.]+\) \.\.\. ",original))
        assert len({m.group(1) for m in starts})==12
        for index,m in enumerate(starts):
            end=starts[index+1].start() if index+1<len(starts) else len(original)
            segment=original[m.end():end]
            assert re.search(r"^(?:ok)(?:\s|$)",segment,re.MULTILINE),m.group(1)
        out={}
        for name,local in pairs.items():
            hosted=json.loads(z.read(name));portable=json.loads((reference/local).read_bytes())
            left,right=dict(leaves(hosted)),dict(leaves(portable))
            assert set(left)==set(right)
            delta={}
            differing_text=[]
            for key,v in left.items():
                w=right[key]
                if type(v) in (float,int) and type(w) in (float,int):
                    delta[key]=abs(v-w)
                elif v!=w:
                    assert key in ("/torch","/torch_version","/reference_sha256"),(key,v,w)
                    differing_text.append(key)
            worst=max(delta,key=delta.get)
            assert delta[worst]<1e-8
            out[name]={"numeric_entries":len(delta),"different_numeric_entries":sum(d>0 for d in delta.values()),
                       "largest_absolute_difference":delta[worst],"largest_absolute_path":worst,"version_or_reference_fields":differing_text}
        generated=z.read("finite-marked-reference.json")
        exact=json.loads(z.read("finite-marked.json"))
        assert exact["torch"]=="2.10.0+cpu" and hashlib.sha256(generated).hexdigest()==exact["reference_sha256"]
        bridge=json.loads(z.read("qvi-finite-bridge.json"))
        mixed=json.loads(z.read("mixed-continuum.json"))
        return dict(source=SOURCE,tree=TREE,artifact=14814275143,zip_sha256=DIGEST,job=137650500461,run=45162302799,
                    upstream_passed=12,hosted_torch=exact["torch"],portable_torch="2.15.0+cpu",comparisons=out,
                    hosted_physical_gradient_max_error=max(a["absolute_error"] for a in exact["derivatives"].values()),
                    hosted_two_neuron_gradient_max_error=max(v["max_error"] for v in bridge["numerical_reference"].values()),
                    hosted_mixed_split_max_errors=[v["64"]["max_abs"] for v in mixed["orders"].values()],
                    hosted_signed_and_unmarked_flux_max_error=mixed["wall_flux"]["max_absolute"])


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("science_root",type=Path)
    args=p.parse_args()
    print(json.dumps(main(args.science_root),indent=2,allow_nan=False))
