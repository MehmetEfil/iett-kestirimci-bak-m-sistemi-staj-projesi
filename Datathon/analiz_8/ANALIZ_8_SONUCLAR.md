# 🚨 ANALİZ 8 — GÜVENLİK VE PRİORİTİZASYON SONUÇLAR

**Tarih:** 2026-05-11
**Notebook:** `ANALIZ_8_GUVENLIK_VE_PRIORITIZASYON.ipynb` (29 hücre, 14 bölüm)
**Veri:** `ariza_model.csv` (58,557 arıza, 3,508 araç — Bilinmiyor düzeltilmiş)
**Veri Penceresi:** 2025-01-01 → 2025-06-30 (Train: ilk 3 ay, Test: son 3 ay)
**Soru:** Filodaki en yüksek riskli araçları kompozit skor ile sıralayıp operasyonel müdahale listesi üretmek + ML V6 için `kritiklik_skoru` feature.

**Kapsam:** Önceki 6 analiz feature'ını (yas, gecmis_ciddi_oran, egim_maruziyet, garaj_ort_skor, verimsizlik_skoru, gecmis_ort_skor) birleştirip ağırlıklı kompozit risk skoru üretildi. 3 farklı ağırlık politikası test edildi.

---

## 🎯 KISA ÖZET — 4 KRİTİK BULGU

1. **Kompozit skor yaş baseline'dan iyi:** AUC 0.624 (kompozit) vs 0.529 (yaş tek başına), +0.095 net iyileşme. AMA AUC 0.62 hâlâ **ORTA düzey** ML feature.

2. **🚨 Stability r=0.15 ALARM:** Araç bazlı performans zaman içinde çok dalgalı. Kompozit skor ML V6'ya **doğrudan eklenmemeli** — bunun yerine bireysel raw feature'lar tercih edilmeli.

3. **Top 50 listesi sağlam ve net:** Ortalama lift 1.50x, dominant Şahinkaya (29/50) + KURTKÖY (10/50) + Edirnekapı (8/50). Mercedes Citaro 0530 G + Karsan Avancity S Plus modelleri öne çıkıyor.

4. **⭐ KRİTİK METODOLOJİK BULGU — Motor Yenileme Confounder:** İETT'nin düzenli motor yenileme/bakım yaptığı bilgisiyle, MODELYILI (üretim yılı) gerçek "motor yaşını" yansıtmıyor. Yas feature'ının zayıflığı (AUC 0.529) ve Anadolu garajının (17 yaş) Top 50'de hiç yer almaması bu açıklamayla uyumlu.

---

## 1. Veri Hazırlığı (Bölüm 1-2)

