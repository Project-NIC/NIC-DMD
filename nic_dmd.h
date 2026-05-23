/**
 * NIC DMD — Delta Markov Duda
 * ============================
 * Adaptivní komprese pro malé procesory a LoRa přenos.
 *
 * Záhlaví (1 bajt):
 *   MSB                    LSB
 *    7    6    5    4    3    2    1    0
 *   [rez][ans][flg][dlt][dlt][vzo][vzo][vzo]
 *
 *   bit 7:   rezerva (pro DMD+)
 *   bit 6:   µANS komprese (1=ON)
 *   bit 5:   flagování nulových bajtů (1=ON)
 *   bit 4-3: delta: 00=žádná, 01=1B, 10=2B, 11=celý vzorek
 *   bit 2-0: číslo vzorku 0-7 (0 = keyframe)
 *
 * Licence: GPL v3
 * NIC — Native Intellect Community
 * https://github.com/Project-NIC
 */

#ifndef NIC_DMD_H
#define NIC_DMD_H

#include <stdint.h>

/* ---------------------------------------------------------------------------
 * Konfigurace
 * ------------------------------------------------------------------------- */

#define DMD_PKT_MAX      255u   /* maximální délka vstupního paketu (bajtů) */
#define DMD_OUT_MAX      260u   /* maximální délka výstupu (PKT_MAX + overhead) */
#define DMD_KEYFRAME     8u     /* keyframe každých N vzorků */

/* µANS konstanty */
#define ANS_SCALE        32u
#define ANS_W0           29u    /* váha pro bit=0 */
#define ANS_W1           3u     /* váha pro bit=1 */

/* Delta typy */
#define DELTA_NONE       0u
#define DELTA_1B         1u
#define DELTA_2B         2u
#define DELTA_FULL       3u

/* ---------------------------------------------------------------------------
 * Struktury stavů
 * ------------------------------------------------------------------------- */

typedef struct {
    uint8_t  previous[DMD_PKT_MAX];   /* předchozí paket */
    uint8_t  sample_num;               /* číslo vzorku 0-7 */
    uint16_t pkt_len;                  /* délka paketu */
} dmd_encoder_t;

typedef struct {
    uint8_t  previous[DMD_PKT_MAX];   /* předchozí paket */
    uint16_t pkt_len;                  /* délka paketu */
} dmd_decoder_t;

/* ---------------------------------------------------------------------------
 * API
 * ------------------------------------------------------------------------- */

/**
 * Inicializace enkodéru.
 * @param enc     ukazatel na stav enkodéru
 * @param pkt_len délka paketu (max DMD_PKT_MAX)
 */
void dmd_encoder_init(dmd_encoder_t *enc, uint16_t pkt_len);

/**
 * Komprese jednoho paketu.
 * @param enc     stav enkodéru (udržuj mezi voláními)
 * @param current vstupní data (délka enc->pkt_len)
 * @param out     výstupní buffer (min DMD_OUT_MAX bajtů)
 * @return        délka komprimovaného výstupu
 */
uint8_t dmd_compress(dmd_encoder_t *enc,
                     const uint8_t *current,
                     uint8_t       *out);

/**
 * Inicializace dekodéru.
 * @param dec     ukazatel na stav dekodéru
 * @param pkt_len délka paketu (max DMD_PKT_MAX)
 */
void dmd_decoder_init(dmd_decoder_t *dec, uint16_t pkt_len);

/**
 * Dekomprese jednoho paketu.
 * @param dec      stav dekodéru (udržuj mezi voláními)
 * @param data     komprimovaná data
 * @param data_len délka komprimovaných dat
 * @param out      výstupní buffer (min dec->pkt_len bajtů)
 * @return         0 = OK, 1 = chyba
 */
uint8_t dmd_decompress(dmd_decoder_t *dec,
                       const uint8_t *data,
                       uint8_t        data_len,
                       uint8_t       *out);

#endif /* NIC_DMD_H */
