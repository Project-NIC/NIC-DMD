"""
Stahovací skripty pro reálná meteorologická data
=================================================
5 zdrojů z různých "nejhorších míst na světě":
  1. Sněžka (CZ) - ČHMÚ
  2. Antarktida - NOAA
  3. Death Valley (USA) - NOAA
  4. Sibiř / Ojmjakon (RU) - Open-Meteo
  5. Sahara / In Salah (DZ) - Open-Meteo

Každý skript stáhne ~10000 vzorků, zkomprimuje je a uloží:
  - binární soubor s pakety (.bin)
  - CSV s výsledky analýzy (.csv)
  - souhrnný report (.txt)

Závislosti: pip install requests pandas numpy
"""

import os
import csv
import json
import struct
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from nic_dmd_utils import dmd_analyze_packets as analyze_packets, dmd_print_summary as print_summary

OUTPUT_DIR = "meteo_data"
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Pomocné funkce
# ---------------------------------------------------------------------------

def float_to_fixed(value: float, scale: int = 100) -> int:
    """Převede float na fixed-point integer (×scale, 2B signed)."""
    return max(-32768, min(32767, int(round(value * scale))))


def pack_meteo_16b(temp: float, humidity: float, pressure: float,
                   wind: float, rain: float, temp2: float,
                   temp3: float, temp4: float) -> bytes:
    """
    Zabalí 8 meteo hodnot do 16 bajtů (2B každá, fixed-point):
      temp      [°C × 100]  → -327.68 až +327.67
      humidity  [% × 100]   → 0 až 327.67
      pressure  [hPa × 10]  → 0 až 3276.7
      wind      [m/s × 100] → 0 až 327.67
      rain      [mm × 100]  → 0 až 327.67
      temp2/3/4 [°C × 100]  → další teploty
    """
    values = [
        float_to_fixed(temp,     100),
        float_to_fixed(humidity, 100),
        float_to_fixed(pressure,  10),
        float_to_fixed(wind,     100),
        float_to_fixed(rain,     100),
        float_to_fixed(temp2,    100),
        float_to_fixed(temp3,    100),
        float_to_fixed(temp4,    100),
    ]
    return struct.pack('>8h', *values)


def pack_meteo_32b(temp: float, humidity: float, pressure: float,
                   wind: float, wind_dir: float, rain: float,
                   temp2: float, temp3: float, temp4: float,
                   temp5: float, uv: float, solar: float,
                   dew: float, feels: float, vis: float,
                   cloud: float) -> bytes:
    """
    Zabalí 16 meteo hodnot do 32 bajtů.
    """
    values = [
        float_to_fixed(temp,     100),
        float_to_fixed(humidity, 100),
        float_to_fixed(pressure,  10),
        float_to_fixed(wind,     100),
        float_to_fixed(wind_dir,  10),
        float_to_fixed(rain,     100),
        float_to_fixed(temp2,    100),
        float_to_fixed(temp3,    100),
        float_to_fixed(temp4,    100),
        float_to_fixed(temp5,    100),
        float_to_fixed(uv,       100),
        float_to_fixed(solar,      1),
        float_to_fixed(dew,      100),
        float_to_fixed(feels,    100),
        float_to_fixed(vis,       10),
        float_to_fixed(cloud,    100),
    ]
    return struct.pack('>16h', *values)


def save_results(results: list[dict], source_id: str) -> None:
    """Uloží výsledky do CSV a binárního souboru."""

    # --- CSV ---
    csv_path = os.path.join(OUTPUT_DIR, f"{source_id}_analysis.csv")
    if results:
        keys = results[0].keys()
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(results)
        print(f"  CSV uloženo: {csv_path}")

    # --- souhrnný report ---
    txt_path = os.path.join(OUTPUT_DIR, f"{source_id}_report.txt")
    with open(txt_path, 'w', encoding='utf-8') as f:
        import sys
        old_stdout = sys.stdout
        sys.stdout = f
        print_summary(results)
        sys.stdout = old_stdout
    print(f"  Report uložen: {txt_path}")


