"""
NIC DMD+ — Fetcher reálných dat
================================
Více zdrojů dat pro benchmark bez závislosti na archive-api.open-meteo.com

Zdroje:
  1. DWD SYNOP       — německé meteostanice, 10min data (ověřeno funkční)
  2. Open-Meteo      — forecast API (spolehlivější než archive)
  3. USGS Earthquake — seismická data (malé delty souřadnic)
  4. NOAA Tides      — výška hladiny moře (pomalé změny)
  5. Open-Meteo AQ   — kvalita ovzduší (PM2.5, NO2, O3...)
  6. GPS syntetická  — trek Alpy (offline, vždy dostupné)
  7. Elektroměr syn. — simulace odběru (offline, vždy dostupné)
  8. Senzor sítě     — simulace IoT senzorů (offline)

Závislosti: pip install requests
"""

import os, sys, struct, math, random, time, csv, zipfile, io
import requests
from nic_dmd_utils import dmd_analyze_packets as analyze_packets, dmd_print_summary as print_summary

OUTPUT_DIR = "real_data_plus"
os.makedirs(OUTPUT_DIR, exist_ok=True)

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'NIC-DMD-Plus/1.0'})

# ---------------------------------------------------------------------------
# Pomocné funkce
# ---------------------------------------------------------------------------

def clamp16(v):
    return max(-32768, min(32767, int(round(v))))

def safe_float(v, default=0.0):
    try:
        f = float(v)
        return default if math.isnan(f) or math.isinf(f) else f
    except:
        return default

def save_report(results, filename):
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, 'w', encoding='utf-8') as f:
        old = sys.stdout; sys.stdout = f
        try: print_summary(results)
        finally: sys.stdout = old
    print(f"  Report: {path}")

# ---------------------------------------------------------------------------
# 1. DWD SYNOP — meteostanice Německo
#    10minutová data teploty, vlhkosti, tlaku, rosného bodu
#    Stanice: 00691=Zugspitze, 05792=Fichtelberg, 01975=Helgoland,
#             03456=München, 00433=Berlin-Tempelhof
# ---------------------------------------------------------------------------

DWD_STATIONS = {
    '00691': 'Zugspitze (2962m)',
    '05792': 'Fichtelberg (1213m)',
    '01975': 'Helgoland (pobřeží)',
    '03456': 'München',
    '00433': 'Berlin-Tempelhof',
}

def fetch_dwd_synop(station_id='00691', limit=10000):
    name = DWD_STATIONS.get(station_id, station_id)
    print(f"\n[DWD] {name} ({station_id})")
    base = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/10_minutes/air_temperature/recent/"
    url  = base + f"10minutenwerte_TU_{station_id}_akt.zip"
    try:
        r = SESSION.get(url, timeout=30); r.raise_for_status()
    except Exception as e:
        print(f"  CHYBA: {e}"); return [], []

    try:
        z = zipfile.ZipFile(io.BytesIO(r.content))
        df = [f for f in z.namelist() if f.startswith('produkt_')][0]
        content = z.read(df).decode('latin-1')
    except Exception as e:
        print(f"  CHYBA rozbalování: {e}"); return [], []

    reader = csv.reader(content.strip().split('\n'), delimiter=';')
    hdr    = [h.strip() for h in next(reader)]
    def col(n):
        for i,h in enumerate(hdr):
            if n.upper() in h.upper(): return i
        return None

    idx_ts  = col('MESS_DATUM')
    idx_tt  = col('TT_10')
    idx_tm5 = col('TM5_10')
    idx_rf  = col('RF_10')
    idx_td  = col('TD_10')
    idx_pp  = col('PP_10')

    packets = []; timestamps = []
    for row in reader:
        if not row or len(row) < 3: continue
        try:
            def sf(idx, d=0.0):
                if idx is None or idx >= len(row): return d
                v = row[idx].strip()
                return d if v in ['-999','-999.0','','eor'] else safe_float(v, d)

            pkt = struct.pack('>8h',
                clamp16(sf(idx_tt)  * 100),           # teplota 2m °C×100
                clamp16(sf(idx_rf)  * 100),           # vlhkost %×100
                clamp16((sf(idx_pp, 1013.0)-900)*10), # tlak (hPa-900)×10
                clamp16(sf(idx_td)  * 100),           # rosný bod °C×100
                clamp16(sf(idx_tm5) * 100),           # teplota 5cm °C×100
                0, 0, 0
            )
            packets.append(pkt)
            timestamps.append(row[idx_ts].strip() if idx_ts else str(len(packets)))
            if len(packets) >= limit: break
        except: continue

    print(f"  Načteno {len(packets)} vzorků × 16B")
    return packets, timestamps

