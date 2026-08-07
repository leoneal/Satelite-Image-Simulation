"""
Convert 轨道2.xlsx to standard ephemeris CSV format.

Input: 轨道2.xlsx (22 columns, 200 Hz, distance < 1000 km)
Output: output/ephemeris_v2/ (observer_state.csv, target_state.csv, sun_state.csv,
         aux_data.csv, scene_config.json)

No MATLAB dependency — kepler2cart and Meeus sun position ported to Python.
"""

import os, math, csv, json, argparse
import numpy as np
import openpyxl
from datetime import datetime, timezone

MU = 3.986004418e14  # GM Earth (m^3/s^2)
KM_SCALE = 0.001


def kepler2cart(a, e, inc, raan, argp, nu):
    """Convert Keplerian elements to ECI position (m) and velocity (m/s).
    Direct port of matlab/+stk_helpers/kepler2cart.m — uses pre-computed
    rotation matrix R = Rz(-raan)*Rx(-inc)*Rz(-argp)."""
    p = a * (1.0 - e * e)
    denom = 1.0 + e * math.cos(nu)
    r_pf_x = p * math.cos(nu) / denom
    r_pf_y = p * math.sin(nu) / denom
    h = math.sqrt(MU * p)
    v_pf_x = -h / p * math.sin(nu)
    v_pf_y = h / p * (e + math.cos(nu))

    # Rotation matrix elements (exact MATLAB formula)
    co = math.cos(raan); so = math.sin(raan)
    ci = math.cos(inc);  si = math.sin(inc)
    cw = math.cos(argp); sw = math.sin(argp)

    R11 = co * cw - so * sw * ci
    R12 = -co * sw - so * cw * ci
    R21 = so * cw + co * sw * ci
    R22 = -so * sw + co * cw * ci
    R31 = sw * si
    R32 = cw * si

    r = np.array([R11 * r_pf_x + R12 * r_pf_y,
                   R21 * r_pf_x + R22 * r_pf_y,
                   R31 * r_pf_x + R32 * r_pf_y])
    v = np.array([R11 * v_pf_x + R12 * v_pf_y,
                   R21 * v_pf_x + R22 * v_pf_y,
                   R31 * v_pf_x + R32 * v_pf_y])
    return r, v


def compute_sun_position_eci(jd):
    """Compute Sun position in ECI (J2000 equatorial) using Meeus algorithm.
    Ported from matlab/+stk_helpers/exportAllEphemeris.m.
    Returns position in meters."""
    T = (jd - 2451545.0) / 36525.0
    # Mean anomaly of Sun
    M = math.radians((357.5291 + 35999.0503 * T) % 360.0)
    # Equation of center
    C = math.radians((1.9148 * math.sin(M) + 0.0200 * math.sin(2*M) + 0.0003 * math.sin(3*M)))
    # Ecliptic longitude
    L0 = math.radians((280.4665 + 36000.7698 * T) % 360.0)
    lon_ecl = L0 + C
    # Obliquity of ecliptic
    eps = math.radians(23.4393 - 0.0130 * T)
    # Sun distance in AU
    ecc = 0.0167086 - 0.00004204 * T
    R_au = 1.00014 * (1.0 - ecc * ecc) / (1.0 + ecc * math.cos(M + C))
    R_m = R_au * 149597870700.0  # AU to meters
    # Ecliptic to equatorial (J2000)
    sx = R_m * math.cos(lon_ecl)
    sy = R_m * math.sin(lon_ecl) * math.cos(eps)
    sz = R_m * math.sin(lon_ecl) * math.sin(eps)
    return np.array([sx, sy, sz])


def parse_timestamp(ts_str):
    """Parse '20 Mar 2029 23:44:40.000000000' to datetime."""
    # Strip nanoseconds, parse up to microseconds
    parts = ts_str.strip().split('.')
    dt_part = parts[0]
    # Parse main datetime
    dt = datetime.strptime(dt_part, '%d %b %Y %H:%M:%S')
    # Add microseconds if present
    if len(parts) > 1:
        ns_str = parts[1].rstrip('0')  # remove trailing zeros
        if ns_str:
            dt = dt.replace(microsecond=int(ns_str[:6].ljust(6, '0')))
    return dt.replace(tzinfo=timezone.utc)


def datetime_to_jd(dt):
    """Convert datetime to Julian Date."""
    # Formula from Meeus
    Y = dt.year
    M = dt.month
    D = dt.day + dt.hour/24.0 + dt.minute/1440.0 + dt.second/86400.0 + dt.microsecond/86400000000.0
    if M <= 2:
        Y -= 1
        M += 12
    A = int(Y / 100)
    B = 2 - A + int(A / 4)
    JD = int(365.25 * (Y + 4716)) + int(30.6001 * (M + 1)) + D + B - 1524.5
    return JD