def fetch_open_meteo(lat: float, lon: float, start: str, end: str,
                     extra_vars: list = None) -> dict:
    """
    Stáhne hodinová data z Open-Meteo API.
    Stahuje po měsících aby nedošlo k timeoutu serveru.
    """
    import time
    from datetime import datetime, timedelta

    variables = [
        "temperature_2m", "relative_humidity_2m", "surface_pressure",
        "wind_speed_10m", "wind_direction_10m", "precipitation",
        "dew_point_2m", "apparent_temperature", "cloud_cover",
        "shortwave_radiation", "uv_index", "visibility",
        "soil_temperature_0cm", "soil_temperature_6cm",
        "soil_temperature_18cm", "soil_temperature_54cm",
    ]
    if extra_vars:
        variables += extra_vars

    url = "https://archive-api.open-meteo.com/v1/archive"

    # Rozděl na měsíční úseky
    dt_start = datetime.strptime(start, "%Y-%m-%d")
    dt_end   = datetime.strptime(end,   "%Y-%m-%d")
    chunks   = []
    cur      = dt_start
    while cur < dt_end:
        nxt = min(cur + timedelta(days=30), dt_end)
        chunks.append((cur.strftime("%Y-%m-%d"), nxt.strftime("%Y-%m-%d")))
        cur = nxt + timedelta(days=1)

    print(f"  Stahuji z Open-Meteo ({lat}, {lon}) v {len(chunks)} úsecích...")

    all_data = {}
    for i, (s, e) in enumerate(chunks):
        params = {
            "latitude":        lat,
            "longitude":       lon,
            "start_date":      s,
            "end_date":        e,
            "hourly":          ",".join(variables),
            "timezone":        "UTC",
            "wind_speed_unit": "ms",
        }
        for attempt in range(3):
            try:
                r = requests.get(url, params=params, timeout=30)
                r.raise_for_status()
                chunk = r.json()["hourly"]
                for key, vals in chunk.items():
                    if key not in all_data:
                        all_data[key] = []
                    all_data[key].extend(vals)
                print(f"  [{i+1}/{len(chunks)}] {s} → {e}: "
                      f"{len(chunk.get('time', []))} vzorků")
                time.sleep(0.5)
                break
            except Exception as ex:
                if attempt < 2:
                    print(f"  Pokus {attempt+1} selhal ({ex}), zkouším znovu...")
                    time.sleep(3)
                else:
                    raise

    return {"hourly": all_data}


def open_meteo_to_packets_16b(data: dict, limit: int = 10000) -> tuple:
    """Převede Open-Meteo data na 16B pakety."""
    h = data['hourly']
    n = min(limit, len(h['time']))

    packets = []
    timestamps = []

    for i in range(n):
        def g(key, default=0.0):
            v = h.get(key, [default] * n)[i]
            return v if v is not None else default

        pkt = pack_meteo_16b(
            temp=g('temperature_2m'),
            humidity=g('relative_humidity_2m'),
            pressure=g('surface_pressure', 1013.0),
            wind=g('wind_speed_10m'),
            rain=g('precipitation'),
            temp2=g('soil_temperature_0cm'),
            temp3=g('soil_temperature_6cm'),
            temp4=g('dew_point_2m'),
        )
        packets.append(pkt)
        timestamps.append(h['time'][i])

    return packets, timestamps


def open_meteo_to_packets_32b(data: dict, limit: int = 10000) -> tuple:
    """Převede Open-Meteo data na 32B pakety."""
    h = data['hourly']
    n = min(limit, len(h['time']))

    packets = []
    timestamps = []

    for i in range(n):
        def g(key, default=0.0):
            v = h.get(key, [default] * n)[i]
            return v if v is not None else default

        pkt = pack_meteo_32b(
            temp=g('temperature_2m'),
            humidity=g('relative_humidity_2m'),
            pressure=g('surface_pressure', 1013.0),
            wind=g('wind_speed_10m'),
            wind_dir=g('wind_direction_10m'),
            rain=g('precipitation'),
            temp2=g('soil_temperature_0cm'),
            temp3=g('soil_temperature_6cm'),
            temp4=g('soil_temperature_18cm'),
            temp5=g('soil_temperature_54cm'),
            uv=g('uv_index'),
            solar=g('shortwave_radiation'),
            dew=g('dew_point_2m'),
            feels=g('apparent_temperature'),
            vis=g('visibility', 10000.0) / 100,
            cloud=g('cloud_cover'),
        )
        packets.append(pkt)
        timestamps.append(h['time'][i])

    return packets, timestamps


