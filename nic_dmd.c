/**
 * NIC DMD — Delta Markov Duda
 * Implementace komprese/dekomprese — paměťově optimalizovaná verze
 *
 * Peak RAM při kompresi (pkt_len bajtů):
 *   Stack:   pkt_len*2 + (pkt_len+10) + ~30B = ~2.1 × pkt_len
 *   Strukt:  pkt_len*2 + 3B (enc) + pkt_len + 2B (dec)
 *
 * Licence: GPL v3
 * NIC — Native Intellect Community
 * https://github.com/Project-NIC/NIC-DMD
 */

#include "nic_dmd.h"
#include <string.h>

/* ---------------------------------------------------------------------------
 * Interní pomocné funkce
 * ------------------------------------------------------------------------- */

static uint8_t popcount8(uint8_t x)
{
    x = x - ((x >> 1u) & 0x55u);
    x = (x & 0x33u) + ((x >> 2u) & 0x33u);
    return (x + (x >> 4u)) & 0x0Fu;
}

static uint16_t count_ones(const uint8_t *buf, uint16_t len)
{
    uint16_t n = 0u;
    for (uint16_t i = 0u; i < len; i++) n += popcount8(buf[i]);
    return n;
}

static uint8_t zigzag_enc(uint8_t x)
{
    int8_t s = (int8_t)x;
    return (uint8_t)(((s << 1) ^ (s >> 7)) & 0xFF);
}

static uint8_t zigzag_dec(uint8_t x)
{
    return (uint8_t)(((x >> 1u) ^ (uint8_t)(-(x & 1u))) & 0xFF);
}

/* ---------------------------------------------------------------------------
 * Delta enkódování / dekódování — in-place nebo out-of-place
 * ------------------------------------------------------------------------- */

static void delta_encode(const uint8_t *cur, const uint8_t *prev,
                          uint8_t *out, uint16_t len, uint8_t dtype)
{
    if (dtype == DELTA_1B || dtype == DELTA_FULL) {
        for (uint16_t i = 0u; i < len; i++)
            out[i] = (uint8_t)(cur[i] - prev[i]);
        return;
    }
    uint16_t i = 0u;
    while (i < len) {
        if (i + 1u < len) {
            uint16_t c = ((uint16_t)cur[i] << 8u) | cur[i+1u];
            uint16_t p = ((uint16_t)prev[i] << 8u) | prev[i+1u];
            uint16_t d = (uint16_t)(c - p);
            out[i]     = (uint8_t)(d >> 8u);
            out[i+1u]  = (uint8_t)(d & 0xFFu);
            i += 2u;
        } else {
            out[i] = (uint8_t)(cur[i] - prev[i]);
            i++;
        }
    }
}

static void delta_decode(const uint8_t *data, const uint8_t *prev,
                          uint8_t *out, uint16_t len, uint8_t dtype)
{
    if (dtype == DELTA_1B || dtype == DELTA_FULL) {
        for (uint16_t i = 0u; i < len; i++)
            out[i] = (uint8_t)(data[i] + prev[i]);
        return;
    }
    uint16_t i = 0u;
    while (i < len) {
        if (i + 1u < len) {
            uint16_t d = ((uint16_t)data[i] << 8u) | data[i+1u];
            uint16_t p = ((uint16_t)prev[i] << 8u) | prev[i+1u];
            uint16_t o = (uint16_t)(d + p);
            out[i]     = (uint8_t)(o >> 8u);
            out[i+1u]  = (uint8_t)(o & 0xFFu);
            i += 2u;
        } else {
            out[i] = (uint8_t)(data[i] + prev[i]);
            i++;
        }
    }
}

/* ---------------------------------------------------------------------------
 * µANS enkódování
 * Výstup přímo do `out` bufferu (záhlaví+1).
 * Vrátí délku výstupu nebo 0 pokud se nevyplatí.
 *
 * Paměť na stacku: ans_tmp[len+10] — pouze tolik kolik potřebujeme.
 * Zahod pokud výsledek >= vstup - 3B.
 * ------------------------------------------------------------------------- */

