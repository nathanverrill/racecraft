import numpy as np, pandas as pd, matplotlib
matplotlib.use('Agg'); import matplotlib.pyplot as plt
df = pd.read_csv('clipped/fused_trace.csv')
b = np.load('clipped/lap_bounds_race.npy')
t = df.seconds_elapsed_race.values

def seg(i):
    m = (t >= b[i,0]) & (t <= b[i,1])
    return df.E[m].values, df.N[m].values

fig, ax = plt.subplots(figsize=(8, 12))
# faint full session for context
ax.plot(df.E, df.N, color='0.88', lw=0.4, zorder=1)

E11, N11 = seg(10)   # lap 11 (best)
E12, N12 = seg(11)   # lap 12 (the spin lap - continuation)

ax.plot(E11, N11, color='red', lw=2.4, zorder=3, label='lap 11 (best, 40.53s)')
ax.plot(E12, N12, color='tab:blue', lw=2.0, zorder=2, label='lap 12 (next, 53.76s spin)')

# start/end markers
ax.plot(E11[0], N11[0], 'o', color='red', ms=12, zorder=5, label='lap11 START')
ax.plot(E11[-1], N11[-1], 's', color='darkred', ms=12, zorder=5, label='lap11 END = lap12 start')
ax.plot(E12[-1], N12[-1], 's', color='navy', ms=12, zorder=5, label='lap12 END')

ax.plot(12, -12, 'k+', ms=18, mew=2, zorder=6, label='start/finish gate')
ax.set_aspect('equal'); ax.legend(fontsize=9, loc='upper left')
ax.set_title('Lap 11 (red) -> Lap 12 (blue) continuation')
fig.tight_layout(); fig.savefig('kart/lap11_12.png', dpi=120)
print('lap11 start', (round(E11[0],1), round(N11[0],1)), 'end', (round(E11[-1],1), round(N11[-1],1)))
print('lap12 start', (round(E12[0],1), round(N12[0],1)), 'end', (round(E12[-1],1), round(N12[-1],1)))
print('saved lap11_12.png')