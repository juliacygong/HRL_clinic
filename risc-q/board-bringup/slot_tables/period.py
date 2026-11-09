import sys, glob, numpy as np
sys.path.insert(0, "."); from analyze import load; from spans import env
def onsets(e, fs, thr=0.3):
    on = e > thr*e.max(); r = np.flatnonzero(np.diff(on.astype(int)) == 1)
    return r/fs*1e9
def per(o): return (o[-1]-o[0])/(len(o)-1), len(o)
t,R = load("data/riscq_board/virtz_adc2.csv")
p=[per(onsets(env(R[:,r],2e9,100e6,10),2e9)) for r in range(R.shape[1])]
print("riscq virtz period avg %.2f, pulses seen %s"%(np.mean([x[0] for x in p]), sorted({x[1] for x in p})))
p=[]
for f in sorted(glob.glob("data/tproc_board/v_virtz_mr_*.csv")):
    a=np.loadtxt(f,delimiter=",",skiprows=1); e=np.abs(np.convolve(a[:,0]+1j*a[:,1],np.ones(3)/3,"same"))
    p.append(per(onsets(e,2457.6e6)))
print("tproc virtz period avg %.2f, pulses %s"%(np.mean([x[0] for x in p]), sorted({x[1] for x in p})))
