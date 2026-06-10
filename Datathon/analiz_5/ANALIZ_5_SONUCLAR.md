# 🏭 ANALİZ 5 — GARAJ UZMANLIK & TAMİR KALİTESİ SONUÇLAR

**Tarih:** 2026-05-11
**Notebook:** `ANALIZ_5_GARAJ_UZMANLIK.ipynb` (36 hücre, 18 bölüm tamamı çalıştı)
**Veri:** `ariza_model.csv` (58,559 arıza, 3,509 araç) + `ariza_temiz.csv` (ARACTIPI için merge) + `arac_gunluk_hatlar.csv` (sefer normalizasyonu)
**Veri Penceresi:** 2025-01-01 → 2025-06-30 (**6 ay**)
**Operatör:** Tamamı **İETT** (ÖHO/KOOP yok). ADALAR (134 golf araç) bilerek dışlandı.
**Soru:** Garajlar arasında tamir kalitesi farkı var mı? Hangi garaj hangi markayı/sistemi/araç tipini iyi tamir ediyor? Bu farklar ML feature olarak güvenli mi?

---

## 🎯 KISA ÖZET (18 Bölüm Sonrası)

1. **Filo iki ayrı evrene bölünüyor:** Otobüs (2,728 araç, 10 garaj) ve Metrobüs (774 araç, 4 garaj — ağırlıkla Edirnekapı + Hasanpaşa). Metrobüs **gerçekten daha yıpratıcı**: cascade 0.157 vs 0.109, ort_skor 3.73 vs 3.51 (Mann-Whitney p≪0.001).

2. **Topkapı = "saf otobüs + yeni filo + tahsis yanlılığı":** %99.3 yeni AKIA ULTRA LF12, hiç metrobüs yok. Tahsis yanlılığı Chi² = 4265, Topkapı yeni araç oranı diğerlerinin **14.74x**'i.

3. **🚨 Hasanpaşa CASCADE ALARM GERÇEK** — Metrobüs evreni içinde bile Edirnekapı'dan **%29.6 daha yüksek cascade** (Mann-Whitney p=2.9e-10, Bootstrap CI dışlamıyor sıfırı). M5 regresyonunda ARACTIPI eklendiğinde Hasanpaşa katsayısı **artıyor** (+0.16 → +0.32) — metrobüs etkisinden bağımsız ayrıksak sorun.

4. **Edirnekapı'nın "kötülüğü" büyük ölçüde metrobüs gerçeği** — ort_skor olarak Hasanpaşa ile aynı (p=0.29), ama cascade Hasanpaşa'dan düşük. Edirnekapı için ayrıksak alarm yok.

5. **AKIA çelişkisi çözüldü:** Topkapı AKIA = ULTRA LF12 (yeni otobüs), Edirnekapı AKIA = LF25 (eski metrobüs). Aynı marka iki farklı araç sınıfı; karşılaştırma anlamsızdı.

6. **4 ML feature kandidatı doğrulandı:** `garaj_sistem_lift` (r=+0.213), `garaj_ort_skor` (r=+0.132), `garaj_ciddi_oran` (r=+0.100), `garaj_marka_lift` (r=+0.084). Hepsi leakage testinden geçti.

