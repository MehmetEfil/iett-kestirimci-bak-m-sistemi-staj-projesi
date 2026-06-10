# Analiz 2: Şoför Etkisi (Rotasyon + Sürüş Stili) — Bulgular ve Kanıtlar
**Notebook:** ANALIZ_2_SOFOR_ROTASYONU.ipynb
**Tarih:** 2026-05-12
**Durum:** FİNAL — 13 bölüm tamamlandı, leakage testi yapıldı, ML kararı verildi

---

## 🎯 KARAR ÖZETİ

| Soru | Bulgu | Kanıt |
|---|---|---|
| Şoför etkisi gerçek mi? | **EVET** — random'dan anlamlı yüksek | Cell 9: %99 üzerinde |
| Rotasyon araçları daha çok arıza yapıyor mu? | **EVET** — 6x arıza, +0.46 ciddiyet | Bölüm 13: Mann-Whitney p<0.001 |
| Hangi sistemler rotasyonla artıyor? | **KAPI, ŞANZIMAN, SÜSPANSİYON, ISITMA, KLİMA** | Lift 0.60-0.76 |
| Hangi sistemler sabit araçta çok? | **AKBİL, YAKIT, KAMERA, BASINÇLI HAVA** | Lift 2.25-4.46 |
| sofor_glob_skor güçlü ML feature mi? | **HAYIR — büyük çoğunluğu LEAKAGE** | Bölüm 12: r %391→%76 düşüş |
| Şoför ML feature eklenecek mi? | **HAYIR — atla** | Time-aware r<0.10 |

---

## 1. Veri ve Metodoloji

**Veri kaynağı:** ariza_model.csv (58,559 arıza × 3,509 araç × 5,910 şoför, 180 gün)
**Yardımcı:** arac_gunluk_hatlar.csv (sefer verisi — confounder kontrolü için)

### Metodolojik Notlar
- İETT araçları günde 2-3 vardiya, 2-3 farklı şoför kullanır
- `SOFOR_SICILNO` arıza anındaki son aktif şoför — attribution belirsizliği var
- Sefer verisi attribution belirsizliğini azaltır
- ML kararı VERİYE göre verildi (şartlama yok)

### Önemli Veri Sınırlaması (Analiz 4'ten)
- `ariza_model.csv` sadece İETT operatörü içeriyor
- ÖHO/KOOP araçları arıza kaydı tutmuyor (3,252 araç sefer'de var ama ariza'da yok)
- Bu analiz **sadece İETT öz filosu** için geçerli

---

## 2. Şoför Profil İstatistikleri

```
Benzersiz şoför:        5,910
Şoför/Araç oranı:        1.68
Median farklı araç:      7 (180 gün)
P90 farklı araç:         17
Max farklı araç:         350
```

### Yedek/Havuz Şoför Tespiti
```
>=50 farklı araç:         3 şoför (%0.1)
Toplam arıza katkısı:     606 (%1.0)
Ariza/araç oranı:         1.04 (normal şoför 1.06 — fark yok)
```

→ Yedek şoför etkisi minimal, analize zarar vermiyor.

---

## 3. Şoför Yoğunlaşma Metriği (Sabit vs Göçebe)

**Tanım:** `ana_arac_orani = max(arac_kullanim) / toplam_kullanim`

```
Yoğunlaşma Sınıfı       n_sofor  ort_skor  ort_ciddi  ort_farkli_arac
Çok Göçebe (<20%)       2,999    3.636     0.393      12.5
Göçebe (20-40%)         770      3.597     0.363      7.2
Orta (40-60%)           440      3.566     0.353      5.5
Sabit (60%+)            406      3.543     0.327      3.0

ANOVA F=2.89, p=0.034 — ANLAMLI (zayıf)
Pearson r=-0.042, Spearman rs=-0.053
```

**Veriye göre:** Sabit şoför = hafif daha düşük ciddiyet (süreklilik bonusu). Etki küçük ama istatistiksel olarak anlamlı.

---

## 4. Araç Başına Şoför Rotasyonu (Sefer Confounder)

```
Rotasyon Sınıfı      n_arac  ort_sofor  ort_skor  ort_ciddi  ort_sefer
Düşük (≤5)           608     3.7        3.35      0.30       1475
Orta (6-15)          1559    9.9        3.56      0.36       1349
Yüksek (16-30)       1127    21.7       3.65      0.40       1252
Aşırı (30+)          215     35.6       3.68      0.41       1336

ANOVA F=24.49, p=0.000000
```

