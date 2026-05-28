# SPDX-License-Identifier: MIT

"""
NIC DMD — Delta Markov Duda
===========================
Adaptivní komprese pro embeded.
Nibble Huffman komprese integrována jako standardní metoda.

Záhlaví (1 bajt):
  MSB                    LSB
   7    6    5    4    3    2    1    0
  [huf][ans][flg][dlt][dlt][vzo][vzo][vzo]

  bit 7:   nibble Huffman (1=ON)
  bit 6:   µANS komprese (1=ON)
  bit 5:   flagování nulových bajtů (1=ON)
  bit 4-3: delta: 00=žádná, 01=1B, 10=2B, 11=FULL (big-int s carry)
  bit 2-0: číslo vzorku 0-6 (0 = keyframe, 7 = vyhrazeno pro verzi protokolu)

  Kombinace bit 7 + bit 5 = FLAG+HUF

Poznámky k implementaci:
  Kód odpovídá C implementaci na ATmega328 — stejná logika,
  stejné datové typy (uint8_t / uint16_t), stejné optimalizace:
  [Z1] µANS state = uint16_t (rozsah 32..8191)
  [Z2] uint8_t indexy ve smyčkách
  [Z3] popcount LUT (256B ROM v C, tuple v Pythonu)
  [Z4] rotující maska v FLAG místo variable shift
  [Z5] delta + ZigZag v jednom průchodu
  [Z6] ANS rotace bajtu místo (byte >> j) & 1
  [Z7] ANS skládání bajtu shiftem doleva (žádná reverze v dekodéru)
  [Z8] ANS countdown smyčka (od len-1 dolů)
  [P3] HUF bit buffer uint16_t s flush per nibble
  [P4] DELTA_FULL — big-int s carry propagací
  [P5] ANS early exit per bajt
  [P6] FLAG early exit per bajt, rotující maska
  [P7] FLAG+HUF kombinovaný režim
  [P8] 4-cestný výběr s předáváním best_size jako limitu

Licence: MIT
NIC — Native Intellect Community
https://github.com/Project-NIC
"""

__version__ = "0.1.0"

# ---------------------------------------------------------------------------
# Konstanty — odpovídají #define v C hlavičce
# ---------------------------------------------------------------------------

# Kalibrováno na kombinovaný meteo+GPS dataset (viz benchmarky)
ANS_SCALE    = 32    # uint8_t
ANS_WEIGHT_0 = 29    # uint8_t — váha nulového bitu
ANS_WEIGHT_1 = 3     # uint8_t — váha jedničkového bitu

DELTA_NONE = 0
DELTA_1B   = 1
DELTA_2B   = 2
DELTA_FULL = 3       # [P4] big-int s carry propagací

# Hodnota 7 u vzorku je vyhrazena pro verzování protokolu, cyklus je tedy zkrácen
DMD_KEYFRAME_EVERY = 7

# ---------------------------------------------------------------------------
# [Z3] Popcount LUT — 256 hodnot, odpovídá PROGMEM tabulce v C
# ---------------------------------------------------------------------------

_POPCOUNT_LUT = (
    0,1,1,2,1,2,2,3, 1,2,2,3,2,3,3,4, 1,2,2,3,2,3,3,4, 2,3,3,4,3,4,4,5,
    1,2,2,3,2,3,3,4, 2,3,3,4,3,4,4,5, 2,3,3,4,3,4,4,5, 3,4,4,5,4,5,5,6,
    1,2,2,3,2,3,3,4, 2,3,3,4,3,4,4,5, 2,3,3,4,3,4,4,5, 3,4,4,5,4,5,5,6,
    2,3,3,4,3,4,4,5, 3,4,4,5,4,5,5,6, 3,4,4,5,4,5,5,6, 4,5,5,6,5,6,6,7,
    1,2,2,3,2,3,3,4, 2,3,3,4,3,4,4,5, 2,3,3,4,3,4,4,5, 3,4,4,5,4,5,5,6,
    2,3,3,4,3,4,4,5, 3,4,4,5,4,5,5,6, 3,4,4,5,4,5,5,6, 4,5,5,6,5,6,6,7,
    2,3,3,4,3,4,4,5, 3,4,4,5,4,5,5,6, 3,4,4,5,4,5,5,6, 4,5,5,6,5,6,6,7,
    3,4,4,5,4,5,5,6, 4,5,5,6,5,6,6,7, 4,5,5,6,5,6,6,7, 5,6,6,7,6,7,7,8,
)

