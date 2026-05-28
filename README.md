<p align="center">
  <img src="NICDMD.svg" width="200"/>
</p>

[Pro dokumentaci v češtině klikněte zde](README_cs.md) | [Для документации на русском языке нажмите здесь](README_ru.md)

---

★ N.I.C. ★

# NIC DMD — Delta Markov Duda

## Compression protocol for embedded devices

[![License: MIT](https://img.shields.io/badge/License-MIT-red.svg)](https://opensource.org/licenses/MIT)

---

## What is DMD?

DMD is a cross-platform compression protocol for small data packets from weather stations, smart meters, GPS trackers, and other embedded devices. It is designed for transmission over bandwidth-limited technologies such as LoRa.

The protocol runs fully on an ATmega328 microcontroller and requires no large dictionaries or lookup tables in RAM. Each packet is compressed independently — by adaptively selecting the best method from five candidates.

---

## Why DMD?

Existing compression libraries for embedded devices either require hundreds of extra bytes of RAM (Heatshrink), or need to transmit the Huffman table alongside the data. DMD takes a different approach — it combines several simple methods with heuristic analysis and selects the best result for each packet individually.

**Key advantages:**
- Fixed Huffman table in ROM only (64 B), no extra RAM
- Adaptive method selection per packet — up to 5 candidates
- Fully deterministic decompression — no data loss
- Maximum data expansion of 1 byte (header) in the worst case
- Implementation in both Python and C (ATmega328 / Arduino)

---

## When DMD is not worth using

DMD is designed for data that changes slowly and predictably over time — sensor readings, GPS coordinates, industrial telemetry. If the input data is random, encrypted, or already compressed, DMD will add only 1 byte of header and send it as RAW. This is the correct behaviour — no lossy compression, no degradation.

---

## Compatibility

**Python:** 3.10 or newer (uses `bytes | None` type annotations).

**C:** C99 or newer. Tested with GCC on PC (Linux/Windows) and AVR-GCC for ATmega328. No dependencies on the standard library beyond `<string.h>`. Internal buffers are sized using C99 VLA based on the actual packet length.

**Arduino:** Copy `nic_dmd.c` and `nic_dmd.h` into the project folder. Compatible with Arduino IDE 1.8+ and 2.x (AVR-GCC supports C99 VLA).

**Note for other compilers:** IAR, Keil, and MSVC C++ do not support VLA. For these toolchains, define `-DDMD_PKT_MAX_BUILD=N` (e.g. 32 or 64) at compile time and the buffers will be fixed-size.

**Dependencies for fetch/benchmark:** `pip install requests`

**Packet length:** The minimum technical limit is 1 B, but below 16 B compression is practically worthless — the header overhead (1 B) and ANS state (2 B) consume most of the potential saving. Recommended minimum is **16 B**. Maximum is **255 B**. For LoRa transmission the practical payload limit is 51–64 B depending on spreading factor and region. DMD achieves the best results on data where consecutive packets change slowly — typically 16–64 B sensor telemetry.

---

## Data validation and integrity

In order to achieve maximum performance and minimize processor load, the library performs no additional header checks or validation of the length of the data passed to it.

The protocol design strictly assumes that integrity checking (e.g. hardware CRC) and discarding of corrupted or empty packets is handled by the lower transport layer or the main application (typically the radio module itself, the data acquisition logic, etc.). The library user must ensure at the application level that only structurally correct data enters the compression and decompression functions. This delegation of responsibility achieves low memory overhead without wasting clock cycles.

---

## Results

Tested on more than 50,000 samples from 20 real and synthetic data sources (weather stations, GPS, smart meters, industrial sensors, seismology, air quality). Round-trip errors: **0 in all datasets**.

The **output B/pkt** column is the average actual size of the transmitted packet after compression (including the 1 B header). This is the figure that matters for sizing the LoRa transmission window.

### Table 1 — uniform int16 (fetch_plus.py)

All fields stored as `int16` with ×100 scaling, packets zero-padded to a fixed length. Forecast datasets have 384 samples (16 days × 24 hours), others 8,000–10,000 samples.

```
===================================================================================
  Dataset                    | Pkts  | Input | Output  | Saving | Dominant method
------------------------------|-------|-------|---------|--------|------------------
NOAA San Francisco (tides)    |  8184 |  16 B |   6.4 B |  62.2% | DELTA1+ZZ+FLAG
NOAA New York (tides)         |  8184 |  16 B |   6.7 B |  60.6% | DELTA1+ZZ+FLAG
DWD Fichtelberg (meteo)       | 10000 |  16 B |   8.1 B |  52.6% | DELTA1+ZZ+FLAG 75%
DWD Helgoland (meteo)         | 10000 |  16 B |   8.5 B |  49.8% | DELTA1+ZZ+FLAG 74%
DWD Zugspitze (meteo)         | 10000 |  16 B |   8.6 B |  49.2% | DELTA1+ZZ+FLAG 73%
GPS Trek                      | 10000 |  16 B |   8.6 B |  49.3% | DELTA1+ZZ+FLAG 53%
Complex station               | 10000 |  64 B |  38.6 B |  40.7% | DELTA1+ZZ+HUF  84%
AirQuality Brno               |   168 |  16 B |  10.3 B |  39.7% | FLAG + D1+ZZ+FLAG
AirQuality Ostrava            |   168 |  16 B |  10.5 B |  38.4% | FLAG + D1+ZZ+FLAG
Smart meters                  | 10000 |  16 B |  10.6 B |  37.7% | DELTA1+ZZ+HUF  52%
AirQuality Praha              |   168 |  16 B |  10.6 B |  37.6% | FLAG + D1+ZZ+FLAG
Forecast Praha (32B)          |   384 |  32 B |  22.0 B |  33.2% | DELTA1+ZZ+FLAG 58%
Forecast Brno (32B)           |   384 |  32 B |  22.4 B |  32.1% | DELTA1+ZZ+FLAG 55%
IoT building                  | 10000 |  16 B |  11.7 B |  31.3% | DELTA1+ZZ+HUF  84%
Industrial sensor             | 10000 | 128 B |  89.3 B |  30.7% | DELTA1+ZZ+HUF  80%
Forecast Ostrava (16B)        |   384 |  16 B |  12.3 B |  27.3% | DELTA1+ZZ+FLAG 42%
Forecast Praha (16B)          |   384 |  16 B |  12.4 B |  26.8% | DELTA1+ZZ+FLAG 41%
Forecast Brno (16B)           |   384 |  16 B |  12.5 B |  26.5% | DELTA1+ZZ+FLAG 43%
Forecast Bratislava (16B)     |   384 |  16 B |  12.7 B |  25.3% | DELTA1+ZZ+FLAG 38%
USGS seismics                 | 10000 |  16 B |  13.9 B |  18.2% | FLAG 29% (chaotic)
===================================================================================
  Range: 18 % – 62 %   |   Errors: 0
===================================================================================
```

### Table 2 — schema-aware tight packing (fetch_small.py)

Each field stored in the smallest required type (uint8/int16) with ×10 scaling, no zero padding.

```
===================================================================================
  Dataset                    | Pkts  | Input | Output  | Saving | Dominant method
------------------------------|-------|-------|---------|--------|------------------
Forecast Praha (27B)          |   384 |  27 B |  17.1 B |  39.0% | DELTA1+ZZ+HUF  63%
Forecast Brno (27B)           |   384 |  27 B |  17.2 B |  38.5% | DELTA1+ZZ+HUF  61%
AirQuality Brno (12B)         |   168 |  12 B |   8.3 B |  35.9% | DELTA1+ZZ+HUF  49%
AirQuality Ostrava (12B)      |   168 |  12 B |   8.5 B |  34.8% | DELTA1+ZZ+HUF  47%
AirQuality Praha (12B)        |   168 |  12 B |   8.6 B |  34.2% | DELTA1+ZZ+HUF  44%
Forecast Ostrava (13B)        |   384 |  13 B |   9.3 B |  33.6% | DELTA1+ZZ+HUF  67%
Forecast Brno (13B)           |   384 |  13 B |   9.3 B |  33.3% | DELTA1+ZZ+HUF  69%
Forecast Praha (13B)          |   384 |  13 B |   9.3 B |  33.3% | DELTA1+ZZ+HUF  70%
Forecast Bratislava (13B)     |   384 |  13 B |   9.4 B |  32.5% | DELTA1+ZZ+HUF  72%
DWD Fichtelberg (9B)          | 10000 |   9 B |   6.3 B |  37.0% | D1+ZZ+ANS  49%
DWD Helgoland (9B)            | 10000 |   9 B |   6.4 B |  36.0% | D1+ZZ+ANS  42%
DWD Zugspitze (9B)            | 10000 |   9 B |   6.4 B |  35.6% | D1+ZZ+ANS  42%
USGS seismics (8B)            | 10000 |   8 B |   8.6 B |   3.9% | RAW 79% ⚠ expansion
NOAA New York (3B)            |  8184 |   3 B |   4.0 B |   0.0% | RAW 100% ⚠ expansion
NOAA San Francisco (3B)       |  8184 |   3 B |   4.0 B |   0.0% | RAW 100% ⚠ expansion
===================================================================================
  Range: 0 % – 39 %   |   Errors: 0
  ⚠ For packets < 8 B output is larger than input — header overhead (1 B) exceeds any saving.
===================================================================================
```

### Table 3 — raw JSON/CSV text (fetch_raw_text.py)

Data exactly as received from sources — no binary packing, text as bytes, zero-padded to the length of the first record.

```
===================================================================================
  Dataset                    | Pkts  | Input  | Output  | Saving | Dom. method
------------------------------|-------|--------|---------|--------|---------------
DWD Helgoland (raw CSV)       | 10000 |  72 B  |  21.2 B |  71.0% | D1+ZZ+ANS 69%
DWD Zugspitze (raw CSV)       | 10000 |  72 B  |  21.3 B |  70.9% | D1+ZZ+ANS 68%
DWD Fichtelberg (raw CSV)     | 10000 |  72 B  |  21.4 B |  70.7% | D1+ZZ+ANS 67%
NOAA San Francisco (raw JSON) |  8448 |  72 B  |  26.7 B |  63.4% | D1+ZZ+FLAG 38%
NOAA New York (raw JSON)      |  8448 |  72 B  |  27.3 B |  62.6% | D1+ZZ+FLAG 37%
Forecast Bratislava (raw JSON)|   384 | 200 B  |  73.2 B |  63.6% | D1+ZZ+ANS  40%
Forecast Ostrava (raw JSON)   |   384 | 200 B  |  76.1 B |  62.2% | D1+ZZ+ANS  40%
Forecast Praha (raw JSON)     |   384 | 200 B  |  76.7 B |  61.9% | D1+ZZ+ANS  41%
Forecast Brno (raw JSON)      |   384 | 200 B  |  77.1 B |  61.6% | D1+ZZ+ANS  37%
USGS seismics (raw CSV)       | 10000 | 216 B  |  96.5 B |  55.5% | D1+ZZ+FLAG 34%
===================================================================================
  Range: 56 % – 71 %   |   Errors: 0
===================================================================================
```

---

## How encoding format affects compression

### ×10 vs ×100 scaling and the effect of zero padding

With ×100 scaling and uniform int16 packing (Table 1), DMD achieves 49–53 % savings on DWD data. With tight schema-aware packing and ×10 scaling (Table 2), the result is only 35–37 %. A paradox: coarser scaling with a larger packet gives better compression. The reason is structural — in a 16 B packet with ×100 scaling, the high byte of each int16 is typically close to zero after delta+ZigZag, so the FLAG method can represent the entire byte with a single bit in the bitmap. Tight ×10 packing into uint8/uint16 eliminates this structure and switches compression to HUF or ANS.

NOAA data are the best example of the effect of intentional zero fields: in the 16 B variant with 6 zero fields, the output is **6.4–6.7 B** (saving 61–62 %). In the 3 B variant without padding, the output is **4.0 B** — which is actually worse than the input (3 B), because the mandatory 1 B header outweighs any saving. An intentional zero field is therefore not a waste of bytes — it actively helps compression.

### Absolute output sizes — what you actually transmit

Although the percentage saving looks best for raw text, in terms of bytes actually transmitted binary packing is clearly superior:

```
  DWD data — absolute output size comparison:
  ┌─────────────────────────────────────────────────────┐
  │ Format         │ Input │ Output │ Method            │
  │─────────────────────────────────────────────────────│
  │ 9B  schema-aw. │   9 B │  6.4 B │ D1+ZZ+ANS         │
  │ 16B uniform    │  16 B │  8.4 B │ D1+ZZ+FLAG        │
  │ 72B raw CSV    │  72 B │ 21.3 B │ D1+ZZ+ANS         │
  └─────────────────────────────────────────────────────┘

  Forecast data — absolute output size comparison:
  ┌─────────────────────────────────────────────────────┐
  │ Format         │ Input │ Output │ Method            │
  │─────────────────────────────────────────────────────│
  │ 13B schema-aw. │  13 B │  9.3 B │ D1+ZZ+HUF         │
  │ 16B uniform    │  16 B │ 12.4 B │ D1+ZZ+FLAG        │
  │ 27B schema-aw. │  27 B │ 17.1 B │ D1+ZZ+HUF         │
  │ 32B uniform    │  32 B │ 22.2 B │ D1+ZZ+FLAG        │
  │ 200B raw JSON  │ 200 B │ 76.7 B │ D1+ZZ+ANS         │
  └─────────────────────────────────────────────────────┘
```

For DWD meteorological data, 16 B uniform int16 and 9 B schema-aware packing yield a similar final packet (8.4 B vs 6.4 B — a difference of only 2 B), but the 16 B variant requires no custom schema, is easier to extend with additional variables, and benefits more from zero padding in FLAG compression.

Schema-aware packing makes sense only where every byte matters even before compression — typically when transmitting without DMD or on extremely constrained links.

### Data character and dominant method

```
  Slow changes + zero padding (NOAA, AQ 16B)  → FLAG
  Slow meteo changes (DWD, Forecast)           → DELTA1+ZZ+FLAG
  Synthetic data without zeros (IoT, industry) → DELTA1+ZZ+HUF
  Raw JSON/CSV text                            → DELTA1+ZZ+ANS
  Random data (USGS small packets)             → RAW (no saving)
```

DELTA1 (1-byte delta) dominates across all categories — over 70 % usage across all datasets. DELTA2 and DELTA_FULL appear marginally (under 10 %) only for data with correlation across byte boundaries.

---

## RAM usage

Buffers are sized using C99 VLA based on the actual packet length `N`. Values include the compression stack and encoder/decoder structures.

```
================================================================================
  Packet length | Compress stack | dmd_encoder_t | dmd_decoder_t | Total
---------------+----------------+---------------+---------------+---------------
       16B     |      62B       |      18B      |     17B       |      80B
       32B     |      96B       |      34B      |     33B       |     130B
       64B     |     164B       |      66B      |     65B       |     230B
      128B     |     300B       |     130B      |    129B       |     430B
      255B     |     569B       |     257B      |    256B       |     826B
================================================================================
```

Peak RAM during `dmd_compress` = Compress stack + dmd_encoder_t.

For typical LoRa use (16–64 B packets) the peak is **80–230 B** — no problem on an ATmega328 (2 KB RAM).

---

## How it works

```
+-------------------------------------------------------------------------------+
|                          START: Input data packet                             |
+-------------------------------------------------------------------------------+
                                    |
                                    v
+-------------------------------------------------------------------------------+
|  Step 1: Delta + ZigZag (skipped for keyframe)                                |
|  Try DELTA_1B / DELTA_2B / DELTA_FULL — pick the fewest one-bits             |
+-------------------------------------------------------------------------------+
                                    |
                                    v
+-------------------------------------------------------------------------------+
|  Step 2: Try compression candidates (each with an early-exit limit)           |
|                                                                               |
|   (a) µANS     — only if zero_ratio >= 45%                                    |
|   (b) Huffman  — nibble Huffman with fixed ROM table, always runs             |
|   (c) FLAG     — zero-byte bitmap, always runs                                |
|   (d) FLAG+HUF — FLAG removes zeros, Huffman optionally compresses the rest   |
+-------------------------------------------------------------------------------+
                                    |
                                    v
+-------------------------------------------------------------------------------+
|  Step 3: Select the smallest result                                           |
|  If nothing helps → RAW fallback (delta_type = NONE, original data)          |
+-------------------------------------------------------------------------------+
                                    |
                                    v
+-------------------------------------------------------------------------------+
|  Step 4: Assemble header (1B) + payload → transmit                            |
+-------------------------------------------------------------------------------+
```

### Header (1 byte)

Every compressed packet begins with a single header byte:

```
MSB                    LSB
 7    6    5    4    3    2    1    0
[huf][ans][flg][dlt][dlt][sn ][sn ][sn ]
```

```
=======================================================================
| Bits |        Meaning                                               |
|------|--------------------------------------------------------------|
|   7  | nibble Huffman compression   1 = ON                          |
|   6  | µANS compression             1 = ON                          |
|   5  | zero-byte flagging           1 = ON                          |
|  4-3 | delta type: 00=none, 01=1B, 10=2B, 11=FULL (big-int+carry)  |
|  2-0 | sample number (0–7)          0 = keyframe / start frame      |
=======================================================================

Combination bit 7 + bit 5 = FLAG+HUF (zero map + Huffman on non-zeros)
```

If no method can compress the data better than RAW, the original data are sent with bits 3–7 of the header set to 0. The receiver recognises RAW because the header uses no flags.

### Compression layers

**1. Delta — difference method**

Comparison of two consecutive packets. Where data changes slowly (temperature, pressure, GPS coordinates), subtraction produces strings of zero or very small values. The protocol tests three delta types and selects the one with the best result according to a heuristic (number of one-bits).

Supported types:
- **1B delta** — byte by byte (uint8_t arithmetic)
- **2B delta** — per 16-bit big-endian word (uint16_t arithmetic)
- **FULL delta** — the entire packet as one large number with carry propagation across all bytes. Wins on counters and GPS coordinates where a value overflows across byte boundaries.

**2. ZigZag encoding**

After applying delta, the data are ZigZag-encoded. Negative differences map to small odd numbers, positive to small even numbers. The result is data with a high proportion of zero bits that respond better to the subsequent compression methods.

ZigZag is not applied when delta = none (including keyframe). Delta and ZigZag run in a single pass over the data.

**3. Zero-byte flagging (FLAG)**

Each zero byte is replaced by a single bit in a bitmap. The packet length (1 B) is stored before the map. Non-zero bytes follow in their original order.

Example for a 16 B packet with 12 zeros:
```
Original: [0, 0, 5, 0, 0, 0, 3, 0, 0, 0, 0, 0, 7, 0, 0, 2]  (16B)
Payload:  [16][11011101 11110110][5, 3, 7, 2]
           1B length + 2B map + 4B non-zero = 7B
Result:   8B instead of 16B (1B header + 7B payload)
```

**4. µANS compression**

Asymmetric Numeral Systems (ANS) work at the bit level with two weights: a zero bit is highly probable (29/32), a one bit less so (3/32). For data with a predominance of zeros after delta+ZigZag, it achieves significant compression without a table.

The ANS payload contains the data length (1 B), state (2 B — uint16_t), and the encoded bytes. It runs only when the zero-byte ratio is >= 45 % (heuristic). Both encoder and decoder have an early exit — if the result exceeds the limit, computation stops immediately.

**5. Nibble Huffman (HUF)**

A fixed Huffman table trained on combined meteo and GPS data after delta+ZigZag. Encodes each byte as two nibble codes (hi and lo). The table is stored in ROM (32 B PROGMEM on ATmega), no extra RAM.

Maximum code length is 6 bits, average ~3.2 bits per byte. Wins especially on IoT, industrial, and complex data where zeros are rare but the nibble distribution matches the table.

**6. FLAG+HUF combination**

FLAG first removes zero bytes into a bitmap, then Huffman compresses the remaining non-zero bytes. Payload: `[1B length][map][1B valid bits HUF][HUF stream]`. The best of both worlds — deterministic zero elimination + entropy compression of the remainder.

**Keyframe and start frame**

Sample number 0 is a keyframe. Because no previous packet exists for delta calculation, the difference method and ZigZag are skipped. Data are processed directly by FLAG, HUF, FLAG+HUF, or ANS. A keyframe occurs automatically every 8 packets or after a device reset.

---

## Usage

### Python

```python
from nic_dmd import DmdEncoder, DmdDecoder

PKT_LEN = 16
enc = DmdEncoder(PKT_LEN)
dec = DmdDecoder(PKT_LEN)

data = bytes([0xFC, 0x18, 0x21, 0x34, 0x01, 0x81,
              0x04, 0xCE, 0x00, 0x00, 0xFC, 0x7C,
              0xFC, 0xA8, 0x00, 0x00])

compressed   = enc.compress(data)
decompressed = dec.decompress(compressed)

print(f"Compressed: {PKT_LEN}B → {len(compressed)}B")
assert decompressed == data
```

### C (ATmega328 / Arduino)

```c
#include "nic_dmd.h"

dmd_encoder_t enc;
dmd_decoder_t dec;

void setup() {
    dmd_encoder_init(&enc, 16);   // packet length — must match on both sides
    dmd_decoder_init(&dec, 16);
}

void loop() {
    uint8_t data[16]          = { /* sensor data */ };
    uint8_t compressed[DMD_OUT_MAX];
    uint8_t decompressed[16];

    uint8_t comp_len = dmd_compress(&enc, data, compressed);
    lora.send(compressed, comp_len);

    // On the receiver:
    dmd_decompress(&dec, compressed, comp_len, decompressed);
}
```

### Building without VLA support

If your compiler does not support C99 VLA (IAR, Keil, MSVC C++), define the maximum packet length at compile time:

```
gcc -DDMD_PKT_MAX_BUILD=32 nic_dmd.c ...
```

Buffers will be compiled at a fixed size of 32 B. For projects with a single fixed packet length (typical Arduino use case) this variant is ideal.

---

## Files

| File                 | Description                                              |
| -------------------- | -------------------------------------------------------- |
| `nic_dmd.py`         | Python implementation — reference, for testing           |
| `nic_dmd_utils.py`   | Helper functions — analysis and result output            |
| `nic_dmd.c`          | C implementation for ATmega328                           |
| `nic_dmd.h`          | Header file                                              |
| `Makefile`           | Compilation and testing                                  |

### Testing and benchmark

| File                  | Description                                                        |
| --------------------- | ------------------------------------------------------------------ |
| `nic_dmd_test.py`     | Python tests — round-trip, meteo, keyframe                         |
| `nic_dmd_test.c`      | C tests — round-trip, all-zeros, meteo                             |
| `fetch_plus.py`       | Benchmark — real + synthetic data, uniform int16 (20 sources)      |
| `fetch_small.py`      | Benchmark — same sources, schema-aware tight packing               |
| `fetch_raw_text.py`   | Benchmark — raw JSON/CSV text as bytes                             |
| `benchmark.py`        | Comparison of DMD vs Huffman vs Heatshrink                         |

---

## Licence

MIT License — Copyright (c) 2026 NIC — Native Intellect Community

---

## Acknowledgements

To my brother for advice during the development of this project.
For technical assistance with code optimisation, to AI assistants Claude (Anthropic) and Gemini (Google).

★ Viva La Resistánce ★
