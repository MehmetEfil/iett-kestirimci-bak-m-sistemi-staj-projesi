# İETT Kestirimci Bakım Sistemi

İstanbul İETT otobüs filosu için uçtan uca bir **kestirimci bakım (predictive maintenance)** sistemi: her aracın ve alt sisteminin **2025 Q3 (Temmuz–Eylül) ciddi arıza riskini** önceden tahmin edip bunu somut **bakım önceliklendirmesine** çevirir — risk tier'ları (KRİTİK/YÜKSEK/ORTA/DÜŞÜK), parça bakım takvimi ve araç ikame önerisi. 9 derinlemesine analiz, kalibre edilmiş XGBoost+LightGBM ensemble ve canlı bir yönetim paneli içerir.

> ⚠️ **Veri notu:** Bu repo yalnızca **kod ve çalışma mantığını** içerir. Gerçek İETT operasyonel verisi (arıza/kaza/sefer/yolcu kayıtları, sürücü bilgileri) gizlilik nedeniyle **dahil edilmemiştir**. Notebook'lar ve panel, yerel veriyle çalıştırılmak üzere tasarlanmıştır.

---

## 🎯 Problem
İETT'nin 3.500'ü aşkın otobüsü ve sınırlı bakım bütçesi var. **Hangi araca öncelik verilmeli?** Bu sistem her araç için bir risk seviyesi (KRİTİK / YÜKSEK / ORTA / DÜŞÜK) ve her araçta **hangi sistemin** (motor, fren, klima…) riskli olduğunu üretir.

## 📊 Öne Çıkan Sonuçlar
| Metrik | Değer |
|--------|-------|
| Model (XGBoost + LightGBM ensemble) Test AUC | **0.8167** |
| Dağılım kayması (PSI, Q1→Q3) | **0.067** (deployment-safe) |
| Kalibrasyon hatası (ECE, Platt) | 0.035 |
| Tier saflığı | KRİTİK %86 / DÜŞÜK %27 gerçek pozitif |
| Tahmin granülaritesi | 3.508 araç × ~37 sistem |

**Bilimsel keşif:** Zincirleme (cascade) arızalar rastgele beklentinin **~1.4 katı** (Monte Carlo null, Z≈32) ve **%94'ü** aracın kendi mekaniğinden — yani modellenebilir bir sinyal.

## 🏗️ Mimari
```
Ham veri → temizleme → ciddiyet skoru → 9 analiz (A1–A9)
   → feature seçimi (leakage/VIF testleri) → V6.5 model (Q1→Q2→Q3, sızıntısız)
   → araç + sistem bazlı tier ataması → Flask yönetim paneli
```

- **Veri penceresi:** 2025 H1 (6 ay). Q3 tahmini, mevsim çarpanıyla ekstrapole edilir.
- **Zaman-temiz kurulum:** Feature'lar Q1'den, hedef Q2'den, tahmin Q3 için → veri sızıntısı yok.
- **Model:** XGBoost + LightGBM olasılık ortalaması, Platt (sigmoid) kalibrasyon, 23 feature.

## 📁 Klasör Yapısı
```
iett-ariza-tahmini/
├─ Datathon/              # Analiz & ML (notebook'lar + dokümanlar)
│  ├─ analiz_1..9/        # 9 derinlemesine analiz (cascade, şoför, topografya, kaza, garaj, yorgunluk, yakıt, güvenlik, atama)
│  ├─ v6/                 # V6.5 model pipeline (feature prep, eğitim, sistem tahmini)
│  ├─ ARIZA, DENETİM, YOLCULUK/  # ETL/agregasyon notebook'ları
│  ├─ CIDDIYET_SKORU.ipynb, EDA.ipynb, ...
│  └─ FEATURES_FINAL.md   # Feature seçim metodolojisi
└─ iett_panel/            # Flask yönetim paneli (kod)
   ├─ app.py, routes.py, services.py, models.py
   ├─ templates/          # Dashboard arayüzü
   └─ static/             # CSS / JS / fontlar
```

## 🚀 Kurulum
```bash
# 1) Bağımlılıklar
pip install -r requirements.txt

# 2) Ortam değişkenleri
cp .env.example .env        # ardından .env içine İBB API bilgilerinizi girin

# 3) Paneli çalıştır (yerel veri gerektirir — bkz. Veri notu)
cd iett_panel
python app.py               # http://localhost:5000
```
> Analiz notebook'larını çalıştırmak için Jupyter ve ilgili `panel_data/` veri dosyaları gereklidir (repoda yoktur).

## 📷 Ekran Görüntüleri
> _Buraya panel ekran görüntüleri eklenecek (risk haritası, tier dağılımı, sistem bazlı tahmin, dashboard sekmeleri)._

## 🔬 Metodolojik Notlar (dürüst raporlama)
- **Cluster-driven model:** En güçlü sinyal garaj-marka uyumu; model garajlar **arasını** çok iyi (AUC 0.82), bazı garajların **içinde** zayıf ayırır (garaj-içi ort. ~0.57). Bu garajlar panelde "⚠️ manuel kontrol" etiketlidir.
- **Çürütülen hipotezler:** "Yaşlı araç daha çok zincirleme arıza yapar", "çok çalışan araç yorgunluktan bozulur" gibi sezgisel hipotezler veriyle **reddedildi** ve dürüstçe raporlandı.
- **Bilinen sınırlar:** 6 aylık veri penceresi; mevsim çarpanı varsayımsal ekstrapolasyon; tamir-düzeltme çarpanları yön-gerekçeli ama kalibre edilmemiş.

## 🗺️ Roadmap / Gelecek Özellikler
Proje aktif geliştiriliyor. Planlanan/üzerinde çalışılan başlıklar:
- [ ] **"Nasıl giderim" rota planlayıcı** — çok-bacaklı (aktarmalı) rota + canlı ETA (iskelet: `/api/nasil_gidilir`, `durak_ara`, `durak_eta`)
- [ ] **Garaj derinlemesine analiz sekmesi** (A5) — Hasanpaşa cascade alarmı dahil, diğer 8 analizle simetrik
- [ ] **İlçe / durak / araç bazlı risk panelleri** — risk ısı haritalarının canlı veriyle doldurulması
- [ ] **Model kartı & API dokümantasyonu** — endpoint tablosu + model girdisi/çıktısı/limitasyon belgesi
- [ ] **Canlı veri entegrasyonu cilası** — gerçek zamanlı İBB akışının panele tam yansıtılması

## 🛠️ Teknolojiler
Python · Flask · SQLAlchemy · pandas / numpy · scikit-learn · XGBoost · LightGBM · SHAP · Optuna · Leaflet · Chart.js · İBB Açık Veri (SOAP) API
