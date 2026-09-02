import csv, statistics

rows = list(csv.DictReader(open('Location.csv')))
print('total loc rows', len(rows))
se = [float(r['seconds_elapsed']) for r in rows]
print('se range', round(se[0], 2), round(se[-1], 2))

win = [r for r in rows if 56 <= float(r['seconds_elapsed']) <= 845]
print('loc rows in window', len(win))

wse = [float(r['seconds_elapsed']) for r in win]
dts = [wse[i+1] - wse[i] for i in range(len(wse)-1)]
print('GPS dt median', round(statistics.median(dts), 3),
      'min', round(min(dts), 3), 'max', round(max(dts), 3))

sp = [float(r['speed']) for r in win]
ha = [float(r['horizontalAccuracy']) for r in win]
print('speed min/max (m/s)', round(min(sp), 2), round(max(sp), 2))
print('speed max km/h', round(max(sp) * 3.6, 1))
print('horizAcc min/max/med', min(ha), max(ha), statistics.median(ha))
print('neg-speed rows in window', sum(1 for r in win if float(r['speed']) < 0))
print('neg-bearing rows in window', sum(1 for r in win if float(r['bearing']) < 0))

lat = [float(r['latitude']) for r in win]
lon = [float(r['longitude']) for r in win]
print('lat range', min(lat), max(lat))
print('lon range', min(lon), max(lon))