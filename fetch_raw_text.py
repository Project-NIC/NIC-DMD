"""
NIC DMD — Raw Text Benchmark
=============================
Stáhne data přesně jak je posílají zdrojové agentury a zkomprimuje je
bez jakýchkoliv úprav — surový JSON/CSV text jako bajty.

Jeden časový záznam = jeden paket. Padding nulami na pevnou délku.
Délka paketu se určí automaticky z prvního záznamu.

Závislosti: pip install requests
"""

import os
import sys
import math
import time
import csv
import zipfile
import io
import json
import requests
from nic_dmd_utils import dmd_analyze_packets as analyze_packets, dmd_print_summary as print_summary

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'NIC-DMD-Raw/1.0'})

OUTPUT_DIR = "real_data_raw"
os.makedirs(OUTPUT_DIR, exist_ok=True)


def safe_float(v, default=0.0):
    try:
        f = float(v)
        return default if math.isnan(f) or math.isinf(f) else f
    except:
        return default


def save_report(results, filename):
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, 'w', encoding='utf-8') as f:
        old = sys.stdout
        sys.stdout = f
        try:
            print_summary(results)
        finally:
            sys.stdout = old
    print(f"  Report: {path}")


def to_packet(text: str, pkt_len: int) -> bytes:
    """Převede text na bajty, ořeže nebo doplní nulami na pkt_len."""
    raw = text.encode('utf-8')
    if len(raw) >= pkt_len:
        return raw[:pkt_len]
    return raw + bytes(pkt_len - len(raw))


