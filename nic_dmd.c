// SPDX-License-Identifier: MIT

#include "nic_dmd.h"
#include <string.h>

#if defined(__AVR__)
#include <avr/pgmspace.h>
#define DMD_PROGMEM PROGMEM
#define DMD_READ_BYTE(addr) pgm_read_byte(addr)
#else
#define DMD_PROGMEM
#define DMD_READ_BYTE(addr) (*(addr))
#endif

#define ANS_SCALE    32
#define ANS_WEIGHT_0 29
#define ANS_WEIGHT_1 3

#define DELTA_NONE 0
#define DELTA_1B   1
#define DELTA_2B   2
#define DELTA_FULL 3

/* Vyhledávací tabulky a Huffmanovy stromy (ROM) */
static const uint8_t DMD_PROGMEM _POPCOUNT_LUT[256] = {
    0,1,1,2,1,2,2,3, 1,2,2,3,2,3,3,4, 1,2,2,3,2,3,3,4, 2,3,3,4,3,4,4,5,
    1,2,2,3,2,3,3,4, 2,3,3,4,3,4,4,5, 2,3,3,4,3,4,4,5, 3,4,4,5,4,5,5,6,
    1,2,2,3,2,3,3,4, 2,3,3,4,3,4,4,5, 2,3,3,4,3,4,4,5, 3,4,4,5,4,5,5,6,
    2,3,3,4,3,4,4,5, 3,4,4,5,4,5,5,6, 3,4,4,5,4,5,5,6, 4,5,5,6,5,6,6,7,
    1,2,2,3,2,3,3,4, 2,3,3,4,3,4,4,5, 2,3,3,4,3,4,4,5, 3,4,4,5,4,5,5,6,
    2,3,3,4,3,4,4,5, 3,4,4,5,4,5,5,6, 3,4,4,5,4,5,5,6, 4,5,5,6,5,6,6,7,
    2,3,3,4,3,4,4,5, 3,4,4,5,4,5,5,6, 3,4,4,5,4,5,5,6, 4,5,5,6,5,6,6,7,
    3,4,4,5,4,5,5,6, 4,5,5,6,5,6,6,7, 4,5,5,6,5,6,6,7, 5,6,6,7,6,7,7,8
};

static const uint8_t DMD_PROGMEM _HUF_HI_LEN[]  = {1, 3, 3, 4, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6};
static const uint8_t DMD_PROGMEM _HUF_HI_CODE[] = {0x01, 0x03, 0x00, 0x04, 0x0D, 0x0C, 0x0E, 0x16, 0x15, 0x17, 0x0F, 0x14, 0x0B, 0x0A, 0x08, 0x09};
static const uint8_t DMD_PROGMEM _HUF_LO_LEN[]  = {1, 4, 4, 5, 4, 5, 5, 5, 5, 5, 5, 5, 6, 6, 6, 6};
static const uint8_t DMD_PROGMEM _HUF_LO_CODE[] = {0x01, 0x04, 0x07, 0x0B, 0x03, 0x04, 0x0A, 0x03, 0x05, 0x02, 0x00, 0x01, 0x1B, 0x1A, 0x19, 0x18};

/* Pomocné funkce */
static inline uint8_t _zigzag_enc(uint8_t x) {
    int8_t s = (int8_t)x;
    return (uint8_t)((s << 1) ^ (s >> 7));
}

static inline uint8_t _zigzag_dec(uint8_t x) {
    return (uint8_t)((x >> 1) ^ -(x & 1));
}

static uint16_t _count_onebits(const uint8_t *data, uint8_t len) {
    uint16_t n = 0;
    for (uint8_t i = 0; i < len; i++) {
        n += DMD_READ_BYTE(&_POPCOUNT_LUT[data[i]]);
    }
    return n;
}

