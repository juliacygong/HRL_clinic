import sys, numpy as np
sys.path.insert(0, ".")
from analyze import load
def env(x, fs, f, k):
    n=np.arange(len(x)); x=x-np.median(x[x!=0]) if np.any(x) else x
    return np.abs(np.convolve(x*np.exp(-2j*np.pi*f/fs*n), np.ones(k)/k, "same"))
def span(e, fs):
    on=np.flatnonzero(e>0.15*e.max()); return (on[-1]-on[0])/fs*1e9, on[0]/fs*1e9
for name in ("rate","sweep","virtz"):
    t, R = load(f"data/riscq_board/{name}_adc2.csv")
    s=[span(env(R[:,r],2e9,100e6,10),2e9) for r in range(R.shape[1])]
    s=np.array(s); print(name, "riscq span avg %.1f std %.2f  onset std %.2f"%(s[:,0].mean(), s[:,0].std(), s[:,1].std()))
import glob
for name,pat in (("rate","data/tproc_board/q_same_mr_*.csv"),("sweep","data/tproc_board/q_sweep_mr_*.csv"),("virtz","data/tproc_board/v_virtz_mr_*.csv")):
    s=[]
    for f in sorted(glob.glob(pat)):
        a=np.loadtxt(f,delimiter=",",skiprows=1); e=np.abs(np.convolve(a[:,0]+1j*a[:,1],np.ones(3)/3,"same"))
        s.append(span(e,2457.6e6))
    s=np.array(s); print(name, "tproc span avg %.1f std %.2f onset std %.2f n=%d"%(s[:,0].mean(), s[:,0].std(), s[:,1].std(), len(s)))