### Korelasyonlar
```
sofor_n × ort_skor:     r=+0.118 (orta)
toplam_sefer × ort_skor: r=-0.147 (CONFOUNDER!)
sofor_n × sefer:         r=-0.168 (negatif)
Partial r (sefer kontrol): r=+0.425 ← SUPRESSOR EFFECT!
```

**Yorum:** Sefer kontrol altında rotasyon etkisi DAHA GÜÇLÜ ortaya çıkıyor. Yani: "Çok şoför + az sefer" pattern'i araçların daha ciddi arıza yaptığını gösteriyor.

---

## 5. Vardiya Proxy (Saat Verisi)

Vardiya verisi yok, saat ile proxy oluşturuldu (Sabah 06-14, Akşam 14-22, Gece 22-06).

```
Vardiya  n_ariza  ort_skor  ort_ciddi
Sabah    29,009   3.618     0.373
Akşam    26,155   3.574     0.382
Gece     3,395    3.816     0.433  ← EN YÜKSEK
```

**Veriye göre:** Gece vardiyası arızaları **daha ciddi** (skor +0.20, ciddi %+5).
Olası açıklamalar (sebep belirsiz):
- Gece az trafik, hızlı sürüş
- Gece şoförlerin yorgunluk
- Veya: gece arıza tespiti farklı pattern

---

## 6. Random Null Model — Şoför Etkisi Gerçek mi?

```
Gerçek şoför varyansı:    0.3676
Permute median varyans:   0.2440
Permute P95 varyans:      0.2543
Gerçek %99 üzerinde
```

**VERİYE GÖRE:** Şoför varyansı random permutasyondan **anlamlı yüksek.** Şoförler arası ciddiyet farkı gerçek, şansa bağlı değil.

---

## 7. Şoför-Araç Uyumu (Süreklilik Bonusu Hipotezi) — ÇÜRÜTÜLDÜ

```
Eşleşme Bant   n_cift  ort_skor  ort_ciddi
3-5 kez        1158    3.509     0.325
6-10 kez       354     3.509     0.333
11-20 kez      38      3.446     0.327
20+ kez        0       —         —

Pearson r=-0.014, p=0.58 — ANLAMSIZ
```

**VERİYE GÖRE:** Aynı şoför aynı araca çok bindiğinde ciddiyet **değişmiyor.** Süreklilik bonusu çift bazında YOK.

---

## 8. Şoför × Sistem Detayı

Sistem varyans karşılaştırması (sofor/arac oranı):

```
Sistem                          oran(sof/arac)
KAMERA SİSTEMİ                  2.10  ← şoföre çok bağlı
BASINÇLI HAVA DONANIMI          1.50
AKBİL                           1.49
SÜSPANSİYON                     1.25
KAPI                            1.19
FREN ŞİKAYETLERİ                1.14
YAKIT ve ENJEKSİYON             1.14
OTOMATİK ŞANZIMAN               1.10
SOĞUTMA SİSTEMİ                 1.08
KLİMA                           1.07
ELEKTRİK                        1.06
MOTOR                           1.01

KAROSER                         0.97
ISITMA                          0.91  ← araca bağlı
```

**Yorum:** 12 sistem şoföre, 3 sistem araca bağlı. **KAMERA en şoför-bağımlı sistem** (operasyon stiliyle alakalı).

---

## 9. ML Feature Türetme — 11 Kandidat

### Türetilen Feature'lar
```
Cumulative (her arıza için "o ana kadar geçmiş"):
- sofor_gecmis_n, sofor_gecmis_ciddi_n, sofor_gecmis_ciddi_oran
- gecmis_sa_eslesme (sofor-arac cift)

Global profil:
- sofor_glob_skor, sofor_glob_ciddi, sofor_farkli_arac

Yapısal:
- arac_basi_sofor_n, ana_arac_orani, yedek_sofor_flag, vardiya_kod
```