static void _delta_encode_zz(const uint8_t *current, const uint8_t *previous, uint8_t len, uint8_t delta_type, uint8_t *out) {
    if (delta_type == DELTA_1B) {
        for (uint8_t i = 0; i < len; i++) {
            out[i] = _zigzag_enc(current[i] - previous[i]);
        }
    } else if (delta_type == DELTA_FULL) {
        uint8_t borrow = 0;
        for (int16_t i = len - 1; i >= 0; i--) {
            int16_t d = (int16_t)current[i] - previous[i] - borrow;
            out[i] = _zigzag_enc((uint8_t)(d & 0xFF));
            borrow = (d < 0) ? 1 : 0;
        }
    } else if (delta_type == DELTA_2B) {
        for (uint8_t i = 0; i < len; ) {
            if (i + 1 < len) {
                uint16_t c = (current[i] << 8) | current[i + 1];
                uint16_t p = (previous[i] << 8) | previous[i + 1];
                uint16_t d = c - p;
                out[i] = _zigzag_enc((uint8_t)(d >> 8));
                out[i + 1] = _zigzag_enc((uint8_t)(d & 0xFF));
                i += 2;
            } else {
                out[i] = _zigzag_enc(current[i] - previous[i]);
                i++;
            }
        }
    }
}

static void _delta_decode_zz(const uint8_t *data, const uint8_t *previous, uint8_t len, uint8_t delta_type, uint8_t *out) {
    if (delta_type == DELTA_1B) {
        for (uint8_t i = 0; i < len; i++) {
            out[i] = _zigzag_dec(data[i]) + previous[i];
        }
    } else if (delta_type == DELTA_FULL) {
        uint8_t carry = 0;
        for (int16_t i = len - 1; i >= 0; i--) {
            uint16_t s = _zigzag_dec(data[i]) + previous[i] + carry;
            out[i] = (uint8_t)(s & 0xFF);
            carry = (uint8_t)(s >> 8);
        }
    } else if (delta_type == DELTA_2B) {
        for (uint8_t i = 0; i < len; ) {
            if (i + 1 < len) {
                uint16_t d = (_zigzag_dec(data[i]) << 8) | _zigzag_dec(data[i + 1]);
                uint16_t p = (previous[i] << 8) | previous[i + 1];
                uint16_t o = d + p;
                out[i] = (uint8_t)(o >> 8);
                out[i + 1] = (uint8_t)(o & 0xFF);
                i += 2;
            } else {
                out[i] = _zigzag_dec(data[i]) + previous[i];
                i++;
            }
        }
    }
}

/* Inicializace kodérů a dekodérů */
void dmd_encoder_init(dmd_encoder_t *enc, uint8_t pkt_len) {
    enc->pkt_len = pkt_len;
    enc->sample_num = 0;
    memset(enc->previous, 0, pkt_len);
}

void dmd_decoder_init(dmd_decoder_t *dec, uint8_t pkt_len) {
    dec->pkt_len = pkt_len;
    memset(dec->previous, 0, pkt_len);
}

