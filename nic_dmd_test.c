/**
 * NIC DMD — C testy
 * Spusť přes: make test
 */

#include "nic_dmd.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static int errors = 0;
static int total  = 0;

static void check(const char *name, int ok)
{
    total++;
    if (!ok) {
        errors++;
        printf("  CHYBA: %s\n", name);
    }
}

/* Jednoduchý LCG generátor (bez stdlib rand závislosti) */
static uint32_t rng_state = 42u;
static uint8_t rng_byte(void)
{
    rng_state = rng_state * 1664525u + 1013904223u;
    return (uint8_t)(rng_state >> 16u);
}

static int round_trip(uint16_t pkt_len, uint32_t n_packets)
{
    dmd_encoder_t enc;
    dmd_decoder_t dec;
    dmd_encoder_init(&enc, pkt_len);
    dmd_decoder_init(&dec, pkt_len);

    uint8_t data[DMD_PKT_MAX];
    uint8_t comp[DMD_OUT_MAX];
    uint8_t decomp[DMD_PKT_MAX];

    for (uint32_t i = 0u; i < n_packets; i++) {
        for (uint16_t j = 0u; j < pkt_len; j++) {
            data[j] = rng_byte();
        }

        uint8_t cl = dmd_compress(&enc, data, comp);
        dmd_decompress(&dec, comp, cl, decomp);

        if (memcmp(data, decomp, pkt_len) != 0) {
            printf("  CHYBA round-trip pkt_len=%u i=%u\n", pkt_len, i);
            return 0;
        }
    }
    return 1;
}

int main(void)
{
    printf("\n=== NIC DMD — C testy ===\n\n");

    /* Test 1: round-trip různé délky */
    printf("Test 1: round-trip (náhodná data)\n");
    uint16_t lengths[] = {8, 16, 32, 64, 128, 255};
    for (int i = 0; i < 6; i++) {
        rng_state = 42u;
        int ok = round_trip(lengths[i], 500u);
        printf("  pkt_len=%3u: 500 paketů: %s\n",
               lengths[i], ok ? "OK" : "CHYBA");
        check("round-trip", ok);
    }

    /* Test 2: all-zeros */
    printf("\nTest 2: all-zeros\n");
    {
        uint16_t lens2[] = {16, 64, 128};
        for (int i = 0; i < 3; i++) {
            uint16_t pkt_len = lens2[i];
            dmd_encoder_t enc; dmd_decoder_t dec;
            dmd_encoder_init(&enc, pkt_len);
            dmd_decoder_init(&dec, pkt_len);
            uint8_t data[DMD_PKT_MAX]  = {0};
            uint8_t comp[DMD_OUT_MAX];
            uint8_t decomp[DMD_PKT_MAX];
            int ok = 1;
            for (int j = 0; j < 8; j++) {
                uint8_t cl = dmd_compress(&enc, data, comp);
                dmd_decompress(&dec, comp, cl, decomp);
                if (memcmp(data, decomp, pkt_len) != 0) { ok = 0; break; }
            }
            printf("  pkt_len=%3u: all-zeros: %s\n", pkt_len, ok ? "OK" : "CHYBA");
            check("all-zeros", ok);
        }
    }

    /* Test 3: keyframe reset */
    printf("\nTest 3: keyframe (sample=0) bez předchozích dat\n");
    {
        uint16_t pkt_len = 32u;
        dmd_encoder_t enc; dmd_decoder_t dec;
        dmd_encoder_init(&enc, pkt_len);
        dmd_decoder_init(&dec, pkt_len);
        uint8_t data[DMD_PKT_MAX];
        uint8_t comp[DMD_OUT_MAX];
        uint8_t decomp[DMD_PKT_MAX];
        rng_state = 123u;
        for (uint16_t j = 0; j < pkt_len; j++) data[j] = rng_byte();
        uint8_t cl = dmd_compress(&enc, data, comp);
        dmd_decompress(&dec, comp, cl, decomp);
        int ok = (memcmp(data, decomp, pkt_len) == 0);
        printf("  pkt_len=%3u: keyframe: %s (comp=%uB)\n", pkt_len, ok?"OK":"CHYBA", cl);
        check("keyframe", ok);
    }

    /* Test 4: meteo data (postupné změny) */
    printf("\nTest 4: meteo data (postupné změny)\n");
    {
        uint16_t pkt_len = 16u;
        dmd_encoder_t enc; dmd_decoder_t dec;
        dmd_encoder_init(&enc, pkt_len);
        dmd_decoder_init(&dec, pkt_len);
        uint8_t comp[DMD_OUT_MAX];
        uint8_t decomp[DMD_PKT_MAX];
        int16_t t = -800;
        int ok = 1;
        uint32_t total_orig = 0u, total_comp = 0u;

        for (int i = 0; i < 100; i++) {
            t += (int16_t)((rng_byte() % 41) - 20);
            uint8_t data[16];
            /* temp big-endian */
            data[0] = (uint8_t)((t >> 8) & 0xFF);
            data[1] = (uint8_t)(t & 0xFF);
            /* zbytek konstantní */
            int16_t vals[] = {8500, 385, 1230, 0, -900, -700, -1000};
            for (int k = 0; k < 7; k++) {
                data[2 + k*2]     = (uint8_t)((vals[k] >> 8) & 0xFF);
                data[2 + k*2 + 1] = (uint8_t)(vals[k] & 0xFF);
            }
            uint8_t cl = dmd_compress(&enc, data, comp);
            dmd_decompress(&dec, comp, cl, decomp);
            if (memcmp(data, decomp, pkt_len) != 0) { ok = 0; break; }
            total_orig += pkt_len + 1u;
            total_comp += cl;
        }
        float saving = 100.0f * (1.0f - (float)total_comp / (float)total_orig);
        printf("  100 meteo paketů: %s (úspora %.1f%%)\n",
               ok ? "OK" : "CHYBA", saving);
        check("meteo", ok);
    }

    /* Výsledek */
    printf("\n%s\n", "=================================================");
    printf("CELKEM: %d testů, %d chyb\n", total, errors);
    printf("VÝSLEDEK: %s\n", errors == 0 ? "✓ VŠE OK" : "✗ CHYBY!");
    printf("%s\n\n", "=================================================");

    return errors == 0 ? 0 : 1;
}
