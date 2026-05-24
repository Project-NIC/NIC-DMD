★ N.I.C. ★

# NIC DMD — Delta Markov Duda

## Compression protocol for embedded devices and LoRa transmission

[![Licence: GPL v3](https://img.shields.io/badge/Licence-GPLv3-red.svg)](https://www.gnu.org/licenses/gpl-3.0)

---

## What is DMD?

DMD is a multiplatform compression protocol for small data packets from weather stations, energy meters, GPS trackers and other embedded devices. It is designed for transmission over bandwidth-limited technologies such as LoRa.

The protocol runs fully on the ATmega328 controller and requires no large dictionaries or lookup tables in memory. Each packet is compressed independently — by adaptive selection of the best method from five candidates.

---

## Why DMD?

Existing compression libraries for embedded devices either require hundreds of extra bytes of RAM (Heatshrink), or need to transmit a Huffman table alongside the data. DMD takes a different approach — it combines several simple methods with heuristic analysis and selects the best result for each packet individually.

**Key advantages:**
- Fixed Huffman table in ROM only (32B), no RAM overhead
- Adaptive method selection per packet — up to 5 candidates
- Fully deterministic decompression — no data loss
- Maximum data expansion of 1 byte (header) in the worst case
- Implementation in both Python and C (ATmega328 / Arduino)

---

## When DMD is not worth using

DMD is designed for data that changes slowly and predictably over time — sensor values, GPS coordinates, industrial telemetry. If the input data is random, encrypted or already compressed, DMD will add only 1 byte of header and send it as RAW. This is correct behaviour — no lossy compression, no degradation.

---

## Compatibility

**Python:** 3.10 or newer (uses `bytes | None` type annotations).

**C:** C99 or newer. Tested with GCC on PC (Linux/Windows) and AVR-GCC for ATmega328. No dependencies on the standard library other than `<string.h>`. Internal buffers are sized using C99 VLA according to the actual packet length.

**Arduino:** Copy `nic_dmd.c` and `nic_dmd.h` into your project folder. Compatible with Arduino IDE 1.8+ and 2.x (AVR-GCC supports C99 VLA).

**Note for other compilers:** IAR, Keil and MSVC C++ do not support VLA. For these toolchains, define `-DDMD_PKT_MAX_BUILD=N` at compile time (e.g. 32 or 64) and buffers will be fixed size.

**Fetch/benchmark dependencies:** `pip install requests`

**Packet length:** The technical minimum is 1B, but below 16B compression is practically not worth it — the header overhead (1B) and ANS state (2B) consume most of any potential saving. Recommended minimum is **16B**. Maximum is **255B**. For LoRa transmission the practical payload limit is 51–64B depending on spreading factor and region. DMD achieves best results on data where adjacent packets change slowly — typically 16–64B sensor telemetry.

---

## Data validation and integrity

In order to achieve maximum performance and absolute minimization of CPU load, the library performs no additional header checks or validation of the length of passed data.

The protocol design strictly assumes that integrity checking (e.g. hardware CRC) and discarding of corrupted or empty packets is handled by the lower transport layer or the main application (typically the radio module itself, data collection logic, etc.). The library user must ensure at the application level that only structurally correct data enters the compression and decompression functions. This delegation of responsibility achieves low memory overhead without wasting CPU clock cycles.

---

## Results

Tested on more than 50,000 samples from 20 real and synthetic data sources (weather stations, GPS, energy meters, industrial sensors, seismics, air quality):

```
=========================================================================================================
        GLOBAL SUMMARY — tested on 20 datasets, packets 16–128B
=========================================================================================================
  Dataset                        |  Saving  |  Note
---------------------------------------------------------------------------------------------------------
NOAA San Francisco (tides)       |   62.2%  | FLAG dominant, ideal for ANS
NOAA New York (tides)            |   60.6%  | FLAG dominant
DWD Fichtelberg (meteo 16B)      |   52.6%  | 74% of packets DELTA1+ZZ+FLAG
GPS Trek (16B)                   |   49.3%  | 21% of packets DELTA1+ZZ+ANS
DWD Helgoland / Zugspitze        |  ~49%    | coastal / mountain meteo
Complex station (64B)            |   40.7%  | 84% DELTA1+ZZ+HUF
AirQuality CZ (16B)              |  37–40%  | mix of FLAG and HUF
Energy meters (16B)              |   37.7%  | 52% DELTA1+ZZ+HUF
IoT building (16B)               |   31.3%  | 84% DELTA1+ZZ+HUF
Industrial sensor (128B)         |   30.7%  | 80% DELTA1+ZZ+HUF
Forecast meteo (16–32B)          |  27–32%  | mix of FLAG and HUF
USGS seismics (16B)              |   18.2%  | worst case — chaotic data
=========================================================================================================
  Saving range:  18% – 62%   |  Round-trip errors: 0 across all datasets
=========================================================================================================
```

---

## RAM usage

Buffers are sized using C99 VLA according to the actual packet length `N`. Values include stack during compression and encoder/decoder structures.

```
================================================================================
  Packet length | Compression stack | dmd_encoder_t | dmd_decoder_t | Total
---------------+-------------------+---------------+---------------+----------
       16B     |        62B        |      18B      |     17B       |     80B
       32B     |        96B        |      34B      |     33B       |    130B
       64B     |       164B        |      66B      |     65B       |    230B
      128B     |       300B        |     130B      |    129B       |    430B
      255B     |       569B        |     257B      |    256B       |    826B
================================================================================
```

Peak RAM during `dmd_compress` call = Compression stack + dmd_encoder_t.

For typical LoRa use (16–64B packets) the peak is **80–230B** — no problem on ATmega328 (2KB RAM).

---

## How it works

```
+-------------------------------------------------------------------------------+
|                          START: Input data packet                             |
+-------------------------------------------------------------------------------+
                                    |
                                    v
+-------------------------------------------------------------------------------+
|  Step 1: Delta + ZigZag (keyframe skips this)                                 |
|  Test DELTA_1B / DELTA_2B / DELTA_FULL — pick lowest one-bit count            |
+-------------------------------------------------------------------------------+
                                    |
                                    v
+-------------------------------------------------------------------------------+
|  Step 2: Try compression candidates (each with early exit limit)              |
|                                                                               |
|   (a) µANS     — only if zero_ratio >= 45%                                   |
|   (b) Huffman  — nibble Huffman with fixed ROM table, always runs             |
|   (c) FLAG     — zero byte bitmap, always runs                                |
|   (d) FLAG+HUF — FLAG removes zeros, Huffman compresses the rest              |
+-------------------------------------------------------------------------------+
                                    |
                                    v
+-------------------------------------------------------------------------------+
|  Step 3: Select smallest result                                               |
|  If nothing helps → RAW fallback (delta_type = NONE, original data)           |
+-------------------------------------------------------------------------------+
                                    |
                                    v
+-------------------------------------------------------------------------------+
|  Step 4: Build header (1B) + payload → transmit                               |
+-------------------------------------------------------------------------------+
```

### Header (1 byte)

Every compressed packet starts with one byte of header:

```
MSB                    LSB
 7    6    5    4    3    2    1    0
[huf][ans][flg][dlt][dlt][smp][smp][smp]
```

```
=======================================================================
| Bits |        Meaning                                               |
|------|--------------------------------------------------------------|
|   7  | nibble Huffman compression  1 = ON                          |
|   6  | µANS compression            1 = ON                          |
|   5  | Zero byte flagging          1 = ON                          |
|  4-3 | Delta type: 00=none, 01=1B, 10=2B, 11=FULL (big-int+carry)  |
|  2-0 | Sample number (0–7)         0 = keyframe / start frame      |
=======================================================================

Combination bit 7 + bit 5 = FLAG+HUF (zero map + Huffman on non-zeros)
```

If no method can compress data better than RAW, the original data is sent with bits 3-7 of the header set to 0. The receiver recognises RAW because the header uses no settings.

### Compression layers

**1. Delta — differential method**

Comparison of two consecutive packets. Where data changes slowly (temperature, pressure, GPS coordinates), subtraction produces chains of zero or very small values. The protocol tests three delta types and selects the one with the best result according to a heuristic (one-bit count).

Supported types:
- **1B delta** — byte by byte (uint8_t arithmetic)
- **2B delta** — in 16-bit big-endian words (uint16_t arithmetic)
- **FULL delta** — entire packet as one large integer with carry propagation across all bytes. Wins on counters and GPS coordinates where values overflow byte boundaries.

**2. ZigZag encoding**

After applying delta, the data is converted using ZigZag encoding. Negative differences map to small odd numbers, positive to small even numbers. The result is data with a high count of zero bits, which responds better to the subsequent compression methods.

ZigZag is not applied when delta = none (including keyframe). Delta and ZigZag run in a single pass over the data.

**3. Zero byte flagging (FLAG)**

Each zero byte is replaced by a single bit in a bitmap. Before the map, the packet length is stored (1B). Non-zero bytes follow in their original order.

Example for a 16B packet with 12 zeros:
```
Original: [0, 0, 5, 0, 0, 0, 3, 0, 0, 0, 0, 0, 7, 0, 0, 2]  (16B)
Payload:  [16][11011101 11110110][5, 3, 7, 2]
           1B length + 2B map + 4B non-zero = 7B
Result:   8B instead of 16B (1B header + 7B payload)
```

**4. µANS compression**

Asymmetric Numeral Systems (ANS) work at the bit level with two weights: a zero bit is highly probable (29/32), a one bit less so (3/32). For data with a majority of zeros after delta+ZigZag, it achieves significant compression without a table.

The ANS payload contains the data length (1B), state (2B — uint16_t) and encoded bytes. Runs only if the zero byte ratio >= 45% (heuristic). Both encoder and decoder have early exit — if the result exceeds the limit, computation stops immediately.

**5. Nibble Huffman (HUF)**

Fixed Huffman table trained on combined meteo and GPS data after delta+ZigZag. Encodes each byte as two nibble codes (hi and lo). The table is stored in ROM (32B PROGMEM on ATmega), no RAM overhead.

Maximum code length is 6 bits, average ~3.2 bits per byte. Wins especially on IoT, industrial and complex data where zeros are rare but nibble distribution matches the table.

**6. FLAG+HUF combination**

FLAG first removes zero bytes into a bitmap, then Huffman compresses the remaining non-zero bytes. Payload: `[1B length][map][1B valid bits HUF][HUF stream]`. Best of both worlds — deterministic zero elimination + entropy compression of the rest.

**Keyframe and start frame**

Sample number 0 is a keyframe. Since no previous packet exists for delta calculation, the differential method and ZigZag are skipped. Data is processed directly by FLAG, HUF, FLAG+HUF or ANS. A keyframe occurs automatically every 8 packets or after a device reset.

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

    // On the receiver side:
    dmd_decompress(&dec, compressed, comp_len, decompressed);
}
```

### Building without VLA (other compilers)

If your compiler does not support C99 VLA (IAR, Keil, MSVC C++), define the maximum packet length at compile time:

```
gcc -DDMD_PKT_MAX_BUILD=32 nic_dmd.c ...
```

Buffers will be compiled to a fixed size of 32B. Ideal for single-purpose firmware with one fixed packet length (typical Arduino use case).

---

## Files

| File                 | Description                                        |
| -------------------- | -------------------------------------------------- |
| `nic_dmd.py`         | Python implementation — reference, for testing     |
| `nic_dmd_utils.py`   | Helper functions — analysis and result printing    |
| `nic_dmd.c`          | C implementation for ATmega328                     |
| `nic_dmd.h`          | Header file                                        |
| `Makefile`           | Compilation and testing                            |

### Testing and benchmark

| File                 | Description                                        |
| -------------------- | -------------------------------------------------- |
| `nic_dmd_test.py`    | Python tests — round-trip, meteo, keyframe         |
| `nic_dmd_test.c`     | C tests — round-trip, all-zeros, meteo             |
| `fetch_plus.py`      | Real data download and benchmark (20 sources)      |
| `benchmark.py`       | Comparison: DMD vs Huffman vs Heatshrink           |

---

## Licence

GPL v3 — NIC Native Intellect Community

---

## Acknowledgements

To my brother for advice during the development of this project.
For technical assistance with code optimisation to AI assistants Claude (Anthropic) and Gemini (Google).

★ Viva La Resistánce ★
