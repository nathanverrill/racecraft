"""GPS+IMU fusion for karting trajectory.

Approach (see chat design):
  * Position/velocity: GPS-dominant ESKF, IMU (horizontal accel) used to
    propagate between 1 Hz GPS fixes -> smooth 100 Hz path.
  * RTS smoother: forward-backward pass for clean offline trace.
  * Heading-of-facing: separate channel from gravity-projected gyro yaw
    rate, anchored to course-over-ground during clean driving. The
    divergence between facing and course = spin/slide signature.

State (per 100 Hz step): [E, N, vE, vN]  (constant-velocity model,
acceleration as process input from gravity-compensated horizontal accel).
"""
import numpy as np
import pandas as pd
from scipy.interpolate import splprep, splev
from loaders import load_location, load_imu, to_enu, WINDOW_START, WINDOW_END


def gravity_projected_yaw_rate(imu):
    """Turn rate about the vertical (gravity) axis, independent of how the
    phone sits in the pocket. gyro . gravity_unit."""
    g = imu[["grx", "gry", "grz"]].values
    gyro = imu[["gx", "gy", "gz"]].values
    gnorm = np.linalg.norm(g, axis=1, keepdims=True)
    gunit = g / np.clip(gnorm, 1e-6, None)
    # gravity points 'down'; component of angular velocity about it = yaw rate.
    yaw_rate = -np.sum(gyro * gunit, axis=1)   # sign chosen so +ve = left turn (fixed later vs GPS)
    return yaw_rate


def horizontal_accel(imu):
    """Linear acceleration projected onto the horizontal plane, expressed in
    a heading-relative way is hard without good attitude; here we only use
    its MAGNITUDE lightly. We keep accel out of the position driver to stay
    robust during spins (design choice). Returns nothing used for now."""
    return None


def build_timeline(imu):
    t = imu.seconds_elapsed.values
    return t


def detect_zupt(imu, loc):
    """Detect moments the kart is (nearly) stopped -> zero-velocity updates.

    Two triggers:
      * Hard impact: raw accelerometer magnitude jolt (wall hit). After a
        big jolt the kart is momentarily stopped/very slow.
      * Low GPS speed: GPS reports speed < threshold (genuine crawl/stop).
    Returns a boolean mask over the IMU timeline where velocity ~ 0.
    """
    t = imu.seconds_elapsed.values

    # GPS speed interpolated onto IMU timeline
    gt = loc.seconds_elapsed.values
    gs = loc.speed.values.copy()
    gs[gs < 0] = np.nan                      # sentinel -1 -> unknown
    gspd = np.interp(t, gt, np.nan_to_num(gs, nan=0.0))

    # GPS speed is the reliable stop indicator (raw accel jolt is too noisy:
    # pocket vibration / kerbs produce big spikes everywhere). Stops at the
    # wall (t~608.8) and spin-recoveries (t~615.8) show clearly as GPS<1km/h.
    zupt = gspd < 0.6                        # < ~2 km/h -> truly stopped
    print(f"ZUPT (GPS-speed driven): {zupt.sum()} samples zeroed")
    return zupt


def eskf_smooth(loc, imu):
    """Constant-velocity Kalman filter on a 100 Hz grid with GPS position
    updates + zero-velocity updates (ZUPT) for stops/impacts, followed by an
    RTS smoother. GPS-dominant, spin-robust, and makes the kart physically
    stop at the wall.
    """
    t = imu.seconds_elapsed.values
    N = len(t)

    zupt = detect_zupt(imu, loc)

    lat0, lon0 = loc.latitude.iloc[0], loc.longitude.iloc[0]
    ge, gn = to_enu(loc.latitude.values, loc.longitude.values, lat0, lon0)
    gt = loc.seconds_elapsed.values
    gha = loc.horizontalAccuracy.values

    # State x = [E, N, vE, vN]
    x = np.zeros(4)
    x[0], x[1] = ge[0], gn[0]
    P = np.diag([5.0, 5.0, 5.0, 5.0]) ** 2

    # Process noise: acceleration random-walk. LOW value -> the CV model is
    # only used to interpolate smoothly *between* GPS fixes, not to smooth
    # away corners. GPS leads strongly; corners stay sharp.
    sigma_a = 2.0  # m/s^2 (tuned: keeps hairpins crisp, trace not 'lame')

    H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], float)

    xs = np.zeros((N, 4))
    Ps = np.zeros((N, 4, 4))
    Fs = np.zeros((N, 4, 4))

    gi = 0
    n_updates = 0
    for k in range(N):
        if k == 0:
            dt = t[1] - t[0]
        else:
            dt = t[k] - t[k - 1]
        dt = max(dt, 1e-3)

        F = np.array([[1, 0, dt, 0],
                      [0, 1, 0, dt],
                      [0, 0, 1, 0],
                      [0, 0, 0, 1]], float)
        # Q from acceleration random walk
        q = sigma_a ** 2
        Q = q * np.array([[dt**4/4, 0, dt**3/2, 0],
                          [0, dt**4/4, 0, dt**3/2],
                          [dt**3/2, 0, dt**2, 0],
                          [0, dt**3/2, 0, dt**2]], float)

        if k > 0:
            x = F @ x
            P = F @ P @ F.T + Q
        Fs[k] = F

        # GPS update if a fix falls at/just before this IMU step
        while gi < len(gt) and gt[gi] <= t[k] + 1e-9:
            z = np.array([ge[gi], gn[gi]])
            # Trust GPS hard: clamp reported accuracy down so fixes pull the
            # estimate tightly onto the measured path (sharp corners).
            r = np.clip(gha[gi], 1.5, 4.0) * 0.6
            R = np.diag([r, r]) ** 2
            y = z - H @ x
            S = H @ P @ H.T + R
            K = P @ H.T @ np.linalg.inv(S)
            x = x + K @ y
            P = (np.eye(4) - K @ H) @ P
            gi += 1
            n_updates += 1

        # Zero-velocity update: constrain vE,vN -> 0 when stopped/impacted.
        if zupt[k]:
            Hz = np.array([[0, 0, 1, 0], [0, 0, 0, 1]], float)
            Rz = np.diag([0.3, 0.3]) ** 2            # tight: really stopped
            yz = -Hz @ x
            Sz = Hz @ P @ Hz.T + Rz
            Kz = P @ Hz.T @ np.linalg.inv(Sz)
            x = x + Kz @ yz
            P = (np.eye(4) - Kz @ Hz) @ P

        xs[k] = x
        Ps[k] = P

    # ---- RTS smoother (backward pass) ----
    xsm = xs.copy()
    Psm = Ps.copy()
    for k in range(N - 2, -1, -1):
        F = Fs[k + 1]
        q = sigma_a ** 2
        dt = max(t[k + 1] - t[k], 1e-3)
        Q = q * np.array([[dt**4/4, 0, dt**3/2, 0],
                          [0, dt**4/4, 0, dt**3/2],
                          [dt**3/2, 0, dt**2, 0],
                          [0, dt**3/2, 0, dt**2]], float)
        Ppred = F @ Ps[k] @ F.T + Q
        C = Ps[k] @ F.T @ np.linalg.inv(Ppred)
        xsm[k] = xs[k] + C @ (xsm[k + 1] - F @ xs[k])
        Psm[k] = Ps[k] + C @ (Psm[k + 1] - Ppred) @ C.T

    print(f"Kalman GPS updates applied: {n_updates} / {len(gt)} fixes")
    return t, xsm, Psm, (lat0, lon0)