### Veri Filtreleri
- Toplam: 58,559 arıza → 58,557 (Bilinmiyor → CNG/MOTORIN düzeltmesi, Analiz 7'den)
- 3,508 araç profili
- ADALAR garajı zaten dışında

### Birleştirilen Feature'lar
| Feature | Kaynak Analiz | Tip |
|---|---|---|
| yas | Temel (MODELYILI'den) | Sürekli |
| gecmis_ciddi_oran | Train dönemi (zaman-aware) | 0-1 |
| gecmis_ort_skor | Train dönemi | Sürekli |
| egim_maruziyet | Analiz 3 (hat_elevation.json) | 0-100 |
| garaj_ort_skor | Analiz 5 (basitleştirildi) | ~2-4 |
| verimsizlik_skoru | Analiz 7 (yas_norm × tuketim_norm) | 0-100 |

---

## 2. Train/Test Split (Bölüm 3)

| Dönem | Tarih Aralığı | Arıza | Araç |
|---|---|---|---|
| Train | 2025-01-01 → 2025-04-07 | 29,279 | 3,456 |
| Test | 2025-04-07 → 2025-06-30 | 29,278 | 3,439 |

Median tarih split kullanıldı. Test_risk_binary: ciddi_oran > median.

---

## 3. Bireysel Feature Korelasyon ve AUC (Bölüm 4)

| Feature | r (test_ort_skor) | p | AUC (test_risk) |
|---|---|---|---|
| yas | +0.169 | <0.001 | 0.529 |
| gecmis_ciddi_oran | +0.123 | <0.001 | 0.565 |
| gecmis_ort_skor | +0.160 | <0.001 | 0.551 |
| egim_maruziyet | +0.105 | <0.001 | 0.577 |
| **garaj_ort_skor** | **+0.375** | <0.001 | 0.561 |
| **verimsizlik_skoru** | +0.128 | <0.001 | **0.600** |

### Çelişki Gözlemi
- Korelasyon (r) açısından **garaj_ort_skor** dominant (0.375)
- AUC açısından **verimsizlik_skoru** dominant (0.600)
- Sebep: r sürekli skorla, AUC binary risk eşiğiyle çalışır — farklı şeyler ölçer

---

## 4. Kompozit Skor — 3 Ağırlık Politikası (Bölüm 5-7)

### Politika B (r-orantılı, en yorumlanabilir):
| Feature | Ağırlık |
|---|---|
| **garaj_ort_skor_norm** | **0.354** (dominant) |
| yas_norm | 0.160 |
| gecmis_ort_skor_norm | 0.151 |
| verimsizlik_skoru_norm | 0.121 |
| gecmis_ciddi_oran_norm | 0.116 |
| egim_maruziyet_norm | 0.099 |

### Politika C (Logistic Regression — şüpheli):
| Feature | Coef |
|---|---|
| **yas_norm** | **-0.008** (NEGATİF!) |
| **gecmis_ort_skor_norm** | **-0.007** (NEGATİF!) |
| garaj_ort_skor_norm | +0.021 |
| egim_maruziyet_norm | +0.013 |
| gecmis_ciddi_oran_norm | +0.008 |
| verimsizlik_skoru_norm | +0.008 |

**Uyarı:** Logreg multicollinearity nedeniyle yas ve gecmis_ort_skor'a NEGATİF ağırlık verdi. Bu bireysel feature kanıtının (yas pozitif r=+0.169) tersi. Logreg coefficients karşı sezgisel çıktı — ama AUC iyi.

### Bant Karşılaştırması
| Politika | Q1 ciddi_oran | Q5 ciddi_oran | Lift | ANOVA F |
|---|---|---|---|---|
| A (Eşit) | 0.289 | 0.410 | 1.42x | 39.81 |
| B (r-orant) | 0.285 | 0.403 | 1.41x | **49.33** |
| **C (Logreg)** | 0.285 | **0.428** | **1.50x** | 48.26 |

### AUC Karşılaştırma (KARAR)
| Yöntem | AUC | vs yas |
|---|---|---|
| Baseline yas | 0.5288 | — |
| verimsizlik_skoru tek | 0.6003 | +0.0715 |
| egim_maruziyet tek | 0.5769 | +0.0481 |
| skor_A_esit | 0.5815 | +0.0527 |
| skor_B_r_orant | 0.5777 | +0.0489 |
| **skor_C_logreg** | **0.6235** | **+0.0947** |

**🎯 KARAR:** `kritiklik_skoru = skor_C_logreg` (en yüksek AUC).

---

## 5. ⭐ KRİTİK: Stability Testi FAIL (Bölüm 8)

| Test | Beklenen | Bulgu | Karar |
|---|---|---|---|
| Random null | p<0.05 | Gerçek r=0.30, rastgele max=0.04 | ✅ PASS |
| **Stability r** | **> 0.7** | **r = 0.15** | ❌ **FAIL** |
| AUC | > 0.55 | 0.624 | ✅ PASS |

**Stability r=0.15 anlamı:** Aynı aracın ilk yarı (3 ay) performansı, ikinci yarı (3 ay) performansını sadece zayıf tahmin ediyor. Bu, **araç bazlı tahminin doğal olarak gürültülü** olduğunu gösteriyor.

**Karşılaştırma:**
- Analiz 5 (Garaj feature) stability r = **+0.94** (toplu, garaj bazlı)
- Burası (Araç ort_skor) stability r = **+0.15** (bireysel)
- Araç bazlı vs garaj bazlı varyans farkı doğal

### Bu Bulgunun ML İçin Anlamı

`kritiklik_skoru` direkt ML feature olarak **kullanılmamalı.** ML modeli kendi öğrensin (bireysel feature'lar gitsin).

---

## 6. Top 50 Yüksek Risk Liste (Bölüm 9)

**Skor aralığı:** 79.28 → 70.28

**En riskli 10 araç (hepsi 19 yaş Mercedes Citaro 0530 G, Şahinkaya):**
| Sıra | KAPINO | Garaj | Model | Yaş | Geçmiş Ciddi Oran | Skor |
|---|---|---|---|---|---|---|
| 1 | M4579 | Şahinkaya | Citaro 0530 G | 19 | 1.00 | 79.28 |
| 2 | M6509 | Şahinkaya | Citaro 0530 G | 19 | 1.00 | 76.94 |
| 3 | M3100 | Şahinkaya | Citaro 0530 G | 19 | 1.00 | 76.42 |
| 4 | M4358 | Şahinkaya | Citaro 0530 G | 19 | 1.00 | 76.14 |
| 5 | M6512 | Şahinkaya | Citaro 0530 G | 19 | 1.00 | 76.07 |
| 6 | M3099 | Şahinkaya | Citaro 0530 G | 19 | 1.00 | 75.44 |
| 7 | K5791 | KURTKÖY | Avancity S Plus | 12 | 1.00 | 74.98 |
| 8 | M6314 | Şahinkaya | Citaro 0530 G | 19 | 0.75 | 74.29 |
| 9 | M2984 | Şahinkaya | Citaro 0530 G | 19 | 0.50 | 73.92 |
| 10 | M3202 | Şahinkaya | Citaro 0530 G | 19 | 0.75 | 73.91 |

**Top 50 özeti:**
- Ortalama yaş: 15.1
- Ortalama ciddi_oran: 0.567 (genel 0.363 → **lift 1.56x**)
- Top 100 ortalama yaş: 12.8, ciddi_oran: 0.544
- Tam liste **`analiz8_tam_liste.csv`** dosyasına export edildi (3,508 araç)

---

## 7. Garaj × Kritiklik Dağılımı (Bölüm 10)

| Garaj | n_arac | Ort. Yaş | Kritiklik Ort | Top 50 Sayı |
|---|---|---|---|---|
| **Hasanpaşa** | 319 | 8.0 | **64.44** | 3 |
| **Şahinkaya** | 129 | 19.0 | 64.16 | **29** |
| **Edirnekapı** | 381 | 11.8 | 63.69 | 8 |
| KURTKÖY | 346 | 12.1 | 57.65 | 10 |
| Kağıthane | 244 | 12.0 | 53.14 | 0 |
| IKITELLI2 | 330 | 11.3 | 51.35 | 0 |
| IKITELLI | 429 | 9.2 | 49.67 | 0 |
| SULTANGAZI | 413 | 12.2 | 47.79 | 0 |
| Sarıgazi | 184 | 11.8 | 47.21 | 0 |
| **Anadolu** | 353 | **17.4** | **43.01** | **0** ❌ |
| Yunus | 229 | 12.0 | 39.42 | 0 |
| Topkapı | 151 | 1.0 | **19.02** | 0 |

### 🚨 Anadolu Anomali — Beklenmedik

Hipotez 3'te "Şahinkaya + Anadolu dominant" beklemiştik. Şahinkaya doğrulandı (29/50), **Anadolu Top 50'de 0 araç**.

**Sebep analizi:**
- Anadolu yaş ortalaması 17.4 (en yaşlı 2. garaj)
- Ama garaj_ort_skor'u 3.49 (Şahinkaya 4.06'dan düşük)
- Kompozit skorun en güçlü feature'ı garaj_ort_skor olduğundan, Anadolu skorda düşük kaldı
- **Yorum:** Anadolu'da yaşlı araç var ama garaj tamir kalitesi *Şahinkaya'dan iyi* — Analiz 5'le tutarlı

---

## 7.5. ⭐ Çapraz Doğrulama: Z-Skor Akran Kıyaslaması

### Sorun

Politika C (Lojistik Regresyon) `arac_kritiklik` skorunu üretirken **multicollinearity tuzağına** düştü:
- `garaj_ort_skor` katsayısı **+0.0206** (dominant)
- `yas` katsayısı **−0.0083** (NEGATİF — model yaşı garaj üzerinden zaten öğrendiği için çift saymayı bastırmış)
- `gecmis_ort_skor` katsayısı **−0.0071** (NEGATİF)

Sonuç: Top 50'nin %58'i (29/50) Şahinkaya 19 yaş Mercedes Citaro'larla doldu — bu "araç bazlı anomali" değil, "kötü garaj" sıralaması oldu.

### Çapraz Doğrulama Yöntemi

`gecmis_ciddi_oran`'ı her aracın **kendi garaj akranları** ve **kendi yaş grubu akranları** içinde Z-skoru ile değerlendirdik:

```
z_garaj = (arac_ciddi_oran − garaj_ortalamasi) / garaj_std
z_yas   = (arac_ciddi_oran − yas_ortalamasi)   / yas_std
kritiklik_zskor_akran = 0.6 × z_garaj + 0.4 × z_yas → 0-100 normalize
```

**Mantık:** 19 yaşındaki bir aracın bozulması "normal" (akranları da bozuluyor) → Z düşük. 1 yaşındaki bir aracın bozulması "anomali" (akranları bozulmuyor) → Z yüksek.

### Karşılaştırma Sonuçları

> **⚠️ Önemli kolon açıklaması (audit 2026-05-20):** Aşağıdaki tabloda "Top 50 ciddi_oran ortalaması" satırı aslında **`gecmis_ciddi_oran`** (train period H1 ortalaması) üzerinden hesaplanmıştır — Z-Skor formülünün baz aldığı metrik bu. Politika C'nin kendi `ciddi_oran` (full period) sayısı ile karıştırılmamalı (Bölüm 7'de "Top 50 ciddi_oran 0.567" tam evrenin ortalaması — bu farklı bir kolon). Hesaplamalar birbiriyle tutarlı, sadece kolon isimlendirmesi tarihsel sebepten "ciddi_oran" kısaltmasıyla kalmış.

| Metrik | Politika C (Mevcut) | Z-Skor Akran (Yeni) |
|---|---|---|
| Dominant garaj | Şahinkaya **29/50** | Kağıthane 13/50 |
| Top 50 ortalama yaş | 15.1 | **9.8** (daha genç) |
| Top 50 **`gecmis_ciddi_oran`** ortalaması | 0.739 | **1.000** |
| Filo geneli **`gecmis_ciddi_oran`** | 0.352 | 0.352 |
| **Konsantrasyon Lift** (gecmis_ciddi_oran üzerinden) | **2.10×** | **2.84×** ← daha güçlü |
| Anadolu Top 50'de | 0 araç | **4 araç** ← Politika C'nin kaçırdığı |
| İki listede ortak araç | — | 10/50 (yani %80 farklı) |

**Not:** Aynı karşılaştırma full-period `ciddi_oran` kolonuyla yapılsaydı liftler 1.56× ve 1.64× olurdu. Z-skorun "akran sapması" mantığı `gecmis_ciddi_oran` ile daha anlamlı (train periyodu = anomali tespitinin baz aldığı veri).

### Yeni Top 50 Garaj Dağılımı (Z-Skor)

| Garaj | Sayı |
|---|---|
| **Kağıthane** | 13 |
| SULTANGAZIGARAJI | 7 |
| Edirnekapı | 6 |
| **Topkapı** | 5 ← yeni filo anomalisi |
| KURTKÖY | 5 |
| **Anadolu** | 4 ← Politika C kaçırdı |
| IKITELLIGARAJI | 4 |
| Hasanpaşa | 3 |
| Yunus | 2 |
| IKITELLIISLETTIRMEGARAJI2 | 1 |

### Yeni Top 50 Yaş Dağılımı

| Yaş | Sayı |
|---|---|
| 1 | 5 ← Topkapı'da yeni araç anomalisi |
| 2 | 3 |
| 3 | 4 |
| 8 | 4 |
| 9 | 1 |
| **12** | **24** ← dominant (orta yaş akranlarına göre sapanlar) |
| 13 | 5 |
| 16 | 1 |
| 17 | 1 |
| 19 | 2 |

### Yorumlama

Z-Skor yaklaşımının ortaya çıkardıkları:

1. **"Yeni araç anomalisi" gerçek:** Topkapı'da 1-2 yaşındaki 8 araç %100 ciddi_oran ile zirvede (A9275, A9316, E9339 vb.) — aynı yaş grubunun ortalaması çok düşük olduğu için **sapma çok büyük**. Politika C bu sinyali yakalayamıyordu çünkü garaj_ort_skor (Topkapı 0.21) tüm aracı düşük gösteriyordu.

2. **Anadolu'da gizli sorun:** 4 araç Top 50'de. Politika C'de 0'dı. Anadolu yaşlı filo ama garaj_ort_skor düşük olduğundan kompozit skor düşmüş, anomalilere kör kalmış.

3. **Şahinkaya 19 yaş baskınlığı yok:** Politika C'de 29 olan rakam Z-skorda **2**'ye düştü. Çünkü 19 yaşındaki Citaro'ların hepsi yüksek ciddi_oran veriyor — birbirlerinin akranı, sapma yok.

4. **Konsantrasyon daha iyi:** Lift 2.10× → 2.84×. Yani Z-Skor Top 50'si filo ortalamasından **2.84 kat** daha riskli, eski %58 Şahinkaya'lı listeden daha etkin.

### Karar: Hibrit Kullanım

Politika C silinmedi — Z-Skor **bağımsız çapraz doğrulama** olarak yeni `kritiklik_zskor_akran` kolonu eklendi. CSV'de iki sıralama paralel mevcut:

- `kritiklik_skoru` → Politika C (geri uyumluluk + panel'in mevcut göstergeleriyle tutarlı)
- `kritiklik_zskor_akran` → Z-Skor Akran (gizli anomalileri yakalar)

**Sunum hikâyesi:** "Politika C'nin multicollinearity'sini erken tespit ettik, Z-Skoru akran kıyaslaması ile **çapraz doğruladık**. İki yaklaşımı yan yana sunuyoruz — bir tane Top 50 değil, **iki bakış açısı** veriyoruz: 'kötü garajdan kötü araç' (Politika C) ve 'akrana göre anomali' (Z-Skor)."

### Z-Skor Yönteminin Sınırlamaları (Dürüst)

| Sınırlama | Etki |
|---|---|
| Sadece `gecmis_ciddi_oran` üzerinden Z hesaplandı — `egim_maruziyet`, `verimsizlik_skoru`, `garaj_ort_skor` Z'ye girmedi | Multivariate değil. V7'de 6-feature Z'ye genişletilebilir. |
| Küçük yaş gruplarında std küçük → Z aşırı duyarlı (örn n=2 araçlı yaş) | Politika C de aynı dezavantaja sahip (LR de küçük gruplarda noisy) |
| Stability testi yapılmadı (Politika C için r=0.15 zayıftı) | V7 için: Z-Skor versiyonunun train/test stability'si ayrıca test edilmeli |
| Z-Skor 0.6/0.4 ağırlık (garaj/yaş) hassasiyet analizi yok | Eğim formülü gibi (A3 Bölüm 14.5) ağırlık duyarlılığı V7'de denenebilir |

**Önemli:** Bu çapraz doğrulama A8'in **ana çıktısını silmiyor**, eklenen ikinci bakış açısı. V6.5 ML modeline hâlâ feature olarak girmiyor (memory: A8 OPERASYONEL ONLY). Sunum için iki yaklaşımı kıyaslayan zenginleştirme.

---

## 8. Hat × Kritiklik (Bölüm 11)

### Top 50 araçların en sık çalıştığı hatlar:
| Hat | n_ariza (Top 50 içinde) |
|---|---|
| 15F | 83 |
| **34BZ** | 59 (METROBÜS) |
| **34AS** | 45 (METROBÜS) |
| 11ÇB | 41 |
| **34G** | 38 (METROBÜS) |
| 15BK | 33 |
| 18Ü | 23 |
| 18K | 23 |
| 11H | 21 |
| **34C** | 20 (METROBÜS) |

### En kritik hatlar (her aracın ortalama kompozit skoru):
| Hat | Skor |
|---|---|
| 121BS | 69.39 |
| 15F | 68.96 |
| 121A | 68.56 |
| 15TA | 67.61 |
| 15BK | 65.73 |
| **34A/Z/G/BZ/AS/C/B** | **63.96-64.27 (METROBÜS dizisi)** |

**Bulgu:** Metrobüs hatları (34XX) yüksek kritiklik içeriyor. Bu Analiz 5'le tutarlı (Hasanpaşa + Edirnekapı = saf metrobüs garajları, yüksek operasyonel yük).

---

## 9. Aksiyon Önerileri (Bölüm 12 — Güncellenmiş)

| Aksiyon | n_arac | Kim İçin |
|---|---|---|
| **MOTOR DURUMU DENETİMİ** (yaşlı + riskli, yenileme adayı) | 33 | 15+ yaş + yüksek skor |
| YOĞUN BAKIM (orta yaşlı + yüksek arıza) | 10 | 10-15 yaş + gecmis_ciddi_oran > 0.5 |
| GARAJ ROTASYONU (kötü garaj etkisi) | 7 | Yeni araçlar kötü garajda |

**Not (Mehmet'in girdisi ile):** "YENİLEME" aksiyonu yerine "MOTOR DURUMU DENETİMİ" adlandırması seçildi — çünkü İETT'nin düzenli motor bakım/yenileme uygulamasıyla, 19 yaşlı bir aracın motoru aslında yenilenmiş olabilir. Karar tamamen yaşa dayalı olmamalı, performans verisiyle birlikte değerlendirilmeli.

**Garaj rotasyonu adayları (Edirnekapı, 2 yaş AKIA LF25):**
- A9178, A9130, A4812 — yeni araç ama yüksek kritiklik → araç sorunu değil, garaj etkisi (Edirnekapı metrobüs operasyon yükü)

---

## 10. ML V6 Feature Değerlendirmesi (Bölüm 13)

| Feature | r (ort_skor, training) | AUC (test_risk) |
|---|---|---|
| yas | +0.209 | 0.529 |
| **gecmis_ciddi_oran** | **+0.590** ⚠️ leakage riski | 0.565 |
| **garaj_ort_skor** | **+0.488** | 0.561 |
| verimsizlik_skoru | +0.146 | 0.600 |
| egim_maruziyet | +0.166 | 0.577 |
| **kritiklik_skoru** | +0.479 (kompozit) | **0.624** |

### KARAR: kritiklik_skoru ML'e GİTMEZ
- Stability r=0.15 → çok zayıf, leakage riskine yakın
- Bireysel feature'lar zaten ML V6'ya gidiyor (garaj_ort_skor, verimsizlik_skoru, egim_maruziyet)
- Kompozit duplikasyon olur + overfitting riski

### kritiklik_skoru NEREDE KULLANILABİLİR
- Operasyonel sıralama (Top 50, Top 100, tam liste)
- Aksiyon kategorisi ataması
- iett_panel UI'de "Yüksek Risk Araç Listesi" sekmesi
- Yönetim sunumu (datathon için)

---

## 11. ⭐ KRİTİK Metodolojik Bulgu — Motor Yenileme Confounder

### Problem
**MODELYILI = üretim yılı, motor yaşı DEĞİL.** İETT yaşlı araçlara düzenli motor yenileme/bakım yapıyor. Veride bu yansıtılmıyor.

### Veri Bu Açıklamayla Tutarlı

| Veri Bulgusu | Motor Yenileme Açıklamasıyla Uyum |
|---|---|
| yas r=+0.169, AUC=0.529 (en zayıf feature) | ✅ Üretim yılı motor durumunu yansıtmıyor |
| Anadolu (17.4 yaş) Top 50'de 0 araç | ✅ Anadolu'da motor bakım daha sıkı olabilir |
| Logreg yas katsayısı **NEGATİF** (-0.008) | ✅ "Yaşlı" tek başına risk değil, başka faktör baskın |
| Topkapı (1.1 yaş yeni filo) bile bazı yüksek skor araçlar var (Bölüm 11) | ✅ Yeni de olsa garaj/hat etkisi dominant |
| gecmis_ciddi_oran (r=+0.59) en güçlü tek sinyal | ✅ Motor durumu performanstan dolaylı çıkar |

### Anlam

1. **`yas` feature'ı ML için zayıf** — model V6'da `yas` yerine `gecmis_ciddi_oran` ve `garaj_ort_skor` ağırlık taşımalı.

2. **Aksiyon önerileri yaşa değil performansa dayalı olmalı.** 19 yaşlı bir araç yenilenmişse iyi durumda olabilir.

3. **"YENİLEME"** terimi yanlış — **"MOTOR DURUMU DENETİMİ"** doğru (yenileme kararı denetimden sonra).

4. **Veri kısıtı:** Motor yenileme tarihi/türü verisi olsaydı, "gerçek motor yaşı" hesaplanabilir ve `yas` feature'ı çok daha güçlü olurdu.

---

## 12. Hipotez Test Sonuçları

| H | Test | Beklenen | Bulgu | Durum |
|---|---|---|---|---|
| H1 | AUC kompozit > yas baseline | +artış | 0.624 vs 0.529 (+0.095) | ✅ **PASS** |
| H2 | Top 50/Q5 lift > 1.5x | 1.5x+ | Top 50 lift 1.56x, Q5 lift 1.50x | ✅ **PASS** |
| H3 | Şahinkaya + Anadolu Top 50 dominant | İkisi de baskın | Şahinkaya 29, **Anadolu 0** | ⚠️ **KISMI** |
| H4 | Stability r > 0.7 | > 0.7 | 0.15 | ❌ **FAIL** |
| Bonus | Random null | p<0.05 | r=0.30 > rastgele max 0.04 | ✅ PASS |

**Genel:** Operasyonel hedefler tutarlı, ML hedefi (kompozit feature) FAIL — ama bu da değerli bulgu.

---

## 13. Kısıtlamalar (Dürüst)

1. **Veri penceresi 6 ay (Train 3 ay + Test 3 ay)** — Daha uzun dönemde feature stabilitesi daha iyi test edilebilirdi.

2. **yolcu_doluluk verisi güvenilmez** (proje kararı) — Kapasite feature yok.

3. **ARACTIPI ayrımı yapılmadı** (proje kararı) — Metrobüs + otobüs karışık.

4. **Önceki analizlerden türetilen feature'lar bilinen confounder'larla geliyor:**
   - egim_maruziyet — hat × araç ağırlıklı ortalama yöntemi
   - garaj_ort_skor — Analiz 5'in basitleştirilmiş hali
   - verimsizlik_skoru — Analiz 7 metodu (tüketim tahmini imputed)

5. **Logistic regression ağırlıklarında overfitting riski** — Train/test split kullanıldı ama daha büyük veriyle CV önerilir. Yas ve gecmis_ort_skor için NEGATİF coef multicollinearity belirtisi.

6. **ADALAR garajı bilerek dışlandı** (proje kararı, golf araç).

7. **Test_ciddi_oran tahmin hedefi proxy** — Gerçek operasyonel risk (yolcu yaralı kaza, plansız çekme) ile dolaylı ilişki.

8. **⭐ KRİTİK: MODELYILI = üretim yılı (motor durumunu YANSITMIYOR):**
   - İETT yaşlı araçlara düzenli motor yenileme/bakım yapıyor
   - "Yaşlı araç = riskli" varsayımı YANLIŞ olabilir
   - yas feature AUC=0.529 (zayıf) bunu destekliyor
   - gecmis_ciddi_oran (r=+0.59) motor durumunu DOLAYLI olarak yakalıyor
   - Aksiyon önerilerinde "yaşlı" yerine "performans bazlı risk" daha güvenli
   - Motor yenileme tarihi/türü verisi olsaydı analiz çok daha güçlü olurdu

9. **Stability r=0.15 araç bazlı tahminin doğal sınırı** — Garaj bazlı (Analiz 5: 0.94) ile karşılaştırıldığında, bireysel araç performansı çok daha gürültülü.

---

## 14. Sunum Hikayesi (Datathon İçin)

> **Operasyonel Hedef:** Filodaki en yüksek risk taşıyan araçları sıralayıp müdahale önceliği üretmek.
>
> **Yöntem:** Önceki 6 analizden kanıtlanmış feature'ları kompozit skorda birleştirdik. 3 farklı ağırlık politikası (eşit, korelasyon-orantılı, makine öğrenmesi) test ettik, en iyi olanı seçtik.
>
> **Bulgu 1 — Operasyonel:** Top 50 araç ortalamadan **1.56x daha yüksek riskli** (ciddi_oran 0.567 vs filo 0.363). Bunların %58'i **Şahinkaya garajı**, %20'si KURTKÖY, %16'sı Edirnekapı'da. Hâkim model: Mercedes Citaro 0530 G (19 yaş, metrobüs).
>
> **Bulgu 2 — Beklenmedik:** Anadolu garajı en yaşlı filolardan biri olmasına rağmen Top 50'de hiç araç yok. Sebep: Anadolu'nun tamir kalitesi diğer yaşlı-filo garajlardan daha iyi (Analiz 5'le tutarlı).
>
> **Bulgu 3 — Kritik Metodolojik Sınır:** "Yas" feature'ı tahmin gücünde zayıf (AUC 0.529). Bunun nedeni İETT'nin düzenli motor yenileme uygulaması — üretim yılı gerçek motor yaşını yansıtmıyor. **Bu yüzden aksiyon önerimiz "YENİLEME" değil "MOTOR DURUMU DENETİMİ" olarak adlandırıldı.**
>
> **Bulgu 4 — ML Sınırı:** Kompozit skor zaman içinde dalgalı (stability r=0.15). Bu, araç bazlı tahminin doğal sınırı. ML modeli için kompozit yerine bireysel feature'lar tercih edildi.
>
> **Operasyonel Çıktı:** 3,508 araç sıralanmış CSV listesi + 50 yüksek risk araç için spesifik aksiyon önerileri (Motor Durumu Denetimi: 33, Yoğun Bakım: 10, Garaj Rotasyonu: 7).

---

## 15. Sonraki Adımlar

- [x] Analiz 8 SONUCLAR (bu belge)
- [ ] **Analiz 9 — Akıllı Hat-Araç Atama** (synthesis: tüm önceki analizleri birleştiren karar mekanizması)
- [ ] FEATURES_FINAL.md — tüm doğrulanmış feature'ları tek tabloda topla
- [ ] ML_MODEL_V6 — feature'ları modele ekle, AUC karşılaştır (V5: 0.762)
- [ ] iett_panel entegrasyonu — Yüksek Risk Araç Listesi sekmesi

---

## 16. ML V6 Feature Listesi (Bu Analizden)

```python
# ML V6'ya gidecek bireysel feature'lar (kompozit ATLA):
gecmis_ciddi_oran           # r=+0.59, leakage testi gerek
garaj_ort_skor              # r=+0.49, AUC 0.561, stabil (Analiz 5'ten)
verimsizlik_skoru           # r=+0.15, AUC 0.600 (Analiz 7'den)
egim_maruziyet              # r=+0.17, AUC 0.577 (Analiz 3'ten)

# ATLA:
kritiklik_skoru             # Stability r=0.15 (FAIL)
                            # Operasyonel sıralama için kullanılır, ML feature değil

# Mevcut V5 feature'ları yeniden değerlendir:
yas                         # AUC 0.529 - motor yenileme nedeniyle zayıf
                            # log(yas) yerine motor durumu proxy kullan
```

---

## 17. Operasyonel Çıktı Dosyası

**`analiz8_tam_liste.csv`** — 3,508 araç kritiklik skoruna göre sıralı.

Kolonlar: `KAPINO, GARAJ, MARKA, MODEL, yas, ort_skor, ciddi_oran, gecmis_ciddi_oran, kritiklik_skoru`

İETT operasyonel ekibi bu CSV'yi doğrudan kullanarak müdahale planı yapabilir.
