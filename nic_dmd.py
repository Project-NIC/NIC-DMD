"""
NIC DMD — Delta Markov Duda
===========================
Adaptivní komprese pro malé procesory a LoRa přenos.

Záhlaví (1 bajt):
  MSB                    LSB
   7    6    5    4    3    2    1    0
  [rez][ans][flg][dlt][dlt][vzo][vzo][vzo]

  bit 7:   rezerva (pro DMD+)
  bit 6:   µANS komprese (1=ON)
  bit 5:   flagování nulových bajtů (1=ON)
  bit 4-3: delta: 00=žádná, 01=1B, 10=2B, 11=celý vzorek
  bit 2-0: číslo vzorku 0-7 (0 = keyframe)

Licence: GPL v3
NIC — Native Intellect Community
https://github.com/Project-NIC
"""

import math

# ---------------------------------------------------------------------------
# Konstanty
# ---------------------------------------------------------------------------

ANS_SCALE    = 32
ANS_WEIGHT_0 = 29
ANS_WEIGHT_1 = 3

DELTA_NONE = 0
DELTA_1B   = 1
DELTA_2B   = 2
DELTA_FULL = 3

DMD_KEYFRAME_EVERY = 8

# ---------------------------------------------------------------------------
# Záhlaví
# ---------------------------------------------------------------------------

def _build_header(sample_num: int, use_ans: bool,
                  use_flag: bool, delta_type: int) -> int:
    h  = 0
    h |= (1 << 6) if use_ans  else 0
    h |= (1 << 5) if use_flag else 0
    h |= (delta_type & 0x03) << 3
    h |= (sample_num & 0x07)
    return h


def _parse_header(h: int) -> dict:
    return {
        'use_ans':    bool(h & (1 << 6)),
        'use_flag':   bool(h & (1 << 5)),
        'delta_type': (h >> 3) & 0x03,
        'sample_num': h & 0x07,
    }

# ---------------------------------------------------------------------------
# ZigZag — pouze pokud delta != NONE
# ---------------------------------------------------------------------------

def _zigzag_enc(x: int) -> int:
    s = x if x <= 127 else x - 256
    return ((s << 1) ^ (s >> 7)) & 0xFF


def _zigzag_dec(x: int) -> int:
    return ((x >> 1) ^ -(x & 1)) & 0xFF


def zigzag_encode(data: bytes) -> bytes:
    return bytes(_zigzag_enc(b) for b in data)


def zigzag_decode(data: bytes) -> bytes:
    return bytes(_zigzag_dec(b) for b in data)

# ---------------------------------------------------------------------------
# Delta
# ---------------------------------------------------------------------------

def delta_encode(current: bytes, previous: bytes, delta_type: int) -> bytes:
    n = len(current)

    if delta_type in (DELTA_1B, DELTA_FULL):
        return bytes((current[i] - previous[i]) & 0xFF for i in range(n))

    # DELTA_2B
    result = bytearray(n)
    i = 0
    while i < n:
        if i + 1 < n:
            c = (current[i] << 8) | current[i + 1]
            p = (previous[i] << 8) | previous[i + 1]
            d = (c - p) & 0xFFFF
            result[i]     = (d >> 8) & 0xFF
            result[i + 1] = d & 0xFF
            i += 2
        else:
            result[i] = (current[i] - previous[i]) & 0xFF
            i += 1
    return bytes(result)


def delta_decode(data: bytes, previous: bytes, delta_type: int) -> bytes:
    n = len(data)

    if delta_type in (DELTA_1B, DELTA_FULL):
        return bytes((data[i] + previous[i]) & 0xFF for i in range(n))

    # DELTA_2B
    result = bytearray(n)
    i = 0
    while i < n:
        if i + 1 < n:
            d = (data[i] << 8) | data[i + 1]
            p = (previous[i] << 8) | previous[i + 1]
            o = (d + p) & 0xFFFF
            result[i]     = (o >> 8) & 0xFF
            result[i + 1] = o & 0xFF
            i += 2
        else:
            result[i] = (data[i] + previous[i]) & 0xFF
            i += 1
    return bytes(result)

