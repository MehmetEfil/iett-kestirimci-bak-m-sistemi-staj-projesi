# Analiz 1: Cascade (Zincirleme) Arıza Analizi — Bulgular ve Kanıtlar
**Notebook:** ANALIZ_1_CASCADE_ARIZALAR.ipynb
**Tarih:** 2026-05-11
**Durum:** FİNAL — 22 bölüm tamamlandı, Common Cause testleri ile validasyon yapıldı, ML kandidat seti belirlendi

---

## 🎯 KARAR ÖZETİ

| Soru | Bulgu | Kanıt |
|---|---|---|
| Cascade gerçek mi yoksa rastgele mi? | **GERÇEK** — random'dan ~1.4x yüksek | Z≈32, p<1e-200 (Monte Carlo null) |
| Cascade sequential mi yoksa common cause mi? | **TRUE SEQUENTIAL** — common cause %2.7-6.1 | Cell 41, Cell 43 (yeni) |
| Cascade ciddiyeti artırıyor mu? | **Sisteme göre değişir** | 10 sistem ANLAMLI, 11 sistem değil (Cell 31) |
| Tekrar pattern hangi seviyede güçlü? | **Alt kategori (ARIZAKODU)** seviyesinde | Lift 100+ (Cell 29) |
| Yaş cascade'i artırır mı? | **HAYIR** — yaş × cascade r=+0.03 | Cell 15 |
| Fırtına yapan araçlar daha mı ciddi? | **HAYIR — paradoks** | Cell 11, p=0.98 |
| En güçlü ML feature? | `sistem_cas_lift` (rs=-0.184) + `cascade_risk_skor` | Cell 39 |

---

## 1. Veri ve Cascade Tanımı

**Veri kaynağı:** ariza_model.csv (ana referans), 58,559 arıza × 3,509 araç, 180 gün penceresi.
Bölüm 22'de ENLEM/BOYLAM için ariza_temiz.csv kullanıldı (sadece koordinat için).

### Ardışık Arıza Süre Dağılımı
```
Median: 5.14 gün
P25:    1.85 gün
P75:    11.97 gün

Eşik altı kümülatif:
< 24s (1g):  15.85% (8,727 kayıt)  ← Cascade tanımı
< 7g:        59.25%
< 30g:       93.87%
```

**CASCADE TANIMI:** Aynı araçta önceki arızadan **24 saat içinde** yeni arıza.
- Cascade arıza: 8,727 (%14.9)
- Stand-alone: 49,832

---

## 2. Cascade Random Mi? — Null Model Testi

**Random null:** Eğer arızalar rastgele dağılsa beklenen cascade oranı.

```
Gözlemlenen (tüm satır):        14.90%
Beklenen (Monte Carlo, doğru):  10.79%   (±0.11, 200 tekrar)
Oran:                           x1.38
Z = 32.1, p < 1e-200
```

**VERİYE GÖRE:** Cascade oranı random beklentinin **~1.4x üstünde** (p son derece küçük).
→ Arızalar rastgele değil, **gerçek bir tekrar pattern var.**

> ⚠️ **Metodolojik düzeltme (2026-06):** İlk sürümde "beklenen" oran analitik Poisson formülüyle (`1-exp(-λ)=%8.85`) hesaplanıp oran **1.68x**, Z=**49.95** raporlanmıştı. Ancak `1-exp(-λ)` bir **per-gap** niceliği (önceki arızası olan satır bazı) iken gözlem **tüm-satır** bazında — iki farklı payda karşılaştırıldığı için oran şişmişti. Aynı paydada Monte Carlo permütasyon null'u (her aracın tarihlerini 180 güne uniform dağıt) **%10.79** verir → gerçek oran **1.38x**, Z≈**32**. Nitel sonuç (cascade gerçek, rastgele değil) değişmez. Yeniden üretim: `cascade_permutasyon_null.py`.

---

## 3. Common Cause vs True Cascade — Validasyon (KRİTİK)

Cascade pattern iki sebepten gelebilir:
- **True Cascade:** A bozulması B'yi mekanik olarak tetikledi
- **Common Cause:** Dış faktör (yol, hava, sürüş) hem A hem B'yi aynı anda bozdu

