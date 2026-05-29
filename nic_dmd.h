// SPDX-License-Identifier: MIT

#ifndef NIC_DMD_H
#define NIC_DMD_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

/* Dimenzování bufferů — dva režimy:
   - DEFAULT (bez -DDMD_PKT_MAX_BUILD): pracovni buffery pres C99 VLA (delka za
     behu podle paketu), trvaly previous[] = 255 B. Univerzalni, vhodne pro PC/testy.
   - s -DDMD_PKT_MAX_BUILD=N: vse fixni na N, ZADNE VLA, minimalni RAM, funguje
     i na prekladacich bez VLA (IAR/Keil/SDCC). Doporuceno pro MCU — N nastav
     na svoji maximalni delku paketu. */
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

/* Komprese paketu. Vraci delku vystupu = 1B hlavicka + payload.
   Rozsah navratove hodnoty: 2 az 256 (uint16_t).
   Nejhorsi pripad je 255B nekomprimovatelny paket -> 256B vystup (RAW),
   tj. maximalni expanze o 1B (hlavicka). Komprese vzdy uspeje. */
uint16_t dmd_compress(dmd_encoder_t *enc, const uint8_t *current, uint8_t *output);

/* Dekomprese paketu. Vraci 0 pri uspechu, zaporny kod pri chybe:
     0  = OK
    -1  = poskozeny/nevalidni vstup (in_len=0 nebo nesedi delka payloadu)
    -3  = rezervovana verze protokolu (sample_num=7 v hlavicce)
   in_len je uint16_t, aby pojal i maximalni 256B paket. */
int dmd_decompress(dmd_decoder_t *dec, const uint8_t *input, uint16_t in_len, uint8_t *output);

#endif /* NIC_DMD_H */
