#include "nic_dmd.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

void check(const char* name, bool ok) {
    if (!ok) {
        printf("  CHYBA: %s\n", name);
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
            dmd_decompress(&dec, comp, c_len, decomp);

            if (memcmp(data, decomp, pkt_len) != 0) {
                errors++;
            }
        }
        
        printf("  pkt_len=%3d: 500 paketu: %s\n", pkt_len, (errors == 0) ? "OK" : "CHYBY");
        check("round-trip", errors == 0);
    }

    printf("\nTest dokonceno.\n\n");
    return 0;
}