İki bağımsız test yapıldı:

### 3.1 Hat Bazlı Common Cause (Cell 41)
Test: Aynı saat + aynı HATKODU + farklı araç + aynı sistem → common cause sinyali
```
Toplam grup:                     56,930
Common cluster (>=2 farklı araç): 1,407
Cascade overlap:                  534 / 8,727 = %6.1
```

### 3.2 Coğrafi-Zamansal Cluster (Cell 43)
Test: 1 saat + ~1 km grid + aynı sistem → fiziksel dış faktör
```
Cografi koordinatlı arıza:        58,990 (ariza_temiz'den)
Toplam grup:                      58,282
Common cluster (>=2 farklı araç): 647
Cascade overlap:                  241 / 8,727 = %2.7
```

### 3.3 Final Yargı
```
Hat bazlı:           %6.1  (< %10 eşik) ✓
Coğrafi-zamansal:    %2.7  (< %10 eşik) ✓
```

**VERİYE GÖRE:** Cascade'lerimiz **BÜYÜK ÖLÇÜDE TRUE SEQUENTIAL.** Common cause overlap her iki testte de %10 altında.

### Mevsimsel/Operasyonel Common Cluster Yan Bulgusu
Common cluster yapan top sistemler:
- KLİMA: 271 cluster (yaz aylarında aynı hat, birden fazla araç)
- KAPI: 324 cluster
- SOĞUTMA: 209 cluster
- ELEKTRİK: 155 cluster

Bunlar **mevsimsel/operasyonel** pattern. Toplam %6 olduğu için cascade analizini bozmuyor ama yan bilgi olarak değerli.

---

## 4. Tetikleyici Matrisi — Kategori × Kategori

### En Güçlü Self-Cascade (üst kategori)
```
İLAVE DİREKSİYON → İLAVE DİREKSİYON: lift 76.55
ROT AYARLARI → ROT AYARLARI:         lift 33.63
KWS → KWS:                            lift 33.37
BASINÇLI YAĞ → BASINÇLI YAĞ:         lift 32.72
DİREKSİYON → DİREKSİYON:             lift 23.78
KAMERA → KAMERA:                     lift 12.74 (n=71)
ISITMA → ISITMA:                     lift 9.23  (n=195)
```

### Chi-square Test (Top 10 kategori × Top 10)
```
Chi² = 5,247, df = 81, p = 0.000000
```
→ Geçiş matrisi **ANLAMLI sekilde non-random.** Sistem tetikleme pattern'ı veriden net.

---

## 5. Alt Kategori (ARIZAKODU) Lift — Spesifik Parça Pattern

Üst kategori lift'ten daha güçlü:

```
ARIZAKODU                              Üst Kategori           Self-Lift
VİTESTEN ATIYOR                        OTOMATİK ŞANZIMAN      136.0
KORNA ÇALMIYOR                         ELEKTRİK SİSTEMİ       110.9
İÇ AYDINLATMA YANMIYOR                 ELEKTRİK SİSTEMİ        96.1
KAMERA AÇILARI UYGUN DEĞİL             KAMERA                  96.0
ŞOFÖR KABİN KAPISI ARIZALI             KAROSER                 87.1
KAPI DURACAK DÜĞMESİ                   KAPI                    72.7
BEYİN ARIZALARI                        ELEKTRİK SİSTEMİ        71.2
AKBİL OKUMUYOR                         AKBİL                   57.8
ŞANZIMAN YAĞ SICAKLIĞI YÜKSEK          OTOMATİK ŞANZIMAN       51.3
SİLECEK ARIZALARI                      ELEKTRİK SİSTEMİ        44.1
ÖN TAKIM KONTROL                       ROT AYARLARI            38.2
DİREKSİYON ÇOK AĞIR                    DİREKSİYON              34.2
```

**Yorum:** Spesifik arıza kodları 24 saat içinde 100x'e kadar tekrar ediyor.

**ÖNEMLİ NOT:** Bakım türü (değişim vs tamir) verimizde YOK. Sebep yorumlanamaz — yalnızca pattern raporlanır.

---

## 6. Inter-arrival Time Dağılımı (Survival)

