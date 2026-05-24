"""
Srovnání kompresních metod pro embedded / LoRa
===============================================
Férové srovnání — každá metoda vrátí kompletní paket připravený na přenos.
Stejně jako NIC protokol — záhlaví + vše co dekodér potřebuje.

Formát paketů:
  NIC:       [1B záhlaví][payload — vše co dekodér potřebuje]
  RAW:       [1B typ=0x00][data]
  Heatshrink:[1B typ][1B délka orig][komprimovaná data]
  Huffman:   [1B typ][1B délka orig][1B platných bitů v posl.bajtu][bity]

Záchrana: pokud komprimovaný paket >= RAW → pošli RAW

Závislosti: pip install requests heatshrink2
"""

import struct, math, heapq, random, sys
import requests
import heatshrink2
from collections import defaultdict

from nic_dmd import (
    delta_encode,
    zigzag_encode,
    DELTA_FULL,
    DmdEncoder,
    DmdDecoder,
)
from nic_dmd_utils import dmd_analyze_packets as analyze_packets, dmd_print_summary

    
# ---------------------------------------------------------------------------
# Převod dat
# ---------------------------------------------------------------------------

def pack_16b(row):
    return struct.pack('>8h', *[max(-32768,min(32767,v)) for v in row])

def pack_32b(row):
    return struct.pack('>16h', *[max(-32768,min(32767,v)) for v in row])

def fv(v, scale, default=0.0):
    return int(round((v if v is not None else default) * scale))

def fetch_open_meteo(lat, lon, start, end):
    import time
    from datetime import datetime, timedelta
    variables = [
        "temperature_2m","relative_humidity_2m","surface_pressure",
        "wind_speed_10m","wind_direction_10m","precipitation",
        "dew_point_2m","apparent_temperature","cloud_cover",
        "shortwave_radiation","uv_index","visibility",
        "soil_temperature_0cm","soil_temperature_6cm",
        "soil_temperature_18cm","soil_temperature_54cm",
    ]
    url = "https://archive-api.open-meteo.com/v1/archive"
    session = requests.Session()
    session.headers.update({'User-Agent': 'DMD-Benchmark/1.0'})
    dt_s = datetime.strptime(start, "%Y-%m-%d")
    dt_e = datetime.strptime(end,   "%Y-%m-%d")
    chunks, cur = [], dt_s
    while cur < dt_e:
        nxt = min(cur + timedelta(days=60), dt_e)
        chunks.append((cur.strftime("%Y-%m-%d"), nxt.strftime("%Y-%m-%d")))
        cur = nxt + timedelta(days=1)
    all_data = {}
    for i, (s, e) in enumerate(chunks):
        params = {"latitude":lat,"longitude":lon,"start_date":s,"end_date":e,
                  "hourly":",".join(variables),"timezone":"UTC","wind_speed_unit":"ms"}
        for attempt in range(3):
            try:
                r = session.get(url, params=params, timeout=30)
                r.raise_for_status()
                chunk = r.json()["hourly"]
                for key, vals in chunk.items():
                    if key not in all_data: all_data[key] = []
                    all_data[key].extend(vals)
                time.sleep(1)
                break
            except Exception as ex:
                if attempt < 2: time.sleep(5)
                else: raise
    return all_data

