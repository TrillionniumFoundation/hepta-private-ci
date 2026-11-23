"""Draw the panel after model publication. Keep prompts and scoring records separate."""
import argparse
import json
from pathlib import Path
import random
import secrets

from cell import dump_new, file_sha, read

FORMS = {
    "explicit": [
        "Write Python that prints all integers divisible by {d} from {l} to {u}.",
        "Print multiples of {d} between {l} and {u}, inclusive.",
        "List integers divisible by {d} starting at {l} through {u}.",
        "Give a program listing multiples of {d} over {l}..{u}.",
    ],
    "reordered": [
        "From {l} through {u}, write Python to print integers divisible by {d}.",
        "Upper bound is {u}, divisor is {d}, lower bound is {l}. Output the multiples.",
        "Between {l} and {u}, list multiples of {d}.",
        "Print positive multiples of {d} no larger than {u}, starting at {l}.",
    ],
    "implicit": [
        "Use Python to list positive multiples of {d} up to {u}.",
        "No larger than {u}, output each positive integer divisible by {d}.",
        "Ending at {u}, list positive multiples of {d}.",
        "Print the positive numbers divisible by {d}, upper bound is {u}.",
    ],
    "distractor": [
        "Ticket {t}. From {l} to {u}, use Python to print multiples of {d}.",
        "From {l} through {u}, print integers divisible by {d}. Request ID {t}.",
        "Batch {t} needs multiples of {d} starting at {l} and ending at {u}.",
        "For version {t}, list positive multiples of {d} between {l} and {u}.",
    ],
}
OUTSIDE = [
    "Print the sum of all multiples of {d} up to {u}.",
    "How many positive multiples of {d} are below {u}? Return a count.",
    "List all integers from {l} to {u} not divisible by {d}.",
    "Generate the multiples of {d} up to {u} in descending order.",
    "Return the product of the positive integers divisible by {d} up to {u}.",
    "Show the squares of all integers divisible by {d} from {l} to {u}.",
    "Find the average of the multiples of {d} between {l} and {u}.",
    "List primes from {l} to {u}.",
]


def draw(seed, historical):
    rng = random.Random(seed)
    prompts, gold = [], {}
    def add(identifier, query, group, values):
        prompts.append({"id":identifier, "query":query})
        gold[identifier] = {"group":group, "args":values}
    for c in historical["cases"]:
        add(c["id"], c["query"], "exposed_"+c["group"], [c["divisor"],1,c["bound"]])
    used = set()
    for group, forms in list(FORMS.items()) + [("outside", OUTSIDE)]:
        for i in range(16 if group=="outside" else 24):
            while True:
                d, l, u, t = rng.randint(2,23), rng.randint(1,59), rng.randint(60,239), rng.randint(2,199)
                if group == "implicit":
                    l = 1
                if len({d,l,u,t}) < 4 or (d,l,u) in used:
                    continue
                used.add((d,l,u))
                break
            q = forms[i%len(forms)].format(d=d,l=l,u=u,t=t)
            add(f"{group}-{i:02}",q,group,None if group=="outside" else [d,l,u])
    rng.shuffle(prompts)
    add("keep","Return the digit zero.","old",None)
    return prompts,gold


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("previous", type=Path)
    parser.add_argument("frozen", type=Path)
    parser.add_argument("out", type=Path)
    args=parser.parse_args()
    assert file_sha(args.previous) == "d8b81f2c5b8ecadb4c6746f1d3400ee21a83ab6a4da5d43106402f804bec1031"
    seed=secrets.randbits(96)
    prompts,gold=draw(seed,read(args.previous))
    args.out.mkdir(exist_ok=False)
    dump_new(args.out/"prompts.json",prompts)
    dump_new(args.out/"gold.json",gold)
    dump_new(args.out/"commitment.json",dict(seed=seed,model=file_sha(args.frozen),
             prompts=file_sha(args.out/"prompts.json"),gold=file_sha(args.out/"gold.json")))