# ---------------------------------------------------------------------------
# 1. Sněžka (CZ) — nejvyšší bod ČR, extrémní počasí
# ---------------------------------------------------------------------------

def fetch_snezka(limit: int = 10000) -> None:
    print("\n[1/5] Sněžka (CZ) — 1602m n.m.")
    source_id = "snezka"

    # ~10000 hodin = cca 416 dní, vezmeme 2021-2022
    data = fetch_open_meteo(
        lat=50.7364, lon=15.7394,
        start="2020-01-01", end="2021-02-14"
    )

    # 16B pakety
    packets_16, ts = open_meteo_to_packets_16b(data, limit)
    results_16 = analyze_packets(packets_16, ts, f"{source_id}_16B")
    print_summary(results_16)
    save_results(results_16, f"{source_id}_16B")

    # 32B pakety
    packets_32, ts = open_meteo_to_packets_32b(data, limit)
    results_32 = analyze_packets(packets_32, ts, f"{source_id}_32B")
    print_summary(results_32)
    save_results(results_32, f"{source_id}_32B")

    print(f"  Sněžka hotovo: {len(packets_16)} vzorků")


# ---------------------------------------------------------------------------
# 2. Antarktida (Amundsen-Scott) — nejchladnější místo
# ---------------------------------------------------------------------------

def fetch_antarktida(limit: int = 10000) -> None:
    print("\n[2/5] Antarktida — Amundsen-Scott South Pole Station")
    source_id = "antarktida"

    data = fetch_open_meteo(
        lat=-90.0, lon=0.0,
        start="2020-01-01", end="2021-02-14"
    )

    packets_16, ts = open_meteo_to_packets_16b(data, limit)
    results_16 = analyze_packets(packets_16, ts, f"{source_id}_16B")
    print_summary(results_16)
    save_results(results_16, f"{source_id}_16B")

    packets_32, ts = open_meteo_to_packets_32b(data, limit)
    results_32 = analyze_packets(packets_32, ts, f"{source_id}_32B")
    print_summary(results_32)
    save_results(results_32, f"{source_id}_32B")

    print(f"  Antarktida hotovo: {len(packets_16)} vzorků")


# ---------------------------------------------------------------------------
# 3. Death Valley (USA) — nejhorší horko
# ---------------------------------------------------------------------------

def fetch_death_valley(limit: int = 10000) -> None:
    print("\n[3/5] Death Valley (USA) — nejteplejší místo na Zemi")
    source_id = "death_valley"

    data = fetch_open_meteo(
        lat=36.4614, lon=-116.8675,
        start="2020-01-01", end="2021-02-14"
    )

    packets_16, ts = open_meteo_to_packets_16b(data, limit)
    results_16 = analyze_packets(packets_16, ts, f"{source_id}_16B")
    print_summary(results_16)
    save_results(results_16, f"{source_id}_16B")

    packets_32, ts = open_meteo_to_packets_32b(data, limit)
    results_32 = analyze_packets(packets_32, ts, f"{source_id}_32B")
    print_summary(results_32)
    save_results(results_32, f"{source_id}_32B")

    print(f"  Death Valley hotovo: {len(packets_16)} vzorků")


# ---------------------------------------------------------------------------
# 4. Ojmjakon (RU) — nejchladnější trvale obydlené místo
# ---------------------------------------------------------------------------