### Korelasyon Testleri (Full-data)
| Feature | Pearson r | Spearman rs | CiddiAriza r | İlk İzlenim |
|---|---|---|---|---|
| **sofor_glob_skor** | **+0.391** | +0.371 | +0.293 | EN GÜÇLÜ |
| **sofor_glob_ciddi** | **+0.324** | +0.323 | +0.354 | GÜÇLÜ |
| sofor_gecmis_ciddi_n | +0.037 | +0.058 | +0.024 | Zayıf |
| sofor_farkli_arac | +0.033 | +0.032 | +0.020 | Zayıf |
| arac_basi_sofor_n | +0.030 | +0.057 | +0.053 | Zayıf |
| sofor_gecmis_n | +0.029 | +0.030 | +0.019 | Zayıf |
| yedek_sofor_flag | +0.028 | +0.021 | +0.010 | Zayıf |
| ana_arac_orani | -0.019 | -0.041 | -0.042 | Zayıf |
| diğerleri | <0.01 | <0.01 | <0.01 | İhmal |

---

## 10. Confounder Kontrolü (Multiple Regression)

```
M1 (sadece ana_arac_orani):  k=-0.15, p=0.004
M2 (+yaş):                    k=-0.20, p=0.0001
M3 (+yaş+sefer):              k=-0.26, p=0.001 (anlamlı)
```

**Veriye göre:** ana_arac_orani sefer+yaş kontrolü altında **negatif anlamlı** (sabit şoför = daha az ciddi). Sureklilik bonusu vehicle bazlı VAR.

---

## 11. KRİTİK — Time-Based Leakage Testi

`sofor_glob_skor` r=+0.391 çekici görünüyordu. Time-based split testi:

```
Train (ilk 90g):   29,279 ariza, 5,566 sofor
Test (sonraki 90g): 29,280 ariza, 5,538 sofor

Coverage:
  Test'te ortak sofor: 5,194 (%93.8)
  Test'te yeni sofor:  344  (%6.2)

LEAKAGE TESTİ SONUCU:
  Full-data (leakage'lı):  r=+0.3907
  Time-aware (train→test): r=+0.0755  ← GERÇEK DEĞER
  DÜŞÜŞ ORANI: %81

SOFOR PROFIL STABILITESI:
  Train_skor × test_skor: r=+0.224 (ORTA STABIL, gürültülü)
```

**VERİYE GÖRE:** r=+0.391'in %81'i leakage'dan geliyordu. Gerçek prediktif değer sadece **r=+0.076**.

**Sebepler:**
1. Şoför profili zaman içinde değişken (r=+0.224 stabilite)
2. Test'te %6.2 yeni şoför var (target encoding yapılamaz)
3. ML için fallback strategy gerekir

**KARAR:** `sofor_glob_skor` ML için **GÜVENİLİR DEĞİL.** Atılacak.

---

## 12. ASIL HEDEF — Sabit Şoförlü vs Rotasyonlu Araç (KRİTİK CEVAP)

Senin asıl sorduğun: **Aynı şoförle sürekli kullanılan araç vs çok farklı şoförü olan araç → arıza oranı aynı mı? Hangi sistemler farklı?**

### Genel Karşılaştırma (TÜM testler p<0.001)
```
Grup                  n_arac  ort_sofor  ort_ariza  ort_skor  ciddi_oran  ariza/1000sefer
Sabit (≤3 sofor)       249    2.5        4.8        3.21      0.27        7.85
Orta (4-19)            2,307  10.3       13.1       3.55      0.36        10.81
Rotasyon (≥20)         953    26.6       28.4       3.67      0.40        23.86
```

### Cevap: ROTASYON ARAÇLARI DAHA ÇOK VE DAHA CİDDİ ARIZA YAPIYOR
- Toplam arıza: **6x** daha çok
- Ortalama ciddiyet: **+0.46** daha yüksek
- Ciddi oran: **+%13.4** daha yüksek
- Arıza/1000 sefer: **3x** daha çok

### Sefer Normalize (En Adil Metrik)
- Sabit: 0.66 arıza/1000 sefer
- Rotasyon: 0.78 arıza/1000 sefer
- **Sefer normalize fark sadece %18**

→ Büyüklük farkının çoğu rotasyon araçlarının daha çok kullanılmasından geliyor. Ama **gerçek rotasyon etkisi hâlâ var** (%18 fark + anlamlı).

### Sistem Bazlı Farklar — EN İLGİNÇ KISIM