# ---------------------------------------------------------------------------
# 2. Open-Meteo FORECAST — spolehlivější než archive
#    Aktuální předpověď 7-16 dní, hodinová data
#    Lokace: Praha, Brno, Ostrava, Bratislava, Vídeň
# ---------------------------------------------------------------------------

FORECAST_LOCATIONS = [
    ('Praha',      50.0755, 14.4378),
    ('Brno',       49.1951, 16.6068),
    ('Ostrava',    49.8209, 18.2625),
    ('Bratislava', 48.1486, 17.1077),
    ('Vídeň',      48.2082, 16.3738),
    ('Mnichov',    48.1351, 11.5820),
    ('Varšava',    52.2297, 21.0122),
    ('Budapešť',   47.4979, 19.0402),
]

def fetch_open_meteo_forecast(lat, lon, name, limit=10000):
    print(f"\n[Open-Meteo forecast] {name} ({lat},{lon})")
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude":        lat,
        "longitude":       lon,
        "hourly":          ",".join([
            "temperature_2m", "relative_humidity_2m", "surface_pressure",
            "wind_speed_10m", "wind_direction_10m", "precipitation",
            "dew_point_2m",   "apparent_temperature", "cloud_cover",
            "shortwave_radiation", "uv_index", "visibility",
            "soil_temperature_0cm", "soil_temperature_6cm",
            "soil_temperature_18cm", "soil_temperature_54cm",
        ]),
        "forecast_days":   16,
        "timezone":        "UTC",
        "wind_speed_unit": "ms",
    }
    try:
        r = SESSION.get(url, params=params, timeout=20); r.raise_for_status()
        h = r.json()["hourly"]
    except Exception as e:
        print(f"  CHYBA: {e}"); return [], []

    def g(key, d=0.0, i=0):
        v = h.get(key, [d]*999)
        v = v[i] if i < len(v) else d
        return safe_float(v, d)

    n = min(limit, len(h.get('time', [])))
    packets = []; timestamps = []
    for i in range(n):
        pkt16 = struct.pack('>8h',
            clamp16(g('temperature_2m',0,i)       * 100),
            clamp16(g('relative_humidity_2m',0,i)  * 100),
            clamp16((g('surface_pressure',1013,i)-900) * 10),
            clamp16(g('wind_speed_10m',0,i)        * 100),
            clamp16(g('precipitation',0,i)         * 100),
            clamp16(g('soil_temperature_0cm',0,i)  * 100),
            clamp16(g('soil_temperature_6cm',0,i)  * 100),
            clamp16(g('dew_point_2m',0,i)          * 100),
        )
        packets.append(pkt16)
        timestamps.append(h['time'][i] if i < len(h.get('time',[])) else str(i))

    print(f"  Načteno {len(packets)} vzorků × 16B")
    return packets, timestamps

def fetch_open_meteo_forecast_32b(lat, lon, name, limit=10000):
    """32B varianta — 16 proměnných."""
    print(f"\n[Open-Meteo forecast 32B] {name}")
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude":        lat,
        "longitude":       lon,
        "hourly":          ",".join([
            "temperature_2m", "relative_humidity_2m", "surface_pressure",
            "wind_speed_10m", "wind_direction_10m", "precipitation",
            "dew_point_2m",   "apparent_temperature", "cloud_cover",
            "shortwave_radiation", "uv_index", "visibility",
            "soil_temperature_0cm", "soil_temperature_6cm",
            "soil_temperature_18cm", "soil_temperature_54cm",
        ]),
        "forecast_days":   16,
        "timezone":        "UTC",
        "wind_speed_unit": "ms",
    }
    try:
        r = SESSION.get(url, params=params, timeout=20); r.raise_for_status()
        h = r.json()["hourly"]
    except Exception as e:
        print(f"  CHYBA: {e}"); return [], []

    def g(key, d=0.0, i=0):
        v = h.get(key, [d]*999)
        v = v[i] if i < len(v) else d
        return safe_float(v, d)

    n = min(limit, len(h.get('time', [])))
    packets = []; timestamps = []
    for i in range(n):
        pkt32 = struct.pack('>16h',
            clamp16(g('temperature_2m',0,i)        * 100),
            clamp16(g('relative_humidity_2m',0,i)   * 100),
            clamp16((g('surface_pressure',1013,i)-900) * 10),
            clamp16(g('wind_speed_10m',0,i)         * 100),
            clamp16(g('wind_direction_10m',0,i)     * 10),
            clamp16(g('precipitation',0,i)          * 100),
            clamp16(g('dew_point_2m',0,i)           * 100),
            clamp16(g('apparent_temperature',0,i)   * 100),
            clamp16(g('cloud_cover',0,i)            * 100),
            clamp16(g('shortwave_radiation',0,i)    * 1),
            clamp16(g('uv_index',0,i)               * 100),
            clamp16(g('visibility',10000,i) / 100   * 10),
            clamp16(g('soil_temperature_0cm',0,i)   * 100),
            clamp16(g('soil_temperature_6cm',0,i)   * 100),
            clamp16(g('soil_temperature_18cm',0,i)  * 100),
            clamp16(g('soil_temperature_54cm',0,i)  * 100),
        )
        packets.append(pkt32)
        timestamps.append(h['time'][i] if i < len(h.get('time',[])) else str(i))

    print(f"  Načteno {len(packets)} vzorků × 32B")
    return packets, timestamps