# ---------------------------------------------------------------------------
# Popcount heuristika
# ---------------------------------------------------------------------------

def _popcount(x: int) -> int:
    x = x - ((x >> 1) & 0x55)
    x = (x & 0x33) + ((x >> 2) & 0x33)
    return (x + (x >> 4)) & 0x0F


def _count_onebits(data: bytes) -> int:
    return sum(_popcount(b) for b in data)

# ---------------------------------------------------------------------------
# µANS
# Výstup: [1B délka vstupních dat][2B state big-endian][zakódované bajty]
# Zahod pokud výsledek >= vstup - 3B
# ---------------------------------------------------------------------------

def _uans_encode(data: bytes) -> bytes | None:
    n      = len(data)
    state  = ANS_SCALE
    output = []

    for byte in reversed(data):
        for j in range(8):
            bit    = (byte >> j) & 1
            weight = ANS_WEIGHT_0 if bit == 0 else ANS_WEIGHT_1

            while state >= weight * 256:
                output.append(state & 0xFF)
                state >>= 8

            state = (state // weight) * ANS_SCALE \
                  + (0 if bit == 0 else ANS_WEIGHT_0) \
                  + (state % weight)

    encoded = bytes([n]) + state.to_bytes(2, 'big') + bytes(reversed(output))

    if len(encoded) >= n - 3:
        return None

    return encoded


def _uans_decode(data: bytes) -> bytes:
    length = data[0]
    state  = int.from_bytes(data[1:3], 'big')
    stream = list(data[3:])
    result = bytearray(length)

    for i in range(length):
        byte = 0
        for j in range(8):
            pos = state % ANS_SCALE
            if pos < ANS_WEIGHT_0:
                bit    = 0
                weight = ANS_WEIGHT_0
                offset = pos
            else:
                bit    = 1
                weight = ANS_WEIGHT_1
                offset = pos - ANS_WEIGHT_0

            byte  |= (bit << j)
            state  = weight * (state // ANS_SCALE) + offset

            if state < ANS_SCALE and stream:
                state = (state << 8) | stream.pop(0)

        rev = 0
        for j in range(8):
            rev |= ((byte >> j) & 1) << (7 - j)
        result[i] = rev

    return bytes(result)

# ---------------------------------------------------------------------------
# Flagování nulových bajtů
# Formát: [1B délka][⌈N/8⌉B mapa][nenulové bajty]
# Zahod pokud počet_nul <= (1 + ⌈N/8⌉)
# ---------------------------------------------------------------------------

def _flag_estimated_size(data: bytes) -> int | None:
    n        = len(data)
    zeros    = sum(1 for b in data if b == 0)
    map_size = math.ceil(n / 8)

    if zeros <= (1 + map_size):
        return None

    return 1 + map_size + (n - zeros)


def _flag_encode(data: bytes) -> bytes:
    n        = len(data)
    map_size = math.ceil(n / 8)
    flag_map = bytearray(map_size)
    non_zero = bytearray()

    for i, b in enumerate(data):
        if b == 0:
            flag_map[i // 8] |= (1 << (7 - (i % 8)))
        else:
            non_zero.append(b)

    return bytes([n]) + bytes(flag_map) + bytes(non_zero)


def _flag_decode(data: bytes) -> bytes:
    n        = data[0]
    map_size = math.ceil(n / 8)
    flag_map = data[1:1 + map_size]
    non_zero = list(data[1 + map_size:])
    result   = bytearray(n)
    nz_idx   = 0

    for i in range(n):
        if flag_map[i // 8] & (1 << (7 - (i % 8))):
            result[i] = 0
        else:
            result[i] = non_zero[nz_idx]
            nz_idx += 1

    return bytes(result)

# ---------------------------------------------------------------------------
# Komprese jednoho paketu
# ---------------------------------------------------------------------------

def dmd_compress(current: bytes, previous: bytes, sample_num: int) -> bytes:
    """
    Komprese jednoho paketu.
    Vrátí komprimovaná data včetně záhlaví (1B).
    """
    is_keyframe = (sample_num == 0)

    # Krok 1: Delta + ZigZag — keyframe přeskočí
    if is_keyframe:
        work       = current
        delta_type = DELTA_NONE
    else:
        best_dt    = DELTA_NONE
        best_score = _count_onebits(current)
        best_work  = current

        for dt in (DELTA_1B, DELTA_2B, DELTA_FULL):
            d     = delta_encode(current, previous, dt)
            zz    = zigzag_encode(d)
            score = _count_onebits(zz)
            if score < best_score:
                best_score = score
                best_dt    = dt
                best_work  = zz

        delta_type = best_dt
        work       = best_work

    # Krok 2: ANS
    ans_data = _uans_encode(work)

    # Krok 3: Flagování
    flag_size = _flag_estimated_size(work)

    # Krok 4: Vyber nejmenší
    use_ans  = False
    use_flag = False
    payload  = current    # RAW záchrana

    if ans_data is not None and flag_size is not None:
        if len(ans_data) <= flag_size:
            use_ans  = True
            payload  = ans_data
        else:
            use_flag = True
            payload  = _flag_encode(work)
    elif ans_data is not None:
        use_ans = True
        payload = ans_data
    elif flag_size is not None:
        use_flag = True
        payload  = _flag_encode(work)

    # RAW záchrana — žádná delta
    if not use_ans and not use_flag:
        delta_type = DELTA_NONE

    header = _build_header(sample_num, use_ans, use_flag, delta_type)
    return bytes([header]) + payload


# ---------------------------------------------------------------------------
# Dekomprese jednoho paketu
# ---------------------------------------------------------------------------

def dmd_decompress(data: bytes, previous: bytes) -> bytes:
    """
    Dekomprese jednoho paketu.
    previous musí mít stejnou délku jako původní paket.
    """
    h          = _parse_header(data[0])
    payload    = data[1:]
    delta_type = h['delta_type']

    # Vrstva 1: dekomprimuj payload
    if h['use_ans']:
        work = _uans_decode(payload)
    elif h['use_flag']:
        work = _flag_decode(payload)
    else:
        work = payload

    # Vrstva 2: inverzní ZigZag + inverzní delta
    if delta_type != DELTA_NONE:
        work = zigzag_decode(work)
        work = delta_decode(work, previous, delta_type)

    return work


# ---------------------------------------------------------------------------
# Stavový enkodér / dekodér
# ---------------------------------------------------------------------------

class DmdEncoder:
    """Stavový enkodér — jeden objekt na komunikační kanál."""

    def __init__(self, pkt_len: int):
        self.pkt_len    = pkt_len
        self.previous   = bytes(pkt_len)
        self.sample_num = 0

    def compress(self, data: bytes) -> bytes:
        assert len(data) == self.pkt_len, \
            f"Délka dat {len(data)} != pkt_len {self.pkt_len}"
        result          = dmd_compress(data, self.previous, self.sample_num)
        self.previous   = data
        self.sample_num = (self.sample_num + 1) % DMD_KEYFRAME_EVERY
        return result

    def reset(self):
        self.previous   = bytes(self.pkt_len)
        self.sample_num = 0


class DmdDecoder:
    """Stavový dekodér — jeden objekt na komunikační kanál."""

    def __init__(self, pkt_len: int):
        self.pkt_len  = pkt_len
        self.previous = bytes(pkt_len)

    def decompress(self, data: bytes) -> bytes:
        result        = dmd_decompress(data, self.previous)
        self.previous = result
        return result

    def reset(self):
        self.previous = bytes(self.pkt_len)