def to_packets(h, bits=16, limit=2000):
    n = min(limit, len(h['time']))
    def g(key, d=0.0, i=0):
        v = h.get(key,[d]*n)[i]
        return v if v is not None else d

    packets = []
    for i in range(n):
        if bits == 16:
            row = [fv(g('temperature_2m',0,i),100),
                   fv(g('relative_humidity_2m',0,i),100),
                   fv(g('surface_pressure',1013,i)-900,10),
                   fv(g('wind_speed_10m',0,i),100),
                   fv(g('precipitation',0,i),100),
                   fv(g('soil_temperature_0cm',0,i),100),
                   fv(g('soil_temperature_6cm',0,i),100),
                   fv(g('dew_point_2m',0,i),100)]
            packets.append(pack_16b(row))
        else:
            row = [fv(g('temperature_2m',0,i),100),
                   fv(g('relative_humidity_2m',0,i),100),
                   fv(g('surface_pressure',1013,i)-900,10),
                   fv(g('wind_speed_10m',0,i),100),
                   fv(g('wind_direction_10m',0,i),10),
                   fv(g('precipitation',0,i),100),
                   fv(g('dew_point_2m',0,i),100),
                   fv(g('apparent_temperature',0,i),100),
                   fv(g('cloud_cover',0,i),100),
                   fv(g('shortwave_radiation',0,i),1),
                   fv(g('uv_index',0,i),100),
                   fv(g('visibility',10000,i)/100,10),
                   fv(g('soil_temperature_0cm',0,i),100),
                   fv(g('soil_temperature_6cm',0,i),100),
                   fv(g('soil_temperature_18cm',0,i),100),
                   fv(g('soil_temperature_54cm',0,i),100)]
            packets.append(pack_32b(row))
    return packets

# ---------------------------------------------------------------------------
# Huffman
# ---------------------------------------------------------------------------

def build_huffman(packets_sample):
    freq = defaultdict(int)
    prev = packets_sample[0]
    for pkt in packets_sample[1:]:
        for b in zigzag_encode(delta_encode(pkt, prev, DELTA_FULL)):
            freq[b] += 1
        prev = pkt
    heap = [[f,[s,""]] for s,f in freq.items()]
    heapq.heapify(heap)
    if len(heap)==1: heapq.heappush(heap,[1,[256,""]])
    while len(heap)>1:
        lo,hi = heapq.heappop(heap), heapq.heappop(heap)
        for p in lo[1:]: p[1]='0'+p[1]
        for p in hi[1:]: p[1]='1'+p[1]
        heapq.heappush(heap,[lo[0]+hi[0]]+lo[1:]+hi[1:])
    return {s:c for s,c in heap[0][1:]}

# Statická tabulka natrénovaná na neutrálních datech
random.seed(999)
_sp = []
_t,_h,_p,_w = -500,7000,3850,800
for _ in range(500):
    _t+=random.randint(-50,50); _h+=random.randint(-200,200)
    _p+=random.randint(-20,20); _w+=random.randint(-300,300)
    _sp.append(pack_16b([_t,max(0,min(10000,_h)),max(0,_p),
                          max(0,_w),0,_t-500,_t-300,_t-400]))
STATIC_CODES = build_huffman(_sp)
STATIC_TABLE_ROM_BYTES = sum(math.ceil(len(c)/8)+1 for c in STATIC_CODES.values())


def huffman_encode_packet(pkt, prev, codes, typ_byte):
    """
    Zakóduje jeden paket Huffmanem do přenosového formátu.
    Formát: [1B typ][1B délka orig][1B platných bitů][bity v bajtech]
    Záchrana: [1B typ=0xFF][data] pokud větší než RAW
    """
    after = zigzag_encode(delta_encode(pkt, prev, DELTA_FULL))

    # Zakóduj do bitového řetězce
    bits = ""
    for b in after:
        bits += codes.get(b, "1"*8)

    # Zaokrouhli na celé bajty
    valid_bits = len(bits)
    while len(bits) % 8 != 0:
        bits += "0"

    # Převeď bity na bajty
    comp_bytes = bytearray()
    for i in range(0, len(bits), 8):
        byte = int(bits[i:i+8], 2)
        comp_bytes.append(byte)

    # Kompletní paket:
    # [1B typ][1B délka orig][1B počet platných bitů v posledním bajtu][data]
    last_byte_bits = valid_bits % 8 or 8  # 0 → 8 (celý bajt platný)
    packet = bytes([typ_byte, len(pkt), last_byte_bits]) + bytes(comp_bytes)

    # Záchrana — pokud větší nebo rovno RAW
    raw_packet = bytes([0xFF]) + pkt
    if len(packet) >= len(raw_packet):
        return raw_packet, True
    return packet, False


