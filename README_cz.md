★ N.I.C. ★

# NIC DMD — Delta Markov Duda

## Kompresní protokol pro embedded zařízení a LoRa přenos

[![Licence: GPL v3](https://img.shields.io/badge/Licence-GPLv3-red.svg)](https://www.gnu.org/licenses/gpl-3.0)

---

## Co je DMD?

DMD je multiplatformní kompresní protokol pro malé pakety dat z meteostanic, elektroměrů, GPS trackerů a dalších embedded zařízení. Je navržen pro přenos přes technologie s omezenou šířkou pásma, jako je LoRa.

Protokol je plně funkční na kontroléru ATmega328 a nevyžaduje žádné velké slovníky ani vyhledávací tabulky v paměti. Každý paket je komprimován nezávisle — adaptivním výběrem nejlepší metody z pěti kandidátů.

---

## Proč DMD?

Existující kompresní knihovny pro embedded zařízení buď vyžadují stovky bajtů RAM navíc (Heatshrink), nebo potřebují přenášet Huffmanovu tabulku spolu s daty. DMD volí jinou cestu — kombinuje několik jednoduchých metod s heuristickou analýzou a vybírá nejlepší výsledek pro každý paket zvlášť.

**Hlavní výhody:**
- Pevná Huffmanova tabulka pouze v ROM (32B), žádná RAM navíc
- Adaptivní výběr metody pro každý paket — až 5 kandidátů
- Plně deterministická dekomprese — žádné ztráty dat
- Maximální expanze dat o 1 bajt (záhlaví) v nejhorším případě
- Implementace v Pythonu i C (ATmega328 / Arduino)

---

## Kdy se DMD nevyplatí

DMD je navržen pro data která se v čase mění pomalu a předvídatelně — senzorové hodnoty, GPS souřadnice, průmyslová telemetrie. Pokud jsou vstupní data náhodná, šifrovaná nebo již komprimovaná, DMD přidá pouze 1 bajt záhlaví a odešle je jako RAW. To je správné chování — žádná ztrátová komprese, žádné zhoršení.

---

## Kompatibilita

**Python:** 3.10 nebo novější (používá typové anotace `bytes | None`).

**C:** C99 nebo novější. Testováno s GCC na PC (Linux/Windows) a AVR-GCC pro ATmega328. Bez závislostí na standardní knihovně kromě `<string.h>`. Interní buffery jsou dimenzovány pomocí C99 VLA podle skutečné délky paketu.

**Arduino:** Zkopíruj `nic_dmd.c` a `nic_dmd.h` do složky projektu. Kompatibilní s Arduino IDE 1.8+ a 2.x (AVR-GCC podporuje C99 VLA).

**Poznámka pro jiné překladače:** IAR, Keil a MSVC C++ VLA nepodporují. Pro tyto toolchainy lze při kompilaci definovat `-DDMD_PKT_MAX_BUILD=N` (např. 32 nebo 64) a buffery budou fixní.

**Závislosti pro fetch/benchmark:** `pip install requests`

**Délka paketu:** Minimální technické omezení je 1B, ale pod 16B se komprese prakticky nevyplatí — overhead záhlaví (1B) a ANS state (2B) sežere většinu případné úspory. Doporučené minimum je **16B**. Maximum je **255B**. Pro LoRa přenos je praktický limit payload 51–64B podle spreading factoru a regionu. Nejlepších výsledků dosahuje DMD na datech kde se sousední pakety mění pomalu — typicky 16–64B senzorová telemetrie.

---

## Validace a integrita dat

V zájmu dosažení maximálního výkonu a absolutní minimalizace zátěže procesoru knihovna neprovádí žádné dodatečné kontroly záhlaví ani validaci délky předaných dat.

Návrh protokolu striktně předpokládá, že kontrolu integrity (např. hardwarové CRC) a zahození poškozených či prázdných paketů řeší nižší transportní vrstva nebo hlavní program (typicky samotný rádiový modul, logika sběru dat apod.). Uživatel knihovny musí na aplikační úrovni zajistit, že do kompresních a dekompresních funkcí vstupují pouze strukturálně korektní data. Tímto delegováním odpovědnosti bylo dosaženo nízké paměťové režie bez plýtvání hodinovými cykly procesoru.

---

## Výsledky

Testováno na více než 50 000 vzorcích z 20 reálných a syntetických zdrojů dat (meteostanice, GPS, elektroměry, průmyslové senzory, seizmika, kvalita ovzduší):

```
=========================================================================================================
        GLOBÁLNÍ SOUHRN — testováno na 20 datasetech, pakety 16–128B
=========================================================================================================
  Dataset                      |  Úspora  |  Poznámka
---------------------------------------------------------------------------------------------------------
NOAA San Francisco (přílivy)   |   62.2%  | dominuje FLAG, ideální pro ANS
NOAA New York (přílivy)        |   60.6%  | dominuje FLAG
DWD Fichtelberg (meteo 16B)    |   52.6%  | 74% paketů DELTA1+ZZ+FLAG
GPS Trek (16B)                 |   49.3%  | 21% paketů DELTA1+ZZ+ANS
DWD Helgoland / Zugspitze      |  ~49%    | meteo pobřeží / hora
Komplexní stanice (64B)        |   40.7%  | 84% DELTA1+ZZ+HUF
AirQuality CZ (16B)            |  37–40%  | mix FLAG a HUF
Elektroměry (16B)              |   37.7%  | 52% DELTA1+ZZ+HUF
IoT budova (16B)               |   31.3%  | 84% DELTA1+ZZ+HUF
Průmyslový senzor (128B)       |   30.7%  | 80% DELTA1+ZZ+HUF
Forecast meteo (16–32B)        |  27–32%  | mix FLAG a HUF
USGS seizmika (16B)            |   18.2%  | nejhorší vstup — chaotická data
=========================================================================================================
  Rozsah úspory:  18% – 62%   |  Chyby round-trip: 0 ve všech datasetech
=========================================================================================================
```

---

## Spotřeba RAM

Buffery jsou dimenzovány pomocí C99 VLA podle skutečné délky paketu `N`. Hodnoty zahrnují stack při kompresi a struktury enkodéru/dekodéru.

```
================================================================================
  Délka paketu | Stack komprese | dmd_encoder_t | dmd_decoder_t | Celkem
---------------+----------------+---------------+---------------+---------------
       16B     |      62B       |      18B      |     17B       |      80B
       32B     |      96B       |      34B      |     33B       |     130B
       64B     |     164B       |      66B      |     65B       |     230B
      128B     |     300B       |     130B      |    129B       |     430B
      255B     |     569B       |     257B      |    256B       |     826B
================================================================================
```

Peak RAM při volání `dmd_compress` = Stack komprese + dmd_encoder_t.

Pro typické použití s LoRa (16–64B pakety) je peak **80–230B** — bez problémů na ATmega328 (2KB RAM).

---

## Jak to funguje

```
+-------------------------------------------------------------------------------+
|                          START: Vstupní paket dat                             |
+-------------------------------------------------------------------------------+
                                    |
                                    v
+-------------------------------------------------------------------------------+
|  Krok 1: Delta + ZigZag (keyframe přeskočí)                                   |
|  Testuj DELTA_1B / DELTA_2B / DELTA_FULL — vyber nejmenší počet jedniček      |
+-------------------------------------------------------------------------------+
                                    |
                                    v
+-------------------------------------------------------------------------------+
|  Krok 2: Zkus kompresní kandidáty (každý s early exit limitem)                |
|                                                                               |
|   (a) µANS     — jen pokud zero_ratio >= 45%                                  |
|   (b) Huffman  — nibble Huffman s pevnou tabulkou v ROM se spouští vždy       |
|   (c) FLAG     — mapa nulových bajtů se spouští vždy                          |
|   (d) FLAG+HUF — FLAG odstraní nuly a Huffman případně zkomprimuje zbytek     |
+-------------------------------------------------------------------------------+
                                    |
                                    v
+-------------------------------------------------------------------------------+
|  Krok 3: Vyber nejmenší výsledek                                              |
|  Pokud nic nepomůže → RAW záchrana (delta_type = NONE, original data)         |
+-------------------------------------------------------------------------------+
                                    |
                                    v
+-------------------------------------------------------------------------------+
|  Krok 4: Sestav záhlaví (1B) + payload → odešli                               |
+-------------------------------------------------------------------------------+
```

### Záhlaví (1 bajt)

Každý komprimovaný paket začíná jedním bajtem záhlaví:

```
MSB                    LSB
 7    6    5    4    3    2    1    0
[huf][ans][flg][dlt][dlt][vzo][vzo][vzo]
```

```
=======================================================================
| Bity |        Význam                                                |
|------|--------------------------------------------------------------|
|   7  | nibble Huffman komprese    1 = ON                            |
|   6  | µANS komprese              1 = ON                            |
|   5  | Flagování nulových bajtů   1 = ON                            |
|  4-3 | Typ delty: 00=žádná, 01=1B, 10=2B, 11=FULL (big-int+carry)   |
|  2-0 | Číslo vzorku (0–7)         0 = keyframe / start frame        |
=======================================================================

Kombinace bit 7 + bit 5 = FLAG+HUF (mapa nul + Huffman na nenulových)
```

Pokud žádná metoda nedokáže zkomprimovat data lépe než RAW, pošlou se původní data s bity 3-7 záhlaví nastavenými na 0. Přijímač pozná RAW protože záhlaví nepoužívá žádná nastavení.

### Vrstvy komprese

**1. Delta — rozdílová metoda**

Porovnání dvou po sobě jdoucích paketů. Tam kde se data mění pomalu (teplota, tlak, GPS souřadnice) vznikají po odečtení řetězce nulových nebo velmi malých hodnot. Protokol testuje tři typy delty a vybere ten s nejlepším výsledkem podle heuristiky (počet jedničkových bitů).

Podporované typy:
- **1B delta** — bajt po bajtu (uint8_t aritmetika)
- **2B delta** — po 16-bit slovech big-endian (uint16_t aritmetika)
- **FULL delta** — celý paket jako jedno velké číslo s carry propagací napříč všemi bajty. Vyhrává na čítačích a GPS souřadnicích kde hodnota přetéká přes bajtové hranice.

**2. ZigZag kódování**

Po aplikaci delty se data převedou ZigZag kódováním. Záporné rozdíly se zobrazí jako malá lichá čísla, kladné jako malá sudá čísla. Výsledkem jsou data s vysokým počtem nulových bitů, která lépe reagují na následující kompresní metody.

ZigZag se nepoužije pokud delta = žádná (včetně keyframe). Delta a ZigZag probíhají v jednom průchodu daty.

**3. Flagování nulových bajtů (FLAG)**

Každý nulový bajt se nahradí jedním bitem v bitové mapě. Před mapou je uložena délka paketu (1B). Nenulové bajty následují v původním pořadí.

Příklad pro 16B paket s 12 nulami:
```
Původní:  [0, 0, 5, 0, 0, 0, 3, 0, 0, 0, 0, 0, 7, 0, 0, 2]  (16B)
Payload:  [16][11011101 11110110][5, 3, 7, 2]
           1B délka + 2B mapa + 4B nenulové = 7B
Výsledek: 8B místo 16B (1B záhlaví + 7B payload)
```

**4. µANS komprese**

Asymetrické číselné systémy (ANS) pracují na úrovni bitů se dvěma váhami: nulový bit je vysoce pravděpodobný (29/32), jedničkový méně (3/32). Pro data s převahou nul po deltě+ZigZag dosahuje výrazné komprese bez tabulky.

ANS payload obsahuje délku dat (1B), stav (2B — uint16_t) a zakódované bajty. Spouští se pouze pokud podíl nulových bajtů >= 45% (heuristika). Enkodér i dekodér mají early exit — pokud výsledek přeroste limit, výpočet se okamžitě zastaví.

**5. Nibble Huffman (HUF)**

Pevná Huffmanova tabulka natrénovaná na kombinovaných meteo a GPS datech po deltě+ZigZag. Kóduje každý bajt jako dva nibble kódy (hi a lo). Tabulka je uložena v ROM (32B PROGMEM na ATmega), žádná RAM navíc.

Maximální délka kódu je 6 bitů, průměr ~3.2 bitu na bajt. Vyhrává zejména na IoT, průmyslových a komplexních datech kde jsou nuly vzácné ale distribuce nibblů sedí na tabulku.

**6. FLAG+HUF kombinace**

FLAG nejprve odstraní nulové bajty do bitové mapy, Huffman pak zkomprimuje zbývající nenulové bajty. Payload: `[1B délka][mapa][1B valid bits HUF][HUF stream]`. Nejlepší z obou světů — deterministická eliminace nul + entropická komprese zbytku.

**Keyframe a start frame**

Vzorek s číslem 0 je keyframe. Protože neexistuje předchozí paket pro výpočet delty, přeskočí se rozdílová metoda a ZigZag. Data jsou zpracována přímo metodami FLAG, HUF, FLAG+HUF nebo ANS. Keyframe nastane automaticky každých 8 paketů nebo po resetu zařízení.

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
    uint8_t data[16]          = { /* senzorová data */ };
    uint8_t compressed[DMD_OUT_MAX];
    uint8_t decompressed[16];

    uint8_t comp_len = dmd_compress(&enc, data, compressed);
    lora.send(compressed, comp_len);

    // Na přijímači:
    dmd_decompress(&dec, compressed, comp_len, decompressed);
}
```

### Překlad pro jiné překladače (bez VLA)

Pokud tvůj překladač nepodporuje C99 VLA (IAR, Keil, MSVC C++), definuj maximální délku paketu při kompilaci:

```
gcc -DDMD_PKT_MAX_BUILD=32 nic_dmd.c ...
```

Buffery se zkompilují na pevnou velikost 32B. Pro projekty s jednou pevnou délkou paketu (typický Arduino use case) je tato varianta ideální.

---

## Soubory

| Soubor               | Popis                                              |
| -------------------- | -------------------------------------------------- |
| `nic_dmd.py`         | Python implementace — referenční, pro testování    |
| `nic_dmd_utils.py`   | Pomocné funkce — analýza a výpis výsledků          |
| `nic_dmd.c`          | C implementace pro ATmega328                       |
| `nic_dmd.h`          | Hlavičkový soubor                                  |
| `Makefile`           | Kompilace a testování                              |

### Testování a benchmark

| Soubor               | Popis                                              |
| -------------------- | -------------------------------------------------- |
| `nic_dmd_test.py`    | Python testy — round-trip, meteo, keyframe         |
| `nic_dmd_test.c`     | C testy — round-trip, all-zeros, meteo             |
| `fetch_plus.py`      | Stažení reálných dat a benchmark (20 zdrojů)       |
| `benchmark.py`       | Srovnání DMD vs Huffman vs Heatshrink              |

---

## Licence

GPL v3 — NIC Native Intellect Community

---

## Poděkování

Bratrovi za rady při tvorbě tohoto projektu.
Za technickou asistenci s optimalizací kódu AI asistentům Claude (Anthropic) a Gemini (Google).

★ Viva La Resistánce ★