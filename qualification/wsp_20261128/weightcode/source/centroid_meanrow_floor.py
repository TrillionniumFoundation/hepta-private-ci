
import numpy as np

HYPOTHESIS = (
    "The model fails on jump compositions because the jump embedding lies far outside the cluster of the trained "
    "primitives walk/look/run (larger norm, mostly in directions those primitives never use), so every layer "
    "processes a jump command as an unseen structure (e.g. 'jump twice' -> RUN RUN RUN). The network is close to "
    "linear in the 2-D identity plane spanned by walk/look/run: replacing the jump embedding by the centroid of the "
    "three primitive embeddings makes it a primitive with no identity, the command structure is then computed exactly "
    "as for walk/look/run, and at the slots where that primitive's action goes the W, L and R logits come out nearly "
    "level (all at about the mean level), whereas at a true walk/look/run slot the winner exceeds mean(W,L,R) by "
    "about 2/3 of its margin. A head row for I_JUMP equal to the mean of the W/L/R rows plus a bias offset b placed "
    "between these two distributions therefore wins exactly at the jump slots and nowhere else."
)
PREDICTED_EFFECT = (
    "Target (jump) commands: from 0% to about 99.8-99.9% of rows right (slightly more than with b at the midpoint of "
    "the 1% tails, since b = 0.9 x the floor of the old identity margins also covers jump slots where the other "
    "primitive leaks by up to ~8 logits); the remaining failures are short commands such as 'jump and walk', "
    "'walk after jump', 'jump thrice and walk', which inherit the original model's own bug on bare 'X and Y' or a "
    "leak larger than b. Old commands: no slot of a correctly answered jump-free command has winner - mean(W,L,R) "
    "below the floor, so none can turn into I_JUMP: score_old = 0. Changes 1 embedding row, 1 head row, 1 head bias."
)

GRAMMAR_U = ["walk", "look", "run", "jump"]


def _commands():
    vs = []
    for d in GRAMMAR_U + ["turn"]:
        for dirn in ["left", "right"]:
            vs += [d + " opposite " + dirn, d + " around " + dirn, d + " " + dirn]
    vs += GRAMMAR_U
    ss = []
    for v in vs:
        ss += [v, v + " twice", v + " thrice"]
    cs = list(ss)
    for a in ss:
        for b in ss:
            cs.append(a + " and " + b)
            cs.append(a + " after " + b)
    return cs


