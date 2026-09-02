import numpy as np, pandas as pd, matplotlib
matplotlib.use('Agg'); import matplotlib.pyplot as plt
df = pd.read_csv('clipped/fused_trace.csv')
b = np.load('clipped/lap_bounds_race.npy')
t = df.seconds_elapsed_race.values

def seg(i):
    m = (t >= b[i,0]) & (t <= b[i,1])
    return df.E[m].values, df.N[m].values

# lap 11 start/end coords - should be ~same point (closed loop)
for i in [10]:
    E,N = seg(i)
    print(f"lap{i+1}: start=({E[0]:.1f},{N[0]:.1f}) end=({E[-1]:.1f},{N[-1]:.1f}) "
          f"gap={np.hypot(E[0]-E[-1],N[0]-N[-1]):.1f}m  npts={len(E)}")

# overlay lap 11 vs a couple other clean laps (5, 7) to compare lines
fig,ax=plt.subplots(figsize=(7,11))
for i,c,lw,lab in [(4,'0.6',1,'lap5 41.56'),(6,'tab:blue',1.2,'lap7 41.16'),(10,'red',2.2,'lap11 40.53 BEST')]:
    E,N=seg(i); ax.plot(E,N,color=c,lw=lw,label=lab)
    ax.plot(E[0],N[0],'o',color=c,ms=8)        # start dot
    ax.plot(E[-1],N[-1],'x',color=c,ms=10)      # end x
ax.plot(12,-12,'ks',ms=12,mfc='none',label='gate')
ax.set_aspect('equal'); ax.legend(fontsize=9); ax.set_title('lap 11 vs other clean laps (o=start x=end)')
fig.tight_layout(); fig.savefig('kart/lap11_compare.png',dpi=120); print('saved lap11_compare.png')