"""
Stahovač reálných binárních dat pro testování komprese
=======================================================
Závislosti: pip install requests
"""

import os
import sys
import struct
import requests
import zipfile
import io
import csv
import math

from nic_dmd_utils import dmd_analyze_packets as analyze_packets, dmd_print_summary as print_summary
OUTPUT_DIR = "real_data"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Windows cp1250 fix
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


# ---------------------------------------------------------------------------
# 1. DWD SYNOP - Zugspitze
# ---------------------------------------------------------------------------

def fetch_dwd_synop(station_id: str = "00691", limit: int = 10000) -> tuple:
    """
    Stáhne 10minutová data z DWD.
    Stanice 00691 = Zugspitze (2962m)
    Stanice 05792 = Fichtelberg
    Stanice 01975 = Helgoland
    """
    print(f"\n[DWD SYNOP] Stanice {station_id}")

    base_url = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/10_minutes/air_temperature/recent/"
    filename = f"10minutenwerte_TU_{station_id}_akt.zip"
    url = base_url + filename
    print(f"  Stahuji: {url}")

    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"  CHYBA: {e}")
        return [], []

    try:
        z = zipfile.ZipFile(io.BytesIO(r.content))
        data_file = [f for f in z.namelist() if f.startswith('produkt_')][0]
        content = z.read(data_file).decode('latin-1')
    except Exception as e:
        print(f"  CHYBA rozbalování: {e}")
        return [], []

    packets = []
    timestamps = []
    reader = csv.reader(content.strip().split('\n'), delimiter=';')
    header = [h.strip() for h in next(reader)]
    print(f"  Sloupce: {header}")

    # Zjisti indexy sloupců dynamicky
    def col(name):
        for i, h in enumerate(header):
            if name.upper() in h.upper():
                return i
        return None

    idx_ts   = col('MESS_DATUM')
    idx_pp   = col('PP_10')   # tlak
    idx_tt   = col('TT_10')   # teplota 2m
    idx_tm5  = col('TM5_10')  # teplota 5cm
    idx_rf   = col('RF_10')   # vlhkost
    idx_td   = col('TD_10')   # rosný bod

    print(f"  Indexy: ts={idx_ts} pp={idx_pp} tt={idx_tt} tm5={idx_tm5} rf={idx_rf} td={idx_td}")

    def safe_float(row, idx, default=0.0):
        if idx is None or idx >= len(row):
            return default
        val = row[idx].strip()
        if val in ['-999', '-999.0', '', 'eor']:
            return default
        try:
            return float(val)
        except:
            return default

    def clamp(v, scale=100):
        return max(-32768, min(32767, int(round(v * scale))))

    for row in reader:
        if not row or len(row) < 3:
            continue
        try:
            ts       = row[idx_ts].strip() if idx_ts else ''
            temp     = safe_float(row, idx_tt)
            temp_5cm = safe_float(row, idx_tm5)
            humidity = safe_float(row, idx_rf)
            dew      = safe_float(row, idx_td)
            # tlak je v hPa - scale 10 ale může být 900-1100
            # použijeme offset: (tlak - 900) × 10 aby se vešel do 2B
            pressure_raw = safe_float(row, idx_pp, 1013.0)
            pressure_off = pressure_raw - 900.0  # 0-200 hPa rozsah

            pkt = struct.pack('>8h',
                clamp(temp,      100),   # °C × 100
                clamp(humidity,  100),   # % × 100
                clamp(pressure_off, 10), # (hPa-900) × 10
                clamp(dew,       100),   # °C × 100
                clamp(temp_5cm,  100),   # °C × 100
                0, 0, 0                  # reserved
            )
            packets.append(pkt)
            timestamps.append(ts)

            if len(packets) >= limit:
                break
        except Exception as e:
            continue

    print(f"  Nacteno {len(packets)} vzorku")
    return packets, timestamps


# ---------------------------------------------------------------------------
# 2. GPS syntetická data - realistický trek
# ---------------------------------------------------------------------------

