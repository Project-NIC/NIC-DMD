# SPDX-License-Identifier: MIT

"""
NIC DMD — Python tests
Run via: make python  or  python3 nic_dmd_test.py
"""

import random, struct, sys
sys.path.insert(0, '.')
from nic_dmd import DmdEncoder, DmdDecoder, dmd_compress, dmd_decompress

errors = 0
total  = 0

def check(name, ok):
    global errors, total
    total += 1
    if not ok:
        errors += 1
        print(f"  FAIL: {name}")

print("\n=== NIC DMD — Python tests ===\n")

# Test 1: round-trip various lengths
print("Test 1: round-trip (random data)")
random.seed(42)
for pkt_len in [8, 16, 32, 64, 128, 255]:
    enc = DmdEncoder(pkt_len)
    dec = DmdDecoder(pkt_len)
    e   = 0
    for i in range(500):
        data   = bytes(random.randint(0, 255) for _ in range(pkt_len))
        comp   = enc.compress(data)
        decomp = dec.decompress(comp)
        if decomp != data:
            e += 1
    print(f"  pkt_len={pkt_len:3d}: 500 packets: {'OK' if e==0 else f'ERRORS={e}'}")
    check(f"round-trip pkt_len={pkt_len}", e == 0)

# Test 2: all-zeros
print("\nTest 2: all-zeros")
for pkt_len in [16, 64, 128]:
    enc = DmdEncoder(pkt_len)
    dec = DmdDecoder(pkt_len)
    e   = 0
    for _ in range(8):
        data   = bytes(pkt_len)
        comp   = enc.compress(data)
        decomp = dec.decompress(comp)
        if decomp != data: e += 1
    print(f"  pkt_len={pkt_len:3d}: all-zeros: {'OK' if e==0 else f'ERRORS={e}'}")
    check(f"all-zeros pkt_len={pkt_len}", e == 0)

# Test 3: keyframe
print("\nTest 3: keyframe (sample=0)")
random.seed(123)
for pkt_len in [16, 64, 255]:
    data     = bytes(random.randint(0, 255) for _ in range(pkt_len))
    previous = bytes(pkt_len)
    comp     = dmd_compress(data, previous, 0)
    decomp   = dmd_decompress(comp, previous)
    ok       = decomp == data
    print(f"  pkt_len={pkt_len:3d}: {'OK' if ok else 'FAIL'} (comp {len(comp)}B)")
    check(f"keyframe pkt_len={pkt_len}", ok)

# Test 4: meteo data
print("\nTest 4: meteo data (gradual changes)")
enc  = DmdEncoder(16)
dec  = DmdDecoder(16)
t    = -800
e    = 0
s_o  = 0; s_c = 0
random.seed(42)
for _ in range(100):
    t += random.randint(-20, 20)
    data   = struct.pack('>8h', t, 8500, 385, 1230, 0, -900, -700, -1000)
    comp   = enc.compress(data)
    decomp = dec.decompress(comp)
    if decomp != data: e += 1
    s_o += 17; s_c += len(comp)
saving = (1 - s_c / s_o) * 100
print(f"  100 packets: {'OK' if e==0 else f'ERRORS={e}'} (saving {saving:.1f}%)")
check("meteo", e == 0)

# Test 5: Reserved protocol version
print("\nTest 5: Reserved protocol version (sample_num=7)")
total += 1
reserved_header = bytes([7])  # Sets sample_num = 7
dummy_payload = bytes(16)
try:
    dmd_decompress(reserved_header + dummy_payload, dummy_payload)
    print("  FAIL: Decoder incorrectly accepted a packet with reserved protocol version!")
    errors += 1
except ValueError:
    print("  OK (ValueError correctly raised for unsupported version)")

# Test 6: C vs Python cross-check (via ctypes if available)
print("\nTest 6: skipped (run ctypes cross-check separately)")

print(f"\n{'='*50}")
print(f"TOTAL: {total} tests, {errors} failures")
print(f"RESULT: {'✓ ALL OK' if errors == 0 else '✗ FAILURES!'}")
print(f"{'='*50}\n")

sys.exit(0 if errors == 0 else 1)