static uint8_t uans_encode(const uint8_t *data, uint8_t len,
                            uint8_t *out)
{
    /* Dynamická velikost tmp bufferu — max co ANS může vyprodukovat
     * před early exitem je (len - 3) bajtů, přidáme 10B rezervu */
    uint8_t  tmp_buf[DMD_PKT_MAX + 10u];
    uint16_t tmp_len  = 0u;
    uint32_t state    = ANS_SCALE;
    uint8_t  threshold = (len > 3u) ? (uint8_t)(len - 3u) : 0u;

    for (int16_t bi = (int16_t)(len - 1); bi >= 0; bi--) {
        uint8_t byte = data[bi];
        for (uint8_t j = 0u; j < 8u; j++) {
            uint8_t bit    = (byte >> j) & 1u;
            uint8_t weight = (bit == 0u) ? ANS_W0 : ANS_W1;

            while (state >= (uint32_t)weight * 256u) {
                if (tmp_len >= (uint16_t)(DMD_PKT_MAX + 10u)) return 0u;
                tmp_buf[tmp_len++] = (uint8_t)(state & 0xFFu);
                state >>= 8u;
            }

            state = (state / weight) * ANS_SCALE
                  + (bit == 0u ? 0u : ANS_W0)
                  + (state % weight);
        }

        /* Early exit */
        if ((uint16_t)(3u + tmp_len) >= threshold) return 0u;
    }

    uint8_t total = (uint8_t)(3u + tmp_len);
    if (total >= threshold) return 0u;

    /* Sestav výstup: [length][state_hi][state_lo][bajty pozpátku] */
    out[0] = len;
    out[1] = (uint8_t)((state >> 8u) & 0xFFu);
    out[2] = (uint8_t)(state & 0xFFu);
    for (uint16_t i = 0u; i < tmp_len; i++)
        out[3u + i] = tmp_buf[tmp_len - 1u - i];

    return total;
}

static void uans_decode(const uint8_t *data, uint8_t data_len, uint8_t *out)
{
    uint8_t  length     = data[0];
    uint32_t state      = ((uint32_t)data[1] << 8u) | data[2];
    uint8_t  si         = 3u;
    uint8_t  stream_end = data_len;

    for (uint8_t i = 0u; i < length; i++) {
        uint8_t byte = 0u;
        for (uint8_t j = 0u; j < 8u; j++) {
            uint8_t pos = (uint8_t)(state % ANS_SCALE);
            uint8_t bit, weight, offset;

            if (pos < ANS_W0) {
                bit = 0u; weight = ANS_W0; offset = pos;
            } else {
                bit = 1u; weight = ANS_W1; offset = pos - ANS_W0;
            }

            byte  |= (uint8_t)(bit << j);
            state  = (uint32_t)weight * (state / ANS_SCALE) + offset;

            if (state < ANS_SCALE && si < stream_end)
                state = (state << 8u) | data[si++];
        }

        uint8_t rev = 0u;
        for (uint8_t j = 0u; j < 8u; j++)
            rev |= (uint8_t)(((byte >> j) & 1u) << (7u - j));
        out[i] = rev;
    }
}

/* ---------------------------------------------------------------------------
 * Flagování nulových bajtů
 * Formát: [1B délka][⌈N/8⌉B mapa][nenulové bajty]
 * ------------------------------------------------------------------------- */

static uint16_t flag_estimated_size(const uint8_t *data, uint16_t len)
{
    uint16_t zeros    = 0u;
    uint16_t map_size = (len + 7u) / 8u;
    for (uint16_t i = 0u; i < len; i++)
        if (data[i] == 0u) zeros++;
    if (zeros <= (1u + map_size)) return 0u;
    return (uint16_t)(1u + map_size + (len - zeros));
}

static uint8_t flag_encode(const uint8_t *data, uint16_t len, uint8_t *out)
{
    uint16_t map_size = (len + 7u) / 8u;
    uint8_t  nz_idx   = (uint8_t)(1u + map_size);
    out[0] = (uint8_t)len;
    memset(out + 1u, 0, map_size);
    for (uint16_t i = 0u; i < len; i++) {
        if (data[i] == 0u)
            out[1u + i/8u] |= (uint8_t)(1u << (7u - (i % 8u)));
        else
            out[nz_idx++] = data[i];
    }
    return nz_idx;
}

static void flag_decode(const uint8_t *data, uint8_t *out)
{
    uint8_t  n        = data[0];
    uint16_t map_size = ((uint16_t)n + 7u) / 8u;
    uint8_t  nz_idx   = (uint8_t)(1u + map_size);
    for (uint8_t i = 0u; i < n; i++) {
        if (data[1u + i/8u] & (uint8_t)(1u << (7u - (i % 8u))))
            out[i] = 0u;
        else
            out[i] = data[nz_idx++];
    }
}

/* ---------------------------------------------------------------------------
 * Záhlaví
 * ------------------------------------------------------------------------- */

static uint8_t build_header(uint8_t sn, uint8_t use_ans,
                              uint8_t use_flag, uint8_t dt)
{
    uint8_t h = sn & 0x07u;
    if (use_ans)  h |= (1u << 6u);
    if (use_flag) h |= (1u << 5u);
    h |= (uint8_t)((dt & 0x03u) << 3u);
    return h;
}

/* ---------------------------------------------------------------------------
 * Veřejné API
 * ------------------------------------------------------------------------- */

