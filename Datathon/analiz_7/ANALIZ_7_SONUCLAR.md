# ⛽ ANALİZ 7 — YAKIT EKONOMİSİ VE FİLO STRATEJİSİ SONUÇLAR

**Tarih:** 2026-05-11
**Notebook:** `ANALIZ_7_YAKIT_EKONOMISI_VE_FILO_STRATEJISI.ipynb` (29 hücre, 14 bölüm)
**Veri:** `ariza_model.csv` (58,557 arıza, 3,508 araç — Bilinmiyor/E-JEST/Elektrik filtreli) + `sefer_temiz.csv` (10.1M sefer detayı)
**Veri Penceresi:** 2025-01-01 → 2025-06-30 (6 ay) — yıllık ekstrapolasyon ×2
**Soru:** CNG vs MOTORIN aracları operasyonel risk farkı + filo yakit maliyeti + modernizasyon ROI

**Kapsam:** Orijinal Analiz 7 (Yakıt Verimliliği) + Analiz 8 (Maliyet Simülasyonu) birleştirildi → tek bütünsel "Filo Stratejisi" analizi.

---

## 🎯 KISA ÖZET — 3 KRİTİK BULGU

1. **CNG araçlar operasyonel olarak üstün:** %26.9 daha az ciddi arıza (Chi² = 204, p ≈ 10⁻⁴⁶), M4 confounder altı katsayı **-0.358** (p ≈ 0). Yaş+garaj+araç tipi sabit tutulduğunda CNG avantajı kayboluyor değil, **güçleniyor**.

2. **Filo yakıt maliyeti büyük:** **4.43 milyar TL/yıl**. Motorin araç başına yıllık 1.36M TL, CNG araç başına 407K TL — 3.3x fark. En verimsiz model: Mercedes Capacity (30.17 TL/km).

3. **🚨 CNG geçişi finansal olarak yetersiz cazip:** Senaryo 1 (top 50 yaşlı motorin → CNG) geri ödeme süresi **21 yıl**. Sensitivity testinde 9/9 senaryo >15 yıl. Sadece yakıt tasarrufu modernizasyon için **YETERSİZ NEDEN**.

---

## 1. Veri Hazırlığı (Bölüm 1)

### Veri Filtreleri
- Toplam: 58,559 arıza, 3,509 araç
- "Bilinmiyor" YAKITTURU düzeltmesi:
  - MODEL adında "CNG" varsa → CNG (48 kayıt, 2 TEMSA AVENUE LF CNG aracı)
  - MODEL adında "CNG" yoksa → MOTORIN (592 kayıt, AKIA ULTRA LF12 dominant)
- ELEKTRIK 2 kayıt + E-JEST 2 kayıt → dışlandı
- Final: 58,557 arıza, 3,508 araç

### Dış Veri Kaynakları
| Veri | Kaynak |
|---|---|
| Motorin fiyat 2025 H1 | EPDK aylık ortalama bayi (hakedis.org) |
| CNG fiyat 2025 | BOTAS + belediye CNG operatörleri |
| Tüketim (L/100km) | Daimler/BMC/Otokar spec + Belgrade CNG study |
| İstanbul BRT kalibrasyonu | 78.4M km/yıl × 47M+ litre = 60 L/100km |
| Araç alım fiyatı | Ankara 2024 ihalesi (Otokar/Mercedes/BMC ~200K EUR/solo) |

### Tüketim Tablosu (14 marka-model)
| Marka × Model | Tip | Yakıt | L veya m³ /100km |
|---|---|---|---|
| OTOKAR KENT 290LF | SOLO | MOTORIN | 40 |
| OTOKAR KENT XL | KORUKLU | MOTORIN | 60 |
| MERCEDES CITARO 0530 | SOLO | MOTORIN | 39 |
| MERCEDES CITARO 0530 G | KORUKLU | MOTORIN | 58 |
| MERCEDES CONECTO G | KORUKLU | MOTORIN | 62 |
| MERCEDES CONECTO | SOLO | MOTORIN | 42 |
| MERCEDES CAPACITY | KORUKLU | MOTORIN | 65 |
| BMC PROCITY TR | SOLO | MOTORIN | 41 |
| BMC PROCITY | SOLO | MOTORIN | 41 |
| KARSAN AVANCITY S PLUS | KORUKLU | MOTORIN | 58 |
| **KARSAN AVANCITY CNG** | SOLO | **CNG** | 52 |
| **TEMSA AVENUE LF CNG** | SOLO | **CNG** | 50 |
| AKIA ULTRA LF12 | SOLO | MOTORIN | 40 |
| AKIA LF25 | KORUKLU | MOTORIN | 60 |