def detect_pkt_len(samples: list[str]) -> int:
    """Zjistí délku paketu z prvních vzorků — zaokrouhlí nahoru na násobek 8."""
    if not samples:
        return 64
    avg = sum(len(s.encode('utf-8'))
              for s in samples[:10]) // min(10, len(samples))
    # Zaokrouhli nahoru na násobek 8, max 255
    pkt_len = min(255, ((avg + 15) // 8) * 8)
    return max(8, pkt_len)

# ---------------------------------------------------------------------------
# 1. DWD SYNOP — raw CSV řádky
# ---------------------------------------------------------------------------


DWD_STATIONS = {
    '00691': 'Zugspitze',
    '05792': 'Fichtelberg',
    '01975': 'Helgoland',
}


def fetch_dwd_raw(station_id='00691', limit=10000):
    name = DWD_STATIONS.get(station_id, station_id)
    print(f"\n[DWD raw] {name} ({station_id})")
    base = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/10_minutes/air_temperature/recent/"
    url = base + f"10minutenwerte_TU_{station_id}_akt.zip"
    try:
        r = SESSION.get(url, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"  CHYBA: {e}")
        return [], []

    try:
        z = zipfile.ZipFile(io.BytesIO(r.content))
        names = z.namelist()
        print(f"  ZIP obsah: {names}")
        candidates = [f for f in names if f.startswith('produkt_')]
        if not candidates:
            candidates = [f for f in names if f.endswith('.txt')]
        if not candidates:
            candidates = names
        if not candidates:
            print(f"  CHYBA: ZIP je prázdný")
            return [], []
        df = candidates[0]
        content = z.read(df).decode('latin-1')
    except Exception as e:
        print(f"  CHYBA rozbalování: {e}")
        return [], []

    lines = content.strip().split('\n')
    print(f"  lines count: {len(lines)}")
    print(f"  lines[0]: {repr(lines[0])}")
    print(f"  lines[1]: {repr(lines[1]) if len(lines) > 1 else 'NENI'}")
    l = lines[1]
    print(repr(l.strip()))
    print(l.strip().endswith(';eor'))
    data_lines = [l.strip().removesuffix(';eor') for l in lines[1:] if l.strip()]
    print(f"  data_lines count: {len(data_lines)}")
    print(f"  prvni radek: {data_lines[0] if data_lines else 'PRAZDNE'}")
    pkt_len = detect_pkt_len(data_lines[:10])
    print(
        f"  Délka paketu: {pkt_len}B (z CSV řádku ~{len(data_lines[0].encode())}B)")

    packets = []
    timestamps = []
    for line in data_lines[:limit]:
        if not line:
            continue
        parts = line.split(';')
        ts = parts[0].strip() if parts else str(len(packets))
        packets.append(to_packet(line, pkt_len))
        timestamps.append(ts)

    print(f"  Načteno {len(packets)} vzorků × {pkt_len}B (raw CSV)")
    return packets, timestamps
# ---------------------------------------------------------------------------
# 2. Open-Meteo — raw JSON záznamy po jednom časovém kroku
# ---------------------------------------------------------------------------


FORECAST_LOCATIONS = [
    ('Praha',      50.0755, 14.4378),
    ('Brno',       49.1951, 16.6068),
    ('Ostrava',    49.8209, 18.2625),
    ('Bratislava', 48.1486, 17.1077),
]


def fetch_meteo_raw(lat, lon, name, limit=10000):
    print(f"\n[Open-Meteo raw] {name}")
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude":        lat,
        "longitude":       lon,
        "hourly":          ",".join([
            "temperature_2m", "relative_humidity_2m", "surface_pressure",
            "wind_speed_10m", "wind_direction_10m", "precipitation",
            "dew_point_2m",   "apparent_temperature",
        ]),
        "forecast_days":   16,
        "timezone":        "UTC",
        "wind_speed_unit": "ms",
    }
    try:
        r = SESSION.get(url, params=params, timeout=20)
        r.raise_for_status()
        h = r.json()["hourly"]
    except Exception as e:
        print(f"  CHYBA: {e}")
        return [], []

    keys = [k for k in h.keys() if k != 'time']
    n = min(limit, len(h.get('time', [])))

    # Sestavení raw JSON záznamu pro každý časový krok
    samples = []
    for i in range(min(10, n)):
        rec = {k: h[k][i] for k in keys if i < len(h.get(k, []))}
        samples.append(json.dumps(rec, separators=(',', ':')))

    pkt_len = detect_pkt_len(samples)
    print(
        f"  Délka paketu: {pkt_len}B (z JSON záznamu ~{len(samples[0].encode())}B)")

    packets = []
    timestamps = []
    for i in range(n):
        rec = {k: h[k][i] for k in keys if i < len(h.get(k, []))}
        raw = json.dumps(rec, separators=(',', ':'))
        packets.append(to_packet(raw, pkt_len))
        timestamps.append(h['time'][i] if i < len(
            h.get('time', [])) else str(i))

    print(f"  Načteno {len(packets)} vzorků × {pkt_len}B (raw JSON)")
    return packets, timestamps

# ---------------------------------------------------------------------------
# 3. NOAA Tides — raw JSON záznamy
# ---------------------------------------------------------------------------


NOAA_STATIONS = {
    '8518750': 'New_York',
    '9414290': 'San_Francisco',
}


def fetch_noaa_raw(station='8518750', limit=10000):
    from datetime import datetime, timedelta
    name = NOAA_STATIONS.get(station, station)
    print(f"\n[NOAA Tides raw] {name} ({station})")

    end = datetime.utcnow()
    start = end - timedelta(days=365)
    url = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"

    raw_list = []
    timestamps = []
    cur = start
    first_sample = None

    while cur < end and len(raw_list) < limit:
        nxt = min(cur + timedelta(days=30), end)
        params = {
            "station":     station,
            "product":     "hourly_height",
            "datum":       "MLLW",
            "time_zone":   "GMT",
            "units":       "metric",
            "application": "NIC_DMD",
            "begin_date":  cur.strftime("%Y%m%d"),
            "end_date":    nxt.strftime("%Y%m%d"),
            "format":      "json",
        }
        try:
            r = SESSION.get(url, params=params, timeout=20)
            r.raise_for_status()
            data = r.json()
            if 'data' not in data:
                break
            for rec in data['data']:
                raw = json.dumps(rec, separators=(',', ':'))
                if first_sample is None:
                    first_sample = raw
                raw_list.append(raw)
                timestamps.append(rec.get('t', str(len(raw_list))))
                if len(raw_list) >= limit:
                    break
            time.sleep(0.3)
        except Exception as e:
            print(f"  CHYBA chunk: {e}")
            break
        cur = nxt

    pkt_len = detect_pkt_len([first_sample] if first_sample else [])
    print(
        f"  Délka paketu: {pkt_len}B (z JSON záznamu ~{len((first_sample or '').encode())}B)")
    packets = [to_packet(r, pkt_len) for r in raw_list]
    print(f"  Načteno {len(packets)} vzorků × {pkt_len}B (raw JSON)")
    return packets, timestamps

# ---------------------------------------------------------------------------
# 4. USGS Earthquake — raw CSV záznamy
# ---------------------------------------------------------------------------


def fetch_usgs_raw(limit=10000):
    print(f"\n[USGS Earthquake raw] posledních 30 dní")
    url = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_month.csv"
    try:
        r = SESSION.get(url, timeout=30)
        r.raise_for_status()
        lines = r.text.strip().split('\n')
    except Exception as e:
        print(f"  CHYBA: {e}")
        return [], []

    data_lines = [l.strip() for l in lines[1:] if l.strip()]
    pkt_len = detect_pkt_len(data_lines[:10])
    print(
        f"  Délka paketu: {pkt_len}B (z CSV řádku ~{len(data_lines[0].encode())}B)")

    packets = []
    timestamps = []
    reader = csv.DictReader(lines)
    for row in reader:
        # Vezmi jen klíčové pole — lat, lon, depth, mag, place, time
        raw = f"{row.get('time', '')},{row.get('latitude', '')},{row.get('longitude', '')},{row.get('depth', '')},{row.get('mag', '')},{row.get('place', '')}"
        packets.append(to_packet(raw, pkt_len))
        timestamps.append(row.get('time', str(len(packets)))[:19])
        if len(packets) >= limit:
            break

    print(f"  Načteno {len(packets)} vzorků × {pkt_len}B (raw CSV)")
    return packets, timestamps

# ---------------------------------------------------------------------------
# Hlavní spuštění
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    print("=" * 70)
    print("NIC DMD — Raw Text Benchmark")
    print("Data přesně jak přicházejí — surový JSON/CSV text")
    print("=" * 70)

    all_results = {}

    # DWD
    for sid in ['00691', '05792', '01975']:
        try:
            pkts, ts = fetch_dwd_raw(sid)
            if pkts:
                name = f"DWD_{DWD_STATIONS[sid]}_raw_csv"
                r = analyze_packets(pkts, ts, name)
                print_summary(r)
                save_report(r, f"{name}.txt")
                all_results[name] = r
        except Exception as e:
            print(f"  CHYBA: {e}")
        time.sleep(1)

    # Open-Meteo
    for city, lat, lon in FORECAST_LOCATIONS[:4]:
        try:
            pkts, ts = fetch_meteo_raw(lat, lon, city)
            if pkts:
                name = f"Forecast_{city}_raw_json"
                r = analyze_packets(pkts, ts, name)
                print_summary(r)
                save_report(r, f"{name}.txt")
                all_results[name] = r
        except Exception as e:
            print(f"  CHYBA: {e}")
        time.sleep(0.5)

    # NOAA
    for sid in ['8518750', '9414290']:
        try:
            pkts, ts = fetch_noaa_raw(sid)
            if pkts:
                name = f"NOAA_{NOAA_STATIONS[sid]}_raw_json"
                r = analyze_packets(pkts, ts, name)
                print_summary(r)
                save_report(r, f"{name}.txt")
                all_results[name] = r
        except Exception as e:
            print(f"  CHYBA: {e}")
        time.sleep(1)

    # USGS
    try:
        pkts, ts = fetch_usgs_raw()
        if pkts:
            r = analyze_packets(pkts, ts, "USGS_Earthquake_raw_csv")
            print_summary(r)
            save_report(r, "USGS_Earthquake_raw_csv.txt")
            all_results["USGS_Earthquake_raw_csv"] = r
    except Exception as e:
        print(f"  CHYBA USGS: {e}")

    # Globální souhrn
    print(f"\n{'='*70}")
    print("GLOBÁLNÍ SOUHRN — raw text data")
    print(f"{'='*70}")
    print(f"{'Dataset':<40} {'Paketů':>7} {'Úspora%':>8} {'Chyby':>6}")
    print(f"{'-'*70}")
    for name, r in all_results.items():
        if not r:
            continue
        orig = sum(x['original_len']+1 for x in r)
        comp = sum(x['compressed_len'] for x in r)
        errs = sum(1 for x in r if not x['roundtrip_ok'])
        pct = (1-comp/orig)*100 if orig > 0 else 0
        print(f"  {name:<38} {len(r):>7} {pct:>7.1f}% {errs:>6}")
    print(f"{'='*70}")
    print(f"\nReporty uloženy v: {OUTPUT_DIR}/")
    print("Hotovo!")
