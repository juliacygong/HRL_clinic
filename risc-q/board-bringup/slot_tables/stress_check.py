import sys, csv, cmath, math
import numpy as np
def load(p):
    rows = [(int(r[0]), [int(x) for x in r[1:]]) for r in list(csv.reader(open(p)))[1:]]
    c0 = rows[0][0]; n = rows[-1][0] - c0 + 1
    x = np.zeros(n * 16)
    for c, s in rows: x[(c - c0) * 16:(c - c0 + 1) * 16] = s
    return c0, x
c0, g = load(sys.argv[1]); _, h = load(sys.argv[2])
fs = 8e9
a = np.abs(g) ; on = np.nonzero(a > 0)[0]; s0 = on[0]
print(f"gen0 first sample at gen cycle {c0 + s0 // 16}; per 50 ns slot (400 samples):")
n = np.arange(len(g)); ref = np.exp(-2j * np.pi * 500e6 / fs * n)
for shot in range(3):
    base = s0 + shot * 1249 * 16
    amps, phs = [], []
    for i in range(30):
        seg = slice(base + i * 400, base + i * 400 + 320)
        z = (g[seg] * ref[seg]).sum()
        amps.append(np.abs(g[seg]).max()); phs.append(math.degrees(cmath.phase(z)))
    rel = [((p - phs[0] + 180) % 360) - 180 for p in phs]
    print(f" shot {shot+1}: peak ", " ".join(f"{v/1000:4.1f}" for v in amps[:9]), "k ...")
    print(f"          phase", " ".join(f"{v:5.0f}" for v in rel[:9]), "...")
hon = np.nonzero(np.abs(h) > 0)[0]; h0 = hon[0]
print(f"gen1 first sample at gen cycle {c0 + h0 // 16} (gen0 + {(h0 - s0) / 16:.0f} cycles, expect +10)")
for shot in range(3):
    base = h0 + shot * 1249 * 16
    fr = []
    for i in range(15):
        seg = h[base + i * 800: base + i * 800 + 640]
        spec = np.abs(np.fft.rfft(seg, 8192)); fr.append(np.argmax(spec) * fs / 8192 / 1e6)
    print(f" shot {shot+1}: carrier MHz", " ".join(f"{f:4.0f}" for f in fr))
