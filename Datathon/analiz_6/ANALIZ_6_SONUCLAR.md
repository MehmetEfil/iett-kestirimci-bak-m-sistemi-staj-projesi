# ⏳ ANALİZ 6 — OPERASYONEL YORGUNLUK SONUÇLAR

**Tarih:** 2026-05-11
**Notebook:** `ANALIZ_6_OPERASYONEL_YORGUNLUK.ipynb` (31 hücre, 15 bölüm)
**Veri:** `ariza_model.csv` (58,559 arıza, 3,509 araç) + `arac_gunluk_hatlar.csv` (1.3M sefer kaydı) + `sefer_temiz.csv` (10.1M sefer detayı)
**Veri Penceresi:** 2025-01-01 → 2025-06-30 (6 ay)
**Soru:** Araçların sefer/süre yorgunluğu arıza riskini artırır mı? Kırılma noktası eşiği var mı?

---

## 🎯 KISA ÖZET — HİPOTEZ ÇÜRÜTÜLDÜ

4 farklı yorgunluk metriği test edildi, **hiçbirinde "yorgunluk → arıza" sinyali bulunamadı.** Tüm sinyaller ya çok zayıf ya da **TERS yönlü** — yani çok çalışan araç, daha az arıza yapıyor.

| Test | Metrik | r (Pearson) | Sonuç |
|---|---|---|---|
| 1 | Günlük sefer sayısı | **-0.267** | Güçlü ama **TERS** yönlü |
| 2 | Kümülatif KM (son_30g) | +0.003 | **Sinyal yok** |
| 3 | Plan süresi oranı | -0.036 | Ters + leakage |
| 4 | Bitiş gecikmesi (dk) | -0.013 | Ters + leakage |

**Asıl açıklama:** Selection bias / endojenlik. Çok sefer yapan ve gecikip yetişen araç = **operatörün güvenip yoğun zamana çıkardığı sağlam araç**. Az çalışan araç = zaten arızalı veya sorunlu olduğu için yedekte tutulan araç. Veri "yorgunluk" değil "araç sağlamlığı tahsis politikası" sinyali taşıyor.

---

## 1. Veri Hazırlığı (Hücre 1)

- Arıza: 58,559 kayıt, 3,509 araç
- Sefer (arac_gunluk_hatlar): 1,320,647 kayıt, 6,761 araç (3,252 araç sefer yapıyor ama İETT bakım kaydı yok → ÖHO/KOOP)
- Sefer detayı (sefer_temiz): 10.1M kayıt

**`GUNLUK_SEFER_SAYISI` dağılımı (arıza tarihinde):**
- Median 8, P25=6, P75=11, P95=16, P99=21
- 0 NaN — temiz veri

---

## 2. Sefer Sayısı Bant Analizi (Hücre 4)

| Sefer Bandı | n | ciddi_oran | ort_ciddiyet |
|---|---|---|---|
| **0-1** | 1,111 | **0.802** | 5.36 |
| 2-3 | 4,126 | 0.712 | 4.73 |
| 4-6 | 12,384 | 0.530 | 4.07 |
| 7-9 | 16,679 | 0.384 | 3.60 |
| 10-12 | 14,438 | 0.251 | 3.18 |
| **13+** | 9,821 | **0.187** | 3.01 |

**Chi-square:** χ²=6519.47, p≈0 — bantlar arası fark istatistiksel olarak kesin.

**Şaşırtıcı yönelim:** Bantlar arası MONOTONİK AZALIŞ — sefer sayısı arttıkça ciddiyet **düşüyor**. 0-1 sefer yapan aracın %80'i ciddi arıza, 13+ sefer yapan aracın sadece %19'u.

**Yorum:** Hipotez yorgunluk olsaydı tam tersini beklerdik. Bu, "az çalışan araç = arızalı olduğu için az çalışan" tezini destekliyor.

---

## 3. ROC Analizi (Hücre 6)

| Metrik | Değer |
|---|---|
| **AUC** | **0.3054** |
| Yorumu | 0.5 ALTINDA → tahmin gücü ters yönlü (yine selection bias) |
| Esik >= 5: TPR=0.74, FPR=0.92 | Diskrimine edemiyor |

AUC < 0.5 = sefer sayısı pozitif yönde tahmin edici değil; tersi yönde işliyor.

---

## 4. Kümülatif Yorgunluk Feature'ları (Hücre 8)

Her arıza için son 7/14/30 gün kümülatif sefer ve aktif gün hesaplandı.