def _count_onebits(data: bytes) -> int:
    """Počet jedničkových bitů — odpovídá count_ones() v C."""
    n = 0
    for b in data:
        n += _POPCOUNT_LUT[b]
    return n

# ---------------------------------------------------------------------------
# [P2] Pevná nibble Huffman tabulka v ROM
# Natrénovaná na kombinovaných datech (meteo + GPS) po delta+ZZ
# 64B ROM — hi nibble kódy + lo nibble kódy
# ---------------------------------------------------------------------------

_HUF_HI_LEN  = (1, 3, 3, 4, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6)
_HUF_HI_CODE = (
    0x01,  # 0x0
    0x03,  # 0x1
    0x00,  # 0x2
    0x04,  # 0x3
    0x0D,  # 0x4
    0x0C,  # 0x5
    0x0E,  # 0x6
    0x16,  # 0x7
    0x15,  # 0x8
    0x17,  # 0x9
    0x0F,  # 0xA
    0x14,  # 0xB
    0x0B,  # 0xC
    0x0A,  # 0xD
    0x08,  # 0xE
    0x09,  # 0xF
)

_HUF_LO_LEN  = (1, 4, 4, 5, 4, 5, 5, 5, 5, 5, 5, 5, 6, 6, 6, 6)
_HUF_LO_CODE = (
    0x01,  # 0x0
    0x04,  # 0x1
    0x07,  # 0x2
    0x0B,  # 0x3
    0x03,  # 0x4
    0x04,  # 0x5
    0x0A,  # 0x6
    0x03,  # 0x7
    0x05,  # 0x8
    0x02,  # 0x9
    0x00,  # 0xA
    0x01,  # 0xB
    0x1B,  # 0xC
    0x1A,  # 0xD
    0x19,  # 0xE
    0x18,  # 0xF
)

# [N1] Precomputované masky pro optimalizaci bitových operací
_MASKS = (0x00, 0x01, 0x03, 0x07, 0x0F, 0x1F, 0x3F, 0x7F, 0xFF)

# ---------------------------------------------------------------------------
# [P3] Nibble Huffman enkódování
# Bit buffer uint16_t s flush per nibble — přesně jako C implementace.
# Formát výstupu: [1B platných bitů v posl. bajtu][stream MSB-first]
# ---------------------------------------------------------------------------

def _huffman_encode(data: bytes, limit: int) -> bytes | None:
    """
    Zakóduj data nibble Huffmanem.
    limit = max přípustná délka výstupu včetně 1B hlavičky.
    Vrátí None pokud výsledek >= limit. [P3] early exit.
    """
    if limit < 2:
        return None

    # [P3] uint16_t bit buffer s flush per nibble
    bit_buf    = 0       # uint16_t
    bit_cnt    = 0       # uint8_t
    out        = bytearray(limit)
    out_pos    = 1       # out[0] vyhradíme pro "valid bits"
    total_bits = 0
    bits_cap   = (limit - 1) * 8   # uint16_t

    for b in data:
        hi = b >> 4
        lo = b & 0x0F

        hi_len  = _HUF_HI_LEN[hi]
        hi_code = _HUF_HI_CODE[hi]
        lo_len  = _HUF_LO_LEN[lo]
        lo_code = _HUF_LO_CODE[lo]

        total_bits += hi_len + lo_len
        if total_bits > bits_cap:   # [P3] early exit
            return None

        # Emit hi nibble
        bit_buf = ((bit_buf << hi_len) | hi_code) & 0xFFFF
        bit_cnt += hi_len
        while bit_cnt >= 8:
            bit_cnt -= 8
            out[out_pos] = (bit_buf >> bit_cnt) & 0xFF
            out_pos += 1
        bit_buf &= (1 << bit_cnt) - 1

        # Emit lo nibble
        bit_buf = ((bit_buf << lo_len) | lo_code) & 0xFFFF
        bit_cnt += lo_len
        while bit_cnt >= 8:
            bit_cnt -= 8
            out[out_pos] = (bit_buf >> bit_cnt) & 0xFF
            out_pos += 1
        bit_buf &= (1 << bit_cnt) - 1

    # Flush zbývající bity — zarovnání k MSB
    if bit_cnt > 0:
        out[out_pos] = (bit_buf << (8 - bit_cnt)) & 0xFF
        out_pos += 1
        out[0] = bit_cnt       # validních bitů v posledním bajtu (1..7)
    else:
        out[0] = 8             # poslední bajt je plný

    return bytes(out[:out_pos])