def generate_gps_packets(count: int = 10000) -> tuple:
    """
    Generuje realistická GPS data - trek přes Alpy.
    Formát paketu (16B):
      lat_int  [2B signed]  - stupně × 100
      lat_frac [2B unsigned] - zlomek stupně × 10000 (0-9999)
      lon_int  [2B signed]  - stupně × 100
      lon_frac [2B unsigned] - zlomek stupně × 10000
      altitude [2B signed]  - metry
      speed    [2B unsigned] - km/h × 10
      heading  [2B unsigned] - stupně × 10
      sats     [1B]
      hdop     [1B] - × 10
    """
    print(f"\n[GPS] Generuji realistická GPS data (trek Alpy)...")

    packets = []
    timestamps = []

    # Trasa: Chamonix → Zermatt přes několik průsmyků
    waypoints = [
        (45.9237, 6.8694,  1035),  # Chamonix
        (45.9500, 6.9000,  2000),  # Stoupání
        (45.9800, 7.0000,  2800),  # Col de Balme
        (46.0200, 7.1000,  2200),  # Trient
        (46.0500, 7.2000,  2500),  # Grand Col Ferret
        (45.9800, 7.4000,  1900),  # La Fouly
        (45.9500, 7.5500,  2100),  # Champex
        (46.0000, 7.6500,  1500),  # Sembrancher
        (46.0200, 7.7500,  1200),  # Martigny oblast
        (46.0400, 7.7800,  1300),  # Chemin
        (46.0000, 7.7500,  2100),  # Stoupání Zermatt
        (45.9833, 7.7500,  1620),  # Zermatt
    ]

    n_wps = len(waypoints)
    prev_lat, prev_lon = waypoints[0][0], waypoints[0][1]

    for i in range(count):
        # Interpoluj podél trasy
        t = (i / count) * (n_wps - 1)
        wp_idx = min(int(t), n_wps - 2)
        frac = t - wp_idx

        lat1, lon1, ele1 = waypoints[wp_idx]
        lat2, lon2, ele2 = waypoints[wp_idx + 1]

        lat = lat1 + (lat2 - lat1) * frac + 0.0003 * math.sin(i * 0.3)
        lon = lon1 + (lon2 - lon1) * frac + 0.0003 * math.cos(i * 0.27)
        ele = ele1 + (ele2 - ele1) * frac + 20 * math.sin(i * 0.1)

        # Rychlost z pohybu
        dlat = (lat - prev_lat) * 111000
        dlon = (lon - prev_lon) * 111000 * math.cos(math.radians(lat))
        dist = math.sqrt(dlat**2 + dlon**2)
        speed = min(999, int(dist * 360 * 10))  # km/h × 10

        # Heading
        heading = int(math.degrees(math.atan2(dlon, dlat)) % 360 * 10)

        # Rozlož souřadnice
        lat_int  = int(lat)
        lat_frac = int((abs(lat) - abs(lat_int)) * 10000)
        lon_int  = int(lon)
        lon_frac = int((abs(lon) - abs(lon_int)) * 10000)

        pkt = struct.pack('>hHhHhHHBB',
            lat_int,
            min(9999, lat_frac),
            lon_int,
            min(9999, lon_frac),
            max(-32768, min(32767, int(ele))),
            min(65535, speed),
            min(65535, heading),
            12,   # satelity
            15,   # HDOP × 10
        )
        packets.append(pkt)
        timestamps.append(f"trek_{i:05d}")
        prev_lat, prev_lon = lat, lon

    print(f"  GPS pakety: {len(packets)} x 16B")
    return packets, timestamps


# ---------------------------------------------------------------------------
# 3. Kombinovaný meteo+GPS (32B)
# ---------------------------------------------------------------------------