void dmd_encoder_init(dmd_encoder_t *enc, uint16_t pkt_len)
{
    memset(enc->previous, 0, sizeof(enc->previous));
    enc->sample_num = 0u;
    enc->pkt_len    = pkt_len;
}

void dmd_decoder_init(dmd_decoder_t *dec, uint16_t pkt_len)
{
    memset(dec->previous, 0, sizeof(dec->previous));
    dec->pkt_len = pkt_len;
}

uint8_t dmd_compress(dmd_encoder_t *enc,
                     const uint8_t *current,
                     uint8_t       *out)
{
    uint16_t len        = enc->pkt_len;
    uint8_t  sample_num = enc->sample_num;

    /*
     * Sdílený pracovní buffer:
     *   work[0..len-1]  = aktuálně nejlepší kandidát (delta+ZZ nebo originál)
     *   tmp [0..len-1]  = dočasný výpočet (přepíše se v každé iteraci)
     *
     * Oba leží v jednom poli work[2*DMD_PKT_MAX] rozděleném na půl.
     * Tím šetříme jeden plný buffer oproti původní verzi.
     */
    uint8_t  buf[DMD_PKT_MAX * 2u];
    uint8_t *work = buf;
    uint8_t *tmp  = buf + DMD_PKT_MAX;

    uint8_t delta_type = DELTA_NONE;

    if (sample_num == 0u) {
        /* Keyframe — žádná delta, žádný ZigZag */
        memcpy(work, current, len);
    } else {
        uint16_t best_score = count_ones(current, len);
        memcpy(work, current, len);   /* výchozí: DELTA_NONE */

        for (uint8_t dt = DELTA_1B; dt <= DELTA_FULL; dt++) {
            delta_encode(current, enc->previous, tmp, len, dt);
            for (uint16_t i = 0u; i < len; i++)
                tmp[i] = zigzag_enc(tmp[i]);
            uint16_t score = count_ones(tmp, len);
            if (score < best_score) {
                best_score = score;
                delta_type = dt;
                memcpy(work, tmp, len);
            }
        }
    }

    /*
     * ANS — zapíše přímo do out+1.
     * Pokud ANS nevyhraje, přepíšeme out+1 FLAG nebo RAW.
     */
    uint8_t ans_len  = uans_encode(work, (uint8_t)len, out + 1u);
    uint16_t flag_sz = flag_estimated_size(work, len);

    uint8_t use_ans  = 0u;
    uint8_t use_flag = 0u;

    if (ans_len > 0u && flag_sz > 0u) {
        if (ans_len <= (uint8_t)flag_sz) use_ans  = 1u;
        else                             use_flag = 1u;
    } else if (ans_len > 0u) {
        use_ans  = 1u;
    } else if (flag_sz > 0u) {
        use_flag = 1u;
    }

    if (!use_ans && !use_flag) delta_type = DELTA_NONE;

    out[0] = build_header(sample_num, use_ans, use_flag, delta_type);

    uint8_t comp_len;
    if (use_ans) {
        /* Už zapsáno v out+1 */
        comp_len = (uint8_t)(1u + ans_len);
    } else if (use_flag) {
        comp_len = (uint8_t)(1u + flag_encode(work, len, out + 1u));
    } else {
        memcpy(out + 1u, current, len);
        comp_len = (uint8_t)(1u + len);
    }

    memcpy(enc->previous, current, len);
    enc->sample_num = (uint8_t)((sample_num + 1u) % DMD_KEYFRAME);

    return comp_len;
}

uint8_t dmd_decompress(dmd_decoder_t *dec,
                       const uint8_t *data,
                       uint8_t        data_len,
                       uint8_t       *out)
{
    uint16_t       len        = dec->pkt_len;
    uint8_t        h          = data[0];
    uint8_t        use_ans    = (h >> 6u) & 1u;
    uint8_t        use_flag   = (h >> 5u) & 1u;
    uint8_t        delta_type = (h >> 3u) & 0x03u;
    const uint8_t *payload    = data + 1u;

    /* work buffer — jen pro delta+ZigZag, sdílíme s out pokud není delta */
    uint8_t work[DMD_PKT_MAX];

    if (use_ans) {
        uans_decode(payload, (uint8_t)(data_len - 1u), work);
    } else if (use_flag) {
        flag_decode(payload, work);
    } else {
        /* RAW — rovnou do work (nebo out pokud není delta) */
        if (delta_type == DELTA_NONE) {
            memcpy(out, payload, len);
            memcpy(dec->previous, out, len);
            return 0u;
        }
        memcpy(work, payload, len);
    }

    if (delta_type != DELTA_NONE) {
        for (uint16_t i = 0u; i < len; i++)
            work[i] = zigzag_dec(work[i]);
        delta_decode(work, dec->previous, out, len, delta_type);
    } else {
        memcpy(out, work, len);
    }

    memcpy(dec->previous, out, len);
    return 0u;
}