# ---------------------------------------------------------------------------
# [P3] Nibble Huffman dekódování
# Bit buffer uint16_t — přesně jako C implementace.
# ---------------------------------------------------------------------------

def _huf_decode_nibble(stream: bytes, stream_len: int,
                       in_pos: list, bit_buf: list, bit_cnt: list,
                       valid_last: int,
                       codes_tab: tuple, lens_tab: tuple) -> int:
    """
    Dekóduj jeden nibble z bit bufferu.
    in_pos, bit_buf, bit_cnt jsou jednoprvkové listy (mutable reference).
    """
    # Načti dost bitů — max kód je 6 bitů
    while bit_cnt[0] < 6 and in_pos[0] < stream_len:
        next_byte = stream[in_pos[0]]
        in_pos[0] += 1
        if in_pos[0] == stream_len and valid_last < 8:
            bit_buf[0] = ((bit_buf[0] << valid_last) | (next_byte >> (8 - valid_last))) & 0xFFFF
            bit_cnt[0] += valid_last
        else:
            bit_buf[0] = ((bit_buf[0] << 8) | next_byte) & 0xFFFF
            bit_cnt[0] += 8

    # Vyzkoušej každý symbol
    for sym in range(16):
        code_len = lens_tab[sym]
        if bit_cnt[0] < code_len:
            continue
        # [N1] Použití předpočítané masky místo (1 << code_len) - 1
        peek = (bit_buf[0] >> (bit_cnt[0] - code_len)) & _MASKS[code_len]
        if peek == codes_tab[sym]:
            bit_cnt[0] -= code_len
            bit_buf[0] &= _MASKS[bit_cnt[0]]
            return sym

    # [V3] Tvrdá kontrola chyb
    raise ValueError(f"Invalid Huffman code at index {in_pos[0]}")


def _huffman_decode(data: bytes, n_symbols: int) -> bytes:
    valid_last = data[0]
    if valid_last == 0:
        valid_last = 8
    stream     = data[1:]
    stream_len = len(stream)

    # Mutable reference pro in_pos, bit_buf, bit_cnt
    in_pos  = [0]
    bit_buf = [0]
    bit_cnt = [0]

    result = bytearray(n_symbols)
    for i in range(n_symbols):
        hi = _huf_decode_nibble(stream, stream_len, in_pos, bit_buf, bit_cnt,
                                valid_last, _HUF_HI_CODE, _HUF_HI_LEN)
        lo = _huf_decode_nibble(stream, stream_len, in_pos, bit_buf, bit_cnt,
                                valid_last, _HUF_LO_CODE, _HUF_LO_LEN)
        result[i] = (hi << 4) | lo
    return bytes(result)


# ---------------------------------------------------------------------------
# Záhlaví
# ---------------------------------------------------------------------------

def _build_header(sample_num: int, use_huf: bool, use_ans: bool,
                  use_flag: bool, delta_type: int) -> int:
    # [V4] Hodnota 7 je rezervována pro budoucí rozšíření protokolu
    h  = sample_num & 0x07
    h |= (delta_type & 0x03) << 3
    if use_flag: h |= (1 << 5)
    if use_ans:  h |= (1 << 6)
    if use_huf:  h |= (1 << 7)
    return h