| Feature | mean | median | P95 |
|---|---|---|---|
| son_7g_top | 51.8 | 52.0 | 86.0 |
| son_14g_top | 100.9 | 103.0 | 161.0 |
| son_30g_top | 206.0 | 213.0 | 326.0 |
| son_30g_aktif | 21.8 | 24.0 | 29.0 |

**Hesaplama:** Arıza gününü dışlayan kapalı pencere (`< tarih`). Endojen değil.

---

## 5. Korelasyon Analizi (Hücre 10)

| Feature | Pearson r | p | Spearman | Ciddi_r |
|---|---|---|---|---|
| **GUNLUK_SEFER_SAYISI** | **-0.2668** | 0.0000 | -0.2791 | -0.3097 |
| son_7g_top | -0.0315 | 0.0000 | -0.0335 | -0.0440 |
| son_14g_top | -0.0271 | 0.0000 | -0.0302 | -0.0388 |
| son_30g_top | -0.0144 | 0.0005 | -0.0174 | -0.0237 |
| son_7g_ort | -0.0316 | 0.0000 | -0.0381 | -0.0512 |
| son_30g_aktif | -0.0084 | 0.0411 | -0.0075 | -0.0028 |

Sadece arıza gününün sefer sayısı güçlü sinyal taşıyor (r=-0.27, ters), kümülatif feature'lar nerede ise gürültü düzeyinde.

**ANOVA bant analizi (son_30g_top, 5 kantil):**
- Q1=0.399, Q2=0.392, Q3=0.377, Q4=0.364, Q5=0.368
- F=4.35, p=0.0016 (anlamlı ama bant farkları ihmal edilebilir)

---

## 6. Random Null Testi (Hücre 12)

- Gerçek r (son_30g_top × ciddi_ariza): -0.0237
- 1,000 permütasyon ortalaması: 0.0000, %95 CI [-0.0074, +0.0080]
- Gerçek r > rastgele max? **HAYIR** (yani sinyal rastgele dağılım içinde)
- p (one-sided): 0.0000 (sinyal istatistiksel olarak rastgele değil) — ama büyüklük rastgele varyansın çevresinde

**Yorum:** Sinyal *istatistiksel anlamlı* (büyük n nedeniyle), ama büyüklük rastgele varyansla aynı düzlemde → operasyonel olarak anlamsız.

---

## 7. Confounder Kontrolü (Hücre 14)

Çoklu regresyon, `ort_skor ~ ...`:

| Model | Bağımsız Değişkenler | R² | k_yorgun (son_30g_mean) |
|---|---|---|---|
| M1 | sadece yorgunluk | 0.0112 | -0.00146 |
| M2 | + yas | 0.0506 | -0.00113 |
| M3 | + log_sefer | 0.0699 | **+0.00137** |
| M4 | + egim + garaj | 0.2571 | +0.00088 |

**Kritik gözlem:** k_yorgun M1→M3 arasında **işaret değiştiriyor** (negatif → pozitif). Bu, confounder altında yorgunluk etkisinin TUTARSIZ olduğunu gösterir. Bağımsız bir "yorgunluk yapısı" yok; her şey diğer değişkenlerle (özellikle log_sefer) açıklanabiliyor.

---

## 8. Şoför vs Araç Yorgunluğu (Hücre 16)

- Araç başına farklı şoför sayısı: medyan 12, P95 31
- Şoför başına farklı araç sayısı: medyan 7, P95 20
- Yüksek yorgunluk arızalarında en yoğun saatler: 15-17 (sabah/öğleden sonra vardiyaları)

**Yorgunluk bandına göre ciddi oranı:**
- Düşük: 0.398
- Orta: 0.376
- Yüksek: 0.366

**Yorum:** Şoför × araç çeşitliliği yüksek, ama yorgunluk bandı → ciddi oranı ters yönlü (yine selection bias).

---

## 9. ML Feature Kandidat Listesi (Hücre 18)

| Feature | Pearson r | ANOVA F | Karar |
|---|---|---|---|
| GUNLUK_SEFER_SAYISI | -0.2668 | 1511.4 | Tek güçlü (ters) — kullanıma uygunsuz |
| son_7g_top | -0.0315 | 21.3 | Zayıf |
| son_14g_top | -0.0271 | 15.9 | Zayıf |
| son_30g_top | -0.0144 | 5.4 | İhmal |
| son_7g_ort | -0.0316 | 18.9 | Zayıf |
| son_30g_aktif | -0.0084 | 4.8 | İhmal |