**ROTASYON ARAÇTA ÇOK DAHA YÜKSEK (Lift < 0.8 → kullanım stresi):**
| Sistem | Sabit% | Rotasyon% | Lift |
|---|---|---|---|
| **KAPI** | 8.2 | 13.6 | **0.60** |
| OTOMATIK ŞANZIMAN | 3.7 | 5.7 | 0.65 |
| ISITMA | 2.9 | 4.4 | 0.66 |
| SÜSPANSİYON | 4.3 | 6.3 | 0.68 |
| KLİMA | 5.3 | 7.0 | 0.76 |

**Yorum:** Bu sistemler **kullanım stresine bağlı.** Farklı şoför = farklı kapı kullanım stili, farklı vites geçişi, farklı süspansiyon yükü → daha çok arıza.

**SABİT ARAÇTA DAHA YÜKSEK (Lift > 1.2):**
| Sistem | Sabit% | Rotasyon% | Lift |
|---|---|---|---|
| **AKBİL** | 8.0 | 1.8 | **4.46** |
| YAKIT/ENJEKSİYON | 5.3 | 1.7 | 3.06 |
| KAMERA | 4.5 | 1.5 | 2.91 |
| BASINÇLI HAVA DONANIMI | 3.0 | 1.3 | 2.25 |
| KAROSER | 9.0 | 7.0 | 1.29 |

**Yorum:** Elektronik/sensör sistemler sabit araçta daha sık arızalanıyor. Olası sebepler (kesin değil — bakım türü verisi yok):
- Sabit araçlar daha eski/spesifik tip
- Belirli operasyon koşulları (hava donanımı kullanımı)

---

## 13. ML Feature KARARI — Şoför Feature ATLANIYOR

Veri sonuçlarına göre:

| Feature | r (Time-aware) | Karar |
|---|---|---|
| sofor_glob_skor | +0.076 | ❌ ATLA (leakage hayal kırıklığı) |
| sofor_glob_ciddi | ~+0.05 | ❌ ATLA (benzer leakage) |
| arac_basi_sofor_n | +0.030 (partial +0.42) | ⚠️ Confounder sorunlu |
| ana_arac_orani | -0.019 (M3 -0.26) | ⚠️ Marjinal anlamlı |
| sofor_gecmis_* | <0.04 | ❌ ATLA |
| diğerleri | ~0 | ❌ ATLA |

**SONUÇ:** Şoför bazlı ML feature ekleme YAPILMAYACAK. Time-aware korelasyonlar çok zayıf. Tree model için bile marjinal.

---

## 14. Vaka Analizi — En Riskli vs En İyi Şoförler

```
EN RISKLI 10 SOFOR (ort_skor ≥ 5.24):
  P_56022: 12 arıza, 6 araç, ort_skor 5.64
  P_6646:  11 arıza, 7 araç, ort_skor 5.42
  P_31869: 10 arıza, 10 araç, ort_skor 5.41
  P_50990: 12 arıza, 11 araç, ort_skor 5.38
  ...

EN IYI 10 SOFOR (ort_skor ≤ 1.69):
  P_51020: 11 arıza, 10 araç, ort_skor 1.13, ciddi 0%
  P_59327: 19 arıza, 18 araç, ort_skor 1.16, ciddi 0%
  P_55855: 10 arıza, 10 araç, ort_skor 1.36
  ...

Fark: 4.5 puan (skor) — büyük varyans var
```

**Veriye göre:** Şoförler arası dramatik fark var (1.13 vs 5.64). Ama bu fark zaman içinde STABIL DEĞİL (Bölüm 11 stabilite r=+0.22).

---

## 15. Operasyonel Bulgular (Sunum İçin)

### A) Rotasyon Stratejisi Arıza Üretiyor
- Rotasyon araçları sefer başına %18 daha çok arıza
- KAPI, ŞANZIMAN, SÜSPANSİYON, ISITMA, KLİMA sistemleri rotasyonda dramatik artıyor
- **Aksiyon önerisi:** Bu sistemleri etkileyen şoför pattern'ları için zimmetleme önceliği

### B) Sabit Şoför Bonusu Var (Mütevazi)
- ana_arac_orani 60%+ şoförler ortalamadan -0.05 daha düşük ciddiyet (M3 sonrası)
- **Aksiyon önerisi:** Mümkün olduğunca aynı şoför-araç eşleştirmesi