def _parse_header(h: int) -> dict:
    sample_num = h & 0x07
    # [V4] Zamezení zpracování nepodporované verze
    if sample_num == 7:
        raise ValueError("Unsupported protocol version (sample_num=7 is reserved)")
    return {
        'use_huf':    bool(h & (1 << 7)),
        'use_ans':    bool(h & (1 << 6)),
        'use_flag':   bool(h & (1 << 5)),
        'delta_type': (h >> 3) & 0x03,
        'sample_num': sample_num,
    }


# ---------------------------------------------------------------------------
# ZigZag — odpovídá int8_t aritmetice v C
# ---------------------------------------------------------------------------

def _zigzag_enc(x: int) -> int:
    s = x if x <= 127 else x - 256   # uint8_t → int8_t
    return ((s << 1) ^ (s >> 7)) & 0xFF


def _zigzag_dec(x: int) -> int:
    return ((x >> 1) ^ -(x & 1)) & 0xFF


# ---------------------------------------------------------------------------
# [Z5] Delta enkódování + ZigZag v jednom průchodu
# [P4] DELTA_FULL — big-int odečet s carry propagací od LSB k MSB
# ---------------------------------------------------------------------------

def _delta_encode_zz(current: bytes, previous: bytes,
                     delta_type: int) -> bytearray:
    """Delta enkódování + ZigZag v jednom průchodu. [Z5]"""
    n = len(current)
    out = bytearray(n)

    if delta_type == DELTA_1B:
        for i in range(n):
            d = (current[i] - previous[i]) & 0xFF
            out[i] = _zigzag_enc(d)
        return out

    if delta_type == DELTA_FULL:
        # [P4] Big-int odečet — od LSB (konec bufferu) k MSB, neseme borrow
        borrow = 0
        i = n - 1
        while i >= 0:
            d = current[i] - previous[i] - borrow
            db = d & 0xFF
            out[i] = _zigzag_enc(db)
            borrow = 1 if d < 0 else 0
            i -= 1
        return out

    # DELTA_2B — po 16-bit slovech big-endian
    i = 0
    while i < n:
        if i + 1 < n:
            c = (current[i] << 8) | current[i + 1]
            p = (previous[i] << 8) | previous[i + 1]
            d = (c - p) & 0xFFFF
            out[i]     = _zigzag_enc((d >> 8) & 0xFF)
            out[i + 1] = _zigzag_enc(d & 0xFF)
            i += 2
        else:
            d = (current[i] - previous[i]) & 0xFF
            out[i] = _zigzag_enc(d)
            i += 1
    return out


def _delta_decode_zz(data: bytes, previous: bytes,
                     delta_type: int) -> bytearray:
    """Inverzní ZigZag + delta dekódování v jednom průchodu. [Z5]"""
    n = len(data)
    out = bytearray(n)

    if delta_type == DELTA_1B:
        for i in range(n):
            d = _zigzag_dec(data[i])
            out[i] = (d + previous[i]) & 0xFF
        return out

    if delta_type == DELTA_FULL:
        # [P4] Big-int součet s carry od LSB k MSB
        carry = 0
        i = n - 1
        while i >= 0:
            d = _zigzag_dec(data[i])
            s = d + previous[i] + carry
            out[i] = s & 0xFF
            carry  = (s >> 8) & 0xFF
            i -= 1
        return out

    # DELTA_2B
    i = 0
    while i < n:
        if i + 1 < n:
            zh = _zigzag_dec(data[i])
            zl = _zigzag_dec(data[i + 1])
            d  = (zh << 8) | zl
            p  = (previous[i] << 8) | previous[i + 1]
            o  = (d + p) & 0xFFFF
            out[i]     = (o >> 8) & 0xFF
            out[i + 1] = o & 0xFF
            i += 2
        else:
            d = _zigzag_dec(data[i])
            out[i] = (d + previous[i]) & 0xFF
            i += 1
    return out


# ---------------------------------------------------------------------------
# [Z1][Z6][Z7][Z8] µANS enkódování / dekódování
# state = uint16_t (rozsah 32..8191)
# [Z6] rotace bajtu místo (byte >> j) & 1
# [Z7] skládání bajtu shiftem doleva v dekodéru (žádná reverze)
# [Z8] countdown smyčka od len-1 dolů
# [P5] early exit per bajt podle délky output streamu
# Výstup: [1B délka][2B state big-endian][stream]
# ---------------------------------------------------------------------------

