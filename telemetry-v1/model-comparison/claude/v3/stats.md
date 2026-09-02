# Sensor Logger session stats

`v3`

## Sensors
| file | rows | duration (s) | rate (Hz) | columns |
|---|---|---|---|---|
| Accelerometer.csv | 218,218 | 2194 | 99.5 | z, y, x |
| AccelerometerUncalibrated.csv | 218,222 | 2194 | 99.5 | z, y, x |
| Compass.csv | 218,218 | 2194 | 99.5 | magneticBearing |
| Gravity.csv | 218,218 | 2194 | 99.5 | z, y, x |
| Gyroscope.csv | 218,218 | 2194 | 99.5 | z, y, x |
| GyroscopeUncalibrated.csv | 218,222 | 2194 | 99.5 | z, y, x |
| HeadMotion.csv | 50,095 | 2096 | 50.0 | roll, rotationRateZ, quaternionY, rotationRateY, quaternionZ, quaternionW, yaw, devicelocation, accelerationZ, pitch, gravityX, gravityZ, quaternionX, rotationRateX, accelerationX, gravityY, accelerationY |
| Location.csv | 2,197 | 2239 | 1.0 | altitude, speedAccuracy, bearingAccuracy, latitude, altitudeAboveMeanSeaLevel, bearing, horizontalAccuracy, verticalAccuracy, longitude, speed |
| Magnetometer.csv | 218,218 | 2194 | 99.5 | z, y, x |
| MagnetometerUncalibrated.csv | 217,807 | 2194 | 99.2 | z, y, x |
| Metadata.csv | 1 | — | — | version, device name, recording epoch time, recording time, recording timezone, platform, appVersion, device id, sensors, sampleRateMs, standardisation, platform version |
| Microphone.csv | 21,036 | 2194 | 9.5 | dBFS |
| Orientation.csv | 218,218 | 2194 | 99.5 | yaw, qx, qz, roll, qw, qy, pitch |

## GPS / track summary
- GPS fixes: **2197**  (pre-fix lat/lon=0 rows: 0)
- bounding box: **869 m × 0 m**  (centre 38.65000, -90.14000)
- GPS speed (mph): median 23.1 · p90 37.4 · p99 42.2 · p99.9 42.7 · **max 43.2**
- implausible-speed fixes (>130 mph, treated as glitches): **0**
- horizontal accuracy (m): median 4.6 · p90 6.7 · p99 11.6
- driving fraction (speed>4 mph-ish): **63%** of fixes
- estimated laps (revolutions while driving): **≈ 0.0**
- recording gaps >30 s: none

## Metadata
- **version**: 3
- **device name**: iPhone 17 Pro Max
- **recording epoch time**: 1782421356199
- **recording time**: 2026-06-25_21-02-36
- **recording timezone**: America/Chicago
- **platform**: ios
- **appVersion**: 1.60.1
- **device id**: 835c60c0-e0e0-49b1-90b2-1071684070d5
- **sensors**: Accelerometer|Gravity|Gyroscope|Orientation|Magnetometer|Compass|Barometer|Location|Heart Rate|Wrist Motion|Watch Location|Watch Barometer|Watch Magnetometer|Watch Compass|Microphone|Pedometer|Activity|Headphone|Annotation|MagnetometerUncalibrated|GyroscopeUncalibrated|AccelerometerUncalibrated
- **sampleRateMs**: 10|10|10|10|10|10|0|0|10|10|10|10|10|10|100|10|0|10||10|10|10
- **standardisation**: False
- **platform version**: 26.5.1

## Value ranges
### Accelerometer.csv
| column | min | max | mean | std | median |
|---|---|---|---|---|---|
| z | -71.93 | 57.67 | -0.11 | 4.12 | -0.02 |
| y | -59.33 | 47.37 | -0.24 | 3.98 | -0.01 |
| x | -48.93 | 66.61 | -1.10 | 6.19 | -0.16 |

### AccelerometerUncalibrated.csv
| column | min | max | mean | std | median |
|---|---|---|---|---|---|
| z | -6.96 | 6.85 | 0.64 | 0.58 | 0.73 |
| y | -6.20 | 5.72 | 0.05 | 0.67 | -0.11 |
| x | -4.90 | 7.35 | 0.19 | 0.71 | 0.16 |

### Compass.csv
| column | min | max | mean | std | median |
|---|---|---|---|---|---|
| magneticBearing | 0.00 | 360.00 | 174.44 | 113.14 | 167.27 |

### Gravity.csv
| column | min | max | mean | std | median |
|---|---|---|---|---|---|
| z | -9.80 | 9.77 | 6.37 | 3.77 | 8.36 |
| y | -7.68 | 9.81 | 0.77 | 5.00 | -1.60 |
| x | -6.34 | 9.46 | 2.93 | 2.68 | 3.90 |