# ---------------------------------------------------------------------------
# Kompresní metody — kompletní přenosové pakety
# ---------------------------------------------------------------------------

def method_raw(packets):
    """RAW — [1B typ=0x00][data]"""
    total_orig = total_comp = 0
    for pkt in packets:
        raw = bytes([0x00]) + pkt
        total_orig += len(raw)
        total_comp += len(raw)
    return total_orig, total_comp, 0


def method_DMD(packets):
    """DMD"""
    results = analyze_packets(packets, source_name="DMD")
    orig    = sum(r['original_len'] + 1 for r in results)
    comp    = sum(r['compressed_len'] for r in results)
    savings = sum(1 for r in results
                  if r['compressed_len'] < r['original_len'] + 1)
    return orig, comp, savings


def method_heatshrink(packets, window=8, lookahead=4):
    """
    Heatshrink — [1B typ][1B délka orig][komprimovaná data]
    Záchrana pokud větší než RAW.
    """
    total_orig = total_comp = savings = 0
    for pkt in packets:
        comp = heatshrink2.compress(pkt,
               window_sz2=window, lookahead_sz2=lookahead)
        # Přenosový paket
        hs_packet  = bytes([0x01, len(pkt)]) + comp
        raw_packet = bytes([0xFF]) + pkt

        total_orig += len(raw_packet)
        if len(hs_packet) < len(raw_packet):
            total_comp += len(hs_packet)
            savings += 1
        else:
            total_comp += len(raw_packet)  # záchrana
    return total_orig, total_comp, savings


def method_huffman_static(packets):
    """
    Delta+Huffman statická ROM.
    Formát: [1B typ][1B délka orig][1B platných bitů][bity]
    Tabulka v ROM — nepřenáší se.
    """
    total_orig = total_comp = savings = 0
    prev = packets[0]
    # První paket = RAW
    raw = bytes([0xFF]) + packets[0]
    total_orig += len(raw)
    total_comp += len(raw)

    for pkt in packets[1:]:
        packet, rescued = huffman_encode_packet(pkt, prev, STATIC_CODES, 0x02)
        raw_packet = bytes([0xFF]) + pkt
        total_orig += len(raw_packet)
        total_comp += len(packet)
        if not rescued:
            savings += 1
        prev = pkt
    return total_orig, total_comp, savings