# ---------------------------------------------------------------------------
# 3. Open-Meteo Air Quality — PM2.5, PM10, NO2, O3, CO
#    Jiný charakter dat než meteo — chemické koncentrace
# ---------------------------------------------------------------------------

def fetch_open_meteo_airquality(lat, lon, name, limit=10000):
    print(f"\n[Open-Meteo AQ] {name}")
    url = "https://air-quality-api.open-meteo.com/v1/air-quality"
    params = {
        "latitude":     lat,
        "longitude":    lon,
        "hourly":       ",".join([
            "pm10", "pm2_5", "carbon_monoxide", "nitrogen_dioxide",
            "sulphur_dioxide", "ozone", "aerosol_optical_depth",
            "dust",
        ]),
        "forecast_days": 7,
        "timezone":      "UTC",
    }
    try:
        r = SESSION.get(url, params=params, timeout=20); r.raise_for_status()
        h = r.json()["hourly"]
    except Exception as e:
        print(f"  CHYBA: {e}"); return [], []

    def g(key, d=0.0, i=0):
        v = h.get(key, [d]*999)
        v = v[i] if i < len(v) else d
        return safe_float(v, d)

    n = min(limit, len(h.get('time', [])))
    packets = []; timestamps = []
    for i in range(n):
        pkt = struct.pack('>8h',
            clamp16(g('pm10',0,i)               * 100),  # μg/m³ × 100
            clamp16(g('pm2_5',0,i)              * 100),
            clamp16(g('carbon_monoxide',0,i)    * 10),   # ppb × 10
            clamp16(g('nitrogen_dioxide',0,i)   * 100),
            clamp16(g('sulphur_dioxide',0,i)    * 100),
            clamp16(g('ozone',0,i)              * 100),
            clamp16(g('aerosol_optical_depth',0,i) * 1000),
            clamp16(g('dust',0,i)               * 100),
        )
        packets.append(pkt)
        timestamps.append(h['time'][i] if i < len(h.get('time',[])) else str(i))

    print(f"  Načteno {len(packets)} vzorků × 16B")
    return packets, timestamps

# ---------------------------------------------------------------------------
# 4. USGS Earthquake — seismická data
#    Souřadnice + magnituda + hloubka — malé postupné změny
# ---------------------------------------------------------------------------

def fetch_usgs_earthquakes(limit=10000):
    print(f"\n[USGS Earthquake] posledních 30 dní")
    url = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_month.csv"
    try:
        r = SESSION.get(url, timeout=30); r.raise_for_status()
        lines = r.text.strip().split('\n')
    except Exception as e:
        print(f"  CHYBA: {e}"); return [], []

    reader = csv.DictReader(lines)
    packets = []; timestamps = []

    for row in reader:
        try:
            lat  = safe_float(row.get('latitude',  0))
            lon  = safe_float(row.get('longitude', 0))
            dep  = safe_float(row.get('depth',     0))
            mag  = safe_float(row.get('mag',       0))
            ts   = row.get('time', '')

            # Formát: lat×100, lon×100, hloubka×10, magnituda×100,
            #         lat_frac, lon_frac, 0, 0
            lat_int  = int(lat); lat_frac = int((abs(lat) - abs(lat_int)) * 10000)
            lon_int  = int(lon); lon_frac = int((abs(lon) - abs(lon_int)) * 10000)

            pkt = struct.pack('>8h',
                clamp16(lat * 100),
                clamp16(lon * 100),
                clamp16(dep * 10),
                clamp16(mag * 100),
                clamp16(lat_frac),
                clamp16(lon_frac),
                0, 0
            )
            packets.append(pkt)
            timestamps.append(ts[:19])
            if len(packets) >= limit: break
        except: continue

    print(f"  Načteno {len(packets)} vzorků × 16B")
    return packets, timestamps