def update(student, experience):
    params = student["params"]
    fwd = student["forward"]
    layout = student["layout"]
    toks = {t["name"]: t["id"] for t in layout["input"]["tokens"]}
    classes = list(layout["classes"])
    seq_len = int(layout["input"]["shape"][0])
    pad = int(layout["input"].get("pad_id", 0))
    emb_name = [l["weight"] for l in layout["layers"] if l["op"] == "embedding"][0]
    head_layer = [l for l in layout["layers"] if l["op"] == "linear"][-1]
    hw_name, hb_name = head_layer["weight"], head_layer["bias"]

    E = np.asarray(params[emb_name], dtype=np.float64)
    HW = np.asarray(params[hw_name], dtype=np.float64)
    HB = np.asarray(params[hb_name], dtype=np.float64)
    prim = ["walk", "look", "run"]
    pid = [toks[p] for p in prim]
    jid = toks["jump"]
    act = {"walk": "I_WALK", "look": "I_LOOK", "run": "I_RUN", "jump": "I_JUMP"}
    pc = [classes.index(act[p]) for p in prim]
    jc = classes.index("I_JUMP")

    # 1) jump embedding -> centroid of the three trained primitives
    mu = E[pid].mean(axis=0)
    d_emb = np.zeros_like(E)
    d_emb[jid] = mu - E[jid]

    # 2) statistics that place the bias offset b
    x_prim = np.asarray(experience["x_prim"])
    out_id = toks["OUT"]
    n_out = int((x_prim[0] == out_id).sum())

    def enc(c):
        row = [toks["BOS"]] + [toks[w] for w in c.split()] + [toks["SEP"]] + [out_id] * n_out
        return row + [pad] * (seq_len - len(row))

    def out_logits(p, X):
        L = np.asarray(fwd(p, X), dtype=np.float64)
        m = X == out_id
        return L, m

    # 2a) identity margin at true walk/look/run slots of the experience's training rows (label-conditioned)
    x_old = np.asarray(experience["x_old"]); y_old = np.asarray(experience["y_old"])
    L_old = np.asarray(fwd(params, x_old), dtype=np.float64)
    sel = np.isin(y_old, pc)
    lo = L_old[sel]
    yk = y_old[sel]
    m_id = lo[np.arange(len(yk)), yk] - lo[:, pc].mean(axis=1)

    # 2b) asymmetry of W/L/R at jump slots with the centroid embedding (no labels: jump slots are the slots where
    #     the original model, given the command with jump replaced by an absent primitive p, outputs p)
    cs = [c for c in _commands() if "jump" in c.split() and c != "jump"]
    cs = cs[::8]
    refs, pidx = [], []
    for c in cs:
        w = c.split()
        p = [q for q in prim if q not in w][0]
        refs.append(" ".join(p if t == "jump" else t for t in w)); pidx.append(pc[prim.index(p)])
    Xj = np.array([enc(c) for c in cs], dtype=np.int64)
    Xr = np.array([enc(c) for c in refs], dtype=np.int64)
    Lr = np.asarray(fwd(params, Xr), dtype=np.float64)
    pc_params = dict(params)
    pc_params[emb_name] = (E + d_emb).astype(np.float32)
    Lj = np.asarray(fwd(pc_params, Xj), dtype=np.float64)
    outm = Xj == out_id
    jslot = (Lr.argmax(-1) == np.array(pidx)[:, None]) & outm
    W3 = Lj[..., pc][jslot]
    asym = W3.max(axis=1) - W3.mean(axis=1)

    a_hi = float(np.percentile(asym, 99))
    m_lo = float(np.percentile(m_id, 1))
    # floor of the identity margin over the model's own W/L/R answers on every jump-free command of the grammar
    # (no labels): b is placed just below it, since a slot of an old command can only turn into I_JUMP if its
    # winner - mean(W,L,R) is below b, while the jump-slot asymmetry has a long right tail
    nj = [c for c in _commands() if "jump" not in c.split()]
    m_all = []
    for s in range(0, len(nj), 2048):
        Xn = np.array([enc(c) for c in nj[s:s + 2048]], dtype=np.int64)
        Ln = np.asarray(fwd(params, Xn), dtype=np.float64)
        on = Xn == out_id
        Lo = Ln[on]
        win = Lo.argmax(-1)
        sel_n = np.isin(win, pc)
        Lo = Lo[sel_n]
        m_all.append(Lo.max(-1) - Lo[:, pc].mean(-1))
    m_all = np.concatenate(m_all)
    m_floor = float(m_all.min())
    b = 0.9 * m_floor
    print("population identity margin: n %d floor %.3f p1 %.3f median %.3f" % (len(m_all), m_floor, np.percentile(m_all, 1), np.median(m_all)))

    # 3) I_JUMP head row = mean of the W/L/R rows, bias = their mean + b
    d_hw = np.zeros_like(HW); d_hb = np.zeros_like(HB)
    d_hw[jc] = HW[pc].mean(axis=0) - HW[jc]
    d_hb[jc] = HB[pc].mean() + b - HB[jc]

    print("n jump cmds used", len(cs), "jump slots", int(jslot.sum()), "old prim slots", int(sel.sum()))
    print("asym median %.3f p99 %.3f max %.3f" % (np.median(asym), a_hi, asym.max()))
    print("id margin median %.3f p1 %.3f min %.3f" % (np.median(m_id), m_lo, m_id.min()))
    print("b = %.3f" % b)
    return {emb_name: d_emb, hw_name: d_hw, hb_name: d_hb}
