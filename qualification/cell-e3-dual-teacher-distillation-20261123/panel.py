"""Deterministic, balanced research tasks, with disjoint records per split."""
import hashlib
import json
import random

SIZES = {"discovery": 12, "train": 32, "holdout": 20, "composition": 8}
DOMAINS = ("review", "order", "arithmetic", "python", "spelling", "category")
NAMES = "Ada Ben Cara Dev Eva Finn Gwen Hugh Iris Joel Kira Luis Mona Noah Opal Paul".split()
WORDS = "basket cotton desert fabric garlic guitar hammer island jacket kettle ladder lizard marble market magnet needle orange paddle pencil pepper pocket rabbit rocket saddle silver tablet tunnel velvet walnut window winter yellow".split()
POS = "superb excellent wonderful delightful fantastic splendid impressive lovely brilliant pleasant enjoyable satisfying".split()
NEG = "awful terrible disappointing horrible dreadful atrocious boring unpleasant annoying mediocre painful frustrating".split()
ANIMALS = "wolf otter lynx panda tiger rabbit camel weasel leopard walrus cobra turtle".split()
OBJECTS = "stapler hammer kettle pencil desk spoon ladder bucket blanket chair bottle magnet".split()


def task(domain, i, split, rng):
    good = i % 2 == 0
    style = split in ("holdout", "composition")
    if domain == "review":
        noun = rng.choice(("concert", "meal", "hotel", "class", "album", "film", "show", "book"))
        adjective = rng.choice(POS if good else NEG)
        phrase = rng.choice((f"The {noun} was {adjective}.", f"What a {adjective} {noun}!", f"I found the {noun} {adjective}."))
        q = (f'Would this reviewer recommend it? "{phrase}"' if style else f'Review: "{phrase}" Is the opinion positive?')
    elif domain == "order":
        first, second = rng.sample(NAMES, 2)
        early, late = (first, second) if good else (second, first)
        q = (f"{early} reached the station before {late}. Was {first} the earlier arrival?" if style
             else f"{early} arrived first, then {late} arrived. Did {first} arrive before {second}?")
    elif domain == "arithmetic":
        a, b = rng.sample(range(4, 80), 2)
        lhs, rhs = (max(a, b), min(a, b)) if good else (min(a, b), max(a, b))
        q = (f"Is {lhs} strictly larger than {rhs}?" if style else f"Is {lhs} greater than {rhs}?")
    elif domain == "python":
        n = rng.randrange(5, 99)
        d = rng.randrange(2, 9)
        expected = n % d if good else (n % d + rng.randrange(1, d)) % d
        expr = f"{n} % {d} == {expected}"
        q = (f"In Python, would the expression ({expr}) evaluate to True?" if style else f"Does Python return True for {expr}?")
    elif domain == "spelling":
        word = rng.choice(WORDS)
        k = rng.randrange(len(word))
        letter = word[k] if good else rng.choice([c for c in "abcdefghijklmnopqrstuvwxyz" if c != word[k]])
        q = (f'Start counting at one. Is character {k+1} in "{word}" the letter {letter}?' if style
             else f'In the word "{word}", is letter number {k+1} (one-based) equal to {letter}?')
    else:
        a = rng.choice(ANIMALS if good else OBJECTS)
        setting = rng.choice(("list", "worksheet", "card", "puzzle", "notebook", "inventory", "sketch", "catalog"))
        q = (f'A {setting} contains the word "{a}". Does that word name an animal?' if style
             else f'On a {setting} the entry is "{a}". Is the thing named an animal?')
    return q, int(good)


def panel():
    rows, used = [], set()
    for split, n in SIZES.items():
        for domain in DOMAINS:
            rng = random.Random(f"hepta-e3-20261123:{split}:{domain}")
            for i in range(n):
                for _ in range(10000):
                    prompt, label = task(domain, i, split, rng)
                    if prompt not in used:
                        break
                else:
                    raise ValueError("Exhausted unique questions")
                used.add(prompt)
                rows.append({"id": f"{split}-{domain}-{i:02}", "split": split,
                             "domain": domain, "prompt": prompt, "label": label})
    for split, n in (("old-train", 16), ("old-test", 12)):
        for i in range(n):
            correct = i % 2 == 0
            action = "approve" if correct else "decline"
            verb = "Signal" if split == "old-train" else "Status"
            rows.append({"id":f"{split}-{i:02}", "split":split,"domain":"old",
                         "prompt":f"{verb} {i+140}: {action}. Should this operation proceed?", "label":int(correct)})
    return rows


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


if __name__ == "__main__":
    print(digest(panel()))