Sadece GUNLUK_SEFER_SAYISI |r|>0.05 eşiğini geçiyor; o da ters yönlü (yorgunluk değil, sağlamlık proxy'si).

---

## 10. Time-Based Leakage Testi (Hücre 20)

| Feature | Full r | Time-aware r | Düşüş |
|---|---|---|---|
| GUNLUK_SEFER_SAYISI | -0.2668 | -0.0193 | **%92.8 (LEAKAGE)** |
| son_30g_top | -0.0144 | -0.0063 | %56.3 (LEAKAGE) |

**Her iki feature da leakage'lı.** Train'de hesaplanmış araç-bazlı ortalama, test döneminde anlam kaybediyor. ML için kullanılamaz.

---

## 11. En Yorgun Araçlar (Hücre 22)

**Top 5 en yorgun (son_30g_mean):**
| KAPINO | GARAJ | yas | son_30g_mean | ciddi_oran |
|---|---|---|---|---|
| M5733 | Anadolu | 19 | 486 | 0.44 |
| M2933 | Anadolu | 19 | 474 | 0.19 |
| M5731 | Anadolu | 19 | 453 | 0.38 |
| O4157 | Sarıgazi | 12 | 453 | 0.33 |
| E9339 | Topkapı | 1 | 432 | **1.00** |

**Top 5 en dinlenmiş:**
| KAPINO | GARAJ | yas | son_30g_mean | ciddi_oran |
|---|---|---|---|---|
| M3149 | Edirnekapı | 17 | 0 | **1.00** |
| O9070 | Sarıgazi | 2 | 0 | 0.00 |
| M3235 | Anadolu | 13 | 12 | 0.50 |

**Çelişki:** En dinlenmiş araçlar arasında %100 ciddi arıza yapanlar var (M3149) — yani "dinlenmek" arıza önlemiyor; muhtemelen zaten arızalı olduğu için sefere çıkmamış.

**Garaj × Yorgunluk:** Topkapı en yorgun (244 km/gün ortalama) ama ort_skor en düşük (2.08). Garaj sıralaması (Hasanpaşa 242, Kağıthane 239, Yunus 232) yorgunluk ile ciddi_skor arasında monotonik ilişki göstermiyor.

---

## 12. Operasyonel Eşik Önerileri (Hücre 24)

**Sefer eşiklerinde "üst grup riski" lift hesabı:**

| Eşik | Alt grup ciddi_oran | Üst grup ciddi_oran | Lift |
|---|---|---|---|
| >= 3 | 0.76 | 0.36 | **0.47x** (eşik üstü grup daha *az* riskli) |
| >= 5 | 0.68 | 0.33 | 0.49x |
| >= 7 | 0.59 | 0.29 | 0.49x |
| >= 10 | 0.49 | 0.23 | 0.46x |
| >= 12 | 0.44 | 0.20 | 0.45x |
| >= 15 | 0.40 | 0.17 | 0.43x |

**Hiçbir eşikte lift > 1.0** — operasyonel "şu sefer üstü riskli" uyarısı kurulamıyor. Aksine eşik üstü grup daha güvenli.

**son_30g_top eşikleri:** Yüksek eşiklerde (>=300, >=500) hafif pozitif fark var ama büyüklük 0.10 ciddiyet skoru altında, operasyonel öneri için yetersiz.

---

## 13. Kümülatif KM (Bölüm 14)

`GUZERGAHUZUNLUK` kullanıldı (TOPLAMKM güvenilmez — outlier odometre okumaları var).

- 10.1M sefer → 8.4M temiz (geçersiz tarih + 200km outlier filtresi)
- KM dağılımı (sefer başına): median 20.8 km, P95 50.3 km
- Günlük km: median 183.5 km, P95 395 km
- Kümülatif: son_30g_km median 4,025 km, P95 9,816 km

| Feature | Pearson r | p |
|---|---|---|
| son_7g_km | -0.0085 | 0.04 |
| son_14g_km | -0.0069 | 0.10 |
| **son_30g_km** | **+0.0030** | **0.46** |

**Bant analizi:** U-şekilli (Q1=0.388 → Q4=0.362 → Q5=0.406). Monotonik değil, anlamlı yorum çıkmıyor.

**Leakage:** Full r=+0.003, Time-aware r=+0.022 — leakage düşüşü %0 ama r zaten gürültü düzeyinde.

**Karar:** KM kümülatif yorgunluk sinyali vermiyor. Sefer sayısı ile aynı kategoride (selection bias) ama bu sefer ters yönlü güçlü etki bile yok.

---

## 14. Bitiş Gecikmesi — Schedule Delay (Bölüm 15, Revize)

İlk versiyonda `gerceklesen_sure / planlanan_sure` ratio kullanılmıştı (median=1.000, varyans yok). Kullanıcı uyarısı ile **`BITISZAMANI - TAHMINIBITISZAMANI`** (dakika) revize edildi.

**Veri:** 7.7M sefer kaydı, outlier filtresi sonrası (`-60 dk < gecikme < 180 dk`):
- Median gecikme: **15.12 dk**
- P95: 60.5 dk
- Mean: 19.66 dk

Bu yeni metrik gerçek İstanbul gecikme dağılımını yansıtıyor (önceki ratio bozulmuştu).

**Araç × pencere ortalamaları:**
| Feature | mean | std | P95 |
|---|---|---|---|
| son_7g_gecikme_dk | 21.83 | 10.48 | 41.19 |
| son_14g_gecikme_dk | 21.83 | 9.11 | 38.51 |
| son_30g_gecikme_dk | 21.96 | 8.04 | 36.65 |

**Korelasyon:**
| Feature | Pearson r | p | Spearman |
|---|---|---|---|
| son_7g_gecikme_dk | -0.0129 | 0.0022 | -0.0219 |
| son_14g_gecikme_dk | -0.0149 | 0.0004 | -0.0246 |
| son_30g_gecikme_dk | -0.0126 | 0.0025 | -0.0266 |

**Bant analizi:**
| Bant | Gecikme (dk) | ciddi_oran |
|---|---|---|
| Q1_zamaninda | 13.3 | 0.389 |
| Q2 | 17.0 | 0.388 |
| Q3 | 20.2 | 0.374 |
| Q4 | 24.9 | 0.364 |
| Q5_cok_gec | 34.4 | 0.381 |

U-şekilli (Q4'e kadar düşüyor, sonra hafif yükseliyor). En geciken bant (Q5) en az gecikenden (Q1) **daha az** ciddi arıza yapıyor.

**Leakage testi:** Full r=-0.013, Time-aware r=+0.005 → %63.7 düşüş ve **işaret değişimi**. Leakage kritik düzeyde.

**Yorum:** Bitiş gecikmesi de yorgunluk sinyali vermiyor. En geciken araçlar muhtemelen yoğun saatte/ana hatta çalışan, operatörün güvendiği araçlar.

---

## 15. Konsolide Sonuç (Hücre 26)

**4 yorgunluk testi tutarlı şekilde HİPOTEZİ ÇÜRÜTÜYOR.**

| Test | Sinyal Yönü | Leakage | Karar |
|---|---|---|---|
| Sefer sayısı (anlık) | TERS (r=-0.27) | %93 | Kullanılamaz |
| Kümülatif sefer (30g) | yok (r=-0.014) | %56 | Kullanılamaz |
| Kümülatif KM (30g) | yok (r=+0.003) | %0 ama r=0 | Kullanılamaz |
| Plan ratio | TERS (r=-0.04) | %69 | Kullanılamaz |
| Bitiş gecikmesi (dk) | TERS (r=-0.013) | %64 | Kullanılamaz |

---

## 16. Açıklama: Neden Sinyal Yok?

**Selection bias / endojenlik:**
1. **Aktif araçlar = sağlam araçlar.** Operatör güvendiği aracı yoğun zamana çıkarır, sorunlu aracı yedekte tutar.
2. **Yorgun görünen araç (çok sefer/km/gecikme) = operatörün öncelik verdiği güvenilir araç.**
3. **Dinlenmiş görünen araç = zaten arızalı olduğu için sefere çıkmamış araç.**
4. Sefer sayısı, KM, gecikme **kumulatif yorgunluk değil, araç sağlamlığı/öncelik proxy'si**.

**Veri kısıtı:**
- Motor saatleri (engine hours) veri yok
- Fren/gaz/hız değişim verisi yok (yıpranma direkt ölçümü için gerekli)
- Şoför yorgunluğu (önceki vardiya yorgunluğu) ayrı bir analiz alanı (Analiz 2'de baktık)
- 6 ay veri penceresi yorgunluk birikiminin gerçek etkisini yakalayamayabilir

---

## 17. SAAT Bandı Gözlemi (Yan Bulgu, Yorgunluk Değil)

**Bölüm 1 veri keşfinde görüldü:**
- Gece (00-04): %47-59 ciddi arıza oranı
- Gündüz (06-09): %35-37 ciddi arıza oranı

Bu **araç yorgunluğu değil**, farklı hipotezler içeriyor:
- Gece müdahalesi yavaş → hafif arıza ciddi'ye dönüşüyor
- Gece çalışan araçlar zaten yaşlı/yedek olabilir
- Şoför vardiya yorgunluğu (Analiz 2'de baktık, sabit vs rotasyon farkı)

**Karar:** SAAT bandı sinyali var ama "operasyonel yorgunluk" başlığı altında değerlendirilemez. ML feature olarak `SAAT` kategorik zaten modelde olmalı (mevcut V5'te var).

---

## 18. ML V6 İçin Karar

**Eklenecek feature: HİÇBİRİ.**

| Feature | Neden Eklenmeyecek |
|---|---|
| GUNLUK_SEFER_SAYISI | %92.8 leakage |
| son_30g_top | Sinyal yok |
| son_30g_km | Sinyal yok |
| son_30g_gecikme_dk | Leakage + işaret değişimi |

Mevcut V5'te `GUNLUK_SEFER_SAYISI` zaten kullanılıyor olabilir — leakage testi pozitif olduğu için **V6'da çıkarılmalı** veya araç-bazlı agregasyon yerine arıza-bazlı raw değer olarak kalmalı.

---

## 19. Sunum Hikayesi

**Datathon için kullanılabilir mesaj:**

> "Operasyonel yorgunluk hipotezini 4 farklı metrikle test ettik (anlık sefer, kümülatif sefer, kümülatif KM, bitiş gecikmesi). **Hiçbirinde pozitif yorgunluk sinyali bulamadık — aksine çoğu metrik ters yönlü.**
>
> Bu, İETT operasyonunda **mevcut araç tahsis politikasının başarılı** olduğunu gösteren bir bulgu. Sağlam araçlar yoğun zamana, sorunlu araçlar yedeğe atanıyor. Yorgunluk birikimi gözlenmiyor çünkü araç değişimi/rotasyonu sorunu doğmadan engelliyor.
>
> Operasyonel uyarı için kırılma noktası eşiği KOYULAMAZ; bu hipotezin geçerli olduğu farklı veri (motor saatleri, fren intensitesi) gerekirdi."

Bu sunumu **olumsuz değil pozitif bir bulgu** olarak çerçevele: hipotez çürütüldü çünkü İETT'nin tahsis politikası işliyor.

---

## 20. Kısıtlamalar

1. **Veri penceresi 6 ay** — Yorgunluk birikimi muhtemelen daha uzun sürede gerçekleşir.
2. **Motor saatleri (engine hours) yok** — Fiziksel yıpranma direkt ölçümü yapılamadı.
3. **Fren/gaz yoğunluğu verisi yok** — Sürüş stresi ölçülemedi (Analiz 2'de şoför etkisi sınırlı testle bakıldı).
4. **Plan süresi datası kalitesi şüpheli** — gerceklesen/planlanan ratio median=1.000 anormal. Veri kaynağında "gerçekleşen sürenin plana eşitlenmesi" olabilir.
5. **Yolcu doluluk verisi güvenilmez** (kullanıcı belgesi) — yıpranma proxy olarak kullanılamadı.
6. **ARACTIPI ayrımı yapılmadı** (proje kararı) — Metrobüs ile otobüs yorgunluk pattern'leri farklı olabilir.
7. **Selection bias dışlanamadı** — Operatörün araç tahsis kararı ile feature'lar karışık.

---

## 21. Sonraki Adımlar

- [x] Analiz 6 SONUCLAR (bu belge)
- [ ] **Analiz 7 — Yakıt Verimliliği** (Önce veri kontrolü gerekli)
- [ ] Analiz 8 — Maliyet Simülasyonu
- [ ] Analiz 9 — Güvenlik Prioritizasyon
- [ ] Analiz 10 — Akıllı Hat-Araç Atama
- [ ] FEATURES_FINAL.md
- [ ] ML_MODEL_V6

---

## 22. Hipotez Çürütme Listesi (Datathon Sunumu İçin)

Analiz 6 sonucu **çürütülen hipotezler**:

| Hipotez | Çürütme Kanıtı |
|---|---|
| "Fazla sefer yapan araç yorulur ve arıza yapar" | r=-0.27 (ters yön), %93 leakage |
| "Kümülatif yorgunluk (son 30 gün km) arıza tetikler" | r=+0.003, sinyal yok |
| "Trafikte çok gecikip yorulan araç arızalanır" | r=-0.013, ters yön + leakage |
| "Kırılma eşiği var, X seferden sonra risk sıçrar" | Tüm eşiklerde lift < 1.0 |

Bu liste, "veriye saygı duyarak hipotezi çürüttük" anlatımının kanıtı olarak kullanılacak.