### Yakıt Fiyatları 2025 H1
| Ay | Motorin (TL/L) | CNG (TL/m³) |
|---|---|---|
| Ocak | 46.29 | 20.77 |
| Şubat | 46.77 | 20.77 |
| Mart | 45.92 | 20.77 |
| Nisan | 45.26 | 20.77 |
| Mayıs | 45.45 | 20.77 |
| Haziran | 48.81 | 20.77 |
| **H1 Ortalama** | **46.42** | **20.77** |

### Araç Alım Fiyatları
| Tip | EUR | TL (kur 35) |
|---|---|---|
| 12m Solo Dizel | 200,000 | 7.0M |
| 12m Solo CNG | 200,000 | 7.0M |
| 18m Körüklü Dizel | 360,000 | 12.6M |
| 18m Körüklü CNG | 380,000 | 13.3M |

---

## 2. KISIM A — Operasyonel Bulgular

### Bölüm 2: YAKITTURU × Ciddi Arıza

| Yakıt | n_arac | n_ariza | ciddi_oran | lift |
|---|---|---|---|---|
| CNG | 350 | 4,825 | **0.284** | 0.748 |
| MOTORIN | 3,158 | 53,732 | **0.389** | 1.023 |

- **Chi² = 204.25, p = 2.47 × 10⁻⁴⁶** — fark istatistiksel olarak kesin
- **CNG araçlar motorin'den %26.9 daha az ciddi arıza yapıyor** (kontrolsüz)

### Bölüm 3: EMISYON × Ciddi Arıza
- EEV: 0.374, EUR: 0.382 — fark sadece 0.008
- Chi² p = 0.041 (anlamlı ama büyüklük ihmal edilebilir)
- Tüm CNG araçlar EEV sınıfında (333 araç)
- Tüm EUR sınıfı motorin (1,516 araç)
- **Yorum:** EMISYON sınıfı YAKITTURU ile kolinear, bağımsız sinyal taşımıyor

### Bölüm 4: Confounder Kontrolü (M1→M4)

Çoklu regresyon, `ort_skor ~ ...`:

| Model | Değişkenler | R² | k_cng | p |
|---|---|---|---|---|
| M1 | sadece is_cng | 0.0014 | **+0.092** | 0.029 |
| M2 | + yas | 0.0450 | +0.087 | 0.035 |
| M3 | + yas + araç tipi | 0.0841 | +0.215 | < 0.001 |
| **M4** | + yas + araç tipi + garaj | **0.2493** | **-0.358** | **< 0.001** |

**🎯 Kritik bulgu:**
- Ham veride (M1) CNG katsayısı +0.092 (hafif KÖTÜ görünüyor)
- M4'te garaj kontrolü eklenince katsayı **-0.358'e düşüyor** (işaret değişimi)
- Sebep: CNG araçlar belirli garajlarda (KARSAN AVANCITY CNG → IKITELLI vb.) toplandığında garaj etkisini taşıyor. Garaj sabit tutulduğunda CNG'nin **gerçek bağımsız iyileştirici etkisi** ortaya çıkıyor.

**Yaş profili karşılaştırması:**
- CNG: ortalama 11.7 yaş, std 0.5 (homojen, hepsi 10-12 yaş)
- MOTORIN: ortalama 11.5 yaş, std 4.9 (1-19 yaş arası)
- Yaş farkı küçük → yaş confounder büyük değil

### Bölüm 5: MARKA × YAKITTURU Lift Matrisi

| Marka | Yakıt | n_ariza | ciddi_oran | lift |
|---|---|---|---|---|
| AKIA | MOTORIN | 2,572 | 0.329 | 0.864 |
| BMC | MOTORIN | 4,675 | 0.361 | 0.950 |
| **KARSAN** | **CNG** | **2,294** | **0.334** | **0.878** |
| **KARSAN** | **MOTORIN** | **7,629** | **0.435** | **1.143** |
| MERCEDES | MOTORIN | 21,346 | 0.387 | 1.018 |
| OTOKAR | MOTORIN | 17,510 | 0.387 | 1.018 |
| **TEMSA** | **CNG** | **2,531** | **0.239** | **0.630** |

