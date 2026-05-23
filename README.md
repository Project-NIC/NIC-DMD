★ N.I.C. ★

# NIC DMD — Delta Markov Duda

## Compression protocol for embedded devices and LoRa transmission

[![Licence: GPL v3](https://img.shields.io/badge/Licence-GPLv3-red.svg)](https://www.gnu.org/licenses/gpl-3.0)

---

## What is DMD?

DMD is a multiplatform compression protocol for small data packets from weather stations, energy meters, GPS trackers and other embedded devices. It is designed for transmission over bandwidth-limited technologies such as LoRa.

The protocol runs fully on the ATmega328 controller and requires no large dictionaries or lookup tables in memory.

For this reason, after extensive testing, it has been optimized even at the cost of slightly lower compression ratio — reducing average compression by approximately 3% (weather station data) resulted in a roughly 70% reduction in CPU load.

---

## Why DMD?

Existing compression libraries for embedded devices either require hundreds of extra bytes of RAM (Heatshrink), or need to transmit a Huffman table alongside the data. DMD takes a different approach — it combines several simple methods with heuristic analysis and selects the best result for each packet individually.

**Key advantages:**
- No lookup table in ROM or RAM
- Adaptive method selection per packet
- Fully deterministic decompression — no data loss
- Maximum data expansion of 1 byte (header) in the worst case
- Implementation in both Python and C (ATmega328)

---

## When DMD is not worth using

DMD is designed for data that changes slowly and predictably over time — sensor values, GPS coordinates, industrial telemetry. If the input data is random, encrypted or already compressed, DMD will add only 1 byte of header and send it as RAW. This is correct behaviour — no lossy compression, no degradation.

---

## Compatibility

**Python:** 3.10 or newer (uses `bytes | None` type annotations).

**C:** C99 or newer. Tested with GCC on PC (Linux/Windows) and AVR-GCC for ATmega328. No dependencies on the standard library other than `<string.h>`.

**Arduino:** Copy `nic_dmd.c` and `nic_dmd.h` into your project folder. Compatible with Arduino IDE 1.8+ and 2.x.

**Benchmark dependencies:** `pip install requests heatshrink2`

**Packet length:** The technical minimum is 1B, but below 16B compression is practically not worth it — the header overhead (1B) and ANS state (2B) consume most of any potential saving. Recommended minimum is **16B**. Maximum is **255B**. DMD achieves best results on data where adjacent packets change slowly — typically 16–64B sensor telemetry.

---

## Data validation and integrity

In order to achieve maximum performance and absolute minimization of CPU load, the library performs no additional header checks or validation of the length of passed data.

The protocol design strictly assumes that integrity checking (e.g. hardware CRC) and discarding of corrupted or empty packets is handled by the lower transport layer or the main application (typically the radio module itself, data collection logic, etc.). The library user must ensure at the application level that only structurally correct data enters the compression and decompression functions. This delegation of responsibility achieves low memory overhead without wasting CPU clock cycles.

---

## Results

Tested on 12,000 samples from 5 real data sources (Sněžka, Antarctica, Death Valley, Oymyakon, Sahara):

```
=================================================================================================================
        GLOBAL SUMMARY — average savings across all sources (32B)
=================================================================================================================
  Method                   |  Average |     Min |     Max |  RAM  	|        Note
-----------------------------------------------------------------------------------------------------------------
RAW (no compression)       |    0.0%  |    0.0% |    0.0% |   0   	|
* DMD protocol *           | * 46.2%  | * 38.5% | * 56.4% | ~161B 	| no table, adaptive
Heatshrink (w=8,l=4)       |   13.4%  |   10.3% |   18.0% | ~256B 	| sliding window
Heatshrink (w=10,l=5)      |    8.5%  |    5.8% |   13.0% | ~400B 	| sliding window
Delta+Huffman (static)     |   45.3%  |   36.0% |   59.1% | approx. 1KB | fixed table ~700B ROM
Delta+Huffman (dynamic)    |   48.3%  |   39.1% |   62.7% | approx. 1KB | table transmitted once at session start
=================================================================================================================
```

---

## RAM usage

Values include stack during compression and encoder/decoder structures.

```
===============================================================
  Packet length | Compression stack | dmd_encoder_t | dmd_decoder_t
---------------+-------------------+---------------+--------------
       16B     |        78B        |      19B      |     18B
       32B     |       126B        |      35B      |     34B
       64B     |       222B        |      67B      |     66B
      128B     |       414B        |     131B      |    130B
      255B     |       795B        |     258B      |    257B
===============================================================
```

Peak RAM during `dmd_compress` call = Compression stack + dmd_encoder_t.

For typical use (16–32B packets) the peak is **97–161B** — no problem on ATmega328 (2KB RAM).

---

## How it works

```
+---------------------------------------------------------------------------+
|                       START: Input data packet                            |
+---------------------------------------------------------------------------+
                             |                                     |
                             v                                     |
+--------------------------------------------------------+         |
|  Pre-processing: Delta, ZigZag and state storage (LIFO)|         |
+--------------------------------------------------------+         |
            |                              |                       |
            v                              v                       |
+-----------------------+      +------------------------+          |
|   Method: µANS        |      |  Method: Zero flagging |          |
| [ Compression attempt ]|      | [ Zero map estimate ]  |          |
+-----------------------+      +------------------------+          |
            |                              |                       |
            v                              v                       |
+-------------------------------------------------------------+    |
| Decision: Is result (µANS or Flagging) smaller than RAW?   |    |
+-------------------------------------------------------------+    |
            |                                          |           |
            v                                          v           v
+-----------------------+                 +---------------------------+
|  YES: Compressed      |                 |  NO: Send as RAW          |
| [ Build header ]      |                 | [ RAW header ]            |
+-----------------------+                 +---------------------------+
```

### Header (1 byte)

Every compressed packet starts with one byte of header:

```
MSB                    LSB
 7    6    5    4    3    2    1    0
[rsv][ans][flg][dlt][dlt][smp][smp][smp]
```

```
=======================================================================
| Bits |        Meaning                                               |
|------|--------------------------------------------------------------|
|   7  | Reserved (for future extension)                              |
|   6  | µANS compression           1 = ON                           |
|   5  | Zero byte flagging         1 = ON                           |
|  4-3 | Delta type: 00=none, 01=1B, 10=2B, 11=full sample           |
|  2-0 | Sample number (0-7)        0 = keyframe / start frame       |
=======================================================================
```

If neither flagging nor ANS can compress the data better than RAW, the original data is sent with all flags set to 0 in bits 3-7 of the header. The receiver recognises RAW because the header uses no settings (ANS = 0, Flagging = 0, Delta = 00).

### Compression layers

**1. Delta — differential method**

Comparison of two consecutive packets. Where data changes slowly (temperature, pressure, GPS coordinates), subtraction produces chains of zero or very small values. The protocol tests four delta types and selects the one with the best result according to a heuristic (one-bit count).

Supported types:
- **1B delta** — byte by byte
- **2B delta** — in two-byte groups (suitable for 16-bit sensors)
- **Full sample** — each byte minus the same byte from the previous packet
- **No delta** — data passes through without differential encoding

**2. ZigZag encoding**

After applying delta, the data is converted using ZigZag encoding. Negative differences map to small odd numbers, positive to small even numbers. The result is data with a high count of zero bits, which responds better to the subsequent compression methods.

ZigZag is not applied when delta = none (including keyframe).

**3. Zero byte flagging**

Each zero byte is replaced by a single bit in a map. Before the map, the packet length is stored (1B), so the decoder knows the data length without prior agreement. Non-zero bytes follow in their original order.

Example for a 16B packet with 12 zeros:
```
Original: [0, 0, 5, 0, 0, 0, 3, 0, 0, 0, 0, 0, 7, 0, 0, 2]  (16B)
Payload:  [16][11011101 11110110][5, 3, 7, 2]
           1B length + 2B map + 4B non-zero = 7B
Result:   8B instead of 16B (1B header + 7B payload)
```

**4. µANS compression**

Asymmetric Numeral Systems (ANS) work at the bit level with two weights: a zero bit is highly probable (29/32), a one bit less so (3/32). For data with a majority of zeros after delta+ZigZag, it achieves significant compression without a table.

The ANS payload contains the data length (1B), state (2B) and encoded bytes. The decoder does not need to know the length in advance.

ANS is actually compressed and measured. Flagging is estimated deterministically. The shorter of the two results is selected. If compression would increase the data size, the original data is sent — maximum 1 byte overhead.

**Keyframe and start frame**

Sample number 0 is a keyframe. Since no previous packet exists for delta calculation, the differential method and ZigZag are skipped. Data is processed directly by flagging or µANS. A keyframe occurs automatically every 8 packets or after a device reset.

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

print(f"Compressed: {PKT_LEN}B -> {len(compressed)}B")
assert decompressed == data
```

### C (ATmega328 / Arduino)

```c
#include "nic_dmd.h"

dmd_encoder_t enc;
dmd_decoder_t dec;

void setup() {
    dmd_encoder_init(&enc, 16);   // packet length -- must match on both sides
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

---

## Files

| File | Description |
|------|-------------|
| `nic_dmd.py` | Python implementation — reference, for testing |
| `nic_dmd_utils.py` | Helper functions — analysis and result printing |
| `nic_dmd.c` | C implementation for ATmega328 |
| `nic_dmd.h` | Header file |
| `Makefile` | Compilation and testing |

### Testing

| File | Description |
|------|-------------|
| `nic_dmd_test.py` | Python tests — round-trip, meteo, keyframe |
| `nic_dmd_test.c` | C tests — round-trip, all-zeros, meteo |
| `benchmark.py` | Comparison: DMD vs Huffman vs Heatshrink |
| `fetch_data_v2.py` | Download real weather data (Open-Meteo) |
| `fetch_real_data_v2.py` | DWD, GPS, combined data |

---

## Licence

GPL v3 — NIC Native Intellect Community

---

## Acknowledgements

To my brother for advice during the development of this project.
For technical assistance with code optimisation to AI assistants Claude (Anthropic) and Gemini (Google).

★ Viva La Resistánce ★