### Gyroscope.csv
| column | min | max | mean | std | median |
|---|---|---|---|---|---|
| z | -10.34 | 6.92 | -0.10 | 0.69 | -0.02 |
| y | -10.03 | 12.12 | 0.03 | 0.86 | 0.01 |
| x | -6.86 | 4.89 | -0.01 | 0.71 | 0.00 |

### GyroscopeUncalibrated.csv
| column | min | max | mean | std | median |
|---|---|---|---|---|---|
| z | -10.43 | 6.91 | -0.10 | 0.69 | -0.02 |
| y | -9.96 | 12.92 | 0.03 | 0.86 | 0.01 |
| x | -6.90 | 5.37 | -0.01 | 0.71 | 0.00 |

### HeadMotion.csv
| column | min | max | mean | std | median |
|---|---|---|---|---|---|
| roll | -3.13 | 3.14 | -0.04 | 0.48 | 0.04 |
| rotationRateZ | -40.07 | 12.65 | 0.09 | 0.70 | 0.05 |
| quaternionY | -0.90 | 0.86 | -0.06 | 0.22 | -0.08 |
| rotationRateY | -27.56 | 16.71 | -0.06 | 0.68 | -0.03 |
| quaternionZ | -1.00 | 1.00 | 0.11 | 0.61 | 0.19 |
| quaternionW | -1.00 | 1.00 | 0.37 | 0.61 | 0.64 |
| yaw | -3.14 | 3.14 | 0.04 | 1.64 | 0.16 |
| accelerationZ | -2.90 | 1.24 | -0.16 | 0.34 | -0.05 |
| pitch | -1.48 | 1.31 | -0.40 | 0.29 | -0.42 |
| gravityX | -9.68 | 7.85 | -0.22 | 3.50 | 0.28 |
| gravityZ | -9.81 | 7.70 | -7.81 | 1.82 | -8.41 |
| quaternionX | -0.73 | 0.79 | -0.08 | 0.21 | -0.11 |
| rotationRateX | -28.74 | 18.45 | 0.08 | 0.60 | 0.04 |
| accelerationX | -2.66 | 4.80 | 0.06 | 0.54 | 0.00 |
| gravityY | -9.47 | 9.77 | 3.64 | 2.52 | 4.01 |
| accelerationY | -11.67 | 6.96 | 0.01 | 0.28 | 0.01 |

### Location.csv
| column | min | max | mean | std | median |
|---|---|---|---|---|---|
| altitude | 0.00 | 96.02 | 92.23 | 2.12 | 92.15 |
| speedAccuracy | -1.00 | 2.72 | 0.71 | 0.39 | 0.64 |
| bearingAccuracy | -1.00 | 180.00 | 56.10 | 75.45 | 7.26 |
| latitude | 38.65 | 38.65 | 38.65 | 0.00 | 38.65 |
| altitudeAboveMeanSeaLevel | 121.11 | 128.13 | 124.39 | 0.79 | 124.27 |
| bearing | -1.00 | 359.70 | 169.78 | 103.23 | 170.29 |
| horizontalAccuracy | 2.00 | 19.32 | 4.64 | 2.02 | 4.59 |
| verticalAccuracy | 3.00 | 33.21 | 4.18 | 2.23 | 3.12 |
| longitude | -90.14 | -90.13 | -90.14 | 0.00 | -90.14 |
| speed | -1.00 | 19.33 | 8.31 | 6.67 | 10.32 |

### Magnetometer.csv
| column | min | max | mean | std | median |
|---|---|---|---|---|---|
| z | -1698.42 | 2048.11 | 18.83 | 30.15 | 20.69 |
| y | -1486.04 | 3211.89 | 8.15 | 42.13 | 5.95 |
| x | -3155.06 | 1393.93 | -5.59 | 40.56 | -3.11 |

### MagnetometerUncalibrated.csv
| column | min | max | mean | std | median |
|---|---|---|---|---|---|
| z | -42.68 | 332.57 | 172.45 | 30.99 | 172.91 |
| y | 455.26 | 968.01 | 638.09 | 69.40 | 616.69 |
| x | -1026.75 | -457.36 | -597.90 | 50.43 | -590.44 |

### Microphone.csv
| column | min | max | mean | std | median |
|---|---|---|---|---|---|
| dBFS | -120.00 | -1.43 | -21.80 | 8.89 | -18.86 |

### Orientation.csv
| column | min | max | mean | std | median |
|---|---|---|---|---|---|
| yaw | -3.14 | 3.14 | 0.47 | 1.74 | 0.84 |
| qx | -1.00 | 1.00 | 0.03 | 0.62 | 0.15 |
| qz | -0.81 | 0.81 | 0.07 | 0.33 | 0.09 |
| roll | -3.14 | 3.14 | 1.78 | 1.72 | 2.63 |
| qw | -0.98 | 0.80 | -0.02 | 0.25 | 0.00 |
| qy | -0.98 | 0.99 | 0.02 | 0.66 | 0.07 |
| pitch | -1.57 | 0.90 | -0.16 | 0.66 | 0.16 |
