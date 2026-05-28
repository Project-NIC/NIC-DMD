// SPDX-License-Identifier: MIT

#ifndef NIC_DMD_H
#define NIC_DMD_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

/* Optimalizace bufferů: Podpora C99 VLA nebo fixní velikosti */
#ifndef DMD_PKT_MAX_BUILD
#define DMD_ENC_BUF_SIZE 255
#define DMD_VLA(type, name, size) type name[size]
#else
#define DMD_ENC_BUF_SIZE DMD_PKT_MAX_BUILD
#define DMD_VLA(type, name, size) type name[DMD_PKT_MAX_BUILD]
#endif

/* Konstanty protokolu */
#define DMD_OUT_MAX (DMD_ENC_BUF_SIZE + 1)
#define DMD_KEYFRAME_EVERY 7 // Hodnota 7 vyhrazena pro verzi protokolu

typedef struct {
    uint8_t pkt_len;
    uint8_t sample_num;
    uint8_t previous[DMD_ENC_BUF_SIZE];
} dmd_encoder_t;

typedef struct {
    uint8_t pkt_len;
    uint8_t previous[DMD_ENC_BUF_SIZE];
} dmd_decoder_t;

void dmd_encoder_init(dmd_encoder_t *enc, uint8_t pkt_len);
void dmd_decoder_init(dmd_decoder_t *dec, uint8_t pkt_len);

uint8_t dmd_compress(dmd_encoder_t *enc, const uint8_t *current, uint8_t *output);
int dmd_decompress(dmd_decoder_t *dec, const uint8_t *input, uint8_t in_len, uint8_t *output);

#endif /* NIC_DMD_H */