```
P(Sonraki arıza > 0 gün) = 1.000
P(Sonraki arıza > 1 gün) = 0.841
P(Sonraki arıza > 7 gün) = 0.408
P(Sonraki arıza > 30 gün) = 0.061

Exponential uyumu (K-S test):
ks_stat = 0.086, p = 0.000000
```

**VERİYE GÖRE:** Inter-arrival dağılımı exponential ile **UYUMSUZ** (p<0.05).
→ Arızalar memoryless değil, geçmiş pattern içeriyor (cascade var).

---

## 7. Sistem Cascade Subgroup — Hangi Sistem Cascade'i Gerçekten Ciddi?

Bu en kritik ayrımdır. **Cascade pattern her sistemde aynı değil.**

### Cascade'ı Anlamlı Şekilde CİDDİ Artıran Sistemler (p<0.05):
| Sistem | Cascade ort | Stand ort | Fark | p |
|---|---|---|---|---|
| **ELEKTRİK SİSTEMİ** | 3.379 | 2.964 | **+0.414** | 0.0000 |
| YAKIT ve ENJEKSİYON | 3.677 | 3.382 | +0.295 | 0.0207 |
| ISITMA SİSTEMİ | 3.364 | 3.115 | +0.250 | 0.0022 |
| MOTOR ARIZALARI | 4.549 | 4.304 | +0.245 | 0.0001 |
| OTOMATİK ŞANZIMAN | 4.659 | 4.427 | +0.232 | 0.0037 |
| BASINÇLI MOTOR YAĞI | 2.863 | 2.631 | +0.232 | 0.0209 |
| KLİMA SİSTEMİ | 3.055 | 2.841 | +0.215 | 0.0001 |
| KAPI ARIZALARI | 3.180 | 3.002 | +0.178 | 0.0001 |
| SOĞUTMA SİSTEMİ | 3.456 | 3.317 | +0.138 | 0.0243 |
| AKBİL | 1.124 | 1.114 | +0.010 | 0.0096 |

### Cascade'ı CİDDİ ETKİSİ OLMAYAN Sistemler (anlamsız):
- KAROSER, FREN, SÜSPANSİYON, KAMERA, LASTİK, KAYIŞ KASNAK, DİREKSİYON, BASINÇLI HAVA, DESTEK

**Yorum:** ELEKTRİK + YAKIT + ISITMA + MOTOR + ŞANZIMAN cascade'i ciddiyet artırıcı. FREN/LASTİK cascade tekrarı ciddiyet farkı yaratmıyor.

---

## 8. Arıza Fırtınası — Yoğun Cluster Patterns

```
24s içinde 3+ arıza yapan araç:  613 / 3,509 (%17.5)
7g içinde 5+ arıza:               670 / 3,509 (%19.1)
30g içinde 10+ arıza:             561 / 3,509 (%16.0)
```

### Fırtına Paradoksu
```
Fırtınalı araç (n=613):  ort_skor=3.597
Diğer (n=2,703):         ort_skor=3.590
Mann-Whitney p = 0.9828 — fark YOK
```

**Açıklama (Cell 33):** Fırtına yaratan sistemler dağılımı genel filo ile aynı (lift 1.07-1.21). Fırtına yaşayan araçlar farklı bir sistem ailesi değil — sadece çok arıza yapanlar.

---

## 9. Yaş × Cascade İlişkisi

```
Yeni (0-5):    n=331, ort_cascade=0.131
Genç (6-10):   n=519, ort_cascade=0.111
Orta (11-15):  n=1803, ort_cascade=0.126
Yaşlı (16+):   n=663, ort_cascade=0.130

Pearson r=+0.030, p=0.084 — ANLAMSIZ
```

**VERİYE GÖRE:** Yaş ile cascade oranı **anlamlı ilişkili değil.** Cascade pattern yaşa bağlı değil, sistemin kendi tekrar etme eğilimi.

---

## 10. Confounder + Suppressor Effect

### Multiple Regression Sonuçları
```
A (kontrolsüz):       cascade_orani k=-0.038, p=0.76 (anlamsız)
B (+yaş):             k=-0.067, p=0.59
C (+yaş+sefer):       k=-0.186, p=0.13
D (+yaş+sefer+garaj): k=-0.364, p=0.003 (NEGATİF ANLAMLI)
```