**🎯 KARSAN içi karşılaştırma (en güvenilir kanıt):**
- KARSAN MOTORIN: 0.435 ciddi_oran
- KARSAN CNG: 0.334 ciddi_oran
- **CNG avantajı %+23.2** (aynı marka içinde, üretici/garaj/yaş confounder'ları minimumda)

TEMSA için motorin karşılaştırması yok (filoda sadece CNG TEMSA var).

---

## 3. KISIM B — Finansal Bulgular

### Bölüm 6: Yıllık Km Tahmini

**6 aylık km × 2 → yıllık tahmin:**

| İstatistik | Değer |
|---|---|
| Median yıllık km | 55,632 |
| P75 | 72,800 |
| P95 | 110,000+ |
| Maks | 153,857 |

| Yakıt | Yıllık km ortalama |
|---|---|
| CNG | 38,201 |
| MOTORIN | 57,450 |

**Gözlem:** CNG araçlar daha az km yaparken bile %27 daha az ciddi arıza yapıyor. Bu, CNG avantajının "az kullanım" ile açıklanmadığını gösteriyor (aksine, az km ile daha iyi performans → kalite avantajı net).

### Bölüm 7: Mevcut Filo Yakıt Maliyeti

**🎯 TOPLAM FİLO YILLIK YAKIT: 4.43 MİLYAR TL**

| Yakıt | n_arac | Ortalama TL/araç/yıl | Toplam TL/yıl |
|---|---|---|---|
| CNG | 350 | 407K | 142M |
| MOTORIN | 3,158 | **1,357K** | **4.29 milyar** |

| Garaj | n_arac | Yaş | Yıllık Yakıt TL |
|---|---|---|---|
| **Edirnekapı** | 381 | 12 | **1.04 milyar** |
| **Hasanpaşa** | 319 | 8 | **944M** |
| IKITELLIGARAJI | 429 | 9 | 466M |
| SULTANGAZIGARAJI | 413 | 12 | 431M |
| KURTKÖY | 346 | 12 | 300M |
| IKITELLI2 | 330 | 11 | 286M |
| Anadolu | 353 | 17 | 260M |
| Yunus | 229 | 12 | 197M |
| Sarıgazi | 184 | 12 | 144M |
| Şahinkaya | 129 | 19 | 133M |
| Topkapı | 151 | 1 | 129M |
| Kağıthane | 244 | 12 | 94M |

**Edirnekapı + Hasanpaşa metrobüs garajları toplam yakıt giderinin %45'ini taşıyor** (BRT operasyon yoğunluğu).

| Yaş Bandı | n_arac | Toplam TL |
|---|---|---|
| Yeni 0-3 | 406 | 751M |
| Orta 3-10 | 551 | 869M |
| **Yaşlı 10-15** | **1,862** | **1.70 milyar** |
| Çok Yaşlı 15+ | 689 | 1.11 milyar |

### Bölüm 8: Marka × Model Verimsizlik Sıralaması (TL/km)

**En verimsiz 6 model:**
| # | Marka × Model | Yakıt | Yaş | TL/km |
|---|---|---|---|---|
| 1 | MERCEDES CAPACITY | MOTORIN | 17 | **30.17** |
| 2 | MERCEDES CONECTO G | MOTORIN | 12 | 28.78 |
| 3 | AKIA LF25 | MOTORIN | 2 | 27.85 |
| 4 | OTOKAR KENT XL | MOTORIN | 3 | 27.85 |
| 5 | KARSAN AVANCITY S PLUS | MOTORIN | 12 | 26.92 |
| 6 | MERCEDES CITARO 0530 G | MOTORIN | 19 | 26.92 |

**En verimli 2 model:**
| # | Marka × Model | Yakıt | TL/km |
|---|---|---|---|
| 1 | **TEMSA AVENUE LF CNG** | **CNG** | **10.38** |
| 2 | **KARSAN AVANCITY CNG** | **CNG** | **10.80** |

**Yorum:** CNG araçlar motorin'in **yaklaşık 1/3'ü kadar yakıt maliyetiyle** çalışıyor. Verimsizlik ağırlıkla körüklü/metrobüs araçlarda (yüksek tüketim × yüksek km).

---

## 4. KISIM C — Senaryo Simülasyonları

### Bölüm 9: Senaryo 1 — Top 50 Yaşlı Motorin → CNG

**Hedef:** En yaşlı 50 solo motorin aracı CNG modeline dönüştür.

| Profil | Değer |
|---|---|
| Hedef araç sayısı | 50 |
| Ortalama yaş | 19 |
| Garaj dağılımı | Anadolu 31 + Şahinkaya 19 |

| Maliyet | TL |
|---|---|
| Mevcut yıllık motorin | 41.08M |
| CNG sonrası | 24.51M |
| **Yıllık tasarruf** | **16.57M** |

| ROI | Değer |
|---|---|
| Yatırım | 50 × 200K EUR = 10M EUR = **350M TL** |
| **Geri ödeme süresi** | **21.1 yıl** |

**Arıza tasarrufu (operasyonel ek değer):**
- M4 CNG katsayısı: **-0.358** (ort_skor üzerinde)
- Mevcut 50 aracın ciddi_oran: 0.342
- CNG araçlar ciddi_oran: 0.298
- **Tasarruf oranı: %12.8** (kontrolsüz)

### Bölüm 10: Senaryo 2 — 5 Yıllık Aşamalı Geçiş

Her yıl filodaki en yaşlı motorin %20'sini CNG'ye dönüştür:

| Yıl | Dönüştürülen | Yıllık Tasarruf (M TL) | Birikimli |
|---|---|---|---|
| 1 | 632 | 529 | 529 |
| 2 | 1,264 | 1,082 | 1,612 |
| 3 | 1,896 | 1,324 | 2,936 |
| 4 | 2,528 | 1,784 | 4,721 |
| 5 | 3,160 | 2,326 | **7,047** |

| Toplam (5 yıl) | TL |
|---|---|
| Yatırım | 22,120M TL |
| Tasarruf | 7,047M TL |
| **Net 5 yıllık** | **-15,073M TL** (kayıp) |
| 5. yıldan sonra yıllık | 2.3 milyar TL tasarruf |

**Tam geri ödeme:** ~10 yıl (5+5 model)

### Bölüm 11: Sensitivity Analizi (Tüketim ±%20, Fiyat ±%15)

9 senaryolu grid testi:

| Tüketim | Fiyat | Tasarruf (M TL/yıl) | Geri Ödeme (yıl) |
|---|---|---|---|
| -%20 | -%15 | 11.27 | **31.1** |
| -%20 | 0 | 13.26 | 26.4 |
| -%20 | +%15 | 15.25 | 23.0 |
| 0 | -%15 | 14.09 | 24.8 |
| 0 | 0 | 16.57 | 21.1 |
| 0 | +%15 | 19.06 | 18.4 |
| +%20 | -%15 | 16.90 | 20.7 |
| +%20 | 0 | 19.89 | 17.6 |
| +%20 | +%15 | 22.87 | **15.3** |

**🎯 Sensitivity Sonuç:**
- En kötümser: 31 yıl geri ödeme (tasarruf 11.3M TL)
- En iyimser: 15.3 yıl geri ödeme (tasarruf 22.9M TL)
- **9/9 senaryoda geri ödeme >15 yıl**

**Yorum:** Senaryolar geniş aralıkta test edildi, **hiçbiri 15 yıl altına inmedi**. CNG geçişi sadece yakıt tasarrufu mantığıyla finansal olarak GERİ ÖDENMİYOR. Bu sonuç sağlam.

---

## 5. KISIM D — Synthesis

### Bölüm 12: Yenileme Öncelik Listesi

Birleşik skor: yaş %40 + ciddi_oran %30 + yıllık_yakıt %30 (normalize)

**Top 20 araç (hepsi 19 yaş, Mercedes Citaro 0530):**
| KAPINO | Garaj | Öncelik Skoru |
|---|---|---|
| M5508 | Şahinkaya | 67.6 |
| M6306 | Şahinkaya | 65.8 |
| M5740 | Şahinkaya | 65.7 |
| M5977 | Şahinkaya | 65.5 |
| M2739 | Şahinkaya | 65.0 |
| ... (15 daha) | | |

**Top 100 özeti:**
| Metrik | Değer |
|---|---|
| Ortalama yaş | 19.0 |
| Toplam yıllık yakıt | 90.3M TL |
| Garaj dağılımı | Şahinkaya 59 + Anadolu 41 |

**Operasyonel öneri:** İlk öncelik Şahinkaya garajı (59 araç, hepsi 19 yaş Mercedes Citaro). Anadolu ikinci öncelik (41 araç).

### Bölüm 13: ML V6 Feature Kandidatları

| Feature | Tip | r (ort_skor ile) | M4 Katsayı | Karar |
|---|---|---|---|---|
| `yakit_turu_cng` | binary | +0.036 | **-0.358** | **GÜÇLÜ** (confounder altı) |
| `tahmini_yillik_yakit_tl` | sürekli | +0.076 | — | Orta, yaş ile kolinearite riski |
| **`verimsizlik_skoru`** | sürekli | **+0.220** | — | **EN GÜÇLÜ** |

`verimsizlik_skoru = yas_norm × tuketim_norm`

**Notlar:**
- `yakit_turu_cng` ham r düşük (+0.036) ama M4 katsayısı -0.358 — modelde **kategorik etki olarak** ekle (one-hot encoding ile)
- `tahmini_yillik_yakit_tl` yaş × km × tüketim → yaş ile yüksek kolinearite olabilir, leakage testi gerek
- `verimsizlik_skoru` Analiz 3'ten `egim_maruziyet` (r=+0.135) ve Analiz 5'ten `garaj_sistem_lift` (r=+0.213) ile aynı düzlemde, ML V6 için **çekirdek feature**

---

## 6. Bug Tespiti ve Düzeltme

**Bug:** Bilinmiyor YAKITTURU → tek tip MOTORIN olarak düzeltilmişti. 2 TEMSA AVENUE LF CNG aracı (T3379 + T3977) yanlışlıkla MOTORIN sayıldı.

**Düzeltme:** MODEL adında "CNG" varsa CNG ata, yoksa MOTORIN.

**Etki:**
- CNG araç sayısı: 348 → **350**
- CNG arıza kaydı: 4,777 → **4,825**
- CNG avantajı: %26.5 → **%26.9**
- M4 katsayı: -0.349 → **-0.358** (daha güçlü)
- Bölüm 8 verimsizlik tablosunda TEMSA satırı doğru CNG sınıfına oturdu

Ana sonuçlar değişmedi (~%0.5 fark), metodolojik temizlik sağlandı.

---

## 7. Kısıtlamalar (Dürüst)

1. **Tüketim üretici spec + endüstri ortalaması** — Gerçek arac/sürücü/yaş/bakım varyansı yansıtılmadı. Aynı modelin yaşlı vs yeni hali arasında %30+ fark olabilir.

2. **Yakıt fiyatları aylık EPDK ortalaması** — Bayi farkı ve toplu ihale fiyatı (-%5-10) hesaba katılmadı. CNG fiyat tek değer (yıllık trend yansıtılmadı).

3. **Araç alım fiyatı Ankara 2024 ihalesinden ekstrapolasyon** — İETT 2026 ihalesi fiyatları açıklanmadı, ±%15 hata payı.

4. **6 ay verisi × 2 yıllık tahmin** — Mevsimsellik (yaz vs kış AC kullanımı, yokuş trafiği) yansıtılmadı.

5. **ARACTIPI ayrımı yapılmadı** — Metrobüs operasyon yoğunluğu otobüsten farklı (BRT 60 L/100km). Tüketim tablosunda ARACCINSI kısmi ayrım sağlıyor.

6. **CNG istatistiksel güç sınırlı** — 350 CNG araç (filonun %10'u), CNG araçların TEMSA + KARSAN ile sınırlı olması diğer markalar için CNG karşılaştırması imkansız.

7. **ROI hesabı sadece yakıt tasarrufu üzerinden** — Bakım maliyeti azalması, emisyon vergisi avantajı, hurda değer eklenmemiş. Gerçek ROI biraz daha kısa olabilir.

8. **EUR/TL kuru 35 sabit** — 2025 H1 ortalama tahmini, gerçek kur dalgalanması yansıtılmadı.

9. **yolcu_gunluk_doluluk.csv güvenilmez** (proje kararı) — Doluluk × yakıt verimliliği analizi yapılamadı.

---

## 8. Sunum Hikayesi (Datathon İçin)

> **Operasyonel kanıt:** CNG araçlar motorin'den %26.9 daha az ciddi arıza yapıyor (Chi² p ≈ 10⁻⁴⁶). Confounder altında (yaş+garaj+araç tipi sabit) bu avantaj **güçleniyor** (M4 katsayı -0.358). KARSAN içi karşılaştırma %+23 ile en güvenilir kanıt.
>
> **Finansal gerçek:** İETT filosu yıllık 4.43 milyar TL yakıt harcıyor. CNG araç başına 407K TL/yıl, motorin 1.36M TL/yıl — **3.3x fark**. En verimsiz model Mercedes Capacity (30 TL/km), en verimli CNG'ler (10.4-10.8 TL/km).
>
> **🚨 Stratejik bulgu:** Sadece yakıt tasarrufuyla CNG geçişi **21 yılda geri ödenir** (sensitivity'de 9/9 senaryo >15 yıl). Tek başına finansal cazibe yetersiz.
>
> **Çok-kriterli karar:** CNG modernizasyonu sadece yakıt değil, **operasyonel avantaj + emisyon politikası + arıza azalması** birleşince çekici. Öncelik: 100 en yaşlı motorin araç (Şahinkaya 59 + Anadolu 41, Mercedes Citaro 0530, 19 yaş).
>
> **Veriye saygı:** Hipotezimiz "CNG geçişi finansal cazip" idi, veri bunu desteklemedi. Dürüstçe sunduğumuz bu bulgu çürütme değil **gerçeklik kontrolü** — operasyonel avantaj kalır, finansal hikaye revize edilir.

---

## 9. ML V6 Feature Listesi (Bu Analizden)

```python
yakit_turu_cng              # binary, M4 katsayi -0.358, kategorik etkili
verimsizlik_skoru           # yas_norm * tuketim_norm, r=+0.220 (EN GÜÇLÜ)
tahmini_yillik_yakit_tl     # surekli, r=+0.076, yas ile kolinearite riski
```

**Leakage testi V6 hazırlığında yapılacak.**

---

## 10. Sonraki Adımlar

- [x] Analiz 7 SONUCLAR (bu belge)
- [ ] **Analiz 8 — Güvenlik Prioritizasyon** (Top 50 riskli araç, kritiklik skoru)
- [ ] Analiz 9 — Akıllı Hat-Araç Atama (synthesis)
- [ ] FEATURES_FINAL.md
- [ ] ML_MODEL_V6

---

## 11. Datathon Sunum Tabloları (Hazır)

### Tablo 1: CNG vs MOTORIN Operasyonel
| Metrik | CNG (n=350) | MOTORIN (n=3,158) | Fark |
|---|---|---|---|
| Ciddi arıza oranı | 0.284 | 0.389 | **-%26.9** |
| Ort skor | 3.52 | 3.62 | -0.10 |
| Chi² p | < 10⁻⁴⁶ | | |
| M4 katsayı | -0.358 | (referans) | p<0.001 |

### Tablo 2: Mevcut Filo Yakıt Maliyeti
| Kategori | TL/yıl |
|---|---|
| Toplam filo | **4.43 milyar** |
| Edirnekapı garajı | 1.04 milyar |
| Hasanpaşa garajı | 944M |
| Motorin filosu | 4.29 milyar |
| CNG filosu | 142M |

### Tablo 3: ROI Senaryoları
| Senaryo | Tasarruf (M TL/yıl) | Geri Ödeme (yıl) |
|---|---|---|
| Top 50 yaşlı → CNG | 16.6 | 21.1 |
| En kötümser sensitivity | 11.3 | 31.1 |
| En iyimser sensitivity | 22.9 | 15.3 |

### Tablo 4: Verimsizlik Top/Bottom
| En verimsiz | TL/km | En verimli | TL/km |
|---|---|---|---|
| Mercedes Capacity | 30.17 | TEMSA Avenue LF CNG | 10.38 |
| Mercedes Conecto G | 28.78 | Karsan Avancity CNG | 10.80 |
| AKIA LF25 | 27.85 | Mercedes Citaro 0530 | 18.10 |
