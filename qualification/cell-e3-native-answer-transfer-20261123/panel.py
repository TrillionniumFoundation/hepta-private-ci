"""Locked native-completion panel. Gold and foil completions are scored symmetrically."""
import hashlib
import json
import random

DOMAINS = ("german","french","agreement","addition","python","capital")
SIZES = {"discovery":12,"train":32,"holdout":20,"composition":8}
TRANSLATE = (
    ("house","Haus","maison"),("water","Wasser","eau"),("dog","Hund","chien"),
    ("cat","Katze","chat"),("bread","Brot","pain"),("milk","Milch","lait"),
    ("fish","Fisch","poisson"),("tree","Baum","arbre"),("book","Buch","livre"),
    ("apple","Apfel","pomme"),("door","Tür","porte"),("table","Tisch","table"),
    ("moon","Mond","lune"),("sun","Sonne","soleil"),("hand","Hand","main"),
    ("head","Kopf","tête"),("flower","Blume","fleur"),("bird","Vogel","oiseau"),
    ("horse","Pferd","cheval"),("window","Fenster","fenêtre"),("rain","Regen","pluie"),
    ("snow","Schnee","neige"),("cheese","Käse","fromage"),("city","Stadt","ville"),
)
CAPS = (("France","Paris"),("Germany","Berlin"),("Italy","Rome"),("Spain","Madrid"),
        ("Portugal","Lisbon"),("Japan","Tokyo"),("China","Beijing"),("Thailand","Bangkok"),
        ("Canada","Ottawa"),("Mexico","Mexico City"),("Norway","Oslo"),("Sweden","Stockholm"),
        ("Finland","Helsinki"),("Greece","Athens"),("Egypt","Cairo"),("Kenya","Nairobi"),
        ("Argentina","Buenos Aires"),("Chile","Santiago"),("Peru","Lima"),("Venezuela","Caracas"),
        ("Austria","Vienna"),("Poland","Warsaw"),("Hungary","Budapest"),("Ireland","Dublin"))
NOUNS = "artist doctor runner writer farmer singer baker teacher sailor dancer painter gardener pilot player driver lawyer worker swimmer reader designer".split()
ADJS = "young busy tired quiet careful eager patient friendly cheerful lucky polite alert calm clever honest brave".split()
STEMS = {"discovery":0,"train":1,"holdout":2,"composition":3}

def generate(domain, split, rng):
    style=STEMS[split]
    if domain in ("german","french"):
        lang, col = ("German",1) if domain=="german" else ("French",2)
        (english,*_), foil = rng.sample(TRANSLATE,2)
        lexical=next(row for row in TRANSLATE if row[0]==english)
        query=(f'Translate "{english}" into {lang}.', f'English to {lang}: {english}',
               f'Give the {lang} translation of the English noun "{english}".', f'In {lang}, how do you say "{english}"?')[style]
        return query,lexical[col],foil[col]
    if domain=="capital":
        (country,gold),(_,foil)=rng.sample(CAPS,2)
        query=(f'What is the capital of {country}?',f'{country}: name its capital city.',
               f'Give the name of the capital city of {country}.',f'Which city is the capital of {country}?')[style]
        return query,gold,foil
    if domain=="agreement":
        adj,noun=rng.choice(ADJS),rng.choice(NOUNS)
        plural=rng.choice((True,False))
        subject = f'The {adj} {noun}'+("s" if plural else "")
        phrase = (f'{subject} ___ here.',f'{subject} ___ outside.',f'{subject} ___ ready.',f'{subject} ___ nearby.')[style]
        return f'Fill the blank with one word: {phrase}', ('are' if plural else 'is'), ('is' if plural else 'are')
    if domain=="addition":
        a,b=rng.randrange(1,45),rng.randrange(1,45)
        g=a+b
        q=(f'What is {a} + {b}?',f'Add {a} and {b}.',f'Compute the sum of {a} and {b}.',f'{a} + {b} =')[style]
        return q,str(g),str(g+rng.choice((-2,-1,1,2)))
    seq = rng.sample(range(1,20),4)
    ix=rng.randrange(4)
    expr=f'{seq}[{ix}]'
    query=(f'In Python what value does {expr} return?',f'Find the Python result: {expr}',
           f'Evaluate this Python expression and give its value: {expr}',f'Python output of print({expr})?')[style]
    return query,str(seq[ix]),str(rng.choice([x for x in seq if x!=seq[ix]]))

def panel():
    rows,used=[],set()
    for split,n in SIZES.items():
        for d in DOMAINS:
            rng=random.Random(f'native-answer-e3-v1-{d}-{split}')
            classes=[0,1]*(n//2)
            rng.shuffle(classes)
            for i,y in enumerate(classes):
                for _ in range(1000):
                    query,gold,foil=generate(d,split,rng)
                    c=[foil,gold] if y else [gold,foil]
                    prompt=f'{query}\nFirst candidate: {c[0]}. Second candidate: {c[1]}.'
                    if prompt not in used:
                        break
                else:
                    raise ValueError("Unique query exhausted")
                used.add(prompt)
                rows.append(dict(id=f'{split}-{d}-{i:02}',domain=d,split=split,prompt=prompt,
                                 query=query,candidates=c,label=y))
    for split,n in (("old-train",16),("old-test",12)):
        for i in range(n):
            ok=i%2==0
            verb="Signal" if split=="old-train" else "Status"
            instruction="approve" if ok else "decline"
            rows.append(dict(id=f'{split}-{i:02}',split=split,domain="old",
                            prompt=f'{verb} {i+140}: {instruction}. Should this operation proceed?',label=int(ok)))
    return rows

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":")).encode()).hexdigest()