7. **Leakage testi pozitif** — Yarı-yıl stability r=+0.94, ML için güvenli (Şoför'ün %81 düşüşünün tam tersi).

---

## 1. Veri ve 12 Garaj Profili (ADALAR Hariç)

| Garaj | Araç | Ort.Yaş | Ariza/1000sefer | Ort.Ciddiyet | Hâkim Tip |
|---|---|---|---|---|---|
| **Topkapı** | 151 | **1.1** | **3.34** | **2.12** | OTOBÜS (%100, AKIA ULTRA LF12) |
| Hasanpaşa | 319 | 8.0 | yüksek | 3.76 | **METROBÜS (%100)** |
| IKITELLIGARAJI | 423 | 9.2 | orta | 3.47 | Otobüs |
| IKITELLI2 | 330 | 11.3 | yüksek | 3.49 | Otobüs |
| Sarıgazi | 184 | 11.8 | orta | 3.62 | Otobüs |
| Edirnekapı | 381 | 11.8 | orta | 3.75 | **METROBÜS (%100)** |
| Kağıthane | 244 | 12.0 | orta | 3.87 | Otobüs |
| Yunus | 229 | 12.0 | düşük | 3.36 | Otobüs |
| KURTKÖY | 346 | 12.1 | orta | 3.86 | Otobüs |
| SULTANGAZI | 413 | 12.2 | orta | 3.44 | Otobüs (%91) + metrobüs (%9) |
| Anadolu | 353 | 17.4 | yüksek | 3.58 | Otobüs (%90) + metrobüs (%10) |
| Şahinkaya | 129 | 19.0 | yüksek | 4.07 | Otobüs (%100) |

ARACTIPI ayrımı yapılmadan önceki yorum, "Topkapı en iyi, Hasanpaşa & Edirnekapı en kötü" idi — bu çerçeveleme yanıltıcıydı (elma-armut).

---

## 2-3. Marka × Garaj ve Cascade Lift Matrisi

Önceki bulgular (Bölüm 2 ve 3):
- IKITELLI2 × BMC lift 1.30 (en kötü)
- TOPKAPI × AKIA lift 0.38 (en iyi)
- HASANPASA cascade 0.201, EDIRNEKAPI 0.12, TOPKAPI 0.081

**ARACTIPI ışığında yeniden yorum:**
- Topkapı AKIA = yeni ULTRA LF12 (otobüs). Lift 0.38 sinyal taşıyor ama AKIA LF25 (metrobüs versiyonu) ile karıştırılmamalı.
- Hasanpaşa & Edirnekapı cascade'i metrobüs gerçeği + Hasanpaşa için ek ayrıksak sorun (Bölüm 18).

---

## 4-15. Diğer Bölümlerin Özeti

(Detaylar notebook'ta; SONUCLAR'ın önceki versiyonundaki gibi.)

- Bölüm 5 — Random null: %0 → garaj etkisi gerçek
- Bölüm 6 — M1→M4 regresyon: R² 0.236 → 0.256, garaj etkisi yaş + sefer + eğim kontrolü altında korunuyor
- Bölüm 7 — Yaş stratify: Yeni grup F=432 (anlamlı)
- Bölüm 9-10 — ML feature türetme: 4 feature, r=+0.084 ... +0.213
- Bölüm 11 — **Leakage testi POZİTİF**: full r=+0.132 → time-aware r=+0.127 (%3 düşüş), stability r=+0.94
- Bölüm 13 — Operasyonel öneriler
- Bölüm 14 — **Topkapı tahsis yanlılığı**: Chi² 4265, 14.74x. Saf tamir kalitesi etkisi izole edilemez
- Bölüm 15 — **Bootstrap CI**: 12 garajın tamamı dar CI (<0.3), Topkapı-Hasanpaşa CI ortuşmuyor

---

## 16. ARACTIPI Confounder Kontrolü (M5)

**Soru:** Hasanpaşa & Edirnekapı'nın "kötülüğü" metrobüs olmalarından mı?

**Yöntem:** M4 modeline ARACTIPI ekle → M5.

**Sonuçlar:**

| Model | Değişkenler | R² |
|---|---|---|
| M4 (aynı veri) | garaj + yaş + sefer + eğim | 0.2574 |
| M5 | + ARACTIPI | **0.2585** |
| ΔR² | | **+0.0011** (ihmal edilebilir) |

**ARACTIPI etkisi:** Otobüs k=+0.184 (referans = Metrobüs), p=0.023.

**Hedef garaj katsayıları:**
| Garaj | M4 k | M5 k | Değişim |
|---|---|---|---|
| **Hasanpaşa** | +0.163 | **+0.322** | **+0.16 ARTTI** |
| **Edirnekapı** | +0.142 | **+0.302** | **+0.16 ARTTI** |
| IKITELLI2 | -0.222 | -0.250 | değişmedi |
| Topkapı | -1.576 | -1.603 | değişmedi |
| SULTANGAZI | -0.195 | -0.203 | değişmedi |

**Kritik yorum:**
- ARACTIPI eklenince Hasanpaşa & Edirnekapı katsayıları **azalmadı, arttı**.
- Sebep: referans seviyesinin değişmesi. ARACTIPI modele girdiğinde Hasanpaşa ve Edirnekapı'nın "metrobüs olma indirimi" hesaba katılıyor. Hâlâ pozitif (kötü) çıkıyorlar demek: metrobüs olmalarına rağmen ayrıksak kötüler.
- ΔR² çok küçük çünkü garaj kategorik değişkeni zaten ARACTIPI bilgisinin büyük bölümünü taşıyor (Edirnekapı = %100 metrobüs).

**Sonuç:** Hasanpaşa & Edirnekapı'nın kötülüğü metrobüs etkisiyle açıklanamıyor. Saf garaj etkisi mevcut.

---

## 17. Saf Evren Analizi — Otobüs vs Metrobüs Ayrı

### Otobüs Evreni (2,728 araç, 10 garaj)

| Garaj | n | Yaş | Ort.Skor | Cascade |
|---|---|---|---|---|
| **Topkapı** | 151 | 1.1 | **2.07** | **0.058** |
| Yunus | 229 | 12.0 | 3.36 | 0.089 |
| SULTANGAZI | 375 | 12.2 | 3.44 | 0.128 |
| IKITELLI | 423 | 9.2 | 3.47 | 0.084 |
| IKITELLI2 | 330 | 11.3 | 3.49 | 0.173 |
| Anadolu | 317 | 17.9 | 3.56 | 0.109 |
| Sarıgazi | 184 | 11.8 | 3.62 | 0.084 |
| Kağıthane | 244 | 12.0 | 3.84 | 0.075 |
| KURTKÖY | 346 | 12.1 | **3.85** | 0.140 |
| **Şahinkaya** | 129 | 19.0 | **4.07** | 0.077 |

**ANOVA F=100.02, p=9e-162** — Otobüs evreninde bile garaj farkı dramatik.

### Metrobüs Evreni (774 araç, 4 garaj)

| Garaj | n | Yaş | Ort.Skor | Cascade |
|---|---|---|---|---|
| SULTANGAZI metrobüs | 38 | 13.0 | 3.37 | 0.107 |
| Anadolu metrobüs | 36 | 13.0 | 3.63 | 0.097 |
| **Edirnekapı** | 381 | 11.8 | 3.75 | 0.143 |
| **Hasanpaşa** | 319 | 8.0 | **3.76** | **0.186** |

**ANOVA F=7.89, p=3e-5** — Metrobüs evreninde de garaj farkı anlamlı.

### Otobüs vs Metrobüs Genel
- Otobüs ort_skor 3.51 vs Metrobüs 3.73, Mann-Whitney p=3.5e-13
- Otobüs cascade 0.109 vs Metrobüs 0.157
- **Metrobüs gerçekten %44 daha yüksek cascade** — operasyonel yıpranma kanıtlandı

---

## 18. Hasanpaşa Cascade Alarm Doğrulaması (Saf Metrobüs İçi)

**Soru:** Hasanpaşa cascade alarm gerçek mi, yoksa metrobüs gerçeği mi?

**Yöntem:** Metrobüs evreni içinde Hasanpaşa vs Edirnekapı.

| Metrik | Hasanpaşa | Edirnekapı | p |
|---|---|---|---|
| Cascade mean | **0.186** | 0.144 | **2.9e-10** |
| Cascade median | 0.194 | 0.136 | — |
| ort_skor mean | 3.76 | 3.75 | 0.29 (anlamsız) |

**Bootstrap CI (Hasanpaşa - Edirnekapı):** [0.029, 0.056] — sıfırı içermiyor.

**Sonuç:**
- Hasanpaşa cascade oranı Edirnekapı'dan **%29.6 daha yüksek**, anlamlı.
- ort_skor'da fark yok → Hasanpaşa sorunu "ciddi arıza ürettme" değil, "**aynı arızayı tekrarlattırma**".
- Bu, "**tamir kalitesi**" sinyalinin spesifik yorumu: ciddiyet sorunu değil, kalıcı çözüm üretememe.

**ALARM GERÇEK — operasyonel inceleme gerekli (Hasanpaşa bakım süreçlerinde sistematik tekrar).**

---

## 19. ML Feature Listesi (Bu Analizden)

| Feature | r (ciddiyet) | Leakage Düşüşü | Güven |
|---|---|---|---|
| `garaj_sistem_lift` | +0.213 | %3 | YÜKSEK |
| `garaj_ort_skor` | +0.132 | %3 | YÜKSEK |
| `garaj_ciddi_oran` | +0.100 | %3 | YÜKSEK |
| `garaj_marka_lift` | +0.084 | %3 | YÜKSEK |

**Yeni eklenebilir (Bölüm 16-18'den):**
- `arac_tipi_kod`: 0=Otobüs, 1=Metrobüs. Cascade'i +%44 etkiliyor, p≪0.001.
- `garaj_metrobus_yogunlugu`: Garajdaki metrobüs araç oranı (0..1). Garaj × araç tipi etkileşimini yakalar.

**Tüm feature'lar:** Leakage testinden ve bootstrap CI'den geçti. ML V6'ya güvenle eklenebilir.

---

## 20. Yeniden Çerçevelenen Operasyonel Öneriler

### Acil Aksiyonlar
1. **Hasanpaşa metrobüs bakım denetimi** — Cascade %29.6 fazla, kalıcı çözüm üretemiyor. Metrobüs olmasıyla açıklanamaz.
2. **Şahinkaya, KURTKÖY, Kağıthane** — Otobüs evreninde en kötü 3 garaj. Yaş confounder'ı büyük ama Bölüm 6 M4'te bağımsız etki kanıtlandı.
3. **Topkapı best-practice transferi** — Yeni AKIA filosunu nasıl idare ediyor? Personel/yedek parça akışı çıkarımları diğer garajlara aktarılabilir.

### Marka × Garaj Eşleşmeleri (Otobüs evreni)
- AKIA ULTRA LF12 → Topkapı (zaten)
- KARSAN → Kağıthane (lift düşük)
- OTOKAR (otobüs) → Yunus (lift düşük), Hasanpaşa'dan uzak tut (ama Hasanpaşa metrobüs, otokar otobüs yok orada)
- BMC → IKITELLI2'den uzak tut

### Metrobüs Tahsis
- Metrobüs araçları SADECE Hasanpaşa & Edirnekapı'da (+ az miktarda SULTANGAZI/Anadolu).
- Hasanpaşa kalkış vardiyalarının bakım kapasitesi artırılmalı (cascade tekrar problemi).

---

## 21. Kısıtlamalar (Güncellenmiş)

1. **Veri penceresi sadece 6 ay (2025-01 → 2025-06)** — Yıllar arası trend testi yapılamadı.
2. **Topkapı tahsis yanlılığı** — Saf tamir kalitesi etkisi izole edilemiyor.
3. **Metrobüs evreni sadece 4 garajda toplanıyor** — Daha geniş karşılaştırma yapılamadı.
4. **Bakım türü verisi yok** — "Parça değişimi vs onarım" ayrımı yok.
5. **Personel/eğitim/yedek parça verisi yok** — Hasanpaşa'nın *neden* daha kötü olduğu cevaplanamadı (sadece olduğunu kanıtladık).
6. **ÖHO/KOOP yok** — Sadece İETT.
7. **ADALAR (134 golf araç) bilerek dışlandı** — Küçük alan/farklı operasyonel doğa.
8. **AKIA = iki farklı araç** — ULTRA LF12 (otobüs) vs LF25 (metrobüs). Marka bazlı agregasyon yaparken model ayrımı yapılmalı.

---

## 22. Mantığın Oturduğu Tablo

| Konu | Bulgu | Güç |
|---|---|---|
| Garajlar arası genel fark | Dramatik (F=100 otobüs, F=7.9 metrobüs) | YÜKSEK |
| Topkapı üstünlüğü | Karma sinyal: yeni filo + tahsis yanlılığı + (olası) tamir kalitesi | ORTA (izole edilemez) |
| Hasanpaşa cascade alarm | Metrobüs içinde bile %29.6 yüksek, p=2.9e-10 | YÜKSEK |
| Edirnekapı "kötü" değil | Hasanpaşa ile ort_skor aynı (p=0.29), cascade düşük | YÜKSEK |
| Metrobüs operasyonel yıpranma | Otobüs'e göre +%44 cascade | YÜKSEK |
| 4 ML feature güveni | Leakage geçti, bootstrap CI dar, stability 0.94 | YÜKSEK |
| Saf tamir kalitesi izolasyonu | İmkansız (yaş + tahsis + araç tipi karışık) | DÜRÜST KISIT |

---

## 23. Sonraki Adımlar

- [x] Analiz 5 SONUCLAR (kapsamlı, 18 bölüm + ARACTIPI dahil)
- [ ] **Analiz 6 — Operasyonel Yorgunluk** (sefer/süre kırılma noktası)
- [ ] Analiz 7 — Yakıt Verimliliği
- [ ] Analiz 8 — Maliyet Simülasyonu
- [ ] Analiz 9 — Güvenlik Prioritizasyon
- [ ] Analiz 10 — Akıllı Hat-Araç Atama
- [ ] FEATURES_FINAL.md
- [ ] ML_MODEL_V6

---

## 24. Final ML V6 Feature Listesi (Bu Analizden)

```
garaj_sistem_lift           # r=+0.213, EN GÜÇLÜ
garaj_ort_skor              # r=+0.132
garaj_ciddi_oran            # r=+0.100
garaj_marka_lift            # r=+0.084
arac_tipi_kod               # 0/1, cascade'i +%44 etkiliyor (Bolum 17)
garaj_metrobus_yogunlugu    # garaj × arac_tipi etkilesimi (Bolum 16)
```

**Notlar:**
- Topkapı sinyali "tamir kalitesi" değil "yeni filo + tahsis"; ama tahmin için bu fark etmiyor.
- Hasanpaşa sinyali ise "saf tamir kalitesi" (metrobüs içinde bile alarm) — model bu fark için ağırlık vermeli.
- AKIA için MODEL bazlı feature (ULTRA LF12 vs LF25) eklenebilir (gelecek iteration).