def fetch_ojmjakon(limit: int = 10000) -> None:
    print("\n[4/5] Ojmjakon (RU) — nejchladnější obydlené místo")
    source_id = "ojmjakon"

    data = fetch_open_meteo(
        lat=63.4608, lon=142.7858,
        start="2020-01-01", end="2021-02-14"
    )

    packets_16, ts = open_meteo_to_packets_16b(data, limit)
    results_16 = analyze_packets(packets_16, ts, f"{source_id}_16B")
    print_summary(results_16)
    save_results(results_16, f"{source_id}_16B")

    packets_32, ts = open_meteo_to_packets_32b(data, limit)
    results_32 = analyze_packets(packets_32, ts, f"{source_id}_32B")
    print_summary(results_32)
    save_results(results_32, f"{source_id}_32B")

    print(f"  Ojmjakon hotovo: {len(packets_16)} vzorků")


# ---------------------------------------------------------------------------
# 5. In Salah (DZ) — nejsušší a nejžhavější Sahara
# ---------------------------------------------------------------------------

def fetch_sahara(limit: int = 10000) -> None:
    print("\n[5/5] In Salah (Alžírsko) — srdce Sahary")
    source_id = "sahara"

    data = fetch_open_meteo(
        lat=27.1967, lon=2.4643,
        start="2020-01-01", end="2021-02-14"
    )

    packets_16, ts = open_meteo_to_packets_16b(data, limit)
    results_16 = analyze_packets(packets_16, ts, f"{source_id}_16B")
    print_summary(results_16)
    save_results(results_16, f"{source_id}_16B")

    packets_32, ts = open_meteo_to_packets_32b(data, limit)
    results_32 = analyze_packets(packets_32, ts, f"{source_id}_32B")
    print_summary(results_32)
    save_results(results_32, f"{source_id}_32B")

    print(f"  Sahara hotovo: {len(packets_16)} vzorků")


# ---------------------------------------------------------------------------
# Souhrnný report přes všechny zdroje
# ---------------------------------------------------------------------------

def global_summary() -> None:
    """Načte všechna CSV a udělá globální porovnání."""
    print("\n" + "="*80)
    print("GLOBÁLNÍ SOUHRN PŘES VŠECHNY ZDROJE")
    print("="*80)

    all_dfs = []
    for f in os.listdir(OUTPUT_DIR):
        if f.endswith("_analysis.csv"):
            df = pd.read_csv(os.path.join(OUTPUT_DIR, f))
            all_dfs.append(df)

    if not all_dfs:
        print("Žádná data!")
        return

    df = pd.concat(all_dfs, ignore_index=True)

    print(f"\nCelkem vzorků: {len(df)}")
    print(f"Celková úspora: {df['saving_pct'].mean():.1f}% průměr")
    print(f"Min úspora: {df['saving_pct'].min():.1f}%")
    print(f"Max úspora: {df['saving_pct'].max():.1f}%")

    print(f"\nPoužití metod (globálně):")
    method_counts = df['method'].value_counts()
    for method, count in method_counts.items():
        pct = count / len(df) * 100
        bar = '█' * int(pct / 2)
        print(f"  {pct:>5.1f}% {bar:<50} {method}")

    print(f"\nPrůměrná úspora podle zdroje a šířky:")
    summary = df.groupby('source')['saving_pct'].agg(['mean', 'min', 'max'])
    print(summary.to_string())

    # uložit globální CSV
    global_csv = os.path.join(OUTPUT_DIR, "global_summary.csv")
    df.to_csv(global_csv, index=False)
    print(f"\nGlobální CSV: {global_csv}")


# ---------------------------------------------------------------------------
# Hlavní spuštění
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    LIMIT = 10000  # počet vzorků na zdroj

    # můžeš spustit jen jeden zdroj: python fetch_data.py snezka
    sources = {
        "snezka":       fetch_snezka,
        "antarktida":   fetch_antarktida,
        "death_valley": fetch_death_valley,
        "ojmjakon":     fetch_ojmjakon,
        "sahara":       fetch_sahara,
    }

    if len(sys.argv) > 1:
        name = sys.argv[1].lower()
        if name in sources:
            sources[name](LIMIT)
        else:
            print(f"Neznámý zdroj: {name}")
            print(f"Dostupné: {', '.join(sources.keys())}")
    else:
        # spusť vše
        for name, fn in sources.items():
            try:
                fn(LIMIT)
            except Exception as e:
                print(f"  CHYBA ({name}): {e}")

        global_summary()

    print("\nHotovo!")