# ---------------------------------------------------------------------------
# 5. NOAA Tides — výška hladiny moře, hodinová data
#    Stanice: 8518750=New York, 9414290=San Francisco, 8771450=Galveston
# ---------------------------------------------------------------------------

NOAA_STATIONS = {
    '8518750': 'New York',
    '9414290': 'San Francisco',
    '8771450': 'Galveston TX',
    '8443970': 'Boston',
    '8726520': 'St. Petersburg FL',
}

def fetch_noaa_tides(station='8518750', limit=10000):
    name = NOAA_STATIONS.get(station, station)
    print(f"\n[NOAA Tides] {name} ({station})")

    # Poslední rok po měsících
    from datetime import datetime, timedelta
    end   = datetime.utcnow()
    start = end - timedelta(days=365)

    url = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
    packets = []; timestamps = []

    cur = start
    while cur < end and len(packets) < limit:
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
            r = SESSION.get(url, params=params, timeout=20); r.raise_for_status()
            data = r.json()
            if 'data' not in data:
                print(f"  Prázdná odpověď: {data.get('error',{}).get('message','?')}")
                break
            for rec in data['data']:
                v  = safe_float(rec.get('v', 0))
                s  = safe_float(rec.get('s', 0))   # sigma (odchylka)
                ts = rec.get('t', '')
                pkt = struct.pack('>8h',
                    clamp16(v * 1000),   # výška mm
                    clamp16(s * 1000),   # sigma mm
                    0, 0, 0, 0, 0, 0
                )
                packets.append(pkt)
                timestamps.append(ts)
                if len(packets) >= limit: break
            time.sleep(0.3)
        except Exception as e:
            print(f"  CHYBA chunk: {e}"); break
        cur = nxt + timedelta(days=1)

    print(f"  Načteno {len(packets)} vzorků × 16B")
    return packets, timestamps

# ---------------------------------------------------------------------------
# 6. GPS syntetická — trek Chamonix → Zermatt
#    Offline, vždy dostupné
# ---------------------------------------------------------------------------

def generate_gps_trek(count=10000):
    print(f"\n[GPS syntetická] Trek Chamonix→Zermatt ({count} bodů)")
    waypoints = [
        (45.9237,6.8694,1035),(45.9500,6.9000,2000),(45.9800,7.0000,2800),
        (46.0200,7.1000,2200),(46.0500,7.2000,2500),(45.9800,7.4000,1900),
        (45.9500,7.5500,2100),(46.0000,7.6500,1500),(46.0200,7.7500,1200),
        (46.0400,7.7800,1300),(46.0000,7.7500,2100),(45.9833,7.7500,1620),
    ]
    n_wps = len(waypoints)
    packets = []; timestamps = []
    prev_lat, prev_lon = waypoints[0][0], waypoints[0][1]

    for i in range(count):
        t = (i/count)*(n_wps-1); wi = min(int(t), n_wps-2); frac = t-wi
        lat1,lon1,ele1 = waypoints[wi]; lat2,lon2,ele2 = waypoints[wi+1]
        lat = lat1+(lat2-lat1)*frac+0.0003*math.sin(i*0.3)
        lon = lon1+(lon2-lon1)*frac+0.0003*math.cos(i*0.27)
        ele = ele1+(ele2-ele1)*frac+20*math.sin(i*0.1)
        dlat = (lat-prev_lat)*111000
        dlon = (lon-prev_lon)*111000*math.cos(math.radians(lat))
        dist = math.sqrt(dlat**2+dlon**2)
        speed   = min(9999, int(dist*360*10))
        heading = int(math.degrees(math.atan2(dlon,dlat))%360*10)
        lat_int=int(lat); lat_frac=int((abs(lat)-abs(lat_int))*10000)
        lon_int=int(lon); lon_frac=int((abs(lon)-abs(lon_int))*10000)
        packets.append(struct.pack('>hHhHhHHBB',
            lat_int, min(9999,lat_frac), lon_int, min(9999,lon_frac),
            max(-32768,min(32767,int(ele))), min(65535,speed),
            min(65535,heading), 12, 15))
        timestamps.append(f"trek_{i:05d}")
        prev_lat,prev_lon = lat,lon

    print(f"  Vygenerováno {len(packets)} vzorků × 16B")
    return packets, timestamps