/* Hlavní kompresní smyčka využívající VLA pro dynamickou správu polí */
uint8_t dmd_compress(dmd_encoder_t *enc, const uint8_t *current, uint8_t *output) {
    uint8_t n_raw = enc->pkt_len;
    bool is_keyframe = (enc->sample_num == 0);

    DMD_VLA(uint8_t, work, n_raw);
    uint8_t delta_type = DELTA_NONE;

    if (is_keyframe) {
        memcpy(work, current, n_raw);
    } else {
        uint16_t best_score = _count_onebits(current, n_raw);
        memcpy(work, current, n_raw);

        uint8_t dts[] = {DELTA_1B, DELTA_2B, DELTA_FULL};
        DMD_VLA(uint8_t, tmp, n_raw);
        for (uint8_t i = 0; i < 3; i++) {
            _delta_encode_zz(current, enc->previous, n_raw, dts[i], tmp);
            uint16_t score = _count_onebits(tmp, n_raw);
            if (score < best_score) {
                best_score = score;
                delta_type = dts[i];
                memcpy(work, tmp, n_raw);
            }
        }
    }

    uint8_t best_size = n_raw;
    uint8_t winning_method = 0; // 0=RAW, 3=FLAG (pro zjednodušenou ukázku)
    DMD_VLA(uint8_t, payload, n_raw);
    memcpy(payload, work, n_raw);

    /* (c) Zkouška metody FLAG - Rotující maska a early exit */
    uint8_t map_size = (n_raw + 7) / 8;
    if (1 + map_size < best_size) {
        DMD_VLA(uint8_t, flag_data, n_raw);
        uint8_t nz_limit = best_size - 1 - map_size;
        uint8_t nz_count = 0;
        uint8_t mask = 0x80;
        uint8_t map_pos = 1;
        bool flag_ok = true;

        flag_data[0] = n_raw;
        memset(&flag_data[1], 0, map_size);

        for (uint8_t i = 0; i < n_raw; i++) {
            if (work[i] == 0) {
                flag_data[map_pos] |= mask;
            } else {
                if (nz_count >= nz_limit) { flag_ok = false; break; }
                flag_data[1 + map_size + nz_count++] = work[i];
            }
            mask >>= 1;
            if (mask == 0) { mask = 0x80; map_pos++; }
        }

        if (flag_ok) {
            uint8_t flag_len = 1 + map_size + nz_count;
            if (flag_len < best_size) {
                best_size = flag_len;
                winning_method = 3;
                memcpy(payload, flag_data, flag_len);
            }
        }
    }

    /* Zestavení hlavičky */
    uint8_t header = enc->sample_num & 0x07;
    header |= (delta_type & 0x03) << 3;
    if (winning_method == 3) header |= (1 << 5); // FLAG bit

    output[0] = header;
    memcpy(&output[1], payload, best_size);

    /* Aktualizace stavu a vzorku */
    memcpy(enc->previous, current, n_raw);
    enc->sample_num = (enc->sample_num + 1) % DMD_KEYFRAME_EVERY;

    return best_size + 1;
}

/* Dekompresní funkce s tvrdým ošetřením chyb (V3, V4, K2) */
int dmd_decompress(dmd_decoder_t *dec, const uint8_t *input, uint8_t in_len, uint8_t *output) {
    if (in_len == 0) return -1; // Neplatná data / prázdný paket

    uint8_t n_raw = dec->pkt_len;
    uint8_t header = input[0];
    const uint8_t *payload = &input[1];
    
    uint8_t sample_num = header & 0x07;
    if (sample_num == 7) {
        return -3; // Chyba: Nepodporovaná verze protokolu
    }

    bool use_huf = (header & (1 << 7)) != 0;
    bool use_ans = (header & (1 << 6)) != 0;
    if (use_huf || use_ans) {
        return -2; // Chyba: Komprese Huffman a ANS nejsou v této C implementaci podporovány
    }

    bool use_flag = (header & (1 << 5)) != 0;
    uint8_t delta_type = (header >> 3) & 0x03;

    DMD_VLA(uint8_t, work, n_raw);

    if (use_flag) {
        if (in_len <= 1) return -1; // Ochrana proti přetečení
        uint8_t n = payload[0];
        if (n != n_raw) return -1;  // Rozpor v délce paketu
        
        uint8_t map_size = (n + 7) / 8;
        if (1 + map_size > in_len - 1) return -1; // Nedostatek dat pro mapu

        uint8_t nz_idx = 1 + map_size;
        uint8_t mask = 0x80;
        uint8_t map_pos = 1;

        for (uint8_t i = 0; i < n; i++) {
            if (payload[map_pos] & mask) {
                work[i] = 0;
            } else {
                if (nz_idx >= in_len - 1) return -1; // Ochrana proti přetečení
                work[i] = payload[nz_idx++];
            }
            mask >>= 1;
            if (mask == 0) { mask = 0x80; map_pos++; }
        }
    } else {
        if (in_len - 1 < n_raw) return -1; // Nedostatek dat pro RAW
        memcpy(work, payload, n_raw);
    }

    if (delta_type != DELTA_NONE) {
        _delta_decode_zz(work, dec->previous, n_raw, delta_type, output);
    } else {
        memcpy(output, work, n_raw);
    }

    memcpy(dec->previous, output, n_raw);
    return 0; // Úspěch
}