def _uans_encode(data: bytes, limit: int) -> bytes | None:
    """
    limit = max délka celého výstupu. Stream smí být max limit-3 bajtů.
    Vrátí None pokud přeteče. [P5] early exit.
    """
    n      = len(data)
    state  = ANS_SCALE   # uint16_t
    output = bytearray()

    if limit < 4:
        return None
    stream_limit = limit - 3

    # [Z8] countdown od n-1 dolů
    bi = n - 1
    while bi >= 0:
        byte = data[bi]

        # [Z6] rotace bajtu — bit vždy z LSB
        for _ in range(8):
            bit    = byte & 1          # uint8_t
            weight = ANS_WEIGHT_0 if bit == 0 else ANS_WEIGHT_1
            byte   = byte >> 1         # rotace

            while state >= weight * 256:
                output.append(state & 0xFF)
                state >>= 8

            state = (state // weight) * ANS_SCALE \
                  + (0 if bit == 0 else ANS_WEIGHT_0) \
                  + (state % weight)

        # [P5] Early exit po každém bajtu
        if len(output) >= stream_limit:
            return None

        bi -= 1

    total = 3 + len(output)
    if total > limit:
        return None

    result = bytearray(total)
    result[0] = n & 0xFF
    result[1] = (state >> 8) & 0xFF
    result[2] = state & 0xFF
    # stream pozpátku
    for i in range(len(output)):
        result[3 + i] = output[len(output) - 1 - i]

    return bytes(result)


def _uans_decode(data: bytes) -> bytes:
    length     = data[0]                               # uint8_t
    state      = ((data[1] << 8) | data[2]) & 0xFFFF # uint16_t
    si         = 3
    stream_end = len(data)
    result     = bytearray(length)

    for i in range(length):
        # [Z7] skládání bajtu shiftem doleva — bity přicházejí MSB-first
        byte = 0
        for _ in range(8):
            pos = state % ANS_SCALE     # uint8_t
            if pos < ANS_WEIGHT_0:
                bit    = 0
                weight = ANS_WEIGHT_0
                offset = pos
            else:
                bit    = 1
                weight = ANS_WEIGHT_1
                offset = pos - ANS_WEIGHT_0

            # [Z7] shift doleva — žádná reverze na konci
            byte = ((byte << 1) | bit) & 0xFF

            state = (weight * (state // ANS_SCALE) + offset) & 0xFFFF

            if state < ANS_SCALE and si < stream_end:
                state = ((state << 8) | data[si]) & 0xFFFF
                si += 1

        result[i] = byte

    return bytes(result)


# ---------------------------------------------------------------------------
# [P6][Z4] Flagování nulových bajtů
# Rotující maska místo variable shift [Z4]
# Early exit per bajt [P6]
# Formát: [1B délka][⌈N/8⌉B mapa][nenulové bajty]
# ---------------------------------------------------------------------------

def _flag_encode(data: bytes, limit: int) -> bytes | None:
    """
    limit = max přípustná délka výstupu.
    Vrátí None pokud výsledek >= limit. [P6] early exit, [Z4] rotující maska.
    """
    n        = len(data)
    map_size = (n + 7) // 8

    # Quick check — minimum je 1 + map_size (samé nuly)
    if 1 + map_size >= limit:
        return None

    flag_map = bytearray(map_size)
    non_zero = bytearray()
    nz_limit = limit - 1 - map_size   # kolik nenulových bajtů se vejde
    nz_count = 0  # [N1] cachovaný čítač pro optimalizaci

    # [Z4] Rotující maska
    mask    = 0x80
    map_pos = 0

    for b in data:
        if b == 0:
            flag_map[map_pos] |= mask
        else:
            # [P6] Early exit
            if nz_count >= nz_limit:
                return None
            non_zero.append(b)
            nz_count += 1

        mask >>= 1
        if mask == 0:
            mask = 0x80
            map_pos += 1

    return bytes([n]) + bytes(flag_map) + bytes(non_zero)


def _flag_decode(data: bytes) -> bytes:
    n        = data[0]
    map_size = (n + 7) // 8
    nz_idx   = 1 + map_size
    result   = bytearray(n)

    # [Z4] Rotující maska
    mask    = 0x80
    map_pos = 1

    for i in range(n):
        if data[map_pos] & mask:
            result[i] = 0
        else:
            result[i] = data[nz_idx]
            nz_idx += 1

        mask >>= 1
        if mask == 0:
            mask = 0x80
            map_pos += 1

    return bytes(result)


# ---------------------------------------------------------------------------
# [P8] Komprese jednoho paketu — 4-cestný výběr metody
# ---------------------------------------------------------------------------

def dmd_compress(current: bytes, previous: bytes, sample_num: int) -> bytes:
    """
    Komprese jednoho paketu.
    Vrátí komprimovaná data včetně záhlaví (1B).
    Maximální expanze: 1B (záhlaví) — nikdy nedojde ke ztrátě dat.
    """
    n_raw      = len(current)
    is_keyframe = (sample_num == 0)

    # ------------------------------------------------------------------
    # Krok 1: Delta + ZigZag v jednom průchodu [Z5] — keyframe přeskočí
    # ------------------------------------------------------------------
    if is_keyframe:
        work       = bytearray(current)
        delta_type = DELTA_NONE
    else:
        best_score = _count_onebits(current)
        best_dt    = DELTA_NONE
        work       = bytearray(current)

        for dt in (DELTA_1B, DELTA_2B, DELTA_FULL):
            tmp   = _delta_encode_zz(current, previous, dt)
            score = _count_onebits(tmp)
            if score < best_score:
                best_score = score
                best_dt    = dt
                work       = tmp

        delta_type = best_dt

    # ------------------------------------------------------------------
    # Krok 2: Zkus kompresní kandidáty
    # best_size = aktuálně nejmenší výsledek, předává se jako limit [P8]
    # ------------------------------------------------------------------

    best_size      = n_raw
    winning_method = 0        # 0=RAW, 1=ANS, 2=HUF, 3=FLAG, 4=FLAG+HUF
    payload        = bytearray(current)   # RAW záchrana

    # (a) µANS — jen pokud zero_ratio >= 45% (práh kalibrován na meteo+GPS datasetu)
    zero_count = 0
    for b in work:
        if b == 0:
            zero_count += 1
    if zero_count * 100 >= n_raw * 45:
        ans_data = _uans_encode(work, best_size)
        if ans_data is not None and len(ans_data) < best_size:
            best_size      = len(ans_data)
            winning_method = 1
            payload        = bytearray(ans_data)

    # (b) Huffman
    huf_data = _huffman_encode(work, best_size)
    if huf_data is not None and len(huf_data) < best_size:
        best_size      = len(huf_data)
        winning_method = 2
        payload        = bytearray(huf_data)

    # (c) FLAG
    flag_data = _flag_encode(work, best_size)
    if flag_data is not None:
        if len(flag_data) < best_size:
            best_size      = len(flag_data)
            winning_method = 3
            payload        = bytearray(flag_data)

        # (d) FLAG+HUF — jen pokud FLAG uspěla
        map_size     = (n_raw + 7) // 8
        flag_hdr_sz  = 1 + map_size
        if best_size > flag_hdr_sz + 1:
            # Extrahuj nenulové bajty z work
            nonzero = bytearray(b for b in work if b != 0)
            if nonzero:
                huf_limit  = best_size - flag_hdr_sz
                huf_nz     = _huffman_encode(nonzero, huf_limit)
                if huf_nz is not None:
                    total = flag_hdr_sz + len(huf_nz)
                    if total < best_size:
                        best_size      = total
                        winning_method = 4
                        # FLAG hlavička + HUF stream
                        payload = bytearray(flag_data[:flag_hdr_sz]) + bytearray(huf_nz)

    # ------------------------------------------------------------------
    # Krok 3: nastav flagy podle vítěze
    # ------------------------------------------------------------------
    use_huf  = False
    use_ans  = False
    use_flag = False

    if winning_method == 1:
        use_ans  = True
    elif winning_method == 2:
        use_huf  = True
    elif winning_method == 3:
        use_flag = True
    elif winning_method == 4:
        use_huf  = True
        use_flag = True
    else:
        # RAW záchrana — žádná komprese, žádná delta
        delta_type = DELTA_NONE

    header = _build_header(sample_num, use_huf, use_ans, use_flag, delta_type)
    return bytes([header]) + bytes(payload)


# ---------------------------------------------------------------------------
# Dekomprese jednoho paketu
# ---------------------------------------------------------------------------

def dmd_decompress(data: bytes, previous: bytes) -> bytes:
    """
    Dekomprese jednoho paketu.
    previous musí být předchozí dekomprimovaný paket stejné délky.
    """
    h          = _parse_header(data[0])
    payload    = data[1:]
    payload_len = len(payload)
    delta_type = h['delta_type']
    pkt_len    = len(previous)

    # Vrstva 1: dekomprimuj payload
    if h['use_huf'] and h['use_flag']:
        # [P7] FLAG+HUF — FLAG mapa + Huffman na nenulových bajtech
        n        = payload[0]
        map_size = (n + 7) // 8
        flag_map = payload[1:1 + map_size]
        huf_part = payload[1 + map_size:]
        huf_part_len = payload_len - 1 - map_size

        # Počet nenulových bajtů z mapy — [Z4] rotující maska
        n_nonzero = 0
        mask      = 0x80
        map_pos   = 0
        for i in range(n):
            if not (flag_map[map_pos] & mask):
                n_nonzero += 1
            mask >>= 1
            if mask == 0:
                mask = 0x80
                map_pos += 1

        # Dekomprimuj nenulové bajty
        nonzero = _huffman_decode(huf_part, n_nonzero)

        # Rekonstruuj work — [Z4] rotující maska
        work    = bytearray(n)
        mask    = 0x80
        map_pos = 0
        nz_idx  = 0
        for i in range(n):
            if flag_map[map_pos] & mask:
                work[i] = 0
            else:
                work[i] = nonzero[nz_idx]
                nz_idx += 1
            mask >>= 1
            if mask == 0:
                mask = 0x80
                map_pos += 1

    elif h['use_huf']:
        work = bytearray(_huffman_decode(payload, pkt_len))
    elif h['use_ans']:
        work = bytearray(_uans_decode(payload))
    elif h['use_flag']:
        work = bytearray(_flag_decode(payload))
    else:
        # RAW
        if delta_type == DELTA_NONE:
            return bytes(payload[:pkt_len])
        work = bytearray(payload[:pkt_len])

    # Vrstva 2: inverzní ZigZag + inverzní delta v jednom průchodu [Z5]
    if delta_type != DELTA_NONE:
        return bytes(_delta_decode_zz(work, previous, delta_type))

    return bytes(work)


# ---------------------------------------------------------------------------
# Stavový enkodér / dekodér
# ---------------------------------------------------------------------------

class DmdEncoder:
    """Stavový enkodér — jeden objekt na komunikační kanál."""

    def __init__(self, pkt_len: int):
        self.pkt_len    = pkt_len & 0xFF    # uint8_t
        self.previous   = bytes(pkt_len)
        self.sample_num = 0

    def compress(self, data: bytes) -> bytes:
        assert len(data) == self.pkt_len, \
            f"Délka dat {len(data)} != pkt_len {self.pkt_len}"
        result          = dmd_compress(data, self.previous, self.sample_num)
        self.previous   = data
        self.sample_num = (self.sample_num + 1) % DMD_KEYFRAME_EVERY
        return result

    def reset(self):
        self.previous   = bytes(self.pkt_len)
        self.sample_num = 0


class DmdDecoder:
    """Stavový dekodér — jeden objekt na komunikační kanál."""

    def __init__(self, pkt_len: int):
        self.pkt_len  = pkt_len & 0xFF    # uint8_t
        self.previous = bytes(pkt_len)

    def decompress(self, data: bytes) -> bytes:
        result        = dmd_decompress(data, self.previous)
        self.previous = result
        return result

    def reset(self):
        self.previous = bytes(self.pkt_len)