**Bu suppressor effect:**
- Cascade oranı garaj ve sefer ile pozitif korelasyon içinde
- Garaj kontrol edilince ham etki ortaya çıkıyor (negatif yön)
- **Cascade_orani ham olarak ML feature olarak güvensiz**

→ Bunun yerine **ordinal bantsal feature'lar** kullanılmalı.

---

## 11. ML Feature Türetme — 12 Kandidat + Final Sıralama

### Türetilen Feature'lar (Cell 19)
```
gecmis_ariza_n      — toplam geçmiş arıza
gecmis_ciddi_n      — toplam geçmiş ciddi arıza
ariza_son_7g        — son 7 gün arıza
ariza_son_30g       — son 30 gün arıza
ariza_son_60g       — son 60 gün arıza
ciddi_son_30g       — son 30 gün ciddi arıza
ciddi_son_7g        — son 7 gün ciddi arıza
son_ariza_gun       — son arızadan beri gün
farkli_kat_30g      — son 30 gün farklı kategori sayısı
cascade_24s         — binary cascade flag
cascade_7g_3plus    — son 7g 3+ arıza binary
tetik_kat_lift      — önceki kategorinin max lift
```

### Ordinal Feature'lar (Cell 35)
```
ord_gecmis_ciddi  ord_son7g  ord_son_ariza  ord_farkli_kat
cascade_risk_skor = sum(4 ordinal)
```

### Sistem Bazlı Feature (Cell 39)
```
sistem_cas_lift   — her kategorinin cascade ciddiyet artış oranı
lift_x_cascade    — sistem_lift × cascade_24s interaksiyon
```

### Final Korelasyon Sıralaması

| Sıra | Feature | Spearman rs | CiddiAriza r |
|---|---|---|---|
| 1 | **sistem_cas_lift** | **-0.184** | -0.129 |
| 2 | ciddi_son_30g | +0.082 | +0.081 |
| 3 | cascade_risk_skor | +0.078 | +0.080 |
| 4 | gecmis_ciddi_n | +0.074 | +0.069 |
| 5 | ciddi_son_7g | +0.074 | +0.075 |
| 6 | ord_gecmis_ciddi | +0.072 | +0.072 |
| 7 | ord_son_ariza | +0.056 | +0.058 |
| 8 | ord_son7g | +0.053 | +0.055 |
| 9 | ord_farkli_kat | +0.047 | +0.047 |
| 10 | lift_x_cascade | +0.037 | +0.046 |

### `sistem_cas_lift` Bantları (En Güçlü Non-Linear Pattern)
```
Bant            n       ort_skor  ciddi %
Yok (≤1.0)      1,664   3.78      33.5
Hafif (1.0-1.05) 23,547 3.91      43.0  ← EN YÜKSEK
Orta (1.05-1.10) 26,890 3.45      36.6
Yuksek (1.10+)   6,458  3.14      26.8  ← EN DÜŞÜK

ANOVA F=409.64, p=0.000000
```

**Yorum:** Lift yüksek sistemler (İLAVE DİREKSİYON, YANGIN İKAZ, KAMERA, KLİMA) **zaten az ciddi sistemler.** Prevalans confounding nedeniyle ham korelasyon negatif. Tree model (XGBoost) bu non-linear pattern'ı yakalar.

---

## 12. Vaka Analizi — En Çok Cascade Yapan 10 Araç

```
KAPINO   yaş  toplam_n  cascade_n  cascade_%  ort_skor
K3729    12   21        10         47.6%      3.44
M6100    13   20        9          45.0%      2.42
K5729    12   23        10         43.5%      3.14
M2185    19   19        8          42.1%      3.93
O3643    3    43        18         41.9%      4.13  ← yeni araç!
K4256    12   12        5          41.7%      4.28
M3261    17   24        10         41.7%      3.95
T3715    11   12        5          41.7%      3.51
T4689    11   24        10         41.7%      3.89
O6772    3    22        9          40.9%      3.66  ← yeni araç!
```