def main(input_path, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    print(f'Reading {input_path}...')
    wb = openpyxl.load_workbook(input_path, read_only=True, data_only=True)
    ws = wb.active

    obs_pos, obs_vel, obs_quat = [], [], []
    tgt_pos, tgt_vel, tgt_quat = [], [], []
    sun_positions = []
    aux_data = []
    times = []
    timestamps = []

    row_count = 0
    start = datetime.now(timezone.utc)
    for row in ws.iter_rows(min_row=2, values_only=True):
        ts_str = row[0]
        obs_a = float(row[1]); obs_e = float(row[2]); obs_i = float(row[3])
        obs_omega = float(row[4]); obs_w = float(row[5]); obs_f = float(row[6])
        obs_q1 = float(row[7]); obs_q2 = float(row[8]); obs_q3 = float(row[9]); obs_q4 = float(row[10])
        tgt_a = float(row[11]); tgt_e = float(row[12]); tgt_i = float(row[13])
        tgt_omega = float(row[14]); tgt_w = float(row[15]); tgt_f = float(row[16])
        tgt_q1 = float(row[17]); tgt_q2 = float(row[18]); tgt_q3 = float(row[19]); tgt_q4 = float(row[20])
        dist_km = float(row[21])

        # Kepler -> ECI
        o_r, o_v = kepler2cart(obs_a, obs_e, obs_i, obs_omega, obs_w, obs_f)
        t_r, t_v = kepler2cart(tgt_a, tgt_e, tgt_i, tgt_omega, tgt_w, tgt_f)

        obs_pos.append(o_r); obs_vel.append(o_v)
        tgt_pos.append(t_r); tgt_vel.append(t_v)
        obs_quat.append([obs_q1, obs_q2, obs_q3, obs_q4])
        tgt_quat.append([tgt_q1, tgt_q2, tgt_q3, tgt_q4])

        # Sun position
        try:
            dt = parse_timestamp(ts_str)
        except ValueError:
            dt = start  # fallback
        jd = datetime_to_jd(dt)
        sun_pos = compute_sun_position_eci(jd)
        sun_positions.append(sun_pos)

        # Aux data
        rel_vel = np.linalg.norm(o_v - t_v)
        obs_to_tgt = t_r - o_r
        tgt_to_sun = sun_pos - t_r
        cos_phase = np.dot(obs_to_tgt, tgt_to_sun) / (np.linalg.norm(obs_to_tgt) * np.linalg.norm(tgt_to_sun))
        sun_phase = math.degrees(math.acos(max(-1, min(1, cos_phase))))

        aux_data.append([dist_km, rel_vel, sun_phase])
        times.append(row_count / 200.0)  # 200 Hz → seconds from start
        timestamps.append(ts_str)

        row_count += 1
        if row_count % 50000 == 0:
            print(f'  Processed {row_count} rows...')

    print(f'Total: {row_count} rows')

    # Write observer_state.csv
    with open(os.path.join(output_dir, 'observer_state.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['time_epoch_sec', 'pos_x_m', 'pos_y_m', 'pos_z_m',
                     'vel_x_ms', 'vel_y_ms', 'vel_z_ms', 'qx', 'qy', 'qz', 'qw'])
        for i in range(row_count):
            w.writerow([times[i],
                        obs_pos[i][0], obs_pos[i][1], obs_pos[i][2],
                        obs_vel[i][0], obs_vel[i][1], obs_vel[i][2],
                        obs_quat[i][0], obs_quat[i][1], obs_quat[i][2], obs_quat[i][3]])

    # Write target_state.csv
    with open(os.path.join(output_dir, 'target_state.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['time_epoch_sec', 'pos_x_m', 'pos_y_m', 'pos_z_m',
                     'vel_x_ms', 'vel_y_ms', 'vel_z_ms', 'qx', 'qy', 'qz', 'qw'])
        for i in range(row_count):
            w.writerow([times[i],
                        tgt_pos[i][0], tgt_pos[i][1], tgt_pos[i][2],
                        tgt_vel[i][0], tgt_vel[i][1], tgt_vel[i][2],
                        tgt_quat[i][0], tgt_quat[i][1], tgt_quat[i][2], tgt_quat[i][3]])

    # Write sun_state.csv
    with open(os.path.join(output_dir, 'sun_state.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['time_epoch_sec', 'pos_x_m', 'pos_y_m', 'pos_z_m'])
        for i in range(row_count):
            w.writerow([times[i], sun_positions[i][0], sun_positions[i][1], sun_positions[i][2]])

    # Write aux_data.csv
    with open(os.path.join(output_dir, 'aux_data.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['time_epoch_sec', 'rel_dist_km', 'rel_vel_ms', 'sun_phase_deg'])
        for i in range(row_count):
            w.writerow([times[i], aux_data[i][0], aux_data[i][1], aux_data[i][2]])

    # Write scene_config.json
    config = {
        'scenario_name': 'SatelliteRendezvous_v2',
        'start_time': str(datetime.now(timezone.utc)),
        'stop_time': str(datetime.now(timezone.utc)),
        'time_step_sec': 0.005,  # 200 Hz
        'num_frames': row_count,
        'observer_name': 'ObserverSat',
        'target_name': 'TargetSat',
        'sensor_fov_deg': 0.08,
        'coordinate_system': 'J2000 ECI',
        'units': 'meters, seconds',
        'data_source': '轨道2.xlsx',
    }
    with open(os.path.join(output_dir, 'scene_config.json'), 'w') as f:
        json.dump(config, f, indent=2)

    print(f'\nOutput: {output_dir}/')
    print(f'  observer_state.csv: {row_count} frames')
    print(f'  target_state.csv: {row_count} frames')
    print(f'  sun_state.csv: {row_count} frames')
    print(f'  aux_data.csv: {row_count} frames')
    print(f'  scene_config.json')
    print(f'Distance range: {min(d for d,_,_ in aux_data):.1f} - {max(d for d,_,_ in aux_data):.1f} km')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True, help='Path to 轨道2.xlsx')
    parser.add_argument('--output', required=True, help='Output directory for CSV files')
    args = parser.parse_args()
    main(args.input, args.output)
