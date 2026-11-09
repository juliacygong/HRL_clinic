import sys, numpy as np
FS = 2e9
def load(f):
    a = np.loadtxt([l for l in open(f) if l[:1].isdigit()], delimiter=",")
    return a[:, 1], a[:, 3:]          # t_ns, runs (samples x runs)
def segments(x, f0, thr=0.3, smooth=16, gap=6):
    n = np.arange(len(x)); x = x - np.median(x[x != 0]) if np.any(x) else x
    bb = x * np.exp(-2j * np.pi * f0 / FS * n)
    env = np.abs(np.convolve(bb, np.ones(smooth) / smooth, mode="same")) * 2
    on = env > thr * env.max()
    segs, i = [], 0
    while i < len(on):
        if on[i]:
            j = i
            while j < len(on) and (on[j] or np.any(on[j:j + gap])): j += 1
            if j - i > 8: segs.append((i, j))
            i = j
        else: i += 1
    out = []
    for i, j in segs:
        z = bb[i:j].sum()
        out.append(dict(t=i / FS * 1e9, dur=(j - i) / FS * 1e9, ph=np.degrees(np.angle(z)), amp=env[i:j].max()))
    return out, env
if __name__ == "__main__":
    for f in sys.argv[1:]:
        t, runs = load(f)
        print("==", f.rsplit("/", 1)[-1])
        allt, allph = [], []
        for r in range(runs.shape[1]):
            s, _ = segments(runs[:, r], 500e6)
            ph0 = s[0]["ph"] if s else 0
            if r < 3: print(f" run {r}: " + "  ".join(f"t={x['t']:6.1f} len={x['dur']:5.1f} ph={((x['ph']-ph0+180)%360)-180:6.0f}" for x in s))
            allt.append([x["t"] for x in s]); allph.append([((x['ph'] - ph0 + 180) % 360) - 180 for x in s])
        ns = {len(a) for a in allt}; print(" pulses per run:", ns)
        if len(ns) == 1:
            T = np.array(allt); P = np.array(allph)
            print(" onset avg ns:", np.round(T.mean(0), 2), " spread (std) ns:", np.round(T.std(0), 3))
            print(" spacing avg ns:", np.round(np.diff(T.mean(0)), 2))
            Pc = np.degrees(np.angle(np.exp(1j * np.radians(P)).mean(0)))
            print(" phase vs pulse 1 avg deg:", np.round(Pc, 1), " std:", np.round(P.std(0), 2))