def fetch_combined_32b(limit: int = 10000) -> tuple:
    """Stáhne meteo a zkombinuje s GPS do 32B paketu."""
    print(f"\n[KOMBINOVANY] Meteo+GPS 32B pakety (Chamonix)")

    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude":   45.9237,
        "longitude":  6.8694,
        "start_date": "2022-01-01",
        "end_date":   "2023-02-15",
        "hourly":     ",".join([
            "temperature_2m", "relative_humidity_2m", "surface_pressure",
            "wind_speed_10m", "precipitation", "soil_temperature_0cm",
            "soil_temperature_6cm", "dew_point_2m"
        ]),
        "timezone":        "UTC",
        "wind_speed_unit": "ms",
    }

    try:
        import time
        from datetime import datetime, timedelta
        dt_s = datetime.strptime("2022-01-01", "%Y-%m-%d")
        dt_e = datetime.strptime("2023-02-15", "%Y-%m-%d")
        all_data = {}
        cur = dt_s
        chunks = []
        while cur < dt_e:
            nxt = min(cur + timedelta(days=30), dt_e)
            chunks.append((cur.strftime("%Y-%m-%d"), nxt.strftime("%Y-%m-%d")))
            cur = nxt + timedelta(days=1)
        print(f"  Stahuji v {len(chunks)} úsecích...")
        for ci, (s, e) in enumerate(chunks):
            p2 = dict(params); p2["start_date"] = s; p2["end_date"] = e
            for attempt in range(3):
                try:
                    r = requests.get(url, params=p2, timeout=30)
                    r.raise_for_status()
                    chunk = r.json()["hourly"]
                    for key, vals in chunk.items():
                        if key not in all_data: all_data[key] = []
                        all_data[key].extend(vals)
                    print(f"  [{ci+1}/{len(chunks)}] {s} → {e}: {len(chunk.get('time',[]))} vzorků")
                    time.sleep(0.5)
                    break
                except Exception as ex:
                    if attempt < 2:
                        print(f"  Pokus {attempt+1} selhal, zkouším znovu...")
                        time.sleep(3)
                    else:
                        raise
        meteo = all_data
        print(f"  Meteo: {len(meteo.get('time', []))} vzorku")
    except Exception as e:
        print(f"  CHYBA meteo: {e}")
        return [], []

    n = min(limit, len(meteo['time']))
    packets = []
    timestamps = []
    prev_lat, prev_lon = 45.9237, 6.8694

    def clamp(v, scale=100):
        return max(-32768, min(32767, int(round(v * scale))))

    for i in range(n):
        def g(key, default=0.0):
            v = meteo.get(key, [default]*n)[i]
            return v if v is not None else default

        # Meteo část (16B)
        pressure_off = g('surface_pressure', 1013.0) - 900.0
        meteo_part = struct.pack('>8h',
            clamp(g('temperature_2m'),          100),
            clamp(g('relative_humidity_2m'),    100),
            clamp(pressure_off,                  10),
            clamp(g('wind_speed_10m'),          100),
            clamp(g('precipitation'),           100),
            clamp(g('soil_temperature_0cm'),    100),
            clamp(g('soil_temperature_6cm'),    100),
            clamp(g('dew_point_2m'),            100),
        )

        # GPS část (16B) - pohyb podél údolí
        t = (i % 24) / 24
        lat = 45.9237 + 0.05 * math.sin(t * math.pi * 2)
        lon = 6.8694  + 0.03 * math.cos(t * math.pi * 2)
        ele = 1035 + 500 * math.sin(t * math.pi)

        dlat = (lat - prev_lat) * 111000
        dlon = (lon - prev_lon) * 111000 * math.cos(math.radians(lat))
        dist = math.sqrt(dlat**2 + dlon**2)
        speed = min(9999, int(dist * 360 * 10))
        heading = int(math.degrees(math.atan2(dlon, dlat)) % 360 * 10)

        lat_int  = int(lat)
        lat_frac = int((abs(lat) - abs(lat_int)) * 10000)
        lon_int  = int(lon)
        lon_frac = int((abs(lon) - abs(lon_int)) * 10000)

        gps_part = struct.pack('>hHhHhHHBB',
            lat_int,
            min(9999, lat_frac),
            lon_int,
            min(9999, lon_frac),
            max(-32768, min(32767, int(ele))),
            min(65535, speed),
            min(65535, heading),
            12,
            10,
        )

        packets.append(meteo_part + gps_part)
        timestamps.append(meteo['time'][i])
        prev_lat, prev_lon = lat, lon

    print(f"  Kombinovanych paketu: {len(packets)} x 32B")
    return packets, timestamps


# ---------------------------------------------------------------------------
# Hlavní spuštění
# ---------------------------------------------------------------------------

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


if __name__ == "__main__":
    LIMIT = 10000

    print("=" * 70)
    print("Stahovani realnych dat pro testovani komprese")
    print("=" * 70)

    # 1. DWD Zugspitze
    try:
        packets, timestamps = fetch_dwd_synop("00691", LIMIT)
        if packets:
            results = analyze_packets(packets, timestamps, "zugspitze_16B")
            print_summary(results)
            save_report(results, "zugspitze_report.txt")
    except Exception as e:
        print(f"DWD CHYBA: {e}")
        import traceback; traceback.print_exc()

    # 2. GPS trek
    try:
        packets, timestamps = generate_gps_packets(LIMIT)
        if packets:
            results = analyze_packets(packets, timestamps, "gps_trek_16B")
            print_summary(results)
            save_report(results, "gps_trek_report.txt")
    except Exception as e:
        print(f"GPS CHYBA: {e}")
        import traceback; traceback.print_exc()

    # 3. Kombinovaný
    try:
        packets, timestamps = fetch_combined_32b(LIMIT)
        if packets:
            results = analyze_packets(packets, timestamps, "chamonix_32B")
            print_summary(results)
            save_report(results, "chamonix_combined_report.txt")
    except Exception as e:
        print(f"KOMBINOVANY CHYBA: {e}")
        import traceback; traceback.print_exc()

    print("\nHotovo! Vysledky v slozce:", OUTPUT_DIR)