**Pattern:** Yaş çok değişken (3-19). Yeni araçlar da yüksek cascade gösterebiliyor. Bu da yaş × cascade ilişkisinin zayıf olduğunu doğruluyor.

---

## 13. Operasyonel Uyarı Eşiği

```
Kural                       flag_n   ciddi_oran_flag  Lift
Son 7g 2+ ciddi             3,456    47.1%            1.26  ← En güçlü
Son 30g 3+ ciddi            10,212   44.5%            1.21
Cascade 24s                 8,727    43.5%            1.17
Son 7g 3+ arıza             5,420    43.5%            1.16
Tetik_lift > 2              54,657   38.3%            1.13
Son 30g 3+ farklı kat       27,376   40.1%            1.11
```

**Karar:** Hiçbir kural Lift > 1.5 değil. Bu basit kurallar yetersiz, ama composite (cascade_risk_skor) bant analizinde güçlü pattern var.

---

## 14. ML Modele Önerilen FİNAL Feature Seti (V6 için)

```python
# V6 modeline eklenmesi önerilen 5 feature:
1. ciddi_son_30g       # son 30g ciddi arıza sayısı (rs=+0.082)
2. cascade_risk_skor   # composite ordinal (rs=+0.078, ANOVA F=61.66)
3. sistem_cas_lift     # sistem prevalans + lift birlikte (rs=-0.184)
4. ord_son_ariza       # recency signal (rs=+0.056)
5. ciddi_son_7g        # son 7g ciddi arıza (rs=+0.074)
```

**Beklenen V6 etkisi:** AUC iyileşme +0.01 ile +0.025 arası (mevcut V5=0.762). Tree-based modelde non-linear pattern (ANOVA F=409 sistem_cas_lift) güçlü katkı yapabilir.

---

## 15. Sınırlamalar ve Yapılmayan Testler

### Yapılamayan / Sınırlı:
- **Bakım türü (değişim vs tamir) verisi YOK** — Sebep yorumu yapılamadı. "Aynı parça neden tekrar bozuldu?" sorusu açık kaldı.
- **6 aylık veri penceresi** — Uzun vadeli (yıllık) cascade pattern göremiyoruz
- **Operasyonel müdahale verisi yok** — Bakım sonrası "yenileme" izi yok

### Yapılmayan (Diğer Analizlere Bırakıldı):
- Şoför × Cascade pattern → Analiz 2'ye
- Hat × Cascade ilişkisi → Analiz 3 ile cross-ref (zaten geçti)
- Garaj × Cascade tamir kalitesi → Analiz 5'e

### Common Cause Olarak Tespit Edilen Yan Bulgular:
- KLİMA sistemleri: yaz aylarında aynı hatta birden fazla araç (mevsimsel)
- KAPI sistemleri: yoğun kullanım saatlerinde cluster (operasyonel)
- SOĞUTMA: yaz sıcaklığı pattern'ı
- Bu bulgular Analiz 6 (Operasyonel Yorgunluk) ve Analiz 5 (Garaj) için input olabilir

---

## 16. Metodoloji Bütünlüğü

Bu analiz **veri konuşturularak** yapıldı:

| Beklenti | Veri Sonucu | Yorum |
|---|---|---|
| Cascade var | ✓ ~x1.4 random'dan yüksek | Veri destekledi |
| Cascade true sequential | ✓ %6.1 / %2.7 common cause | Veri destekledi |
| Fırtına yapan araç daha ciddi | ✗ p=0.98 anlamsız | Veri TERSİNİ söyledi |
| Yaş cascade'i artırır | ✗ r=+0.03 anlamsız | Veri TERSİNİ söyledi |
| Sistem ayrımsız cascade ciddi | ✗ Sadece 10 sistemde ciddi | Veri AYRIM gösterdi |
| Cascade ML feature olarak güçlü | ⚠️ |rs|=0.18 en yüksek | Veri ZAYIF gösterdi |
| sistem_cas_lift POZİTİF korelasyon | ✗ NEGATİF çıktı | Prevalans confounding |

Şartlama yok — beklentinin TERSİ çıkan bulgular dürüstçe raporlandı.

**Bakım türü verisi yok uyarısı** Bölüm 5, 7'de açıkça belirtildi. Sebep yorumu yapılmadı.