# ---------------------------------------------------------------------------
# 7. Elektroměr syntetický — simulace hodinového odběru
#    Tarif VT/NT, napětí, proud, výkon, frekvence, účiník
#    Offline, vždy dostupné
# ---------------------------------------------------------------------------

def generate_smartmeter(count=10000):
    print(f"\n[Elektroměr syntetický] ({count} vzorků)")
    random.seed(1234)
    packets = []; timestamps = []

    # Základní profil odběru (kW) — denní cyklus
    profile = [0.3,0.2,0.2,0.2,0.2,0.3,0.8,1.5,1.2,1.0,1.1,1.0,
               1.2,1.0,0.9,0.8,1.0,1.5,2.0,1.8,1.5,1.2,0.9,0.5]

    p  = 23000   # výkon W×10
    v  = 2300    # napětí V×10
    i  = 100     # proud A×100
    f  = 5000    # frekvence Hz×100
    pf = 95      # účiník ×100
    e  = 0       # energie kWh×10 (kumulativní)

    for n in range(count):
        hour   = n % 24
        base   = int(profile[hour] * 1000)
        p      = base + random.randint(-50, 50)
        v      = 2300 + random.randint(-30, 30)   # 230V ± 3V
        i_val  = int(p * 10 / max(v, 1))
        f      = 5000 + random.randint(-3, 3)      # 50Hz ± 0.03Hz
        pf     = 95 + random.randint(-3, 3)
        e     += p // 100

        pkt = struct.pack('>8h',
            clamp16(p),       # výkon W×10
            clamp16(v),       # napětí V×10
            clamp16(i_val),   # proud A×100
            clamp16(f),       # frekvence Hz×100
            clamp16(pf),      # účiník ×100
            clamp16(e % 32767),  # energie (mod pro 16bit)
            0, 0
        )
        packets.append(pkt)
        timestamps.append(f"meter_{n:05d}")

    print(f"  Vygenerováno {len(packets)} vzorků × 16B")
    return packets, timestamps

# ---------------------------------------------------------------------------
# 8. IoT senzorová síť — simulace 8 senzorů v budově
#    Teplota, vlhkost, CO2, osvětlení, pohyb
#    Offline, vždy dostupné
# ---------------------------------------------------------------------------