def gps_spline_path(loc, imu):
    """Path that PRESERVES the recognizable track shape (user: 'raw GPS shape
    was closest'). Fit a light smoothing spline through the raw GPS points
    (parameterized by GPS time) and sample at the 100 Hz IMU timeline.

    This keeps corner geometry (hairpins, top loop) sharp -- the dynamics
    Kalman was rounding them off. Jitter from 1 Hz GPS is removed by a small
    smoothing factor, not by a velocity model that fights corners.
    """
    lat0, lon0 = loc.latitude.iloc[0], loc.longitude.iloc[0]
    ge, gn = to_enu(loc.latitude.values, loc.longitude.values, lat0, lon0)
    gt = loc.seconds_elapsed.values
    t = imu.seconds_elapsed.values

    # smoothing factor ~ n * (GPS noise)^2 ; small -> follows GPS shape closely
    n = len(gt)
    s = n * (1.2 ** 2)          # ~1.2 m GPS noise budget -> de-jitter, keep shape
    tck, u = splprep([ge, gn], u=gt, s=s, k=3)
    # sample at IMU times, clipped to GPS span
    tt = np.clip(t, gt[0], gt[-1])
    E, Nn = splev(tt, tck)
    # velocity from spline derivative
    dE, dN = splev(tt, tck, der=1)
    return t, E, Nn, dE, dN, (lat0, lon0)


def run(path_mode="spline"):
    loc = load_location()
    imu = load_imu()

    if path_mode == "spline":
        # Path shape from GPS spline (recognizable track); speed from spline
        # derivative; ZUPT stops applied as a post-step on speed.
        t, E, Nn, vE, vN, anchor = gps_spline_path(loc, imu)
        zupt = detect_zupt(imu, loc)
        speed = np.hypot(vE, vN)
        speed[zupt] = 0.0                         # honor real stops
        course = np.degrees(np.arctan2(vE, vN)) % 360.0
    else:
        t, xs, Ps, anchor = eskf_smooth(loc, imu)
        E, Nn, vE, vN = xs[:, 0], xs[:, 1], xs[:, 2], xs[:, 3]
        speed = np.hypot(vE, vN)
        course = np.degrees(np.arctan2(vE, vN)) % 360.0

    # Facing channel: integrate gravity-projected yaw rate
    yaw_rate = gravity_projected_yaw_rate(imu)
    dt = np.diff(t, prepend=t[0])
    facing = np.cumsum(yaw_rate * dt)
    facing = np.degrees(facing)

    # Event channels for the replay
    acc_mag = np.sqrt(imu.ax.values**2 + imu.ay.values**2 + imu.az.values**2)
    out = pd.DataFrame({
        "seconds_elapsed": t,
        "E": E, "N": Nn, "vE": vE, "vN": vN,
        "speed": speed, "course_deg": course,
        "yaw_rate": yaw_rate, "facing_raw_deg": facing,
        "acc_mag": acc_mag,                      # raw jolt (impact detector)
    })
    out.to_csv("kart/fused_trace.csv", index=False)
    print("Wrote kart/fused_trace.csv with", len(out), "rows")
    print("Speed max km/h:", round(speed.max() * 3.6, 1))
    print("Track bbox m:", round(E.max() - E.min(), 1), "x", round(Nn.max() - Nn.min(), 1))
    return out


if __name__ == "__main__":
    run()