def method_huffman_dynamic(packets):
    """
    Delta+Huffman dynamická tabulka.
    Trénink na prvních 20% — odděleno od testu.
    Tabulka se přenáší jednou (~695B).
    Formát: [1B typ][1B délka orig][1B platných bitů][bity]
    """
    split = max(10, len(packets)//5)
    train = packets[:split]
    test  = packets[split:]

    codes = build_huffman(train)
    # Overhead tabulky přenášené jednou na začátek session
    table_overhead = sum(math.ceil(len(c)/8)+1 for c in codes.values())

    total_orig = total_comp = savings = 0
    total_comp += table_overhead  # tabulka přenášená jednou

    prev = test[0]
    raw = bytes([0xFF]) + test[0]
    total_orig += len(raw)
    total_comp += len(raw)

    for pkt in test[1:]:
        packet, rescued = huffman_encode_packet(pkt, prev, codes, 0x03)
        raw_packet = bytes([0xFF]) + pkt
        total_orig += len(raw_packet)
        total_comp += len(packet)
        if not rescued:
            savings += 1
        prev = pkt
    return total_orig, total_comp, savings

# ---------------------------------------------------------------------------
# Srovnání
# ---------------------------------------------------------------------------

METHODS = [
    ("RAW (bez komprese)",
     method_raw, "0B"),
    ("DMD protokol",
     method_DMD, "~80-230B"),
    ("Heatshrink (w=8,l=4)",
     lambda p: method_heatshrink(p,8,4), "~256B"),
    ("Heatshrink (w=10,l=5)",
     lambda p: method_heatshrink(p,10,5), "~1024B"),
    ("Delta+Huffman (statická ROM)",
     method_huffman_static, f"~{STATIC_TABLE_ROM_BYTES}B ROM"),
    ("Delta+Huffman (dynamická)",
     method_huffman_dynamic, "~695B+send"),
  
]

def compare(packets, name, pkt_size):
    print(f"\n{'='*72}")
    print(f"Zdroj: {name} | Pakety: {len(packets)} × {pkt_size}B")
    print(f"{'='*72}")
    print(f"{'Metoda':<32} | {'Orig':>7} | {'Komp':>7} | {'Úspora':>7} | {'RAM':<14}")
    print(f"{'-'*72}")

    results = {}
    for label, fn, ram in METHODS:
        try:
            orig, comp, savings = fn(packets)
            saving = round((1-comp/orig)*100, 1) if orig > 0 else 0.0
            results[label] = saving
            print(f"{label:<32} | {orig:>7} | {comp:>7} | "
                  f"{saving:>6.1f}% | {ram:<14}")
        except Exception as e:
            print(f"{label:<32} | CHYBA: {e}")

    print(f"{'='*72}")
    if results:
        winner = max(results, key=results.get)
        print(f"Vítěz: {winner} ({results[winner]:.1f}%)")
    return results


# ---------------------------------------------------------------------------
# Hlavní spuštění
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    LIMIT = 2000

    SOURCES = [
        ("Sněžka (CZ)",        50.7364,  15.7394),
        ("Antarktida",         -90.0,      0.0  ),
        ("Death Valley (USA)", 36.4614, -116.8675),
        ("Ojmjakon (RU)",      63.4608,  142.7858),
        ("Sahara (DZ)",        27.1967,    2.4643),
    ]

    all_results = {}

    for name, lat, lon in SOURCES:
        print(f"\nStahuji: {name}...")
        try:
            h = fetch_open_meteo(lat, lon, "2020-01-01", "2020-04-01")
            for bits in [16, 32]:
                packets = to_packets(h, bits, LIMIT)
                key = f"{name} {bits}B"
                all_results[key] = compare(packets, key, bits)
        except Exception as e:
            print(f"  CHYBA: {e}")

    # Globální souhrn
    print(f"\n{'='*72}")
    print("GLOBÁLNÍ SOUHRN — průměrná úspora přes všechny zdroje")
    print(f"{'='*72}")
    print(f"{'Metoda':<32} | {'Průměr':>7} | {'Min':>7} | {'Max':>7}")
    print(f"{'-'*72}")

    totals = defaultdict(list)
    for res in all_results.values():
        for method, saving in res.items():
            totals[method].append(saving)

    for label, _, _ in METHODS:
        if label in totals:
            vals = totals[label]
            print(f"{label:<32} | {sum(vals)/len(vals):>6.1f}% | "
                  f"{min(vals):>6.1f}% | {max(vals):>6.1f}%")

    print(f"{'='*72}")
    print(f"\nPoznámky k přenosovému formátu:")
    print(f"  DMD:       [1B záhlaví][payload] — záhlaví obsahuje vše pro dekodér")
    print(f"  RAW:       [1B typ][data]")
    print(f"  Heatshrink:[1B typ][1B délka orig][komprimovaná data]")
    print(f"  Huffman:   [1B typ][1B délka orig][1B platných bitů][bity]")
    print(f"  — Huffman statická: tabulka {STATIC_TABLE_ROM_BYTES}B v ROM, nepřenáší se")
    print(f"  — Huffman dynamická: tabulka ~695B přenášena jednou na začátek")
    print(f"\nHotovo!")
