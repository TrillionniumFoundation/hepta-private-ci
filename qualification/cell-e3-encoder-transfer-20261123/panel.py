"""Generate independent candidate-choice prompts for each partition."""
import hashlib
import json
from pathlib import Path
import random

DOMAINS = ("german", "french", "agreement", "addition", "python", "capital", "api", "text")
COUNTS = {"fit": 32, "discovery": 16, "holdout": 24, "composition": 8}
WORDS = [
    ("fire", "Feuer", "feu"), ("school", "Schule", "école"), ("brother", "Bruder", "frère"),
    ("sister", "Schwester", "sœur"), ("friend", "Freund", "ami"), ("book", "Buch", "livre"),
    ("horse", "Pferd", "cheval"), ("snow", "Schnee", "neige"), ("forest", "Wald", "forêt"),
    ("child", "Kind", "enfant"), ("uncle", "Onkel", "oncle"), ("wine", "Wein", "vin"),
    ("mountain", "Berg", "montagne"), ("bridge", "Brücke", "pont"), ("island", "Insel", "île"),
    ("river", "Fluss", "rivière"), ("chair", "Stuhl", "chaise"), ("cup", "Tasse", "tasse"),
    ("star", "Stern", "étoile"), ("cloud", "Wolke", "nuage"), ("street", "Straße", "rue"),
    ("song", "Lied", "chanson"), ("boat", "Boot", "bateau"), ("bed", "Bett", "lit"),
]
CAPS = [
    ("Italy","Rome"),("Sweden","Stockholm"),("China","Beijing"),("Germany","Berlin"),
    ("France","Paris"),("Canada","Ottawa"),("Spain","Madrid"),("Japan","Tokyo"),
    ("Greece","Athens"),("Ireland","Dublin"),("Kenya","Nairobi"),("Finland","Helsinki"),
    ("Denmark","Copenhagen"),("Belgium","Brussels"),("Lebanon","Beirut"),("Nepal","Kathmandu"),
    ("Sudan","Khartoum"),("Cuba","Havana"),("Bulgaria","Sofia"),("Serbia","Belgrade"),
    ("Croatia","Zagreb"),("Malta","Valletta"),("Georgia","Tbilisi"),("Ecuador","Quito"),
]
NOUNS = "singer pilot painter runner doctor farmer teacher worker poet writer driver sailor architect chef dancer actor climber violinist librarian judge dentist clerk captain student".split()
TOKENS = "lake hay amber silver tiny story coral branch grass violin sugar lemon slate berry purple tulip winter ocean maple cherry silk ivory amberleaf stone".split()
APIS = [
    ("append", "extend", "add one item to the end", "items", "obj"),
    ("remove", "index", "delete the first matching item", "items", "obj"),
    ("index", "append", "return the position of the first matching item", "items", "obj"),
    ("count", "remove", "count matching items", "items", "obj"),
    ("upper", "lower", "convert to uppercase", "word", ""),
    ("lower", "upper", "convert to lowercase", "word", ""),
    ("strip", "split", "remove surrounding whitespace", "word", ""),
    ("split", "strip", "split on whitespace into words", "word", ""),
    ("isdigit", "isalpha", "test whether every character is a digit", "word", ""),
    ("isalpha", "isdigit", "test whether every character is a letter", "word", ""),
]
WRAPPERS = {
    "fit": ("Task: {}", "Please solve this. {}"),
    "discovery": ("Question: {}", "Respond briefly. {}"),
    "holdout": ("Supply your answer to this request. {}", "What answer would you give? {}"),
    "composition": ("As a separate subtask, {}", "Decide this component. {}"),
}


def digest(obj):
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def example(domain, split, rng):
    start = {"fit": 0, "discovery": 6, "holdout": 12, "composition": 18}[split]
    if domain in ("german", "french"):
        word, wrong = rng.sample(WORDS[start:start + 6], 2)
        col, lang = (1, "German") if domain == "german" else (2, "French")
        q = f'Translate the English word "{word[0]}" into {lang}.'
        return q, word[col], wrong[col]
    if domain == "capital":
        word, wrong = rng.sample(CAPS[start:start + 6], 2)
        return f"What is the capital city of {word[0]}?", word[1], wrong[1]
    if domain == "agreement":
        noun = rng.choice(NOUNS[start:start + 6])
        plural = rng.choice((True, False))
        adj = rng.choice(("kind", "skilled", "calm", "trained", "friendly", "experienced"))
        return f"Fill in one word: The {adj} {noun}{'s' if plural else ''} ___ ready.", ("are" if plural else "is"), ("is" if plural else "are")
    if domain == "addition":
        lo = (4, 29, 51, 81)[start // 6]
        a, b = rng.randrange(lo, lo + 20), rng.randrange(lo, lo + 20)
        return f"What is {a} plus {b}?", str(a + b), str(a + b + rng.choice((-2,-1,1,2)))
    if domain == "python":
        lo = (3, 22, 48, 78)[start // 6]
        seq = rng.sample(range(lo, lo + 15), 4)
        ix = rng.randrange(4)
        return f"In Python, evaluate {seq}[{ix}].", str(seq[ix]), str(rng.choice([x for x in seq if x != seq[ix]]))
    if domain == "api":
        corr, foil, doc, obj, arg = rng.choice(APIS)
        suffix = rng.randrange(1000)
        return f"Complete the missing Python method to {doc}: {obj}{suffix}.___({arg})", corr, foil
    token = rng.choice(TOKENS[start:start + 6])
    action = rng.choice(("uppercase", "reverse", "first letter", "last letter"))
    possible = {"uppercase": token.upper(), "reverse": token[::-1], "first letter": token[0], "last letter": token[-1]}
    gold = possible[action]
    foil = rng.choice([v for v in possible.values() if v != gold])
    return f'For the string "{token}", output the {action} result.', gold, foil


def partition(split, seed):
    rows = []
    for domain in DOMAINS:
        rng = random.Random(f"{seed}:{split}:{domain}")
        positions = [0, 1] * (COUNTS[split] // 2)
        rng.shuffle(positions)
        seen = set()
        for i, label in enumerate(positions):
            for _ in range(10000):
                q, gold, foil = example(domain, split, rng)
                q = rng.choice(WRAPPERS[split]).format(q)
                if (q, gold, foil) not in seen:
                    break
            else:
                raise ValueError("Insufficient distinct examples")
            seen.add((q, gold, foil))
            candidates = [foil, gold] if label else [gold, foil]
            rows.append(dict(id=f"{split}-{domain}-{i:03}", split="train" if split == "fit" else split,
                             domain=domain, query=q, candidates=candidates, label=label))
    return rows


def old(split):
    rows = []
    for i in range(16):
        allowed = i % 2 == 0
        label = (i // 2) % 2
        q = f"{'Task' if split == 'old-train' else 'Record'} {i + (90 if split == 'old-test' else 20)}: {'approve' if allowed else 'decline'}. Is it approved?"
        answers = ["yes", "no"] if (allowed and label == 0 or not allowed and label == 1) else ["no", "yes"]
        rows.append(dict(id=f"{split}-{i}", domain="old", split=split,
                         query=q, candidates=answers, label=label))
    return rows


def panel():
    data = partition("fit", 1381) + partition("discovery", 1481) + old("old-train")
    seed = Path("work/confirmation-seed.json")
    if seed.exists():
        value = json.loads(seed.read_bytes())["seed"]
        data += partition("holdout", value) + partition("composition", value) + old("old-test")
    return data
