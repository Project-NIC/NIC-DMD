// SPDX-License-Identifier: MIT

#include "nic_dmd.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>

int total_errors = 0;

void check(const char* name, bool ok) {
    if (!ok) {
        printf("  CHYBA: %s\n", name);
        total_errors++;
    }
}

int main() {
    printf("\n=== NIC DMD - C testy ===\n\n");
    
    int pkt_lens[] = {8, 16, 32, 64, 128};
    int num_lens = sizeof(pkt_lens) / sizeof(pkt_lens[0]);

    printf("Test 1: round-trip (pseudonahodna data)\n");
    srand(42);

    for (int j = 0; j < num_lens; j++) {
        uint8_t pkt_len = pkt_lens[j];
        dmd_encoder_t enc;
        dmd_decoder_t dec;
        
        dmd_encoder_init(&enc, pkt_len);
        dmd_decoder_init(&dec, pkt_len);
        
        int errors = 0;
        for (int i = 0; i < 500; i++) {
            uint8_t data[DMD_ENC_BUF_SIZE];
            uint8_t comp[DMD_ENC_BUF_SIZE + 1];
            uint8_t decomp[DMD_ENC_BUF_SIZE];

            for (int k = 0; k < pkt_len; k++) {
                data[k] = rand() % 256;
            }

            uint8_t c_len = dmd_compress(&enc, data, comp);
            
            // Ošetření návratové hodnoty podle nové specifikace (0 = úspěch)
            int res = dmd_decompress(&dec, comp, c_len, decomp);
            if (res < 0) {
                errors++;
            } else if (memcmp(data, decomp, pkt_len) != 0) {
                errors++;
            }
        }
        
        printf("  pkt_len=%3d: 500 paketu: %s\n", pkt_len, (errors == 0) ? "OK" : "CHYBY");
        check("round-trip", errors == 0);
    }

    // Test 2: Otestování bezpečnostní pojistky (rezervovaná verze 7)
    printf("\nTest 2: Rezervovana verze protokolu (sample_num=7)\n");
    dmd_decoder_t dec_test;
    dmd_decoder_init(&dec_test, 16);
    
    uint8_t dummy_comp[16] = {0};
    dummy_comp[0] = 7; // Nastavení hlavičky na sample_num = 7
    uint8_t dummy_decomp[16];
    
    int res = dmd_decompress(&dec_test, dummy_comp, 16, dummy_decomp);
    if (res == -3) {
        printf("  OK (Chyba -3 spravne zachycena pro nepodporovanou verzi 7)\n");
    } else {
        printf("  CHYBA: Dekoder neopravnene prijal paket s rezervovanou verzi!\n");
        check("rezervovana verze", false);
    }

    printf("\nTest dokonceno. Celkem chyb: %d\n\n", total_errors);
    return (total_errors == 0) ? 0 : 1;
}