---

## 17. Operasyonel Bulgular (Sunum İçin)

### A) Self-Cascade Spesifik Parça Tekrar Pattern
- VİTESTEN ATIYOR, KORNA, BEYİN ARIZALARI gibi spesifik parçalar 24s içinde 100x'e kadar tekrar
- Bu pattern bakım kalitesi şüphesi yaratıyor (ama bakım türü verisi yok, kesin yorum yapılamaz)
- **Aksiyon önerisi:** Bu spesifik ARIZAKODU'larda tekrar arıza sayısı bakım kalitesi metriği olabilir

### B) Sistem Bazlı Cascade Risk Profili
- ELEKTRİK + YAKIT + ISITMA + MOTOR + ŞANZIMAN cascade'i ciddiyet artırıyor
- KAROSER + FREN + KAMERA + LASTİK cascade'i ciddiyet etkisiz
- **Aksiyon önerisi:** "Cascade öncelik listesi" — bu 5 sistemde tekrar arıza olan araçlar bakıma alınmalı

### C) Cascade ≠ Bakım Kalitesi Kanıtı (henüz)
- Bakım türü verisi olmadığı için "tamir yapıldı ama değişim olmadı" hipotezi test edilemiyor
- **Aksiyon önerisi:** Bakım sistemine "parça değişim/tamir" alanı eklenmesi datathon önerisi olabilir

### D) Tree Model Optimal Yaklaşım
- Lineer korelasyon zayıf (max 0.18) ama ANOVA F=409 çok güçlü
- XGBoost gibi tree-based modeller bu non-linear pattern'ı yakalar
- Linear regression bu feature'lardan değer üretemez

### E) Common Cause Yan Bulgu (Yaz Mevsim Etkisi)
- KLİMA + SOĞUTMA sistemlerinde yaz aylarında cluster artışı
- Aynı hatta birden fazla araç aynı saatte arıza yapıyor
- **Aksiyon önerisi:** Sıcaklık öncesi proaktif klima/soğutma bakımı

---

## 18. Sonraki Adımlar

- [x] Cascade tanımı + null model
- [x] **Common cause vs true sequential validasyon (Bölüm 21+22)**
- [x] Tetikleyici matrisi (üst kategori)
- [x] Sankey diyagramı
- [x] Arıza fırtınası
- [x] Inter-arrival dağılımı
- [x] Araç bazlı cascade profili
- [x] Confounder + suppressor effect
- [x] 12 ML feature türetme
- [x] Korelasyon + ANOVA + Bant analizi
- [x] Sistem subgroup (cascade ciddiyet)
- [x] Alt kategori (ARIZAKODU) lift
- [x] Fırtına paradoksu açıklaması
- [x] Ordinal feature + cascade_risk_skor
- [x] Sistem bazlı cascade lift feature
- [x] Final ML feature sıralaması
- [ ] 5 önerilen feature → iett_full_feature_matrix.csv'ye ekle (Aşama D)
- [ ] V6 model eğitimi → AUC karşılaştırma (Aşama D)

---

## 19. Final Karar Tablosu

| Konu | Veri Söyledi | Karar |
|---|---|---|
| Cascade gerçek mi? | EVET (~x1.4 random) | Pattern var |
| Cascade true sequential mi? | EVET (%6.1 hat / %2.7 coğrafi) | Common cause minimum |
| Yaş etkisi? | YOK (r=+0.03) | Cascade yaştan bağımsız |
| Fırtına = ciddi? | HAYIR (p=0.98) | Paradoks açıklandı (sistem dağılımı) |
| Cascade her sistemde aynı mı? | HAYIR (10 sistem ciddi, 11 değil) | Sistem-bazlı yaklaşım |
| Spesifik parça tekrar? | LIFT 100+ | Veri raporu (sebep bilinmez) |
| ML feature seti? | 5 güçlü kandidat | V6'ya eklensin |
| Bakım türü verisi? | YOK | Sebep yorumu sınırlı |
| Mevsimsel cluster var mı? | EVET (KLİMA/SOĞUTMA) | Operasyonel input |

**Analiz 1 FİNAL durumda. Sıradaki adım: Analiz 2 — Şoför.**
