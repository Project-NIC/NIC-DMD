★ N.I.C. ★

# NIC DMD — Delta Markov Duda

## Kompresní protokol pro embedded zařízení a LoRa přenos

[![Licence: GPL v3](https://img.shields.io/badge/Licence-GPLv3-red.svg)](https://www.gnu.org/licenses/gpl-3.0)

---

## Co je DMD?

DMD je multiplatformní kompresní protokol pro malé balíky dat z meteostanic, elektroměrů, GPS trackerů a dalších embedded zařízení. Je navržen pro přenos přes technologie s omezenou šířkou pásma, jako je LoRa.

Protokol je plně funkční na kontroléru ATmega328 a nevyžaduje žádné velké slovníky ani tabulky v paměti.

Z tohoto důvodu je po mnoha testech optimalizován i na úkor nižší kompresní schopnosti, kdy snížením průměrné komprese o cca 3% (data z meteostanic) došlo ke snížení zátěže procesoru o cca 70%.

---

## Proč DMD?

Existující kompresní knihovny pro embedded zařízení buď vyžadují stovky bajtů RAM navíc (Heatshrink), nebo potřebují přenášet Huffmanovu tabulku spolu s daty. DMD volí jinou cestu — kombinuje několik jednoduchých metod s heuristickou analýzou a vybírá nejlepší výsledek pro každý paket zvlášť.

**Hlavní výhody:**
- Žádná tabulka v ROM ani RAM
- Adaptivní výběr metody pro každý paket
- Plně deterministická dekomprese — žádné ztráty dat
- Maximální expanze dat o 1 bajt (záhlaví) v nejhorším případě
- Implementace v Pythonu i C (ATmega328)

---

## Kdy se DMD nevyplatí

DMD je navržen pro data která se v čase mění pomalu a předvídatelně — senzorové hodnoty, GPS souřadnice, průmyslová telemetrie. Pokud jsou vstupní data náhodná, šifrovaná nebo již komprimovaná, DMD přidá pouze 1 bajt záhlaví a odešle je jako RAW. To je správné chování — žádná ztrátová komprese, žádné zhoršení.

---

## Kompatibilita

**Python:** 3.10 nebo novější (používá `bytes | None` typové anotace).

**C:** C99 nebo novější. Testováno s GCC na PC (Linux/Windows) a AVR-GCC pro ATmega328. Bez závislostí na standardní knihovně kromě `<string.h>`.

**Arduino:** Zkopíruj `nic_dmd.c` a `nic_dmd.h` do složky projektu. Kompatibilní s Arduino IDE 1.8+ a 2.x.

**Závislosti pro benchmark:** `pip install requests heatshrink2`

**Délka paketu:** Minimální technické omezení je 1B, ale pod 16B se komprese prakticky nevyplatí — overhead záhlaví (1B) a ANS state (2B) sežere většinu případné úspory. Doporučené minimum je **16B**. Maximum je **255B**. Nejlepších výsledků dosahuje DMD na datech kde se sousední pakety mění pomalu — typicky 16–64B senzorová telemetrie.

---

## Validace a integrita dat

V zájmu dosažení maximálního výkonu a absolutní minimalizace zátěže procesoru knihovna neprovádí žádné dodatečné kontroly hlaviček ani validaci délky předaných dat.

Návrh protokolu striktně předpokládá, že kontrolu integrity (např. hardwarové CRC) a zahození poškozených či prázdných paketů řeší nižší transportní vrstva  nebo hlavní program (typicky samotný rádiový modul, logika sběru dat ... ). Uživatel knihovny musí na aplikační úrovni zajistit, že do kompresních a dekompresních funkcí vstupují pouze strukturálně korektní data. Tímto delegováním odpovědnosti bylo dosaženo  nízké paměťové režie bez plýtvání hodinovými cykly procesoru.

---

## Výsledky

Testováno na 12000 vzorcích z 5 zdrojů reálných dat (Sněžka, Antarktida, Death Valley, Ojmjakon, Sahara):

```
=========================================================================================================
        GLOBÁLNÍ SOUHRN — průměrná úspora přes všechny zdroje (32B)
=========================================================================================================
  Metoda                   |  Průměr |     Min |     Max |  RAM  	|        Poznámka
---------------------------------------------------------------------------------------------------------
RAW (bez komprese)         |    0.0% |    0.0% |    0.0% |   0   	|
* DMD protokol *           | * 46.2% | * 38.5% | * 56.4% | ~161B  	| bez tabulky, adaptivní
Heatshrink (w=8,l=4)       |   13.4% |   10.3% |   18.0% | ~256B 	| sliding window
Heatshrink (w=10,l=5)      |    8.5% |    5.8% |   13.0% | ~400B 	| sliding window
Delta+Huffman (statická)   |   45.3% |   36.0% |   59.1% | odhadem 1KB  | pevná tabulka ~700B ROM
Delta+Huffman (dynamická)  |   48.3% |   39.1% |   62.7% | odhadem 1KB  | tabulka poslána jednou na start
=========================================================================================================
```

---

## Spotřeba RAM

Hodnoty zahrnují stack při kompresi a struktury enkodéru/dekodéru.

```
===============================================================
  Délka paketu | Stack komprese | dmd_encoder_t | dmd_decoder_t
---------------+----------------+---------------+--------------
       16B     |      78B       |      19B      |     18B
       32B     |     126B       |      35B      |     34B
       64B     |     222B       |      67B      |     66B
      128B     |     414B       |     131B      |    130B
      255B     |     795B       |     258B      |    257B
===============================================================
```

Peak RAM při volání `dmd_compress` = Stack komprese + dmd_encoder_t.

Pro typické použití (16–32B pakety) je peak **97–161B** — bez problémů na ATmega328 (2KB RAM).

---

## Jak to funguje

```
+---------------------------------------------------------------------------+
|                       START: Vstupní paket dat                            |
+---------------------------------------------------------------------------+
                             |                                     |
                             v                                     |
+--------------------------------------------------------+         |
|  Předzpracování: Delta, ZigZag a uložení stavu (LIFO)  |         |
+--------------------------------------------------------+         |
            |                              |                       |
            v                              v                       |
+-----------------------+      +------------------------+          |
|   Metoda: µANS        |      |  Metoda: Flagování nul |          |
| [ Pokus o kompresi ]  |      | [ Odhad mapy nul ]     |          |
+-----------------------+      +------------------------+          |
            |                              |                       |
            v                              v                       |
+-------------------------------------------------------------+    |
| Rozhodnutí: Je výsledek (µANS nebo Flagování) menší než RAW?|    |
+-------------------------------------------------------------+    |
            |                                          |           |
            v                                          v           v
+-----------------------+                 +---------------------------+
|  ANO: Komprimováno    |                 |  NE: Odeslání jako RAW    |
| [ Sestavit hlavičku ] |                 | [ RAW hlavička ]          |
+-----------------------+                 +---------------------------+
```

### Záhlaví (1 bajt)

Každý komprimovaný paket začíná jedním bajtem záhlaví:

```
MSB                    LSB
 7    6    5    4    3    2    1    0
[rez][ans][flg][dlt][dlt][vzo][vzo][vzo]
```

```
=======================================================================
| Bity |        Význam                                                |
|------|--------------------------------------------------------------|
|   7  | Rezerva (pro budoucí rozšíření — DMD+)                      |
|   6  | µANS komprese              1 = ON                            |
|   5  | Flagování nulových bajtů   1 = ON                            |
|  4-3 | Typ delty   00 = žádná, 01 = 1B, 10 = 2B, 11 = celý vzorek  |
|  2-0 | Číslo vzorku (0–7)         0 = keyframe / start frame        |
=======================================================================
```

Pokud ani flagování ani ANS nestačí zkomprimovat data lépe než RAW, pošlou se původní data s nastavením příznaků na 0 na bitech 3-7 v hlavičce. Přijímač pozná RAW podle toho, že záhlaví nepoužívá žádná nastavení (uANS = 0, Flagování = 0, Delta = 00).

### Vrstvy komprese

**1. Delta — rozdílová metoda**

Porovnání dvou po sobě jdoucích paketů. Tam kde se data mění pomalu (teplota, tlak, GPS souřadnice) vznikají po odečtení řetězce nulových nebo velmi malých hodnot. Protokol testuje čtyři typy delty a vybere ten s nejlepším výsledkem podle heuristiky (počet jedničkových bitů).

Podporované typy:
- **1B delta** — bajt po bajtu
- **2B delta** — po dvoubajtových skupinách (vhodné pro 16bitové senzory)
- **Celý vzorek** — každý bajt minus stejný bajt z předchozího paketu
- **Žádná delta** — data jdou dál bez rozdílového kódování

**2. ZigZag kódování**

Po aplikaci delty se data převedou ZigZag kódováním. Záporné rozdíly se zobrazí jako malá lichá čísla, kladné jako malá sudá čísla. Výsledkem jsou data s vysokým počtem nulových bitů, která lépe reagují na následující kompresní metody.

ZigZag se nepoužije pokud delta = žádná (včetně keyframe).

**3. Flagování nulových bajtů**

Každý nulový bajt se nahradí jedním bitem v mapě. Před mapou je uložena délka paketu (1B), díky čemuž dekodér zná délku dat bez předchozí dohody. Za mapou následují nenulové bajty v původním pořadí.

Příklad pro 16B paket s 12 nulami:
```
Původní:  [0, 0, 5, 0, 0, 0, 3, 0, 0, 0, 0, 0, 7, 0, 0, 2]  (16B)
Payload:  [16][11011101 11110110][5, 3, 7, 2]
           1B délka + 2B mapa + 4B nenulové = 7B
Výsledek: 8B místo 16B (1B záhlaví + 7B payload)
```

**4. µANS komprese**

Asymetrické číselné systémy (ANS) pracují na úrovni bitů se dvěma váhami: nulový bit je velmi pravděpodobný (29/32), jedničkový méně (3/32). Pro data s převahou nul po deltě+ZigZag dosahuje výrazné komprese bez tabulky.

ANS payload obsahuje délku dat (1B), stav (2B) a zakódované bajty. Dekodér nepotřebuje znát délku předem.

ANS se skutečně zkomprimuje a změří. Flagování se odhadne deterministicky. Vybere se kratší z obou výsledků. Pokud by komprese data zvětšila, pošlou se původní data — maximálně 1 bajt overhead.

**Keyframe a start frame**

Vzorek s číslem 0 je keyframe. Protože neexistuje předchozí paket pro výpočet delty, přeskočí se rozdílová metoda a ZigZag. Data jsou zpracována přímo flagováním nebo µANS. Keyframe nastane automaticky každých 8 paketů nebo po resetu zařízení.

---

## Použití

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

print(f"Zkomprimováno: {PKT_LEN}B → {len(compressed)}B")
assert decompressed == data
```

### C (ATmega328 / Arduino)

```c
#include "nic_dmd.h"

dmd_encoder_t enc;
dmd_decoder_t dec;

void setup() {
    dmd_encoder_init(&enc, 16);   // délka paketu — musí sedět na obou stranách
    dmd_decoder_init(&dec, 16);
}

void loop() {
    uint8_t data[16]             = { /* senzorová data */ };
    uint8_t compressed[DMD_OUT_MAX];
    uint8_t decompressed[16];

    uint8_t comp_len = dmd_compress(&enc, data, compressed);
    lora.send(compressed, comp_len);

    // Na přijímači:
    dmd_decompress(&dec, compressed, comp_len, decompressed);
}
```

---

## Soubory

| Soubor | Popis |
|--------|-------|
| `nic_dmd.py` | Python implementace — referenční, pro testování |
| `nic_dmd_utils.py` | Pomocné funkce — analýza a výpis výsledků |
| `nic_dmd.c` | C implementace pro ATmega328 |
| `nic_dmd.h` | Hlavičkový soubor |
| `Makefile` | Kompilace a testování |

### Testování

| Soubor | Popis |
|--------|-------|
| `nic_dmd_test.py` | Python testy — round-trip, meteo, keyframe |
| `nic_dmd_test.c` | C testy — round-trip, all-zeros, meteo |
| `benchmark.py` | Srovnání DMD vs Huffman vs Heatshrink |
| `fetch_data_v2.py` | Stažení reálných meteo dat (Open-Meteo) |
| `fetch_real_data_v2.py` | DWD, GPS, kombinovaná data |

---

## Licence

GPL v3 — NIC Native Intellect Community

---

## Poděkování

Bratrovi za rady při tvorbě tohoto projektu.
Za technickou asistenci s optimalizací kódu AI asistentům Claude (Anthropic) a Gemini (Google).

★ Viva La Resistánce ★