def generate_iot_building(count=10000):
    print(f"\n[IoT budova syntetická] ({count} vzorků, 8 místností)")
    random.seed(5678)
    packets = []; timestamps = []

    # 8 místností, každá má trochu jiný profil
    rooms = [
        {'base_t': 2100, 'base_h': 4500, 'base_co2': 400, 'base_lux': 0},
        {'base_t': 2200, 'base_h': 4200, 'base_co2': 500, 'base_lux': 200},
        {'base_t': 2050, 'base_h': 5000, 'base_co2': 420, 'base_lux': 100},
        {'base_t': 2150, 'base_h': 4800, 'base_co2': 600, 'base_lux': 300},
        {'base_t': 2300, 'base_h': 3800, 'base_co2': 450, 'base_lux': 500},
        {'base_t': 1950, 'base_h': 5500, 'base_co2': 380, 'base_lux': 0},
        {'base_t': 2250, 'base_h': 4100, 'base_co2': 550, 'base_lux': 400},
        {'base_t': 2100, 'base_h': 4600, 'base_co2': 410, 'base_lux': 150},
    ]

    state = [dict(r) for r in rooms]
    for n in range(count):
        hour = (n // 6) % 24   # 10min vzorky → 6 za hodinu
        occupied = 8 <= hour <= 18

        vals = []
        for s in state:
            s['base_t']   += random.randint(-5, 5)
            s['base_h']   += random.randint(-30, 30);  s['base_h']  = max(2000, min(8000, s['base_h']))
            s['base_co2'] += random.randint(-10, 20) if occupied else random.randint(-5, 5)
            s['base_co2']  = max(350, min(2000, s['base_co2']))
            s['base_lux']  = s['base_lux'] + random.randint(-20,20) if occupied else 0
            s['base_lux']  = max(0, s['base_lux'])
            vals.append(clamp16(s['base_t']))
            vals.append(clamp16(s['base_h']))

        # 16B paket — teplota a vlhkost prvních 8 místností
        pkt = struct.pack('>8h', *[clamp16(v) for v in vals[:8]])
        packets.append(pkt)
        timestamps.append(f"iot_{n:05d}")

    print(f"  Vygenerováno {len(packets)} vzorků × 16B")
    return packets, timestamps

# ---------------------------------------------------------------------------
# 9. Komplexní stanice 64B — meteo + AQ + GPS + systém
#    32 hodnot × 2B = 64B paket
#    Simuluje reálnou IoT stanici s více senzory
# ---------------------------------------------------------------------------

def generate_complex_64b(count=10000):
    print(f"\n[Komplexní stanice 64B] ({count} vzorků)")
    random.seed(9999)
    packets = []; timestamps = []

    # Počáteční hodnoty
    t     = 2000   # teplota °C×100
    h     = 6000   # vlhkost %×100
    p     = 3800   # tlak (hPa-900)×10
    ws    = 500    # vítr m/s×100
    wd    = 1800   # směr °×10
    rain  = 0      # srážky mm×100
    dp    = 1500   # rosný bod °C×100
    at    = 1900   # zdánlivá teplota
    cc    = 5000   # oblačnost %×100
    sr    = 200    # záření W/m²
    uv    = 30     # UV index×100
    vis   = 10000  # viditelnost m/10
    st0   = 1800   # půda 0cm
    st6   = 1700   # půda 6cm
    st18  = 1600   # půda 18cm
    st54  = 1500   # půda 54cm
    # GPS
    lat   = 4592   # lat×100
    lon   = 1443   # lon×100
    ele   = 250    # nadm.výška m
    spd   = 0      # rychlost km/h×10
    hdg   = 0      # směr °×10
    # Systém
    bat   = 3700   # baterie mV
    rssi  = -80    # RSSI dBm (jako int)
    temp_mcu = 2500 # teplota MCU °C×100
    pm10  = 1500   # PM10 μg/m³×100
    pm25  = 800    # PM2.5
    co    = 200    # CO ppb×10
    no2   = 150    # NO2 μg/m³×100
    o3    = 4000   # O3 μg/m³×100
    so2   = 50     # SO2
    aod   = 100    # aerosol opt. depth×1000
    dust  = 50     # prach μg/m³×100

    for n in range(count):
        # Postupné změny
        t    += random.randint(-20,20)
        h    += random.randint(-50,50);   h    = max(0,min(10000,h))
        p    += random.randint(-10,10)
        ws   += random.randint(-50,50);   ws   = max(0,min(5000,ws))
        wd    = (wd + random.randint(-50,50)) % 3600
        rain  = max(0, rain + random.randint(-10,30))
        dp   += random.randint(-15,15)
        at   += random.randint(-25,25)
        cc   += random.randint(-200,200); cc   = max(0,min(10000,cc))
        sr   += random.randint(-30,30);   sr   = max(0,min(1200,sr))
        uv   += random.randint(-5,5);     uv   = max(0,min(1100,uv))
        vis  += random.randint(-100,100); vis  = max(100,min(10000,vis))
        st0  += random.randint(-5,5)
        st6  += random.randint(-3,3)
        st18 += random.randint(-2,2)
        st54 += random.randint(-1,1)
        lat  += random.randint(-2,2)
        lon  += random.randint(-2,2)
        ele  += random.randint(-5,5)
        spd   = max(0,spd+random.randint(-10,10))
        hdg   = (hdg + random.randint(-20,20)) % 3600
        bat  += random.randint(-5,2);    bat  = max(3000,min(4200,bat))
        rssi += random.randint(-3,3);    rssi = max(-120,min(-40,rssi))
        temp_mcu += random.randint(-10,10)
        pm10 += random.randint(-50,100); pm10 = max(0,min(50000,pm10))
        pm25 += random.randint(-30,60);  pm25 = max(0,min(25000,pm25))
        co   += random.randint(-10,20);  co   = max(0,min(10000,co))
        no2  += random.randint(-10,15);  no2  = max(0,min(5000,no2))
        o3   += random.randint(-20,20);  o3   = max(0,min(10000,o3))
        so2  += random.randint(-5,8);    so2  = max(0,min(2000,so2))
        aod  += random.randint(-10,10);  aod  = max(0,min(5000,aod))
        dust += random.randint(-5,10);   dust = max(0,min(5000,dust))

        pkt = struct.pack('>32h',
            clamp16(t), clamp16(h), clamp16(p), clamp16(ws),
            clamp16(wd), clamp16(rain), clamp16(dp), clamp16(at),
            clamp16(cc), clamp16(sr), clamp16(uv), clamp16(vis),
            clamp16(st0), clamp16(st6), clamp16(st18), clamp16(st54),
            clamp16(lat), clamp16(lon), clamp16(ele), clamp16(spd),
            clamp16(hdg), clamp16(bat), clamp16(rssi), clamp16(temp_mcu),
            clamp16(pm10), clamp16(pm25), clamp16(co), clamp16(no2),
            clamp16(o3), clamp16(so2), clamp16(aod), clamp16(dust),
        )
        packets.append(pkt)
        timestamps.append(f"complex_{n:05d}")

    print(f"  Vygenerováno {len(packets)} vzorků × 64B")
    return packets, timestamps


# ---------------------------------------------------------------------------
# 10. Průmyslový senzor 128B — vibrace + teploty + tlaky + proudy
#     64 hodnot × 2B = 128B paket
#     Simuluje CNC stroj nebo kompresor
# ---------------------------------------------------------------------------

def generate_industrial_128b(count=10000):
    print(f"\n[Průmyslový senzor 128B] ({count} vzorků)")
    random.seed(7777)
    packets = []; timestamps = []

    # 3-osý akcelerometr × 4 body (12 hodnot) — vibrace
    acc = [random.randint(-500,500) for _ in range(12)]
    # Teploty 16 bodů (ložiska, motor, okolí...)
    temps = [random.randint(2000,8000) for _ in range(16)]
    # Tlaky 8 bodů (hydraulika, pneumatika)
    press = [random.randint(1000,30000) for _ in range(8)]
    # Proudy 8 bodů (3 fáze motoru + aux)
    amps  = [random.randint(0,5000) for _ in range(8)]
    # Otáčky, výkon, čas, stav
    rpm   = 15000  # ot/min × 10
    power = 7500   # W × 10
    cycles= 0      # počet cyklů
    state = 1      # stav stroje
    # Zbývajících 20 hodnot — rozšíření (PLC registry, čítače...)
    extra = [random.randint(0,10000) for _ in range(20)]

    for n in range(count):
        # Vibrace — rychlé změny
        acc = [a + random.randint(-100,100) for a in acc]
        # Teploty — pomalé změny
        temps = [t + random.randint(-10,10) for t in temps]
        temps = [max(1500,min(15000,t)) for t in temps]
        # Tlaky
        press = [p + random.randint(-50,50) for p in press]
        press = [max(500,min(40000,p)) for p in press]
        # Proudy
        amps  = [a + random.randint(-20,20) for a in amps]
        amps  = [max(0,min(8000,a)) for a in amps]
        # Otáčky, výkon
        rpm  += random.randint(-100,100); rpm  = max(0,min(30000,rpm))
        power+= random.randint(-200,200); power= max(0,min(50000,power))
        cycles= (cycles + 1) % 32767
        state = random.choice([1,1,1,1,2]) # většinou normální stav
        extra = [e + random.randint(-50,50) for e in extra]
        extra = [max(0,min(32767,e)) for e in extra]

        vals = (acc + temps + press + amps +
                [clamp16(rpm), clamp16(power), clamp16(cycles), clamp16(state)] +
                extra[:16])
        pkt = struct.pack(f'>64h', *[clamp16(v) for v in vals])
        packets.append(pkt)
        timestamps.append(f"cnc_{n:05d}")

    print(f"  Vygenerováno {len(packets)} vzorků × 128B")
    return packets, timestamps




if __name__ == "__main__":
    LIMIT = 10000

    print("=" * 70)
    print("NIC DMD+ — Stahování a analýza reálných dat")
    print("=" * 70)

    all_results = {}

    # --- DWD stanice ---
    for sid in ['00691', '05792', '01975']:
        try:
            pkts, ts = fetch_dwd_synop(sid, LIMIT)
            if pkts:
                name = f"DWD_{DWD_STATIONS[sid].split('(')[0].strip()}_16B"
                r = analyze_packets(pkts, ts, name)
                print_summary(r)
                save_report(r, f"{name}.txt")
                all_results[name] = r
        except Exception as e:
            print(f"  CHYBA: {e}")
        time.sleep(1)

    # --- Open-Meteo forecast 16B ---
    for city, lat, lon in FORECAST_LOCATIONS[:4]:
        try:
            pkts, ts = fetch_open_meteo_forecast(lat, lon, city, LIMIT)
            if pkts:
                name = f"Forecast_{city}_16B"
                r = analyze_packets(pkts, ts, name)
                print_summary(r)
                save_report(r, f"{name}.txt")
                all_results[name] = r
        except Exception as e:
            print(f"  CHYBA: {e}")
        time.sleep(0.5)

    # --- Open-Meteo forecast 32B ---
    for city, lat, lon in FORECAST_LOCATIONS[:2]:
        try:
            pkts, ts = fetch_open_meteo_forecast_32b(lat, lon, city, LIMIT)
            if pkts:
                name = f"Forecast_{city}_32B"
                r = analyze_packets(pkts, ts, name)
                print_summary(r)
                save_report(r, f"{name}.txt")
                all_results[name] = r
        except Exception as e:
            print(f"  CHYBA: {e}")
        time.sleep(0.5)

    # --- Open-Meteo Air Quality ---
    for city, lat, lon in FORECAST_LOCATIONS[:3]:
        try:
            pkts, ts = fetch_open_meteo_airquality(lat, lon, city, LIMIT)
            if pkts:
                name = f"AirQuality_{city}_16B"
                r = analyze_packets(pkts, ts, name)
                print_summary(r)
                save_report(r, f"{name}.txt")
                all_results[name] = r
        except Exception as e:
            print(f"  CHYBA: {e}")
        time.sleep(0.5)

    # --- USGS Earthquake ---
    try:
        pkts, ts = fetch_usgs_earthquakes(LIMIT)
        if pkts:
            r = analyze_packets(pkts, ts, "USGS_Earthquake_16B")
            print_summary(r)
            save_report(r, "USGS_Earthquake_16B.txt")
            all_results["USGS_Earthquake_16B"] = r
    except Exception as e:
        print(f"  CHYBA USGS: {e}")

    # --- NOAA Tides ---
    for sid in ['8518750', '9414290']:
        try:
            pkts, ts = fetch_noaa_tides(sid, LIMIT)
            if pkts:
                name = f"NOAA_{NOAA_STATIONS[sid].replace(' ','_')}_16B"
                r = analyze_packets(pkts, ts, name)
                print_summary(r)
                save_report(r, f"{name}.txt")
                all_results[name] = r
        except Exception as e:
            print(f"  CHYBA NOAA: {e}")
        time.sleep(1)

    # --- Offline generátory ---
    for gen_fn, name in [
        (lambda: generate_gps_trek(LIMIT),        "GPS_Trek_16B"),
        (lambda: generate_smartmeter(LIMIT),       "Elektromery_16B"),
        (lambda: generate_iot_building(LIMIT),     "IoT_Budova_16B"),
        (lambda: generate_complex_64b(LIMIT),      "Komplexni_stanice_64B"),
        (lambda: generate_industrial_128b(LIMIT),  "Prumyslovy_senzor_128B"),
    ]:
        try:
            pkts, ts = gen_fn()
            if pkts:
                r = analyze_packets(pkts, ts, name)
                print_summary(r)
                save_report(r, f"{name}.txt")
                all_results[name] = r
        except Exception as e:
            print(f"  CHYBA {name}: {e}")

    # --- Globální souhrn ---
    print(f"\n{'='*70}")
    print("GLOBÁLNÍ SOUHRN")
    print(f"{'='*70}")
    print(f"{'Dataset':<35} {'Paketů':>7} {'Úspora%':>8} {'Chyby':>6}")
    print(f"{'-'*70}")
    for name, r in all_results.items():
        if not r: continue
        orig  = sum(x['original_len']+1 for x in r)
        comp  = sum(x['compressed_len'] for x in r)
        errs  = sum(1 for x in r if not x['roundtrip_ok'])
        pct   = (1-comp/orig)*100 if orig > 0 else 0
        print(f"  {name:<33} {len(r):>7} {pct:>7.1f}% {errs:>6}")
    print(f"{'='*70}")
    print(f"\nReporty uloženy v: {OUTPUT_DIR}/")
    print("Hotovo!")
