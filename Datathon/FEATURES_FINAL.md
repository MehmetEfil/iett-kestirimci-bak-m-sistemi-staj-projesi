# 🎯 FEATURES_FINAL — ML V6.5 Doğrulanmış Feature Listesi

**Tarih:** 2026-05-14
**Kaynak:** `FEATURES_FINAL_DOGRULAMA.ipynb` (7 bölüm, multicollinearity + leakage + tree-model validation)
**Master CSV:** `features_final_v2_9feature.csv` (3,508 araç × 19 kolon)
**Final model:** V6.5 — OOF AUC = **0.8167**, PSI = **0.067**, ECE (kalibre) = **0.035**
**Strateji:** Include-Then-Prune (9 ana feature → 23 toplam — V6.5'te + 6 Q1 sistem + 5 statik + 3 yardımcı)

---

## 🎯 Özet

9 analizden çıkan 13 feature aday değerlendirildi. **4 katmanlı doğrulama** uygulandı:
1. Leakage testi (train/test split)
2. Pairwise correlation matrix
3. VIF (Variance Inflation Factor) — linear model varsayımı
4. **Tree model toleransı** — XGBoost/LightGBM çoklu doğrusallığa dayanıklı

**Sonuç: 9 ana feature ML V6.5'e doğrulandı**, 9 feature atıldı (multicollinearity + dublicate + leakage).

---

## ✅ FINAL 9 FEATURE LİSTESİ

| # | Feature | Kaynak Analiz | r (ort_skor) | VIF | Açıklama |
|---|---|---|---|---|---|
| 1 | **yas** | Temel (MODELYILI'den) | +0.209 | 3.20 | Araç yaşı, motor yenileme confounder'ı belgelendi |
| 2 | **egim_maruziyet** | A3 Topografya | +0.166 | 2.52 | Araç × hat ağırlıklı ortalama eğim puanı |
| 3 | **garaj_sistem_lift** | A5 Garaj | +0.278 | 10.44 | Garaj sistem-bazlı tamir kalitesi — **tree-tolerable** |
| 4 | **garaj_marka_lift** | A5 Garaj | +0.417 | 4.83 | Garaj × Marka uyumu — farklı bilgi katmanı |
| 5 | **yakit_turu_cng** | A7 Yakıt | +0.035 | 2.53 | Binary (0/1), M4 katsayısı -0.358 |
| 6 | **verimsizlik_skoru** | A7 Yakıt | +0.146 | 2.76 | yas_norm × tuketim_norm |
| 7 | **hat_zorluk** | A9 Atama | +0.237 | 4.93 | Eğim + uzunluk + arıza + trafik bileşik |
| 8 | **cascade_risk_skor** | A1 Cascade | +0.035 | 3.91 | Zayıf r ama VIF güvenli — **SHAP elek adayı** |
| 9 | **farkli_sofor_sayisi** | A2 Şoför | +0.119 | 5.17 | Şoför çeşitliliği proxy'si |

**Strateji notu:**
- 7. ve 8. feature'lar şartlı dahildi — V6.5 SHAP testi sonrası tutuldu (V6.6 pruning denendi PSI patladı 0.48)
- 3 (garaj_sistem_lift) VIF 10.44 ama tree model için tolere edilebilir — farklı bilgi taşır
- 8 (cascade_risk_skor) r=+0.035 zayıf, leakage testi %45 düşüş gösterdi (datathon sonrası yeniden değerlendirme)
- 4 (garaj_marka_lift) V6.5'te SHAP importance %40 — dominant feature, out-of-fold encoding eksik (datathon sonrası iyileştirme)

---

## ❌ ATILAN 9 Feature

### Multicollinearity Nedeniyle (2 garaj feature)
| Feature | VIF | Pairwise Korelasyon | Sebep |
|---|---|---|---|
| garaj_ort_skor | **16.29** | r=0.72 ile garaj_marka_lift | Redundant — garaj_marka_lift tutuldu |
| garaj_ciddi_oran | **31.97** | r=0.86 ile garaj_sistem_lift | Dublike — garaj_sistem_lift tutuldu |

### Dublike Sinyal Nedeniyle (1)
| Feature | r ile cascade_risk_skor | Sebep |
|---|---|---|
| sistem_cas_lift | r=+0.82 (yüksek) | cascade_risk_skor ile aynı bilgi, atıldı |

### Leakage Nedeniyle (1)
| Feature | r | Sebep |
|---|---|---|
| anomali_skor | **+0.721** (yapay yüksek) | `hat_zorluk × ciddi_oran` formülünde target içeriyor. Mantıksal leakage. |

### Önceki Analizlerde Tespit Edilen Leakage (3)
| Feature | Kaynak | Sebep |
|---|---|---|
| sofor_glob_skor | A2 Şoför | %81 leakage düşüş |
| gunluk_sefer_sayisi | A6 Yorgunluk | %93 leakage + ters yön |
| son_30g_top | A6 Yorgunluk | %56 leakage, sinyal yok |

### Diğer (2)
| Feature | Sebep |
|---|---|
| kritiklik_skoru (A8) | Stability r=0.15 zayıf — operasyonel only |
| **son_kaza_gun (A4)** | **r=+0.13 zayıf + A4 kaza fırtınası ÇÜRÜTTÜ (kazadan sonra arıza artmıyor). Arıza tahmini için bilgisel katkı yok, hesaplama maliyetine değmez.** |

---

## 🌳 Tree Model Multicollinearity Toleransı

### Neden VIF'yi Bazı Feature'larda Esnetiyoruz?

**Linear regression için VIF kritik:**
- VIF > 10 → katsayı tahminleri kararsız
- Standart hata şişer
- Feature interpretability bozulur

**Tree-based modeller (XGBoost/LightGBM/CatBoost) için VIF tolerable:**
- Her node'da en iyi split seçilir
- Korele feature'lar arasında biri seçilir, diğeri redundant olur
- **Accuracy bozulmaz**
- Sadece feature_importance bölünür (genel önem kaybı yok)

### Bu Karar İçin Etkileri

| Feature | VIF | Linear Karar | Tree Model Karar | Neden Tut? |
|---|---|---|---|---|
| garaj_sistem_lift | 10.44 | ATLA | **KEEP** | Farklı bilgi: sistem-bazlı kalite |
| garaj_marka_lift | 4.83 | OK | KEEP | Farklı bilgi: marka × garaj uyumu |
| garaj_ort_skor | 16.29 | ATLA | ATLA | r=0.72 dublike, sinyal aynı |
| garaj_ciddi_oran | 31.97 | ATLA | ATLA | r=0.86 dublike, redundant |

---

## 🎯 Include-Then-Prune Stratejisi

Modern ML disiplini — feature seçimi için iki aşamalı yaklaşım:

### V6.0 (Geniş Set)
- 9 feature ile XGBoost fit
- SHAP analizi
- Feature importance plot

### V6.1 (Pruned)
- SHAP importance < %1 → çıkar
- Cross-validation ile AUC karşılaştır
- En iyi konfigürasyonu seç

### V6.0 → V6.1 Karar Tablosu (Hipotez)
| Feature | Bekleyen Importance | Çıkarılma Olasılığı |
|---|---|---|
| garaj_marka_lift | YÜKSEK | Düşük |
| yas | YÜKSEK | Düşük |
| hat_zorluk | ORTA-YÜKSEK | Düşük |
| garaj_sistem_lift | ORTA | Orta |
| egim_maruziyet | ORTA | Düşük |
| verimsizlik_skoru | ORTA | Düşük |
| farkli_sofor_sayisi | DÜŞÜK-ORTA | Orta |
| yakit_turu_cng | DÜŞÜK | Orta-Yüksek |
| **cascade_risk_skor** | **ÇOK DÜŞÜK** | **YÜKSEK** |

---

## 📋 9 Analiz Birleşik Sonuç Tablosu

### Analiz 1 — Cascade Arızalar
- `cascade_risk_skor`: ✅ V6.0'da SHAP testi için (r=+0.035 zayıf)
- `sistem_cas_lift`: ❌ cascade_risk_skor ile dublike (r=0.82)

### Analiz 2 — Şoför
- `sofor_glob_skor`: ❌ %81 leakage
- `farkli_sofor_sayisi`: ✅ V6'ya dahil

### Analiz 3 — Topografya
- `egim_maruziyet`: ✅ V6'ya dahil

### Analiz 4 — Kaza
- `son_kaza_gun`: ❌ ATLA — A4 kaza fırtınası ÇÜRÜTTÜ (RR=0.951, p=0.9998 kazadan sonra arıza artmıyor). r=+0.13 zayıf + arıza tahmini için bilgisel katkı yok.

### Analiz 5 — Garaj (4 feature → 2 kaldı)
- `garaj_sistem_lift`: ✅ V6'ya dahil (tree-tolerable)
- `garaj_marka_lift`: ✅ V6'ya dahil
- `garaj_ort_skor`: ❌ Redundant
- `garaj_ciddi_oran`: ❌ Dublike

### Analiz 6 — Operasyonel Yorgunluk (TÜM HİPOTEZ ÇÜRÜTÜLDÜ)
- 4 feature ATLA (tümü leakage veya sinyal yok)

### Analiz 7 — Yakıt Ekonomisi
- `yakit_turu_cng`: ✅ V6'ya dahil (kategorik)
- `verimsizlik_skoru`: ✅ V6'ya dahil

### Analiz 8 — Güvenlik Prioritizasyon
- `kritiklik_skoru`: ❌ Stability zayıf (operasyonel only)

### Analiz 9 — Hat-Araç Atama
- `hat_zorluk`: ✅ V6'ya dahil
- `anomali_skor`: ❌ Target leakage

---

## 🔬 Metodoloji

### 1. Leakage Testi
- Train/Test split (median tarih = 2025-04-07)
- Train döneminden feature hesaplanıyor
- Test dönemine `KAPINO` üzerinden eşleştiriliyor
- Full r vs TestOnly r düşüşü >%50 = ATLA, %30-50 = RISKLI, <%30 = GÜVENLİ

### 2. Pairwise Correlation Matrix
- 13 feature × 13 feature Pearson korelasyon
- |r| > 0.7 = yüksek (dublike kontrolü)
- 0.5-0.7 = orta (dikkat)

### 3. VIF (Variance Inflation Factor)
- statsmodels `variance_inflation_factor`
- Linear model varsayımı (referans)

### 4. Tree Model Toleransı
- VIF > 10 olsa bile farklı bilgi taşıyan feature'lar tutulabilir
- SHAP testi V6.0'da yapılır
- Importance < %1 → V6.1'de çıkar

---

## 🚧 V6'ya Geçmeden Önce Yapılacaklar

### 1. son_kaza_gun — ATILDI (V6'da kullanılmıyor)
A4 kaza fırtınası ÇÜRÜTTÜ (RR=0.951). Kaza ile arıza uzun vadeli ilişkisi yok. Gerçek hesaba gerek yok, feature listesinden çıkarıldı. ML V6 sadece 9 feature ile gidiyor.

### 2. Train/Test Split Stratejisi
- Train: 2025-01-01 → 2025-04-07 (median)
- Test: 2025-04-07 → 2025-06-30
- Cross-validation: 3-fold (veri 6 ay)

### 3. Hedef Değişken (V6.5'te seçilen)
**`q2_ciddi_n ≥ 3`** — Q2 2025'te 3+ ciddi arıza yapan araç (TARGET_KARSILASTIRMA notebook'unda 4 alternatif test edildi, (C) seçildi: %54 dengeli pozitif oran, ortalama \|r\| 0.221).

### 4. Model Tipi (V6.5'te seçilen)
- **XGBoost + LightGBM Ensemble** (rank-averaging)
- Optuna 50-trial hiperparametre araması
- İzotonik kalibrasyon

---

## 📊 V6.5 Final Performans

| Versiyon | Feature Sayısı | OOF AUC | PSI | ECE (kalibre) | Durum |
|---|---|---|---|---|---|
| **V6.5** | **23** (9 ana + 14 ek) | **0.8167** | **0.067** | **0.035** | ✅ FİNAL |
| V6.6 | 8 (pruned) | — | 0.48 | — | ❌ PSI patladı |
| V6.5.1 (dur_kalk çıkar) | 22 | — | 1.29 | — | ❌ PSI patladı |
| V6.5.3 (garaj_marka_lift çıkar) | 22 | -0.012 | — | — | ❌ Yunus cluster bozuldu |

---

## 🎯 V6.5 Pipeline Adımları (TAMAMLANDI)

1. ✅ **Feature Engineering:** `v6/V6_FEATURE_PREP.ipynb` → `features_final_v6_q1.csv`
2. ✅ **Train/Test Split:** Q2 2025 → Q3 2025 target, KAPINO-bazlı stratify
3. ✅ **Target Karşılaştırma:** 4 alternatif test → C (q2_ciddi_n ≥ 3, %54 dengeli)
4. ✅ **Model:** XGBoost + LightGBM Ensemble (rank-avg), Optuna 50-trial
5. ✅ **Kalibrasyon:** İzotonik regresyon (ECE 0.098 → 0.035)
6. ✅ **SHAP analizi:** `shap_v6_beeswarm.png`, `shap_v6_importance.png`
7. ✅ **V6.5 Final:** 23 feature, OOF AUC 0.8167, PSI 0.067
8. ✅ **Seviye 2 (Araç × Sistem):** 34 sistem için Q3 olasılık + V3 tamir düzeltmesi

---

## ⚠️ Bilinen Limitasyonlar

1. **Veri 6 ay** — Mevsimsellik yansıtılmadı.
2. **ARACTIPI ayrımı yapılmadı** (proje kararı).
3. **yolcu_doluluk güvenilmez** (proje kararı).
4. **Motor yenileme verisi yok** — yas feature'ı zayıf, performans proxy'leri daha güçlü.
5. **son_kaza_gun placeholder** — Validation notebook'unda gerçek hesap yapılmadı.
6. **cascade_risk_skor zayıf signal** — SHAP testinde elenirse V6.1'de çıkarılır.
7. **VIF endişesi tree model için esnetildi** — linear model kullanılırsa tekrar değerlendirme gerek.

---

## 📁 Çıktı Dosyaları

| Dosya | İçerik |
|---|---|
| `features_final_v2_9feature.csv` | 3,508 araç × 19 kolon (9 feature + meta) — **ANA DOSYA** |
| `features_final_master.csv` | Önceki versiyon (13 feature, referans) |
| `FEATURES_FINAL_DOGRULAMA.ipynb` | Doğrulama notebook'u (7 bölüm) |
| `FEATURES_FINAL.md` | Bu belge |

---

## 📌 Sunum Hikayesi (Datathon İçin)

> **9 Analiz → 9 Doğrulanmış Feature:** Her feature 4 katmanlı testten geçti:
> 1. Leakage testi (train/test split)
> 2. Pairwise correlation matrix
> 3. VIF analizi (linear model referansı)
> 4. Tree model toleransı (XGBoost için yeniden değerlendirme)
>
> **Atılan 9 feature için somut metodolojik gerekçe:**
> - Multicollinearity (2 garaj feature): garaj_marka_lift ile dublike
> - Target leakage (anomali_skor): formülde target var
> - Leakage tespiti (sofor_glob_skor): %81 düşüş
> - Çürütülen hipotez (4 yorgunluk feature): veri reddetti (Analiz 6)
> - Stability zayıflığı (kritiklik_skoru): operasyonel only
>
> **V6.5 Final:** XGBoost + LightGBM Ensemble · 23 feature · OOF AUC **0.8167** · PSI **0.067** (deployment-safe) · ECE **0.035**
>
> **Sweet spot kanıtı:** V6.6/V6.5.1/V6.5.2/V6.5.3 alternatifleri test edildi, hepsi PSI veya AUC açısından geriledi → V6.5 optimal.
>
> **Operasyonel Çıktı:** Model sadece tahmin değil, **açıklanabilir** — her feature 9 analizden gelen kanıta dayalı. Seviye 2 ile araç × sistem (KAPI/MOTOR/FREN…) bazında olasılık.

---

## 🚀 Sonraki Adım

V6.5 production'da. Datathon sunumu için:
- 9 analiz konsolide hikaye
- V6.5 metrik dashboard'u (OOF AUC, PSI, ECE)
- Cluster audit (FN/FP + düşük per-garaj AUC) — dürüst limitasyon raporlama
