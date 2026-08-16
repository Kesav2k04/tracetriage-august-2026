"""Physics feasibility probe: can a SatNOGS observation's own stored TLE reproduce a Doppler corridor?

READ-ONLY RECON. This is not the production physics module.

Bob must not import this file into `pipeline/`. It exists to answer one question before
any modelling work starts: does the metadata stored on an observation record contain
enough information to place an expected-frequency corridor on the waterfall, and does
that corridor have a plausible shape and magnitude?

Run:  .venv/Scripts/python.exe scripts/recon/physics_feasibility.py
"""

from __future__ import annotations

import json
import math
import urllib.request
from datetime import datetime, timedelta, timezone

import numpy as np
from sgp4.api import Satrec, jday

UA = {"User-Agent": "TraceTriage-recon/0.1 (kesavk659@gmail.com)"}
API = "https://network.satnogs.org/api/observations/?format=json&end=2026-07-15T00:00:00Z"
C = 299_792_458.0  # m/s
WGS84_A = 6378.137  # km
WGS84_F = 1.0 / 298.257223563


def station_ecef(lat_deg: float, lon_deg: float, alt_m: float) -> np.ndarray:
    """Geodetic station position in ECEF kilometres."""
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    e2 = WGS84_F * (2 - WGS84_F)
    n = WGS84_A / math.sqrt(1 - e2 * math.sin(lat) ** 2)
    alt_km = alt_m / 1000.0
    return np.array(
        [
            (n + alt_km) * math.cos(lat) * math.cos(lon),
            (n + alt_km) * math.cos(lat) * math.sin(lon),
            (n * (1 - e2) + alt_km) * math.sin(lat),
        ]
    )


def gmst(dt: datetime) -> float:
    """Greenwich mean sidereal time in radians (adequate for a feasibility check)."""
    jd = (
        dt.replace(tzinfo=timezone.utc) - datetime(2000, 1, 1, 12, tzinfo=timezone.utc)
    ).total_seconds() / 86400.0
    return (math.radians(280.46061837 + 360.98564736629 * jd)) % (2 * math.pi)


def eci_to_ecef(v: np.ndarray, dt: datetime) -> np.ndarray:
    t = gmst(dt)
    ct, st = math.cos(t), math.sin(t)
    return np.array([ct * v[0] + st * v[1], -st * v[0] + ct * v[1], v[2]])


def fetch_candidate() -> dict:
    req = urllib.request.Request(API, headers=UA)
    for obs in json.loads(urllib.request.urlopen(req, timeout=60).read()):
        if (
            obs.get("tle1")
            and obs.get("tle2")
            and obs.get("waterfall")
            and obs.get("waterfall_status") == "with-signal"
            and obs.get("client_metadata")
        ):
            return obs
    raise SystemExit("no suitable observation on the first page; widen the window")


def main() -> None:
    obs = fetch_candidate()
    print(f"observation      {obs['id']}  ({obs['waterfall_status']})")
    print(f"satellite        NORAD {obs['norad_cat_id']}  {obs['tle0'].strip()}")
    print(f"station          {obs['ground_station']} @ "
          f"{obs['station_lat']}, {obs['station_lng']}, {obs['station_alt']} m")

    meta = json.loads(obs["client_metadata"])
    params = meta.get("radio", {}).get("parameters", {})
    rx_freq = float(params.get("rx-freq") or obs["observation_frequency"])
    samp_rate = float(params.get("samp-rate-rx") or 0)
    print(f"client           {meta.get('radio', {}).get('name')} "
          f"{meta.get('radio', {}).get('version')}")
    print(f"rx-freq          {rx_freq:,.0f} Hz")
    print(f"samp-rate-rx     {samp_rate:,.0f} Hz")
    print(f"doppler-corr/sec {params.get('doppler-correction-per-sec')!r}")
    print(f"rigctl-port      {params.get('rigctl-port')!r}")

    sat = Satrec.twoline2rv(obs["tle1"], obs["tle2"])
    start = datetime.fromisoformat(obs["start"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(obs["end"].replace("Z", "+00:00"))
    duration = (end - start).total_seconds()
    site = station_ecef(obs["station_lat"], obs["station_lng"], obs["station_alt"])

    print(f"\npass             {start.isoformat()} -> {end.isoformat()}  ({duration:.0f} s)")
    print(f"reported         max_altitude {obs['max_altitude']} deg, "
          f"az {obs['rise_azimuth']} -> {obs['set_azimuth']}")

    rows = []
    for i in range(41):
        t = start + timedelta(seconds=duration * i / 40)
        jd, fr = jday(t.year, t.month, t.day, t.hour, t.minute, t.second + t.microsecond / 1e6)
        err, r_eci, v_eci = sat.sgp4(jd, fr)
        if err != 0:
            print(f"  SGP4 error {err} at {t}")
            return
        r_ecef = eci_to_ecef(np.array(r_eci), t)
        v_ecef = eci_to_ecef(np.array(v_eci), t)
        # earth rotation contribution to the topocentric velocity
        omega = 7.2921159e-5
        v_ecef = v_ecef - np.cross(np.array([0, 0, omega]), r_ecef)

        los = r_ecef - site
        rng = float(np.linalg.norm(los))
        range_rate = float(np.dot(los / rng, v_ecef))  # km/s, + = receding
        up = site / np.linalg.norm(site)
        elev = math.degrees(math.asin(float(np.dot(los / rng, up))))
        doppler_hz = -range_rate * 1000.0 / C * rx_freq
        rows.append((i / 40, elev, rng, range_rate, doppler_hz))

    elevs = [r[1] for r in rows]
    dopps = [r[4] for r in rows]
    print(f"\ncomputed         peak elevation {max(elevs):+.1f} deg "
          f"(API says {obs['max_altitude']})")
    print(f"                 elevation at start/end: {elevs[0]:+.1f} / {elevs[-1]:+.1f} deg")
    print(f"doppler swing    {min(dopps):+,.0f} Hz to {max(dopps):+,.0f} Hz "
          f"(total {max(dopps) - min(dopps):,.0f} Hz)")
    if samp_rate:
        print(f"                 = {(max(dopps) - min(dopps)) / samp_rate * 100:.2f}% "
              f"of the {samp_rate:,.0f} Hz sample rate")

    print("\n  frac   elev(deg)   range(km)   range_rate(km/s)   doppler(Hz)")
    for frac, elev, rng, rr, dop in rows[::5]:
        print(f"  {frac:4.2f}   {elev:+8.2f}   {rng:9.1f}   {rr:+16.4f}   {dop:+11.0f}")

    peak_err = abs(max(elevs) - float(obs["max_altitude"]))
    print(f"\nVERDICT")
    print(f"  peak-elevation agreement with API: {peak_err:.2f} deg error")
    if peak_err < 2.0:
        print("  PASS  stored TLE + station coords reproduce the pass geometry.")
    else:
        print("  CHECK disagreement above 2 deg: inspect the GMST/frame handling.")
    print("  The Doppler swing above is the width the corrected corridor must account for.")
    print("  It does NOT prove the waterfall is corrected. That is a separate test on the image.")


if __name__ == "__main__":
    main()