### C) Gece Vardiyası Daha Ciddi
- Skor 3.82 (gündüz 3.62) — anlamlı yüksek
- **Aksiyon önerisi:** Gece vardiyalarına özel kontrol/eğitim

### D) Sistem Tipine Göre Strateji
**Kullanım stresine bağlı (KAPI, ŞANZIMAN vb.):**
- Rotasyon kısıtlaması veya şoför eğitimi

**Bakım gerektiren (AKBİL, KAMERA vb.):**
- Şoför pattern'ından bağımsız — düzenli kontrol kuralı

---

## 16. Metodoloji Bütünlüğü

| Beklenti | Veri Sonucu | Yorum |
|---|---|---|
| Şoför etkisi gerçek | ✓ Random'dan %99 yüksek | Veri destekledi |
| Rotasyon arıza üretir | ✓ p<0.001 TÜM testler | Veri destekledi |
| sofor_glob_skor ML için güçlü | ✗ %81 leakage | Veri TERSİNİ söyledi |
| Şoför-araç süreklilik bonusu | ⚠️ Çift bazlı yok ama yoğunlaşma var | Karışık |
| Yedek şoför sorun yaratır | ✗ Sadece 3 şoför, etkisiz | Veri TERSİNİ söyledi |
| ML feature seti güçlü | ✗ Time-aware tüm r<0.10 | Veri ZAYIF gösterdi |

**Şartlama yok:** Leakage testini yapmasaydık `sofor_glob_skor` r=+0.391'i ML'e ekleyecektik. Veri bizi durdurdu.

---

## 17. Sınırlamalar ve Yapılamayan Testler

### Yapılamayan / Sınırlı
- **Vardiya verisi YOK** — sadece saat proxy'si kullanıldı
- **Bakım türü verisi YOK** — sabit-araç-elektronik paradoksunun sebebi belirsiz
- **ÖHO/KOOP şoförleri YOK** — analiz sadece İETT öz filosu
- **Şoför attribution belirsizliği** — vardiya değişimleri arıza atfını etkileyebilir

### Yapılmayan (Diğer Analizlere Bırakıldı)
- Şoför × Hat çapraz (Analiz 3 cross-ref) — yapılmadı
- Şoför × Garaj çapraz (Analiz 5'e)
- Şoför × Kaza (Analiz 4'te zaten yapamadık — kaza datasında sofor yok)

---

## 18. Sonraki Adımlar

- [x] Şoför profil + yoğunlaşma metriği
- [x] Araç başına şoför rotasyonu
- [x] Vardiya proxy
- [x] Random null model
- [x] Şoför-Araç uyumu
- [x] Sistem detayı
- [x] 11 ML feature türetme
- [x] Korelasyon testleri
- [x] Confounder kontrolü
- [x] Vaka analizi
- [x] **Time-based leakage testi**
- [x] **Sabit vs Rotasyon araç karşılaştırması (ASIL HEDEF)**
- [→] Şoför feature ML'e EKLENMİYOR
- [→] Operasyonel bulgular sunum slaytında kullanılacak

---

## 19. Final Karar Tablosu

| Konu | Veri Söyledi | Karar |
|---|---|---|
| Şoför etkisi var mı? | EVET (random'dan %99 yüksek) | Pattern var |
| Rotasyon araç daha mı sorunlu? | EVET (6x arıza, +0.46 skor) | İşletme bulgusu |
| Hangi sistemler rotasyon-bağımlı? | KAPI, ŞANZIMAN, SÜSPANSİYON, ISITMA, KLİMA | Aksiyon önerisi |
| sofor_glob_skor ML için güçlü mü? | HAYIR (%81 leakage) | Atla |
| Şoför profili zamanda stabil mi? | ORTA (r=+0.22) | Güvensiz |
| ML feature ekleme? | TÜM şoför feature'ları zayıf | Hiçbiri eklenmeyecek |
| Operasyonel öneri? | Rotasyon kısıtlama, gece kontrol | Sunum slaydı |
| Bakım türü verisi yok? | EVET | Sebep yorumu sınırlı |

**Analiz 2 FİNAL durumda.** Şoför feature ML'e eklenmiyor ama **operasyonel bulgular çok değerli.** Sıradaki adım: **Analiz 5 — Garaj Uzmanlık.**
