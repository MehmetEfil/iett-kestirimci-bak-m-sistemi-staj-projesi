import os, requests, json, time, re, threading, concurrent.futures, random
from datetime import datetime, timedelta
from collections import Counter, defaultdict
import xml.etree.ElementTree as ET

from utils import *
from models import TrafficIndexHistoryItem

# ──────────────────────────────────────────────────────────
# KİMLİK & URL'LER
# ──────────────────────────────────────────────────────────
# Kimlik bilgileri repoda TUTULMAZ — .env dosyasından okunur (bkz. .env.example / README)
IETT_USER = os.environ.get("IETT_USER", "")
IETT_PASS = os.environ.get("IETT_PASS", "")
URL_ANA     = "https://api.ibb.gov.tr/iett/UlasimAnaVeri/HatDurakGuzergah.asmx"
URL_IBB     = "https://api.ibb.gov.tr/iett/ibb/ibb.asmx"
URL_FILO    = "https://api.ibb.gov.tr/iett/FiloDurum/SeferGerceklesme.asmx"
URL_IBB360  = "https://api.ibb.gov.tr/iett/ibb/ibb360.asmx"
URL_DINAMIK = "https://api.ibb.gov.tr/iett/UlasimDinamikVeri/Duyurular.asmx"
URL_ARAC_OZELLIK = "https://api.ibb.gov.tr/iett/AracAnaVeri/AracOzellik.asmx"
URL_SAAT    = "https://api.ibb.gov.tr/iett/UlasimAnaVeri/PlanlananSeferSaati.asmx"
URL_TRAFFIC_REST = "https://api.ibb.gov.tr/tkmservices"
TRAFFIC_HISTORY_CACHE = {
    "ts": 0,
    "key": "",
    "data": []
}
TRAFFIC_HISTORY_TTL = 120
# Diğer URL'lerin altına ekleyebilirsin
URL_KAVSAK = "https://api.ibb.gov.tr/isbak/SinyalizeKavsaklar.asmx"

# Global Cache tanımlarının arasına ekle
KAVSAK_CACHE = {"ts": 0, "veri": []}

# ──────────────────────────────────────────────────────────
# TOM (opsiyonel)
# ──────────────────────────────────────────────────────────
TOMTOM_KEY      = os.environ.get("TOMTOM_KEY", "")
TOMTOM_FLOW_URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
TRAFIK_CACHE    = {}
TRAFIK_LOCK     = threading.Lock()
TRAFIK_TTL      = 300

ISTANBUL_PROFIL = {
    0:(0.95,0.90), 1:(0.98,0.88), 2:(0.99,0.85), 3:(1.00,0.90),
    4:(0.99,0.95), 5:(0.95,0.97), 6:(0.80,0.98), 7:(0.55,0.92),
    8:(0.45,0.80), 9:(0.60,0.75), 10:(0.72,0.72), 11:(0.75,0.70),
    12:(0.68,0.68), 13:(0.70,0.70), 14:(0.75,0.73), 15:(0.72,0.72),
    16:(0.60,0.68), 17:(0.42,0.65), 18:(0.38,0.62), 19:(0.48,0.65),
    20:(0.60,0.70), 21:(0.72,0.75), 22:(0.82,0.80), 23:(0.90,0.85),
}
# (lat, lon, etki_yarıçapı_km, trafik_çarpanı)
# Çarpan: 1.0=şehir ortalaması, 0.5=çok yoğun(köprü/E5), 1.3=açık yol
# IBB indeksi bu çarpanlarla çarpılır → her nokta farklı yoğunluk alır
KORIDOR_AGIRLIKLARI = [
    # ── BOĞAZ KÖPRÜLER (en kritik darboğazlar) ───────────────
    (41.0453, 29.0337, 1.2, 0.45),   # FSM Köprüsü
    (41.0461, 29.0338, 0.8, 0.45),   # FSM yaklaşım Anadolu
    (41.0580, 28.9740, 1.2, 0.48),   # Boğaziçi Köprüsü (15 Temmuz)
    (41.0580, 28.9750, 0.8, 0.48),   # Boğaziçi yaklaşım Avrupa
    (41.1167, 29.0644, 1.5, 0.52),   # Yavuz Sultan Selim Köprüsü
    # ── E-5 / D-100 KORİDORU ─────────────────────────────────
    (41.0210, 28.9400, 1.8, 0.55),   # E5 Merter-Topkapı
    (41.0100, 28.9700, 1.5, 0.58),   # E5 Bağcılar-Güngören
    (40.9900, 28.8700, 1.5, 0.60),   # E5 Bahçelievler
    (41.0050, 28.9500, 1.5, 0.57),   # E5 Zeytinburnu
    (41.0180, 29.1300, 1.5, 0.60),   # E5 Ümraniye
    (40.9850, 29.1000, 1.5, 0.62),   # E5 Pendik yönü
    (41.0300, 29.0500, 1.2, 0.63),   # E5 Kadıköy-Kozyatağı
    # ── TEM / O-3 KORİDORU ───────────────────────────────────
    (41.0750, 29.0550, 1.8, 0.55),   # TEM Ümraniye bağlantı
    (41.1050, 29.0500, 1.8, 0.57),   # TEM Çekmeköy
    (41.0850, 29.0050, 1.2, 0.60),   # TEM Sancaktepe
    (41.0900, 28.8800, 1.5, 0.62),   # TEM Eyüpsultan
    (41.1050, 28.7800, 1.5, 0.65),   # TEM Avcılar-Haramidere
    # ── ANA ARTERLER / KAVŞAKLAR ─────────────────────────────
    (41.0450, 28.9450, 1.5, 0.62),   # Mecidiyeköy kavşağı
    (41.0550, 28.9900, 1.2, 0.65),   # Beşiktaş
    (41.0650, 29.0200, 1.2, 0.63),   # Levent-Maslak arası
    (41.0750, 29.0200, 1.0, 0.65),   # Maslak kavşağı
    (41.0100, 29.0300, 1.2, 0.64),   # Kadıköy merkez
    (41.0280, 29.0730, 1.0, 0.66),   # Kozyatağı-Bostancı
    (40.9900, 29.1150, 1.5, 0.65),   # Kartal-Maltepe
    (40.9750, 29.0250, 1.2, 0.67),   # Pendik merkez
    (41.0600, 28.6800, 1.5, 0.65),   # Avcılar merkez
    (41.0300, 28.7800, 1.5, 0.66),   # Bağcılar merkez
    (41.0850, 28.8500, 1.2, 0.68),   # Eyüp-Alibeyköy
    (41.1200, 28.7200, 1.5, 0.67),   # Arnavutköy
    # ── NİSBETEN AÇIK BÖLGELER ───────────────────────────────
    (41.1700, 29.0200, 2.0, 1.20),   # Beykoz kuzey (az trafik)
    (41.2000, 28.7500, 2.0, 1.25),   # Çatalca (az trafik)
    (40.8800, 29.3000, 2.0, 1.20),   # Tuzla sanayi (akıcı)
    (41.1500, 29.0500, 1.5, 1.10),   # Sancaktepe doğu
]

# ──────────────────────────────────────────────────────────
# GLOBAL LOCK + CACHE
# ──────────────────────────────────────────────────────────
_lock = threading.Lock()

MEMORY_DB   = {}
IS_DB_READY = False
DURAK_DICT  = {}

FILO_CACHE = {"ts":0,"liste":[],"kapi_map":{}}
FILO_ARALIK = 120    # 2 dakikada bir — uzun duruş tespiti için

LIVE_BUS_CACHE = {}   # hat_kodu → {"raw":[], "normalized":[], "ts":float}

# FIX: Tek /api/bildirimler endpoint — çift tanım kaldırıldı
OLAY_CACHE = {
    "kaza":   {"ts":0,"aralik":1200,"veri":[]},
    "ariza":  {"ts":0,"aralik":1200,"veri":[]},
    "duyuru": {"ts":0,"aralik":300, "veri":[]},
}

API_RESPONSE_CACHE = {}

HAFTALIK = {
    "ts":0,"haftaici":{},"haftasonu":{},
    "top_hi":[],"top_hs":[],"toplam_hi":0,"toplam_hs":0,
}

ARSIV_CACHE      = {
    "ts": 0,
    "hat_gorev":   {},   # hat_kodu → planlanan sefer sayısı
    "arac_yuku":   {},   # kapi     → {sure_saat, sefer_say, kategori, hat}
    "hat_yk":      {},   # hat_kodu → YK (Yarım Kaldı) sefer sayısı
    "yuk_ozet":    {"kritik":0, "normal":0, "dusuk":0, "toplam_aktif":0},
    "en_yorgun":   [],   # [{"kapi","hat","sure_saat","sefer_say","kategori"}] ilk 10
    "veri_tarihi": "",
    # YENİ: Sefer tamamlanma oranları (T=tamamlandı, YK=yarım kaldı)
    # {hat_kodu: {"tamamlanan":int, "yarim_kaldi":int, "oran_yuzde":float}}
    "hat_tamamlanma": {},
    # YENİ: Ağ geneli T/YK özeti
    "tamamlanma_ozet": {"toplam_t":0, "toplam_yk":0, "oran_yuzde":0.0},
}

# Hat bilgi cache: GetHat_json → SEFER_SURESI, HAT_UZUNLUGU (saatlik yenileme)
# {hat_kodu: {"sefer_suresi_dk": float, "hat_uzunlugu_km": float, "hat_adi": str, "ts": float}}
HAT_BILGI_CACHE = {}
SAAT_CACHE       = {}
GECIKME_CACHE    = {}
YOGUNLUK_CACHE   = {}
YOLCU_AGG_HAT    = {}   # Datathon 6 aylık hat bazlı günlük ortalama — hesapla_yogunluk fallback
DURAK_GECMIS     = defaultdict(list)
DURAK_BEKLEME    = {}

# ── YENİ CACHE'LER ─────────────────────────────────────
FILO_DURUM_CACHE    = {"ts":0,"veri":[],"ozet":{}}
PLANA_UYUM_CACHE    = {"ts":0,"veri":[],"ozet":{}}
SEFER_ZAYI_CACHE    = {"ts":0,"veri":[],"ozet":{}}
KAZA_DETAY_CACHE = {"ts": 0, "veri": {}, "aylik": {}, "bugun": []}
YOLCU_TALEP_CACHE   = {"ts":0,"saatlik":{}}           # saat→{hat:talep}
ARAC_OZELLIK_CACHE  = {}                               # kapi→{model,yakit_tipi,klima,...}
IYS_CACHE           = {"ts":0,"veri":[]}               # İş yeri sağlığı
EKSIKLIK_CACHE      = {"ts":0,"veri":[]}               # Eksiklik bildirimleri

# ── UZUN DURUŞ TESPİTİ CACHE'LERİ ──────────────────────────────────────────
ARAC_KONUM_GECMIS = {}   # kapi → [{ts,lat,lon,hiz,hat}]
UZUN_DURUŞ_CACHE  = {}   # kapi → {hat,tur,sure_sn,durak_ad,...}

ANALYSIS_CACHE = {
    "summary": {"passengers": 0, "active_buses": 0, "alerts": 0, "health": 100},
    "passenger":{"labels":[],"hi_vals":[],"hs_vals":[]},
    "fleet":    {"brands":{"labels":[],"values":[]},"density":{"labels":[],"values":[]}},
    "risk_eff": {"risk":{"labels":[],"scores":[],"total":0},"eff":{"labels":[],"scores":[]}},
    "kota":     {"kullanilan":0,"limit":100,"kalan":100},
    "veri_yasi":0,
    # YENİ bölümler
    "operasyonel": {"plana_uyum_ort":0,"zayi_sefer":0,"aktif_arac":0,"depoda_arac":0,"ariza_arac":0},
    "gercek_zamanli": {"filo_durum":{},"kaza_bugun":0,"ariza_aktif":0,"sefer_oran":0},
}

# ──────────────────────────────────────────────────────────
# PANEL DATA — Pre-computed JSONs + SQLite
# ──────────────────────────────────────────────────────────
import os as _os, sqlite3 as _sqlite3

_HERE        = _os.path.dirname(_os.path.abspath(__file__))
PANEL_DIR    = _os.path.join(_HERE, '..', 'Datathon', 'panel_data')
PANEL_DB_PATH = _os.path.join(PANEL_DIR, 'iett_data.db')

PANEL_DATA = {}   # startup'ta JSON'lar buraya yüklenir
HAT_KAPASITE = {}  # hat_kodu → gerçek ortalama kapasite (sefer tablosundan)

# V5 LightGBM model yükleyici kaldırıldı (final_model_A/B.pkl artıkları silindi).
# Panel artık predictions_q3_v6_5.csv kullanıyor (Q3 sayfası).

_PANEL_FILES = {
    # H1 ham veri agregatleri (Datathon notebook ciktilari)
    'ariza_ozet':            'ariza_ozet.json',
    'ariza_hat':             'ariza_hat.json',
    'yolcu_agg':             'yolcu_agg.json',
    'bilet_agg':             'bilet_agg.json',
    'sefer_agg':             'sefer_agg.json',
    'denetim_agg':           'denetim_agg.json',
    'kaza_geojson':          'kaza_geojson.json',
    'hat_master':            'hat_master.json',
    'hat_elevation':         'hat_elevation.json',
    'hat_guzergah_geo':      'hat_guzergah_geo.json',
    'hat_saat_isi':          'hat_saat_isi.json',
    'arac_master':           'arac_master.json',
    'kapino_km':             'kapino_km.json',
    'kapino_elevation':      'kapino_elevation.json',
    'kapino_sefer_gunler':   'kapino_sefer_gunler.json',
    'kapino_sefer_saatleri': 'kapino_sefer_saatleri.json',
    'garaj_risk':            'garaj_risk.json',
    'garaj_performans':      'garaj_performans.json',
    'kaskad_arac':           'kaskad_arac.json',
    'kaskad_hat':            'kaskad_hat.json',
    'aktarma_pattern':       'aktarma_pattern.json',
    'filo_yolcu_agg':        'filo_yolcu_agg.json',
    'operator_garaj_agg':    'operator_garaj_agg.json',
    'mevsim_carpan':         'mevsim_carpan.json',
    'bakim_takvimi':         'bakim_takvimi.json',
    'hat_kapasite':          'hat_kapasite.json',        # HAT_KAPASITE_BUILD.ipynb
    # H1 operasyonel skorlar (notebook ciktilari, ML degil)
    'smart_maintenance':     'smart_maintenance.json',   # H1_OPERASYONEL_SKOR.ipynb
    'sofor_risk':            'sofor_risk.json',          # SOFOR_RISK_BUILD.ipynb
}

def load_panel_data():
    """Tüm panel JSON'larını RAM'e yükle. start_background_threads'da çağrılır."""
    global PANEL_DATA
    loaded = 0
    for key, fname in _PANEL_FILES.items():
        path = _os.path.join(PANEL_DIR, fname)
        if _os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                PANEL_DATA[key] = json.load(f)
            sz = _os.path.getsize(path) / 1024
            print(f"  [PANEL] {fname} ({sz:.0f} KB) yuklendi")
            loaded += 1
        else:
            print(f"  [PANEL] UYARI: {fname} bulunamadi — {path}")
    print(f"[PANEL] {loaded}/{len(_PANEL_FILES)} JSON yuklendi.")

    # Hızlı KAPINO lookup için liste → dict index oluştur
    sm = PANEL_DATA.get('smart_maintenance')
    if isinstance(sm, list):
        PANEL_DATA['_sm_idx'] = {x.get('kapino', x.get('KAPINO','')): x for x in sm}
        print(f"  [PANEL] smart_maintenance index: {len(PANEL_DATA['_sm_idx'])} arac")

    # ── Hat bazlı gerçek araç kapasitesi — hat_kapasite.json'dan oku ──
    # Önceden HAT_KAPASITE_BUILD.ipynb ile üretilmiş (sefer tablosundan ön-hesap)
    global HAT_KAPASITE
    HAT_KAPASITE = PANEL_DATA.get('hat_kapasite', {}) or {}
    if HAT_KAPASITE:
        print(f"  [PANEL] HAT_KAPASITE: {len(HAT_KAPASITE)} hat (hat_kapasite.json'dan)")
    else:
        print("  [PANEL] HAT_KAPASITE: hat_kapasite.json yok — fallback default 90 kullanilacak")

    # ── Yolcu verisini ANALYSIS_CACHE'e datathon'dan besle ──
    # JSON şeması: YOLCULUK_AGG_ANALIZ.ipynb çıktısı (top_hatlar/saat_dagilim/ay_dagilim)
    yolcu = PANEL_DATA.get('yolcu_agg', {})
    if yolcu:
        kpi      = yolcu.get('kpi', {})
        hat_list = yolcu.get('top_hatlar', [])     # 30 hat (hat/ad/yolculuk)
        saat_lst = yolcu.get('saat_dagilim', [])   # 24 saat (saat/yolculuk)
        aylik    = yolcu.get('ay_dagilim', [])     # 6 ay (ay/yolculuk)
        ilce_lst = yolcu.get('ilce_bazli', [])     # 40 ilçe

        toplam   = kpi.get('toplam_yolculuk', 0)
        # KPI'da hazır haftalık ortalama varsa onu kullan, yoksa 26 haftaya böl
        haftalik = kpi.get('haftalik_ort') or (int(toplam / 26) if toplam else 0)

        # Top 12 hat — yolculuk'a göre sırala
        top_hatlar = sorted(
            [h for h in hat_list if h.get('hat') and h.get('hat') != 'Bilinmiyor'],
            key=lambda x: x.get('yolculuk', 0), reverse=True
        )[:12]

        # Hat cinsi haritası — hat_master.json'dan oku (RAM'de hazır, SQL yok)
        _hat_cinsi_map = {}
        hm = PANEL_DATA.get('hat_master', [])
        if isinstance(hm, list):
            for h in hm:
                kod = h.get('HATKODU') or h.get('hatkodu', '')
                cinsi = h.get('hatcinsi', '') or h.get('HATCINSI', '')
                if kod and cinsi:
                    _hat_cinsi_map[str(kod)] = str(cinsi).strip()

        # Saatlik dağılım — normalize
        saat_vals = [0] * 24
        for s in saat_lst:
            saat_no = int(s.get('saat', 0) or 0)
            if 0 <= saat_no < 24:
                saat_vals[saat_no] = s.get('yolculuk', 0)
        maks = max(saat_vals) or 1
        saat_norm = [round(v / maks, 3) for v in saat_vals]

        # Metrobüs hatlarını DİNAMİK belirle (hardcoded liste yerine HATCINSI'ndan)
        metro_hatlar = [
            {'kod': h.get('hat',''), 'ad': h.get('ad',''), 'yolcu': h.get('yolculuk', 0)}
            for h in hat_list
            if 'METROB' in _hat_cinsi_map.get(h.get('hat',''), '').upper()
        ]

        # Haftaiçi/haftasonu: H1 2025 genel oran (gerçek SQL: hi=%79.2, hs=%20.8)
        # NOT: Hat bazlı detay için yolcu_agg.json'a HAFTASONU agregat eklenmeli
        #      (YOLCULUK_AGG_ANALIZ.ipynb'de SELECT ... HAFTASONU GROUP BY hat).
        #      Şu anda startup'ta 5.1M satır taramamak için global oran kullanıyoruz.
        hi_vals, hs_vals = [], []
        for h in top_hatlar:
            _y = h.get('yolculuk', 0)
            hi_vals.append(int(_y * 0.79))
            hs_vals.append(int(_y * 0.21))

        ANALYSIS_CACHE['summary']['passengers']               = haftalik
        ANALYSIS_CACHE['summary_display'] = ANALYSIS_CACHE.get('summary_display', {})
        ANALYSIS_CACHE['summary_display']['passengers']       = f"{toplam/1_000_000:.1f}M (6 ay)"
        ANALYSIS_CACHE['passenger'] = {
            'labels':       [h['hat'] for h in top_hatlar],
            'hi_vals':      hi_vals,                # haftaiçi (%79 genel oran)
            'hs_vals':      hs_vals,                # haftasonu (%21 genel oran)
            'hat_cinsi':    [_hat_cinsi_map.get(h['hat'], '') for h in top_hatlar],
            'metro_hatlar': metro_hatlar,
            'saat_norm':    saat_norm,
            'aylik':        [{'ay': a.get('ay'), 'yolcu': a.get('yolculuk', 0)} for a in aylik],
            'toplam':       toplam,
            'haftalik':     haftalik,
            'benzersiz_hat':   kpi.get('hat_sayisi', 0),
            'benzersiz_durak': kpi.get('durak_sayisi', 0),
            'aktarma_pct':     kpi.get('aktarma_orani_pct', 0),
            'kaynak':       'YOLCULUK CSV — H1 2025 ham agregat',
        }
        print(f"  [PANEL] yolcu_agg → ANALYSIS_CACHE: {toplam:,} yolcu | {len(top_hatlar)} top hat | {len(metro_hatlar)} metro")

    # ── Datathon yolcu verisini ayrı bir cache'e al — HAFTALIK'a karıştırma ──
    # HAFTALIK = IBB canlı API verisi (son 7 gün)
    # YOLCU_AGG_HAT = Datathon 6 aylık ortalama — hesapla_yogunluk'ta fallback olarak kullanılır
    try:
        hat_list_all = yolcu.get('top_hatlar', []) if yolcu else []
        if hat_list_all:
            global YOLCU_AGG_HAT
            YOLCU_AGG_HAT = {}
            for h in hat_list_all:
                hk = h.get('hat', '')
                if not hk or hk == 'Bilinmiyor':
                    continue
                gun_ort = int(h.get('yolculuk', 0) / 180)  # 6 ay ≈ 180 gün
                if gun_ort > 0:
                    # Haftaiçi gün ortalaması (haftaiçi yolculuk ≈ 1.4× genel ortalama)
                    YOLCU_AGG_HAT[hk] = {
                        'hi': int(gun_ort * 1.4),
                        'hs': int(gun_ort * 0.6),
                    }
            print(f"  [PANEL] YOLCU_AGG_HAT: {len(YOLCU_AGG_HAT)} hat Datathon ortalamasiyla hazir")
    except Exception as _he:
        print(f"  [PANEL] YOLCU_AGG_HAT hatasi: {_he}")

def get_panel_db():
    """Her istek icin yeni SQLite baglantisi acar (thread-safe)."""
    return _sqlite3.connect(PANEL_DB_PATH, check_same_thread=False)

# ──────────────────────────────────────────────────────────
# YARDIMCILAR
# ──────────────────────────────────────────────────────────

def hat_skoru(hat_kodu):
    with _lock:
        live_data = LIVE_BUS_CACHE.get(hat_kodu, {})
        live_say = len(live_data.get("normalized", [])) if isinstance(live_data, dict) else 0
        haftalik = HAFTALIK.get("haftaici", {}).get(hat_kodu, 0)
        gorev = ARSIV_CACHE.get("hat_gorev", {}).get(hat_kodu, 0)

    return (live_say * 1000) + (gorev * 10) + haftalik

# ──────────────────────────────────────────────────────────
# TRAFİK
# ──────────────────────────────────────────────────────────
def trafik_seviye(k):
    # Eşikler IBB TrafficIndex ölçeğiyle hizalandı:
    #   IBB ~30 → serbest, ~50 → akıcı, ~65 → yoğun, ~80 → tıkanık, ~92+ → dur-kalk
    if k >= 0.78: return "serbest",  "#22c55e"
    if k >= 0.63: return "akıcı",    "#84cc16"
    if k >= 0.48: return "yoğun",    "#f59e0b"
    if k >= 0.33: return "tıkanık",  "#ef4444"
    return "dur-kalk", "#991b1b"

def koridor_katsayi(lat, lon):
    k = 1.0
    en_yogun = 1.0   # en yogun (en dusuk katsayili) koridor etkisi
    en_acik  = 1.0   # en acik (en yuksek katsayili) koridor etkisi
    etkilendi = False
    for clat, clon, r, ag in KORIDOR_AGIRLIKLARI:
        d = hav(lat, lon, clat, clon)
        if d < r:
            etkilendi = True
            etki = ag + (1.0 - ag) * (d / r)   # merkeze yaklastikca ag'a yaklasir
            if ag <= 1.0:
                en_yogun = min(en_yogun, etki)  # yogun bolgeler: en kotusunu al
            else:
                en_acik = max(en_acik, etki)    # acik bolgeler: en iyisini al
    if not etkilendi:
        return 1.0
    # Yogun koridor varsa onu, yoksa acik koridor etkisini uygula
    if en_yogun < 1.0:
        return round(en_yogun, 4)
    return round(en_acik, 4)

def saat_trafik_katsayi(lat=None, lon=None):
    simdi = datetime.now()
    saat = simdi.hour
    hici = simdi.weekday() < 5
    th, ts = ISTANBUL_PROFIL.get(saat, (0.75, 0.75))
    kats = th if hici else ts
    if lat is not None and lon is not None:
        kats *= koridor_katsayi(lat, lon)
    return round(max(0.25, kats), 3)

def tomtom_trafik_katsayi(lat,lon):
    if not TOMTOM_KEY: return None
    cache_key=f"{lat:.4f},{lon:.4f}"
    with TRAFIK_LOCK:
        c=TRAFIK_CACHE.get(cache_key)
        if c and time.time()-c["ts"]<TRAFIK_TTL: return c
    try:
        r=requests.get(TOMTOM_FLOW_URL,
            params={"key":TOMTOM_KEY,"point":f"{lat},{lon}","unit":"KMPH","openLr":"false"},timeout=5)
        if r.status_code==200:
            d=r.json().get("flowSegmentData",{})
            cur=float(d.get("currentSpeed",0)); ff=float(d.get("freeFlowSpeed",1))
            if ff>0:
                kats=round(min(1.0,cur/ff),3); sev,renk=trafik_seviye(kats)
                rec={"ts":time.time(),"katsayi":kats,"hiz_mevcut":cur,"hiz_serbest":ff,
                     "seviye":sev,"renk":renk,"kaynak":"tomtom"}
                with TRAFIK_LOCK: TRAFIK_CACHE[cache_key]=rec
                return rec
    except Exception as e: print(f"⚠️ [TOMTOM] {e}")
    return None

def ibb_trafik_katsayi():
    """
    IBB TrafficIndex geçmişinden en güncel değeri alır ve katsayıya (0.0-1.0) çevirir.
    traffic_index: 0 = tamamen serbest, 100 = tam tıkanık → katsayi = 1 - (index/100)
    Cache zaten get_traffic_index_history içinde yönetiliyor (TTL=120s).
    """
    try:
        ozet = get_traffic_index_history_summary(day=1, period="5M")
        values = ozet.get("values", [])
        if not values:
            return None
        # En güncel değer listenin sonunda
        son_index = values[-1]
        if not isinstance(son_index, (int, float)) or son_index < 0:
            return None
        # 0->1.0 (serbest), 100->0.25 (dur-kalk) — linear map
        kats = round(max(0.25, 1.0 - (son_index / 100.0) * 0.75), 3)
        sev, renk = trafik_seviye(kats)
        return {
            "ts": time.time(),
            "katsayi": kats,
            "hiz_mevcut": 0,
            "hiz_serbest": 0,
            "seviye": sev,
            "renk": renk,
            "kaynak": "ibb_traffic_index",
            "ibb_index": son_index,
        }
    except Exception as e:
        print(f"⚠️ [IBB_TRAFIK] {e}")
        return None

def get_trafik(lat, lon):
    # 1. IBB TrafficIndex (şehir geneli canlı veri — öncelikli kaynak)
    ibb = ibb_trafik_katsayi()
    if ibb:
        # IBB index zaten şehir geneli trafik yoğunluğunu yansıtır; üstüne tam koridor
        # çarpanı uygulamak çift ceza oluşturur (index=56 + koridor=0.62 → dur-kalk 💥).
        # Koridor etkisini hafifçe (±%15) ekleyerek yerel renk katıyoruz.
        kor = koridor_katsayi(lat, lon)
        kor_hafif = 1.0 + (kor - 1.0) * 0.25   # tam etki %25'e indirgendi
        kats_nokta = round(max(0.20, min(1.0, ibb['katsayi'] * kor_hafif)), 3)
        sev, renk = trafik_seviye(kats_nokta)
        return {**ibb, 'katsayi': kats_nokta, 'seviye': sev, 'renk': renk,
                'koridor_kats': kor, 'kaynak': 'ibb_traffic_index'}
    # 2. TomTom (gerçek nokta bazlı, API key gerekli)
    tt = tomtom_trafik_katsayi(lat, lon)
    if tt: return tt
    # 3. Son çare: saat + koridor profili (IBB erişilemez)
    kats = saat_trafik_katsayi(lat, lon)
    sev, renk = trafik_seviye(kats)
    return {'katsayi': kats, 'hiz_mevcut': 0, 'hiz_serbest': 0,
            'seviye': sev, 'renk': renk, 'kaynak': 'profil'}

def _parse_traffic_index_history_xml(xml_text, period="5M"):
    root = parse_xml_root(xml_text)
    if root is None:
        return []

    items = xml_findall_local(root, "ResponseTrafficIndexHistory")
    sonuc = []

    for item in items:
        traffic_index = safe_int(xml_child_text(item, "TrafficIndex", "0"), 0)
        traffic_index_date = xml_child_text(item, "TrafficIndexDate", "")

        sonuc.append(
            TrafficIndexHistoryItem(
                traffic_index=traffic_index,
                traffic_index_date=traffic_index_date,
                period=period
            )
        )

    return sonuc

def _parse_traffic_index_history_json(payload, period="5M"):
    sonuc = []
    if isinstance(payload, dict):
        payload = payload.get("data", []) or payload.get("items", []) or []

    if not isinstance(payload, list):
        return sonuc

    for row in payload:
        if not isinstance(row, dict):
            continue

        sonuc.append(
            TrafficIndexHistoryItem(
                traffic_index=safe_int(row.get("TrafficIndex", 0), 0),
                traffic_index_date=temiz_str(row.get("TrafficIndexDate", "")),
                period=period
            )
        )

    return sonuc

def get_traffic_index_history(day=1, period="5M", force=False):
    day = max(1, int(day or 1))
    period = temiz_str(period, "5M").upper()
    cache_key = f"{day}:{period}"
    now = time.time()

    with _lock:
        if (
            not force and
            TRAFFIC_HISTORY_CACHE["key"] == cache_key and
            (now - TRAFFIC_HISTORY_CACHE["ts"]) < TRAFFIC_HISTORY_TTL
        ):
            return TRAFFIC_HISTORY_CACHE["data"]

    url = f"{URL_TRAFFIC_REST}/api/TrafficData/v1/TrafficIndexHistory/{day}/{period}"

    try:
        r = requests.get(
            url,
            timeout=12,
            headers={"Accept": "application/json, text/json, application/xml, text/xml"}
        )

        if r.status_code != 200:
            print(f"⚠️ [TRAFFIC_INDEX_HISTORY] HTTP {r.status_code}")
            return []

        text = (r.text or "").strip()
        content_type = (r.headers.get("Content-Type") or "").lower()

        if text.startswith("[") or text.startswith("{") or "json" in content_type:
            try:
                payload = r.json()
            except Exception:
                payload = json.loads(text)
            sonuc = _parse_traffic_index_history_json(payload, period=period)
        else:
            sonuc = _parse_traffic_index_history_xml(text, period=period)

        with _lock:
            TRAFFIC_HISTORY_CACHE["ts"] = now
            TRAFFIC_HISTORY_CACHE["key"] = cache_key
            TRAFFIC_HISTORY_CACHE["data"] = sonuc

        return sonuc

    except Exception as e:
        print(f"❌ [TRAFFIC_INDEX_HISTORY] {type(e).__name__}: {e}")
        return []

def get_traffic_index_history_summary(day=1, period="5M", force=False):
    """
    Ham trafik indeks geçmişini çeker ve grafiklerde/dashboard'da 
    kolayca kullanılabilecek şekilde özet bir formata (labels, values) dönüştürür.
    """
    # 1. Senin zaten yazmış olduğun ana fonksiyonu çağırıyoruz
    raw_data = get_traffic_index_history(day=day, period=period, force=force)
    
    if not raw_data:
        return {"labels": [], "values": [], "max": 0, "min": 0, "avg": 0, "adet": 0}
        
    labels = []
    values = []
    
    for item in raw_data:
        # Tarih formatı "2024-10-24T14:05:00" şeklinde geliyor. 
        # Grafikte sırıtmasın diye sadece "14:05" kısmını alıyoruz.
        tarih_str = item.traffic_index_date
        saat = tarih_str.split("T")[-1][:5] if "T" in tarih_str else tarih_str
        
        labels.append(saat)
        values.append(item.traffic_index)
        
    # Grafiğin üst kısmına yazdırmak istersin diye basit istatistikler
    max_val = max(values) if values else 0
    min_val = min(values) if values else 0
    avg_val = round(sum(values) / len(values), 1) if values else 0
    
    return {
        "labels": labels,
        "values": values,
        "max": max_val,
        "min": min_val,
        "avg": avg_val,
        "adet": len(values)
    }
def guncelle_kavsaklar(force=False):
    global KAVSAK_CACHE
    import time
    import requests
    import xml.etree.ElementTree as ET
    now = time.time()

    with _lock:
        if not force and (now - KAVSAK_CACHE["ts"]) < 3600:
            return KAVSAK_CACHE["veri"]

    kavsaklar = []
    url = "https://api.ibb.gov.tr/web/api/junction"
    
    try:
        # 1. Tarayıcı gibi davranıyoruz ve her formata açığız diyoruz
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json, text/xml, application/xml, */*'
        }
        
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code == 200:
            icerik = response.text.strip()
            
            # DURUM A: Gelen veri JSON ise ('[' veya '{' ile başlıyorsa)
            if icerik.startswith('[') or icerik.startswith('{'):
                import json
                data = response.json()
                items = data if isinstance(data, list) else data.get("data", [])
                
                for item in items:
                    kavsaklar.append({
                        "id": item.get("JunctionNo", 0),
                        "kavsak_no": item.get("JunctionNo", 0),
                        "ad": item.get("JunctionName", ""),
                        "lat": item.get("YCoord", 0),
                        "lon": item.get("XCoord", 0),
                        "durum": "NORMAL", "ilce": "", "yaka": ""
                    })
                    
            # DURUM B: Gelen veri XML ise ('<' ile başlıyorsa)
            elif icerik.startswith('<'):
                from utils import xml_findall_local, xml_child_text, safe_int, temiz_str, temiz_sayi
                root = ET.fromstring(response.content)
                items = xml_findall_local(root, "JunctionModel_v3")
                
                for item in items:
                    kavsaklar.append({
                        "id": safe_int(xml_child_text(item, "JunctionNo", "0")),
                        "kavsak_no": safe_int(xml_child_text(item, "JunctionNo", "0")),
                        "ad": temiz_str(xml_child_text(item, "JunctionName", "")),
                        "lat": temiz_sayi(xml_child_text(item, "YCoord", "0")),
                        "lon": temiz_sayi(xml_child_text(item, "XCoord", "0")),
                        "durum": "NORMAL", "ilce": "", "yaka": ""
                    })
            else:
                print("❌ İBB ne XML ne JSON döndü! Gelen garip veri:")
                print(icerik[:200])

            # Verileri kaydet
            if kavsaklar:
                with _lock:
                    KAVSAK_CACHE["ts"] = now
                    KAVSAK_CACHE["veri"] = kavsaklar
                print(f"✅ [KAVŞAK] {len(kavsaklar)} kavşak zırhlı kodla çekildi.")
                
        else:
            print(f"❌ İBB Kavşak API HTTP Hatası: {response.status_code}")
            print("Sunucu Cevabı:", response.text[:200])
            
    except Exception as e:
        print(f"❌ Kavşak API Okuma Patladı: {e}")

    return kavsaklar
# ──────────────────────────────────────────────────────────
# SOAP YARDIMCILARI
# ──────────────────────────────────────────────────────────
def fetch_soap(url,action,body_content,timeout_sec=10,use_auth=True):
    auth=(f'<soap:Header><AuthHeader xmlns="http://tempuri.org/">'
          f'<Username>{IETT_USER}</Username><Password>{IETT_PASS}</Password>'
          f'</AuthHeader></soap:Header>') if use_auth else ''
    env=(f'<?xml version="1.0" encoding="utf-8"?>'
         f'<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
         f'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
         f'xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
         f'{auth}<soap:Body>{body_content}</soap:Body></soap:Envelope>')
    hdrs={'Content-Type':'text/xml; charset=utf-8','SOAPAction':f'http://tempuri.org/{action}'}
    try:
        max_deneme = 3
        for deneme in range(max_deneme):
            r = requests.post(
                url,
                data=env.encode("utf-8"),
                headers=hdrs,
                timeout=timeout_sec
            )
            if r.status_code==429:
                bekleme = 2 ** deneme
                print(f"🚫 [SOAP] {action} → 429, {bekleme}s sonra tekrar denenecek...")
                time.sleep(bekleme)
                continue

            if r.status_code!= 200:
                print(f"⚠️  [SOAP] {action} → HTTP {r.status_code}")
                return []
            root=ET.fromstring(r.content)

            for el in root.iter():
                tag=el.tag.split('}')[-1]
                if tag==f'{action}Result' and el.text:
                    try:
                        p=json.loads(el.text.strip())
                        if isinstance(p,str):
                            try: p=json.loads(p)
                            except Exception:
                                pass
                        if isinstance(p,dict) and 'Table' in p: 
                            return p['Table']
                        return p
                    except Exception as je:
                        print(f"⚠️  [SOAP] {action} JSON: {je}")
                        return []
            return []

        print(f"🚫 [SOAP] {action} → 429 nedeniyle tüm tekrar denemeler başarısız")
        return []

    except requests.exceptions.Timeout:
        print(f"⏱️  [SOAP] {action} TIMEOUT ({timeout_sec}s)")
        return []

    except Exception as e:
        print(f"❌ [SOAP] {action}: {type(e).__name__}: {e}")
        return []

def fetch_soap_xml(url,action,body_content,timeout_sec=10,use_auth=True):
    auth=(f'<soap:Header><AuthHeader xmlns="http://tempuri.org/">'
          f'<Username>{IETT_USER}</Username><Password>{IETT_PASS}</Password>'
          f'</AuthHeader></soap:Header>') if use_auth else ''
    env=(f'<?xml version="1.0" encoding="utf-8"?>'
         f'<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
         f'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
         f'xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
         f'{auth}<soap:Body>{body_content}</soap:Body></soap:Envelope>')
    hdrs={'Content-Type':'text/xml; charset=utf-8','SOAPAction':f'http://tempuri.org/{action}'}
    try:
        r=requests.post(url,data=env.encode('utf-8'),headers=hdrs,timeout=timeout_sec)
        if r.status_code==200: return ET.fromstring(r.content)
        return None
    except Exception:
        return None

# ──────────────────────────────────────────────────────────
# ARAÇ NORMALİZASYON
# ──────────────────────────────────────────────────────────
def normalize_arac(b, kapi_map=None):
    if not isinstance(b, dict):
        return None

    kapi = temiz_str(alan_oku(
        b,
        'KapiNo', 'kapino', 'KAPINO', 'kapiNo', 'KAPINUMARASI'
    ))

    lat = temiz_sayi(alan_oku(
        b,
        'Enlem', 'enlem', 'ENLEM', 'NENLEM', 'lat', 'LAT',
        varsayilan=0
    ))

    lon = temiz_sayi(alan_oku(
        b,
        'Boylam', 'boylam', 'BOYLAM', 'NBOYLAM', 'lon', 'LON',
        varsayilan=0
    ))

    if abs(lat) < 1 or abs(lon) < 1:
        return None
    if not (40.5 <= lat <= 41.7 and 27.9 <= lon <= 30.2):
        return None

    hiz_raw = alan_oku(
        b,
        'Hiz', 'hiz', 'HIZ', 'Hız', 'HizKmSaat',
        'SHIZ', 'Speed', 'SPEED', 'speed',
        'AnlikHiz', 'ANLIKHIZ', 'AracHizi', 'ARACHIZI',
        'VELOCITY', 'Velocity',
        varsayilan=0
    )
    hiz = int(round(temiz_sayi(hiz_raw, 0)))
    if hiz < 0:
        hiz = 0
    if hiz > 130:
        hiz = 130

    saat = temiz_str(alan_oku(
        b,
        'Saat', 'SAAT', 'saat'
    ), '—')

    guz = temiz_str(alan_oku(
        b,
        'GuzergahKodu', 'guzergahkodu', 'GUZERGAHKODU', 'SGUZERGAHKODU'
    ))
    # 'yon' alanı terminal adı döndürür (örn: 'ŞİFA SONDURAK') — yön için kullanılmaz
    # Yön sadece guzergahkodu içindeki _G_/_D_ marker'ından alınır
    yon = _yon_coz(guz)

    plaka = temiz_str(alan_oku(b, 'Plaka', 'plaka', 'PLAKA', 'SPLAKAADI'), '—')
    op = temiz_str(alan_oku(b, 'Operator', 'operator', 'OPERATOR', 'SOPERATORADI'), 'İETT')
    garaj = temiz_str(alan_oku(b, 'Garaj', 'garaj', 'GARAJ', 'SGARAJADI'), '—')

    if kapi_map and kapi and kapi in kapi_map:
        info = kapi_map[kapi]
        if plaka == '—':
            plaka = info.get('plaka', '—')
        if op == 'İETT':
            op = info.get('op', 'İETT')
        if garaj == '—':
            garaj = info.get('garaj', '—')

    return {
        "kapi": kapi or '?',
        "lat": lat,
        "lon": lon,
        "hiz": hiz,
        "yon": yon,
        "plaka": plaka,
        "op": op,
        "garaj": garaj,
        "saat": saat
    }
def _yon_coz(guz, yon_raw=None, hat_kodu=''):
    """
    SGUZERGAHKODU formatı: '{HAT}_{G|D}_{D+sefer}'
    Örnekler: '500T_G_D0', '76D_D_D7691', '16D_G_D0', '34_D_D9018'
    _G_ veya _D_ marker'ı her zaman mevcut — tek güvenilir kaynak.

    NOT: GetHatOtoKonum'daki 'yon' alanı terminal adıdır ('ŞİFA SONDURAK' gibi),
    yön bilgisi DEĞILDIR. GetFiloAracKonum'da hiç yön/güzergah alanı yoktur.
    """
    import re as _re
    if guz:
        g = guz.upper()
        if _re.search(r'[_\-]G[_\-]', g):
            return 'G'
        if _re.search(r'[_\-]D[_\-]', g):
            return 'D'
    return None

# ──────────────────────────────────────────────────────────
# ★ ETA DÜZELTME — Araç yön vektörü kontrolü
# ──────────────────────────────────────────────────────────
def arac_durak_yaklasiyor_mu(arac_lat, arac_lon, arac_yon, durak_lat, durak_lon, hat_duraklar):
    """
    Araç durağa doğru mu yaklaşıyor, yoksa uzaklaşıyor mu?
    Güzergah sırasına göre kontrol eder.
    Returns: (yaklasiyor:bool, durak_sirasi_farki:int)
    """
    if not hat_duraklar:
        return True, 0

    yon_duraklar = [d for d in hat_duraklar if d.get('yon') == arac_yon and d.get('lat', 0) > 0]
    if not yon_duraklar:
        return True, 0

    def en_yakin_idx(lat, lon, duraklar):
        min_d, idx = 9999, 0
        for i, d in enumerate(duraklar):
            dist = hav(lat, lon, d['lat'], d['lon'])
            if dist < min_d:
                min_d = dist; idx = i
        return idx, min_d

    arac_idx, _ = en_yakin_idx(arac_lat, arac_lon, yon_duraklar)
    hedef_idx, _ = en_yakin_idx(durak_lat, durak_lon, yon_duraklar)

    if arac_idx > hedef_idx:
        return False, arac_idx - hedef_idx
    return True, hedef_idx - arac_idx


def rota_mesafe_km(arac_lat, arac_lon, durak_lat, durak_lon, arac_yon, hat_duraklar):
    """Kuş uçuşu yerine durak sırası üzerinden yaklaşık hat üstü mesafe hesaplar."""
    try:
        yon_duraklar = [d for d in hat_duraklar if d.get('yon') == arac_yon and d.get('lat', 0) > 0 and d.get('lon', 0) > 0]
        if len(yon_duraklar) < 2:
            return hav(arac_lat, arac_lon, durak_lat, durak_lon)

        def en_yakin_idx(lat, lon):
            min_d, idx = 9999, 0
            for i, d in enumerate(yon_duraklar):
                dist = hav(lat, lon, d['lat'], d['lon'])
                if dist < min_d:
                    min_d = dist; idx = i
            return idx, min_d

        arac_idx, arac_yakin_km = en_yakin_idx(arac_lat, arac_lon)
        hedef_idx, hedef_yakin_km = en_yakin_idx(durak_lat, durak_lon)

        if arac_idx > hedef_idx:
            return hav(arac_lat, arac_lon, durak_lat, durak_lon)

        rota_km = arac_yakin_km + hedef_yakin_km
        for i in range(arac_idx, hedef_idx):
            a = yon_duraklar[i]
            b = yon_duraklar[i + 1]
            rota_km += hav(a['lat'], a['lon'], b['lat'], b['lon'])

        kus_ucusu = hav(arac_lat, arac_lon, durak_lat, durak_lon)
        if rota_km < kus_ucusu:
            rota_km = kus_ucusu
        return round(rota_km, 3)
    except Exception:
        return hav(arac_lat, arac_lon, durak_lat, durak_lon)

# ──────────────────────────────────────────────────────────
# CANLI ARAÇ CACHE
# ──────────────────────────────────────────────────────────
def get_live_buses_cached(hat_kodu, force_refresh=False):
    """
    Canlı araç konumlarını çeker.
    Önce hat bazlı GetHatOtoKonum_json dener.
    Yön bilgisi FILO_CACHE["kapi_map"]'teki hat+yon verisinden gelir (GetIettArsivGorev_json kaynaklı).
    Hız bilgisi GetFiloAracKonum_json'dan gelen gerçek Hiz/HIZ alanından alınır.
    """
    now = time.time()

    with _lock:
        cached = LIVE_BUS_CACHE.get(hat_kodu)

    if (not force_refresh) and cached and (now - cached["ts"]) < 30:
        return cached["normalized"], cached["raw"]

    # ── 1. Hat bazlı GPS çekimi ──────────────────────────────────────────
    body = f'<GetHatOtoKonum_json xmlns="http://tempuri.org/"><HatKodu>{hat_kodu}</HatKodu></GetHatOtoKonum_json>'
    raw = fetch_soap(URL_FILO, 'GetHatOtoKonum_json', body, timeout_sec=6)

    if not isinstance(raw, list):
        raw = []

    # ── 2. Tüm filo GPS'inden hız ve ek veri çek (kapi_map üzerinden birleştir) ──
    # FILO_CACHE zaten tüm filo verisini tutuyor, ayrı istek atmaya gerek yok.
    with _lock:
        kapi_map = dict(FILO_CACHE["kapi_map"])
        filo_liste = list(FILO_CACHE["liste"])

    # Filo listesinden KapiNo → ham veri sözlüğü oluştur (hız için)
    filo_dict = {}
    for a in filo_liste:
        kapi = temiz_str(alan_oku(a, 'KapiNo', 'KAPINO', 'kapino', 'kapiNo', 'KAPINUMARASI'))
        if kapi:
            # Hızı referans kodun yaptığı gibi oku: Hiz veya HIZ, virgül→nokta
            hiz_raw = a.get('Hiz') or a.get('HIZ') or 0
            try:
                hiz_val = int(float(str(hiz_raw).replace(',', '.')))
            except Exception:
                hiz_val = 0
            filo_dict[kapi] = {"hiz": max(0, min(130, hiz_val))}

    # ── 3. Ham veri normalize et ──────────────────────────────────────────
    normalized = []
    for b in raw:
        kapi = temiz_str(alan_oku(
            b, 'KapiNo', 'kapino', 'KAPINO', 'kapiNo', 'KAPINUMARASI'))

        lat = temiz_sayi(alan_oku(
            b, 'Enlem', 'enlem', 'ENLEM', 'NENLEM', 'lat', 'LAT', varsayilan=0))
        lon = temiz_sayi(alan_oku(
            b, 'Boylam', 'boylam', 'BOYLAM', 'NBOYLAM', 'lon', 'LON', varsayilan=0))

        if abs(lat) < 1 or abs(lon) < 1:
            continue
        if not (40.5 <= lat <= 41.7 and 27.9 <= lon <= 30.2):
            continue

        # Hız: Önce filo_dict'ten al (GetFiloAracKonum_json'dan — daha güvenilir),
        #      yoksa doğrudan b'den oku
        if kapi and kapi in filo_dict:
            hiz = filo_dict[kapi]["hiz"]
        else:
            hiz_raw = alan_oku(
                b, 'Hiz', 'hiz', 'HIZ', 'Hız', 'HizKmSaat',
                'SHIZ', 'Speed', 'SPEED', 'speed',
                'AnlikHiz', 'ANLIKHIZ', 'AracHizi', 'ARACHIZI',
                varsayilan=0)
            try:
                hiz = int(round(float(str(hiz_raw).replace(',', '.'))))
            except Exception:
                hiz = 0
            hiz = max(0, min(130, hiz))

        # Yön: FILO_CACHE["kapi_map"]'teki GetIettArsivGorev_json kaynaklı bilgiden al
        yon = None
        guzergah = ''
        if kapi and kapi in kapi_map:
            km_info = kapi_map[kapi]
            yon = km_info.get("yon")          # 'G' veya 'D'
            guzergah = km_info.get("guzergah", '')
        if not yon:
            # Fallback: guzergahkodu içindeki _G_/_D_ marker'ından al
            # 'yon' alanı terminal adı olduğu için kullanılmaz
            guz_raw = temiz_str(alan_oku(b, 'GuzergahKodu', 'guzergahkodu', 'GUZERGAHKODU', 'SGUZERGAHKODU'))
            yon = _yon_coz(guz_raw)

        # Plaka / operatör / garaj: kapi_map'ten zenginleştir
        info = kapi_map.get(kapi, {})
        plaka = temiz_str(alan_oku(b, 'Plaka', 'plaka', 'PLAKA', 'SPLAKAADI'), '—')
        op    = temiz_str(alan_oku(b, 'Operator', 'operator', 'OPERATOR', 'SOPERATORADI'), 'İETT')
        garaj = temiz_str(alan_oku(b, 'Garaj', 'garaj', 'GARAJ', 'SGARAJADI'), '—')
        if plaka == '—': plaka = info.get('plaka', '—')
        if op == 'İETT': op = info.get('op', 'İETT')
        if garaj == '—': garaj = info.get('garaj', '—')

        saat = temiz_str(alan_oku(b, 'Saat', 'SAAT', 'saat'), '—')

        # GetHatOtoKonum_json'dan gelen ek alanlar
        yakin_durak = temiz_str(alan_oku(b, 'yakinDurakKodu', 'YakinDurakKodu',
                                         'YAKINDURAKKODU', 'yakin_durak_kodu'), '')
        son_konum_z = temiz_str(alan_oku(b, 'son_konum_zamani', 'SonKonumZamani',
                                          'SONKONUMZAMANI'), '')

        normalized.append({
            "kapi":              kapi or '?',
            "lat":               lat,
            "lon":               lon,
            "hiz":               hiz,
            "yon":               yon,
            "plaka":             plaka,
            "op":                op,
            "garaj":             garaj,
            "saat":              saat,
            "yakin_durak_kodu":  yakin_durak,   # API'den gelen — uzun duruş için kullan
            "son_konum_zamani":  son_konum_z,
        })

    with _lock:
        LIVE_BUS_CACHE[hat_kodu] = {
            "raw": raw,
            "normalized": normalized,
            "ts": now
        }

    return normalized, raw

# ──────────────────────────────────────────────────────────
# YÖN TAHMİNİ
# ──────────────────────────────────────────────────────────
def tahmin_yon_terminal(hat_kodu, araclar_normalized):
    """
    Sadece yön=None olan araçlara durak mesafesiyle tahmin uygular.
    guzergahkodu'ndan gelen (_G_/_D_ marker) kesin yönlere DOKUNMAZ.
    """
    cache_key = f"durak_detay_{hat_kodu}"
    with _lock:
        cached_durak = API_RESPONSE_CACHE.get(cache_key)
    if not cached_durak:
        return araclar_normalized

    duraklar = cached_durak.get("duraklar", [])
    g_duraklar = sorted([d for d in duraklar if d["yon"] == "G" and d["lat"] > 0], key=lambda x: x["sira"])
    d_duraklar = sorted([d for d in duraklar if d["yon"] == "D" and d["lat"] > 0], key=lambda x: x["sira"])
    if not g_duraklar or not d_duraklar:
        return araclar_normalized

    def en_yakin_dist(lat, lon, dl):
        return min((hav(lat, lon, d["lat"], d["lon"]) for d in dl), default=9999)

    duzeltilmis = []
    for arac in araclar_normalized:
        # Yön zaten guzergahkodu'ndan geldiyse kesindir, dokunma
        if arac.get("yon") in ('G', 'D'):
            duzeltilmis.append(arac)
            continue
        # Yön bilinmiyorsa (None) mesafeye göre tahmin et
        lat, lon = arac["lat"], arac["lon"]
        dist_g = en_yakin_dist(lat, lon, g_duraklar)
        dist_d = en_yakin_dist(lat, lon, d_duraklar)
        if dist_g < dist_d * 1.2:
            yon = 'G'
        elif dist_d < dist_g * 1.2:
            yon = 'D'
        else:
            yon = 'G'  # belirsizse gidiş varsayılan
        duzeltilmis.append({**arac, "yon": yon})
    return duzeltilmis

# ──────────────────────────────────────────────────────────
# FILO CACHE
# ──────────────────────────────────────────────────────────
def guncelle_filo(zorunlu=False):
    global FILO_CACHE
    now=time.time()
    with _lock:
        if not zorunlu and (now-FILO_CACHE["ts"])<FILO_ARALIK: 
            return False
    veri=None
    for deneme in range(1,3):
        veri=fetch_soap(URL_FILO,'GetFiloAracKonum_json',
                        '<GetFiloAracKonum_json xmlns="http://tempuri.org/" />',timeout_sec=20)
        if isinstance(veri,list) and veri: break
        if deneme==1: print("[FILO] ilk deneme boş, 5s…"); time.sleep(5)
    if not isinstance(veri,list) or not veri:
        print("[FILO] veri alınamadı"); return False
    kapi_map={}
    for a in veri:
        kapi=temiz_str(alan_oku(a,'KapiNo','KAPINO','kapino','kapiNo','KAPINUMARASI'))
        if not kapi: continue
        lat=temiz_sayi(alan_oku(a,'Enlem','ENLEM','enlem',varsayilan=0))
        lon=temiz_sayi(alan_oku(a,'Boylam','BOYLAM','boylam',varsayilan=0))
        plaka=temiz_str(alan_oku(a,'Plaka','PLAKA','plaka'),'—')
        op=temiz_str(alan_oku(a,'Operator','OPERATOR','operator','SOPERATORADI'),'İETT')
        garaj=temiz_str(alan_oku(a,'Garaj','GARAJ','garaj','SGARAJADI'),'—')
        marka=temiz_str(alan_oku(a,'Marka','MARKA','marka','AracMarka','ARACMARKA','MarkaAdi','MARKAADI'),'')
        tip=temiz_str(alan_oku(a,'Tip','TIP','AracTipi','ARACTIP','Model','MODEL'),'')
        kapi_map[kapi]={"plaka":plaka,"op":op,"garaj":garaj,"lat":lat,"lon":lon,"marka":marka,"tip":tip}
    with _lock:
        FILO_CACHE["ts"] = now
        FILO_CACHE["liste"] = veri
        # Merge: hat/yon/guzergah bilgisini koru, sadece plaka/op/garaj/konum güncelle
        existing = FILO_CACHE["kapi_map"]
        for kp, info in kapi_map.items():
            if kp in existing:
                existing[kp].update(info)
            else:
                existing[kp] = info
        merged = dict(existing)
    print(f"[FILO] {len(veri)} araç güncellendi")

    # Konum geçmişini güncelle → hat bilgisi de taşınıyor artık
    _konum_guncelle(veri, merged)
    threading.Thread(target=hesapla_uzun_duruş, daemon=True).start()

    return True

# ──────────────────────────────────────────────────────────
# ★ YENİ: FILO DURUM (aktif/pasif/depoda/arızalı)
# ──────────────────────────────────────────────────────────
def guncelle_filo_durum(*args, **kwargs):
    return

# ──────────────────────────────────────────────────────────
# ★ YENİ: PLANA UYUM
# ──────────────────────────────────────────────────────────
def guncelle_plana_uyum(*args, **kwargs):
    return

# ──────────────────────────────────────────────────────────
# ★ YENİ: ZAYİ SEFER
# ──────────────────────────────────────────────────────────
def guncelle_sefer_zayi(*args, **kwargs):
    return

# ──────────────────────────────────────────────────────────
# ★ YENİ: OAS KAZA DETAYI (Yıl/Ay bazlı)
# ──────────────────────────────────────────────────────────
def guncelle_oas_kaza(*args, **kwargs):
    return

# ──────────────────────────────────────────────────────────
# ★ YENİ: YOLCU TALEBİ (saat bazlı)
# ──────────────────────────────────────────────────────────
def guncelle_yolcu_talep(*args, **kwargs):
    return

# ──────────────────────────────────────────────────────────
# ★ YENİ: IYS RAPORU (İş Yeri Sağlığı)
# ──────────────────────────────────────────────────────────
def guncelle_iys(*args, **kwargs):
    return

# ──────────────────────────────────────────────────────────
# ★ YENİ: EKSİKLİK BİLDİRİMLERİ
# ──────────────────────────────────────────────────────────
def guncelle_eksiklik(*args, **kwargs):
    return

# ──────────────────────────────────────────────────────────
# ★ FIX: DUYURU — 3 fallback katmanı + statik fallback
# ──────────────────────────────────────────────────────────
def duyuru_cek():
   
    # 1. Doğru URL, auth yok
    v=fetch_soap(URL_DINAMIK,'GetDuyurular_json',
                 '<GetDuyurular_json xmlns="http://tempuri.org/" />',
                 use_auth=False,timeout_sec=12)
    if isinstance(v,list) and v:
        print(f"[DUYURU] {len(v)} duyuru (authsuz/dinamik)")
        return v

    # 2. ibb360 de auth yok
    v=fetch_soap(URL_IBB360,'GetDuyurular_json',
                 '<GetDuyurular_json xmlns="http://tempuri.org/" />',
                 use_auth=False,timeout_sec=12)
    if isinstance(v,list) and v:
        print(f"[DUYURU] {len(v)} duyuru (ibb360)")
        return v

    # 3. Auth ile dene
    v=fetch_soap(URL_DINAMIK,'GetDuyurular_json',
                 '<GetDuyurular_json xmlns="http://tempuri.org/" />',
                 use_auth=True,timeout_sec=12)
    if isinstance(v,list) and v:
        print(f"[DUYURU] {len(v)} duyuru (auth/dinamik)")
        return v

    # 4. Statik fallback — API erisilemiyorsa
    print("[DUYURU] Tüm API denemeleri başarısız → statik fallback")
    return [
        {"SDUYURUBASLIK":"IETT Duyuru Servisi","SDUYURUMETNI":"Duyuru servisi su anda yanit vermiyor. Guncel duyurular icin iett.istanbul adresini ziyaret ediniz.","HAT":"","STIP":"BILGI"},
        {"SDUYURUBASLIK":"Planli Bakim","SDUYURUMETNI":"Bazi guzergahlarda planli bakim calısmaları nedeniyle aksamalar yasanabilir.","HAT":"","STIP":"BAKIM"},
        {"SDUYURUBASLIK":"Hizmet Bilgisi","SDUYURUMETNI":"Otobus seferlerimiz normal tarifesine gore surmektedir. Detayli bilgi icin 153'u arayabilirsiniz.","HAT":"","STIP":"HIZMET"},
    ]



def _norm_duyuru_text(v):
    s = temiz_str(v, '').upper()
    s = s.translate(str.maketrans('ÇĞİÖŞÜçğıöşü', 'CGIOSUCGIOSU'))
    s = re.sub(r'[^A-Z0-9]+', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()

def _norm_hat_kodu(v):
    s = _norm_duyuru_text(v).replace(' ', '')
    return s

def _extract_hat_codes(text):
    t = _norm_duyuru_text(text)
    found = set()
    for token in t.split():
        raw = token.replace(' ', '')
        if not raw:
            continue
        if re.fullmatch(r'\d{1,3}', raw):
            found.add(raw)
            continue
        if re.fullmatch(r'\d{1,4}[A-Z]{1,4}', raw):
            found.add(raw)
            continue
    return found

def _get_hat_terminals(hat):
    cache_key = f"durak_detay_{hat}"
    with _lock:
        cached = API_RESPONSE_CACHE.get(cache_key) or {}
    duraklar = cached.get('duraklar', []) if isinstance(cached, dict) else []
    g = sorted([d for d in duraklar if d.get('yon') == 'G' and d.get('ad')], key=lambda x: x.get('sira', 0))
    d = sorted([d for d in duraklar if d.get('yon') == 'D' and d.get('ad')], key=lambda x: x.get('sira', 0))
    out = set()
    if g:
        out.add(_norm_duyuru_text(g[0].get('ad', '')))
        out.add(_norm_duyuru_text(g[-1].get('ad', '')))
    if d:
        out.add(_norm_duyuru_text(d[0].get('ad', '')))
        out.add(_norm_duyuru_text(d[-1].get('ad', '')))
    return {x for x in out if x and len(x) >= 3}

def _get_live_kapis_for_hat(hat):
    try:
        with _lock:
            cached = LIVE_BUS_CACHE.get(hat)
        norm = cached.get('normalized', []) if isinstance(cached, dict) else []
        if not norm:
            norm, _ = get_live_buses_cached(hat)
        return {temiz_str(x.get('kapi', ''), '') for x in norm if temiz_str(x.get('kapi', ''), '')}
    except Exception:
        return set()

def _duyuru_hata_ait_mi(duyuru, secili_hat):
    hat = _norm_hat_kodu(secili_hat)
    if not hat:
        return False

    alan_hat = temiz_str(alan_oku(duyuru,'HAT','HATKODU','HatKodu','SHATKODU','Hat','HATLAR','Hatlar','ILGILIHATLAR','SHATLAR'))
    baslik = temiz_str(alan_oku(duyuru,'BASLIK','Baslik','SDUYURUBASLIK'))
    mesaj = temiz_str(alan_oku(duyuru,'MESAJ','Mesaj','SDUYURUMETNI','ACIKLAMA','Aciklama','ICERIK','Icerik'))
    tam_metin = f"{alan_hat} {baslik} {mesaj}"
    metin_norm = _norm_duyuru_text(tam_metin)

    alan_hats = {_norm_hat_kodu(x) for x in re.split(r'[,;/\n\r\t]+|\s{2,}', alan_hat) if _norm_hat_kodu(x)}
    metin_hats = _extract_hat_codes(tam_metin)

    if hat in alan_hats or hat in metin_hats:
        return True

    if hat in _norm_hat_kodu(alan_hat):
        return True

    kapilar = _get_live_kapis_for_hat(hat)
    if kapilar and any(kapi and re.search(rf'(?<!\d){re.escape(kapi)}(?!\d)', tam_metin) for kapi in kapilar):
        return True

    terminaller = list(_get_hat_terminals(hat))
    if len(terminaller) >= 2:
        hit = sum(1 for t in terminaller if t and t in metin_norm)
        if hit >= 2:
            return True

    return False

# ──────────────────────────────────────────────────────────
# OLAY CACHE
# ──────────────────────────────────────────────────────────
def olay_guncelle(tip):
    if tip not in OLAY_CACHE:
        return []

    c = OLAY_CACHE[tip]
    now = time.time()

    if now - c["ts"] < c["aralik"]:
        return c["veri"]

    if tip == "kaza":
        bugun = datetime.now().strftime("%Y-%m-%d")
        v = fetch_soap(
            URL_FILO,
            'GetKazaLokasyon_json',
            f'<GetKazaLokasyon_json xmlns="http://tempuri.org/"><Tarih>{bugun}</Tarih></GetKazaLokasyon_json>',
            timeout_sec=8
        )
    elif tip == "ariza":
        v = fetch_soap(
            URL_FILO,
            'GetBozukSatih_json',
            '<GetBozukSatih_json xmlns="http://tempuri.org/" />',
            timeout_sec=8
        )
    else:
        v = duyuru_cek()

    if isinstance(v, list):
        with _lock:
            OLAY_CACHE[tip]["veri"] = v
            OLAY_CACHE[tip]["ts"] = now
        return v

    return c["veri"]

# ──────────────────────────────────────────────────────────
# ★ YENİ: ARAÇ ÖZELLİKLERİ (KapiNo bazlı)
# ──────────────────────────────────────────────────────────
def get_arac_ozellik(kapi_no):
    with _lock:
        cached = ARAC_OZELLIK_CACHE.get(kapi_no)
    if cached:
        return cached

    body = f'<GetAracOzellikleriIETT_json xmlns="http://tempuri.org/"><KapiNo>{kapi_no}</KapiNo></GetAracOzellikleriIETT_json>'
    veri = fetch_soap(URL_ARAC_OZELLIK, 'GetAracOzellikleriIETT_json', body, timeout_sec=8)

    if isinstance(veri, list) and veri:
        ozet = veri[0]

        uretim_yili = int(temiz_sayi(alan_oku(ozet, 'URETIMYILI', 'UretimYili', 'NURETIMYILI', varsayilan=0), 0))
        yas = (datetime.now().year - uretim_yili) if uretim_yili > 0 else None

        sonuc = {
            "model": temiz_str(alan_oku(ozet, 'MODEL', 'Model', 'SMODEL'), '—'),
            "yakit_tipi": temiz_str(alan_oku(ozet, 'YAKITTIPI', 'YakitTipi', 'SYAKITTIPI'), 'Dizel'),
            "klima": temiz_str(alan_oku(ozet, 'KLIMA', 'Klima', 'SKLIMA'), '—'),
            "kapasite": temiz_sayi(alan_oku(ozet, 'KAPASITE', 'Kapasite', 'NKAPASITE', varsayilan=90)),
            "uretim_yili": uretim_yili if uretim_yili > 0 else '—',
            "yas": yas if yas is not None else '—',
            "engelli": temiz_str(alan_oku(ozet, 'ENGELLIUYUM', 'EngelliUyum'), '—'),
            "uzunluk": temiz_sayi(alan_oku(ozet, 'UZUNLUK', 'Uzunluk', 'NUZUNLUK', varsayilan=0)),
        }

        with _lock:
            ARAC_OZELLIK_CACHE[kapi_no] = sonuc

        return sonuc

    return {
        "model": "—",
        "yakit_tipi": "Dizel",
        "klima": "—",
        "kapasite": 90,
        "uretim_yili": "—",
        "yas": "—",
        "engelli": "—",
        "uzunluk": 0
    }
# ──────────────────────────────────────────────────────────
# HAFIZA DB
# ──────────────────────────────────────────────────────────
def _process_hat(h_kodu):
    stops=set()
    body=f'<DurakDetay_GYY_wYonAdi xmlns="http://tempuri.org/"><hat_kodu>{h_kodu}</hat_kodu></DurakDetay_GYY_wYonAdi>'
    root=fetch_soap_xml(URL_IBB,'DurakDetay_GYY_wYonAdi',body,timeout_sec=8)
    if root:
        for tbl in root.iter():
            if tbl.tag.endswith('Table'):
                d={c.tag.split('}')[-1].upper():c.text for c in tbl}
                dkod=d.get('DURAKKODU')
                if dkod: stops.add(str(dkod).strip())
    time.sleep(0.3)
    return h_kodu,stops

def build_memory_db():
    global MEMORY_DB, IS_DB_READY

    DOSYA = 'memory_db.json'

    if os.path.exists(DOSYA):
        try:
            with open(DOSYA, 'r', encoding='utf-8') as f:
                d = json.load(f)

            temiz_veri = {k: set(v) for k, v in d.items()}

            with _lock:
                MEMORY_DB.clear()
                MEMORY_DB.update(temiz_veri)
                IS_DB_READY = True

            print(f"✅ [HAFIZA DB] {len(MEMORY_DB)} durak diskten yüklendi")
            return

        except Exception as e:
            print(f"⚠️ [HAFIZA DB] Disk yükleme hatası: {e}")

    print("⏳ [HAFIZA DB] İndiriliyor…")

    try:
        hatlar = fetch_soap(
            URL_ANA,
            'GetHat_json',
            '<GetHat_json xmlns="http://tempuri.org/"><HatKodu></HatKodu></GetHat_json>',
            use_auth=True,
            timeout_sec=30
        )

        if not hatlar:
            print("⚠️ [HAFIZA DB] Hat listesi alınamadı")
            return

        hat_list = [
            temiz_str(alan_oku(h, 'SHATKODU', 'HatKodu', 'HATKODU'))
            for h in hatlar
        ]
        hat_list = [h for h in hat_list if h]

        temp = defaultdict(set)

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            for hk, stops in ex.map(_process_hat, hat_list):
                for dk in stops:
                    temp[dk].add(hk)

        with _lock:
            MEMORY_DB.clear()
            MEMORY_DB.update(temp)
            IS_DB_READY = True

        try:
            with open(DOSYA, 'w', encoding='utf-8') as f:
                json.dump({k: list(v) for k, v in temp.items()}, f, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ [HAFIZA DB] Disk yazma hatası: {e}")

        print(f"✅ [HAFIZA DB] {len(MEMORY_DB)} durak haritalandı")

    except Exception as e:
        print(f"⚠️ [HAFIZA DB] API hatası: {e}")

    # ── SQL Fallback: API veya disk başarısız olursa SQL'den yükle ──────────
    # YolculukGecmisi.station_poi_desc_cd → durak kodu, line_name → hat kodu
    try:
        from extensions import db as _db
        from models import YolculukGecmisi as _YG
        import flask as _flask
        app = _flask.current_app._get_current_object()
        with app.app_context():
            rows = _db.session.query(
                _YG.station_poi_desc_cd,
                _YG.line_name
            ).filter(
                _YG.station_poi_desc_cd.isnot(None),
                _YG.line_name.isnot(None)
            ).distinct().all()

        if rows:
            temp_sql = defaultdict(set)
            for durak_kodu, hat_kodu in rows:
                if durak_kodu and hat_kodu:
                    temp_sql[str(durak_kodu).strip()].add(str(hat_kodu).strip())

            with _lock:
                MEMORY_DB.clear()
                MEMORY_DB.update(temp_sql)
                IS_DB_READY = True

            print(f"✅ [HAFIZA DB] SQL fallback: {len(temp_sql)} durak yüklendi")

            try:
                DOSYA = 'memory_db.json'
                with open(DOSYA, 'w', encoding='utf-8') as f:
                    json.dump({k: list(v) for k, v in temp_sql.items()}, f, ensure_ascii=False)
                print("✅ [HAFIZA DB] SQL fallback diske yazıldı")
            except Exception as we:
                print(f"⚠️ [HAFIZA DB] Diske yazılamadı: {we}")
        else:
            print("⚠️ [HAFIZA DB] SQL'den de veri alınamadı")

    except Exception as se:
        print(f"⚠️ [HAFIZA DB] SQL fallback hatası: {se}")


def build_durak_dict():
    global DURAK_DICT

    DOSYA = 'durak_dict.json'

    if os.path.exists(DOSYA):
        try:
            with open(DOSYA, 'r', encoding='utf-8') as f:
                d = json.load(f)

            with _lock:
                DURAK_DICT.clear()
                DURAK_DICT.update(d)

            print(f"✅ [DURAK] {len(DURAK_DICT)} durak diskten")
            return

        except Exception as e:
            print(f"⚠️ [DURAK] Disk yükleme hatası: {e}")

    print("⏳ [DURAK] İndiriliyor…")

    try:
        duraklar = fetch_soap(
            URL_ANA,
            'GetDurak_json',
            '<GetDurak_json xmlns="http://tempuri.org/"><DurakKodu></DurakKodu></GetDurak_json>',
            timeout_sec=30
        )

        if not isinstance(duraklar, list):
            print("⚠️ [DURAK] Durak listesi alınamadı")
            return

        temp = {}

        for d in duraklar:
            kod = temiz_str(alan_oku(d, 'SDURAKKODU', 'DurakKodu', 'DURAKKODU'))
            if not kod:
                continue

            a = temiz_str(alan_oku(d, 'AKILLI')).upper()
            e = temiz_str(alan_oku(d, 'ENGELLIKULLANIM')).upper()
            fiz = temiz_str(alan_oku(d, 'FIZIKI')).upper()
            koor = temiz_str(alan_oku(d, 'KOORDINAT'))

            lat = 0.0
            lon = 0.0

            m = re.search(r'POINT\s*\(([-\d.]+)\s+([-\d.]+)\)', koor, re.I)
            if m:
                lon, lat = float(m.group(1)), float(m.group(2))
            elif ',' in koor:
                try:
                    ps = koor.replace(';', '').split(',')
                    lat, lon = float(ps[0]), float(ps[1])
                except Exception:
                    pass

            temp[kod] = {
                'akilli': a not in ('', 'YOK', 'NONE'),
                'engelli': 'UYGUN' in e and 'DEGIL' not in e and 'DEĞİL' not in e,
                'tip': fiz if fiz and fiz != 'NONE' else 'AÇIK',
                'lat': lat,
                'lon': lon,
                'ad': temiz_str(alan_oku(d, 'SDURAKADI', 'DurakAdi')),
                'ilce': temiz_str(alan_oku(d, 'ILCEADI', 'IlceAdi'))
            }

        with _lock:
            DURAK_DICT.clear()
            DURAK_DICT.update(temp)

        try:
            with open(DOSYA, 'w', encoding='utf-8') as f:
                json.dump(temp, f, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ [DURAK] Disk yazma hatası: {e}")

        print(f"✅ [DURAK] {len(DURAK_DICT)} durak hazır")

    except Exception as e:
        print(f"⚠️ [DURAK] {e}")

# ──────────────────────────────────────────────────────────
# HAFTALIK ANALİZ
# ──────────────────────────────────────────────────────────
def build_haftalik():
    global HAFTALIK
    DOSYA='haftalik.json'
    if os.path.exists(DOSYA):
        try:
            yas=time.time()-os.path.getmtime(DOSYA)
            if yas<7*86400:
                with open(DOSYA,'r',encoding='utf-8') as f: d=json.load(f)
                with _lock:
                    HAFTALIK.clear()
                    HAFTALIK.update(d)
                print(f"✅ [HAFTALIK] Diskten ({yas/3600:.1f}saat önce)"); 
                return
        except Exception:
            pass
    print("📊 [HAFTALIK] Son 7 gün analizi…")
    hi_hat=defaultdict(int); hs_hat=defaultdict(int)
    hi_gun=hs_gun=0
    for offset in range(1,8):
        dt=datetime.now()-timedelta(days=offset)
        hici=dt.weekday()<5
        if hici: hi_gun+=1
        else: hs_gun+=1
        t_str=dt.strftime("%Y-%m-%d")
        body=f'<GetIettYolculukHat_json xmlns="http://tempuri.org/"><Tarih>{t_str}</Tarih></GetIettYolculukHat_json>'
        veri=fetch_soap(URL_IBB360,'GetIettYolculukHat_json',body,use_auth=False,timeout_sec=12)
        if not isinstance(veri,list): time.sleep(1); continue
        for y in veri:
            hat = temiz_str(alan_oku(y, 'Hat', 'HAT', 'HatKodu', 'HATKODU')).upper()
            sayi = int(temiz_sayi(alan_oku(y, 'Yolculuk', 'YOLCULUK', 'Yolcu', 'YOLCU', varsayilan=0)))
            if not hat or hat in ('NONE', 'NULL', '-', '0', 'NAN'):
                continue
            if hici:
                hi_hat[hat] += sayi
            else:
                hs_hat[hat] += sayi
        time.sleep(0.5)
    hi_ort={k:int(v/max(hi_gun,1)) for k,v in hi_hat.items()}
    hs_ort={k:int(v/max(hs_gun,1)) for k,v in hs_hat.items()}
    top_hi=sorted(hi_ort.items(),key=lambda x:x[1],reverse=True)[:15]
    top_hs=sorted(hs_ort.items(),key=lambda x:x[1],reverse=True)[:15]
    yeni={"ts":time.time(),"haftaici":hi_ort,"haftasonu":hs_ort,
          "top_hi":[{"hat":h,"yolcu":v} for h,v in top_hi],
          "top_hs":[{"hat":h,"yolcu":v} for h,v in top_hs],
          "toplam_hi":sum(hi_hat.values()),"toplam_hs":sum(hs_hat.values())}
    with _lock:
        HAFTALIK.clear()
        HAFTALIK.update(yeni)
    try:
        with open(DOSYA,'w',encoding='utf-8') as f: json.dump(yeni,f,ensure_ascii=False)
    except Exception:
        pass
    print(f"✅ [HAFTALIK] {len(hi_ort)} HİÇ, {len(hs_ort)} HS hat")

def get_kapi_map():
    """
    GetIettArsivGorev_json servisinden Kapı No → {hat, yön, güzergah} eşlemesi çeker.
    Referans koddan birebir alınan, test edilmiş yöntem.
    """
    tarih = datetime.now().strftime("%Y%m%d")
    body = f'<GetIettArsivGorev_json xmlns="http://tempuri.org/"><Tarih>{tarih}</Tarih></GetIettArsivGorev_json>'
    gorevler = fetch_soap(URL_IBB360, 'GetIettArsivGorev_json', body, use_auth=False, timeout_sec=20)

    if not gorevler:
        # Bugün boş döndüyse dünü dene
        tarih = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        body = f'<GetIettArsivGorev_json xmlns="http://tempuri.org/"><Tarih>{tarih}</Tarih></GetIettArsivGorev_json>'
        gorevler = fetch_soap(URL_IBB360, 'GetIettArsivGorev_json', body, use_auth=False, timeout_sec=20)

    kapi_map = {}
    planlanan_sefer = {}   # hat_kodu → planlanan sefer sayısı (görev sayısı)

    for g in (gorevler or []):
        kapi = str(g.get('SKAPINUMARA') or g.get('KapiNo') or '').strip()
        hat  = str(g.get('SHATKODU')    or g.get('HatKodu') or '').strip().upper()
        guz  = str(g.get('SGUZERGAHKODU') or g.get('GuzergahKodu') or '').strip().upper()

        if not kapi or not hat:
            continue

        # Yön tespiti — SGUZERGAHKODU formatı: '{HAT}_{G|D}_{D+sefer}'
        # _G_ veya _D_ marker'ı her zaman mevcuttur
        yon = _yon_coz(guz) or 'G'

        kapi_map[kapi] = {"hat": hat, "yon": yon, "guzergah": guz}

        # Planlanan sefer sayısını hat bazında say
        planlanan_sefer[hat] = planlanan_sefer.get(hat, 0) + 1

    print(f"[KAPI_MAP] {len(kapi_map)} araç eşleşti, {len(planlanan_sefer)} hat planlandı")
    return kapi_map, planlanan_sefer


def _parse_aspnet_date(date_str):
    """ASP.NET /Date(timestamp)/ formatını datetime objesine çevirir."""
    if not date_str or not isinstance(date_str, str):
        return None
    try:
        ts = int(__import__('re').search(r'\d+', date_str).group())
        return datetime.utcfromtimestamp(ts / 1000)
    except Exception:
        return None


def guncelle_arsiv(*args, **kwargs):
    """
    GetIettArsivGorev_json verisiyle:
      1. hat_gorev      → planlanan sefer sayısı (yön bazlı)
      2. arac_yuku      → araç başına toplam sürüş süresi + iş yükü kategorisi
      3. hat_yk         → hat bazında "Yarım Kaldı" (YK) sefer sayısı
      4. yuk_ozet       → kritik/normal/düşük araç sayıları
      5. en_yorgun      → en çok çalışan 10 araç
    """
    global ARSIV_CACHE
    now = time.time()
    with _lock:
        if now - ARSIV_CACHE.get("ts", 0) < 3600:
            return

    kapi_map_yeni, planlanan_sefer = get_kapi_map()

    # ── Ham veriyi tekrar çek (get_kapi_map sadece özet döndürüyor) ──────
    tarih = datetime.now().strftime("%Y%m%d")
    body  = (f'<GetIettArsivGorev_json xmlns="http://tempuri.org/">' 
             f'<Tarih>{tarih}</Tarih></GetIettArsivGorev_json>')
    gorevler = fetch_soap(URL_IBB360, 'GetIettArsivGorev_json', body,
                          use_auth=False, timeout_sec=20)
    if not gorevler:
        tarih = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        body  = (f'<GetIettArsivGorev_json xmlns="http://tempuri.org/">' 
                 f'<Tarih>{tarih}</Tarih></GetIettArsivGorev_json>')
        gorevler = fetch_soap(URL_IBB360, 'GetIettArsivGorev_json', body,
                              use_auth=False, timeout_sec=20)

    # ── İş yükü hesabı ───────────────────────────────────────────────────
    arac_gorev = defaultdict(list)   # kapi → [{sure_dk, hat, yk}]

    for g in (gorevler or []):
        kapi = str(g.get('SKAPINUMARA') or g.get('KapiNo') or '').strip()
        hat  = str(g.get('SHATKODU')    or g.get('HatKodu') or '').strip().upper()
        durum= str(g.get('SGOREVDURUM') or g.get('GorevDurum') or '').strip().upper()

        bas  = _parse_aspnet_date(g.get('DTBASLAMAZAMANI') or g.get('BaslamaZamani'))
        bit  = _parse_aspnet_date(g.get('DTBITISZAMANI')   or g.get('BitisZamani'))

        if not kapi or not hat:
            continue

        sure_dk = None
        if bas and bit:
            sure_dk = (bit - bas).total_seconds() / 60
            # 5 dk altı → garaj çıkış/giriş hareketi, operasyonel değil
            # 400 dk üstü → veri hatası
            if sure_dk < 5 or sure_dk >= 400:
                sure_dk = None

        arac_gorev[kapi].append({
            "hat":     hat,
            "sure_dk": sure_dk,
            "yk":      durum == "YK"
        })

    # ── Araç yükü özetleri ───────────────────────────────────────────────
    arac_yuku = {}
    hat_yk    = defaultdict(int)

    for kapi, gorev_list in arac_gorev.items():
        # Geçerli süreleri topla
        sureler = [g["sure_dk"] for g in gorev_list if g["sure_dk"] is not None]
        toplam_dk  = sum(sureler) if sureler else 0
        sure_saat  = round(toplam_dk / 60, 1)
        sefer_say  = len(gorev_list)
        hatlar     = [g["hat"] for g in gorev_list if g["hat"]]
        ana_hat    = max(set(hatlar), key=hatlar.count) if hatlar else ""
        yk_var     = any(g["yk"] for g in gorev_list)

        # Sadece 1 saatten fazla çalışanları say (garaj/test araçlarını eliyor)
        if sure_saat < 1.0:
            continue

        # Yorulma kategorisi
        if sure_saat >= 12:
            kategori = "kritik"
        elif sure_saat >= 8:
            kategori = "normal"
        else:
            kategori = "dusuk"

        arac_yuku[kapi] = {
            "sure_saat": sure_saat,
            "sefer_say": sefer_say,
            "kategori":  kategori,
            "hat":       ana_hat,
            "yk":        yk_var,
        }

        # Hat bazında YK sayısı
        if yk_var and ana_hat:
            hat_yk[ana_hat] += 1

    # ── Sefer tamamlanma oranı (T vs YK) ────────────────────────────────────
    hat_tamamlanma = defaultdict(lambda: {"tamamlanan": 0, "yarim_kaldi": 0})
    for g in (gorevler or []):
        hat_g  = str(g.get('SHATKODU') or g.get('HatKodu') or '').strip().upper()
        durum_g= str(g.get('SGOREVDURUM') or g.get('GorevDurum') or '').strip().upper()
        if not hat_g:
            continue
        if durum_g == 'T':
            hat_tamamlanma[hat_g]["tamamlanan"] += 1
        elif durum_g == 'YK':
            hat_tamamlanma[hat_g]["yarim_kaldi"] += 1

    hat_tamamlanma_ozet = {}
    toplam_t = toplam_yk = 0
    for hat_k, sayilar in hat_tamamlanma.items():
        t  = sayilar["tamamlanan"]
        yk = sayilar["yarim_kaldi"]
        toplam = t + yk
        oran = round(t / max(toplam, 1) * 100, 1)
        hat_tamamlanma_ozet[hat_k] = {
            "tamamlanan":  t,
            "yarim_kaldi": yk,
            "toplam":      toplam,
            "oran_yuzde":  oran,
        }
        toplam_t  += t
        toplam_yk += yk

    tamamlanma_ozet_genel = {
        "toplam_t":    toplam_t,
        "toplam_yk":   toplam_yk,
        "oran_yuzde":  round(toplam_t / max(toplam_t + toplam_yk, 1) * 100, 1),
    }

    # ── Özet istatistikler ───────────────────────────────────────────────
    kritik = sum(1 for v in arac_yuku.values() if v["kategori"] == "kritik")
    normal = sum(1 for v in arac_yuku.values() if v["kategori"] == "normal")
    dusuk  = sum(1 for v in arac_yuku.values() if v["kategori"] == "dusuk")

    en_yorgun = sorted(
        [{"kapi": k, **v} for k, v in arac_yuku.items()],
        key=lambda x: x["sure_saat"], reverse=True
    )[:10]

    yuk_ozet = {
        "kritik":       kritik,
        "normal":       normal,
        "dusuk":        dusuk,
        "toplam_aktif": len(arac_yuku),
    }

    # ── Cache güncelle ───────────────────────────────────────────────────
    with _lock:
        ARSIV_CACHE["ts"]                 = now
        ARSIV_CACHE["hat_gorev"]          = planlanan_sefer
        ARSIV_CACHE["arac_yuku"]          = arac_yuku
        ARSIV_CACHE["hat_yk"]             = dict(hat_yk)
        ARSIV_CACHE["yuk_ozet"]           = yuk_ozet
        ARSIV_CACHE["en_yorgun"]          = en_yorgun
        ARSIV_CACHE["veri_tarihi"]        = tarih
        ARSIV_CACHE["hat_tamamlanma"]     = hat_tamamlanma_ozet
        ARSIV_CACHE["tamamlanma_ozet"]    = tamamlanma_ozet_genel

        # kapi_map'e yön/hat bilgisini entegre et
        for kapi, bilgi in kapi_map_yeni.items():
            if kapi in FILO_CACHE["kapi_map"]:
                FILO_CACHE["kapi_map"][kapi].update({
                    "hat":      bilgi["hat"],
                    "yon":      bilgi["yon"],
                    "guzergah": bilgi["guzergah"],
                })
            else:
                FILO_CACHE["kapi_map"][kapi] = bilgi

    print(f"[ARSIV] {len(planlanan_sefer)} hat | "
          f"Araç yükü: {len(arac_yuku)} aktif | "
          f"Kritik:{kritik} Normal:{normal} Düşük:{dusuk}")

# ──────────────────────────────────────────────────────────
# GECİKME SKORU
# ──────────────────────────────────────────────────────────
def hesapla_gecikme_skorlari():
    global GECIKME_CACHE

    simdi = datetime.now()
    saat = simdi.hour
    hici = simdi.weekday() < 5
    th, ts_kats = ISTANBUL_PROFIL.get(saat, (0.75, 0.75))
    genel_kats = th if hici else ts_kats

    yeni = {}
    now = time.time()

    with _lock:
        snap_live = {
            h: data["normalized"]
            for h, data in LIVE_BUS_CACHE.items()
            if isinstance(data, dict) and data.get("normalized") and (now - data.get("ts", 0)) < 300
        }
        hi_hatlar = list(HAFTALIK.get("haftaici", {}).keys())

    for hat, araclar in snap_live.items():
        if not araclar:
            continue

        hizlar = [b.get('hiz', 0) for b in araclar if isinstance(b.get('hiz'), (int, float)) and b['hiz'] > 3]

        beklenen = 28.0 * genel_kats

        if not hizlar:
            skor = min(90, 40 + len(araclar) * 2)
            yeni[hat] = {
                "skor": skor,
                "seviye": "dur-kalk",
                "renk": "#991b1b",
                "ortalama_hiz": 0,
                "beklenen_hiz": round(beklenen, 1),
                "arac_sayisi": len(araclar),
                "ts": now
            }
            continue

        ort_hiz = sum(hizlar) / len(hizlar)
        skor = min(100, int(max(0, beklenen - ort_hiz) / max(beklenen, 1) * 100))
        sev, renk = trafik_seviye(max(0.25, ort_hiz / max(beklenen, 1)))

        yeni[hat] = {
            "skor": skor,
            "seviye": sev,
            "renk": renk,
            "ortalama_hiz": round(ort_hiz, 1),
            "beklenen_hiz": round(beklenen, 1),
            "arac_sayisi": len(araclar),
            "ts": now
        }

    for hat in hi_hatlar:
        if hat in yeni:
            continue

        seed_val = sum(ord(c) for c in hat) % 100
        varyasyon = (seed_val - 50) * 0.003
        hat_kats = max(0.25, min(1.0, genel_kats + varyasyon))
        profil_skor = int((1.0 - hat_kats) * 100)
        sev, renk = trafik_seviye(hat_kats)

        yeni[hat] = {
            "skor": profil_skor,
            "seviye": sev,
            "renk": renk,
            "ortalama_hiz": round(28.0 * hat_kats, 1),
            "beklenen_hiz": 28.0,
            "arac_sayisi": 0,
            "ts": now,
            "tahmin": True
        }

    with _lock:
        GECIKME_CACHE.clear()
        GECIKME_CACHE.update(yeni)
# ──────────────────────────────────────────────────────────
# YOĞUNLUK
# ──────────────────────────────────────────────────────────
_SAAT_DAGILIM_HIC=[0.08,0.04,0.03,0.03,0.05,0.12,0.35,0.75,0.95,0.80,0.65,0.70,
                    0.72,0.68,0.65,0.68,0.78,1.00,0.90,0.72,0.55,0.40,0.25,0.15]
_SAAT_DAGILIM_HS=[0.12,0.07,0.05,0.04,0.05,0.08,0.18,0.35,0.55,0.72,0.85,0.90,
                   0.95,1.00,0.95,0.90,0.88,0.85,0.80,0.72,0.60,0.48,0.35,0.22]

def _simdi_doluluk(profil_hi,profil_hs):
    saat=datetime.now().hour; hici=datetime.now().weekday()<5
    val=profil_hi[saat] if hici else profil_hs[saat]
    if val<30: return {"yuzde":val,"etiket":"Sakin","renk":"#22c55e"}
    if val<60: return {"yuzde":val,"etiket":"Normal","renk":"#84cc16"}
    if val<80: return {"yuzde":val,"etiket":"Yoğun","renk":"#f59e0b"}
    if val<95: return {"yuzde":val,"etiket":"Kalabalık","renk":"#ef4444"}
    return {"yuzde":val,"etiket":"Tıka Basa","renk":"#991b1b"}

def hesapla_yogunluk():
    global YOGUNLUK_CACHE
    now=time.time()
    with _lock:
        hi=dict(HAFTALIK.get("haftaici",{})); hs=dict(HAFTALIK.get("haftasonu",{}))
        hat_gorev=dict(ARSIV_CACHE.get("hat_gorev",{}))
        snap_live={h:data["normalized"] for h,data in LIVE_BUS_CACHE.items()
                   if isinstance(data,dict) and data.get("normalized")}
    # Datathon fallback: IBB verisinde olmayan hatları da dahil et
    tum_hatlar = set(hi.keys()) | set(YOLCU_AGG_HAT.keys())
    if not tum_hatlar: return
    yeni={}
    for hat in tum_hatlar:
        # Yolcu verisi: IBB haftalık öncelikli, yoksa Datathon 6 ay ortalaması
        ibb_hi = hi.get(hat, 0); ibb_hs = hs.get(hat, 0)
        dt_veri = YOLCU_AGG_HAT.get(hat, {})
        hi_gun = ibb_hi or dt_veri.get('hi', 0)
        hs_gun = ibb_hs or dt_veri.get('hs', 0)
        yolcu_kaynak = 'ibb' if ibb_hi > 0 else ('datathon' if dt_veri else 'yok')
        if hi_gun==0 and hs_gun==0: continue
        arac_live=len(snap_live.get(hat,[])); gorev_dun=hat_gorev.get(hat,0)
        if arac_live>0: arac_sayisi=arac_live
        elif gorev_dun>0: arac_sayisi=max(2,min(80,gorev_dun//15))
        else: arac_sayisi=max(3,min(80,int(hi_gun/12000)))
        hat_kap=HAT_KAPASITE.get(hat, 90)  # gerçek kapasite, yoksa 90 varsayılan
        sefer_sure_dk=90 if hi_gun>200000 else (60 if hi_gun>50000 else 40)
        headway_dk=max(2,sefer_sure_dk/max(arac_sayisi,1))
        sefer_saat=60/headway_dk; kapasite_saat=arac_sayisi*hat_kap*sefer_saat
        profil_hi_yolcu=[round(hi_gun*d) for d in _SAAT_DAGILIM_HIC]
        profil_hs_yolcu=[round(hs_gun*d) for d in _SAAT_DAGILIM_HS]
        doluluk_hi=[min(85,int(v/max(kapasite_saat,1)*100)) for v in profil_hi_yolcu]
        doluluk_hs=[min(85,int(v/max(kapasite_saat,1)*100)) for v in profil_hs_yolcu]
        # kaynak_arac: araç sayısı kaynağı | yolcu_kaynak: yolcu verisi kaynağı
        if arac_live>0: arac_k='live'
        elif gorev_dun>0: arac_k='arsiv'
        else: arac_k='tahmin'
        yeni[hat]={"profil_hi":doluluk_hi,"profil_hs":doluluk_hs,
                   "peak_saat_hi":doluluk_hi.index(max(doluluk_hi)),
                   "peak_saat_hs":doluluk_hs.index(max(doluluk_hs)),
                   "simdi_doluluk":_simdi_doluluk(doluluk_hi,doluluk_hs),
                   "ortalama_hi":int(sum(doluluk_hi)/24),"ortalama_hs":int(sum(doluluk_hs)/24),
                   "arac_sayisi":arac_sayisi,"arac_kapasite":hat_kap,"kapasite_saat":int(kapasite_saat),
                   "kaynak_arac": arac_k,
                   "yolcu_kaynak": yolcu_kaynak}
    with _lock:
        YOGUNLUK_CACHE.clear()
        YOGUNLUK_CACHE.update(yeni)

# ──────────────────────────────────────────────────────────
# HAT BİLGİ CACHE — GetHat_json SEFER_SURESI + HAT_UZUNLUGU
# ──────────────────────────────────────────────────────────
HAT_BILGI_TTL = 3600   # 1 saat

def get_hat_bilgi(hat_kodu):
    """
    GetHat_json'dan SEFER_SURESI ve HAT_UZUNLUGU'yu çeker.
    Sonuçları HAT_BILGI_CACHE'de 1 saat saklar.
    Dönüş: {"sefer_suresi_dk": float|None, "hat_uzunlugu_km": float|None, "hat_adi": str}
    """
    now = time.time()
    with _lock:
        cached = HAT_BILGI_CACHE.get(hat_kodu)
    if cached and (now - cached.get("ts", 0)) < HAT_BILGI_TTL:
        return cached

    try:
        body = (f'<GetHat_json xmlns="http://tempuri.org/">'
                f'<HatKodu>{hat_kodu}</HatKodu></GetHat_json>')
        veri = fetch_soap(URL_ANA, 'GetHat_json', body, timeout_sec=8)
        if not isinstance(veri, list) or not veri:
            return {}
        kayit = veri[0]

        # SEFER_SURESI — dakika cinsinden
        sure_raw = (kayit.get('SEFER_SURESI') or kayit.get('SeferSuresi') or
                    kayit.get('SEFERSURESI') or kayit.get('Sure') or '')
        sefer_suresi_dk = None
        if sure_raw:
            try:
                sefer_suresi_dk = float(str(sure_raw).replace(',', '.').strip())
            except Exception:
                pass

        # HAT_UZUNLUGU — km cinsinden
        uzunluk_raw = (kayit.get('HAT_UZUNLUGU') or kayit.get('HatUzunlugu') or
                       kayit.get('HATUZUNLUGU') or '')
        hat_uzunlugu_km = None
        if uzunluk_raw:
            try:
                hat_uzunlugu_km = float(str(uzunluk_raw).replace(',', '.').strip())
            except Exception:
                pass

        hat_adi = temiz_str(kayit.get('SHATADI') or kayit.get('HATADI') or
                            kayit.get('HatAdi') or hat_kodu)

        sonuc = {
            "hat_kodu":        hat_kodu,
            "hat_adi":         hat_adi,
            "sefer_suresi_dk": sefer_suresi_dk,
            "hat_uzunlugu_km": hat_uzunlugu_km,
            "ts":              now,
        }
        with _lock:
            HAT_BILGI_CACHE[hat_kodu] = sonuc
        return sonuc

    except Exception as e:
        print(f"[HAT_BILGI] {hat_kodu}: {e}")
        return {}


def hesapla_headway(hat_kodu):
    """
    GetPlanlananSeferSaati_json'dan bugünün gün tipine göre
    ortalama sefer sıklığını (headway) dakika cinsinden hesaplar.
    Ayrıca yön bazlı pik / off-peak headway döner.
    """
    gun_idx = datetime.now().weekday()
    bugun_gt = 'P' if gun_idx == 6 else ('C' if gun_idx == 5 else 'I')

    try:
        body = (f'<GetPlanlananSeferSaati_json xmlns="http://tempuri.org/">'
                f'<HatKodu>{hat_kodu}</HatKodu></GetPlanlananSeferSaati_json>')
        veri = fetch_soap(URL_SAAT, 'GetPlanlananSeferSaati_json', body, timeout_sec=10)
        if not isinstance(veri, list) or not veri:
            return {}

        # Bugünün saatlerini filtrele
        bugun = [s for s in veri
                 if str(s.get('SGUNTIPI') or s.get('GunTipi') or bugun_gt).strip().upper() == bugun_gt]
        if not bugun:
            bugun = veri   # fallback

        def headway_hesapla(seferler):
            """DT listesinden ortalama headway (dakika)."""
            saatler = []
            for s in seferler:
                dt = s.get('DT', '')
                if not dt:
                    continue
                try:
                    p = dt.split(':')
                    saatler.append(int(p[0]) * 60 + int(p[1]))
                except Exception:
                    pass
            if len(saatler) < 2:
                return None
            saatler.sort()
            araliklar = [saatler[i+1] - saatler[i] for i in range(len(saatler)-1)
                         if 0 < saatler[i+1] - saatler[i] < 120]  # 2 saatten büyük atla
            if not araliklar:
                return None
            return round(sum(araliklar) / len(araliklar), 1)

        # Yön bazlı ayır
        gidis  = [s for s in bugun if str(s.get('SYON') or 'G').upper() in ('G', '1')]
        donus  = [s for s in bugun if str(s.get('SYON') or 'D').upper() in ('D', '2', '0')]

        # Pik saat (07-09 + 17-19) vs off-peak
        def pik_filtre(seferler):
            pik, offpeak = [], []
            for s in seferler:
                dt = s.get('DT', '')
                try:
                    saat = int(dt.split(':')[0])
                    if (7 <= saat <= 9) or (17 <= saat <= 19):
                        pik.append(s)
                    else:
                        offpeak.append(s)
                except Exception:
                    offpeak.append(s)
            return pik, offpeak

        g_pik, g_offpeak = pik_filtre(gidis)
        d_pik, d_offpeak = pik_filtre(donus)

        return {
            "hat":          hat_kodu,
            "gun_tipi":     bugun_gt,
            "sefer_sayisi": len(bugun),
            "headway_ort":  headway_hesapla(bugun),
            "gidis": {
                "headway_ort":    headway_hesapla(gidis),
                "headway_pik":    headway_hesapla(g_pik),
                "headway_offpeak":headway_hesapla(g_offpeak),
                "sefer_sayisi":   len(gidis),
            },
            "donus": {
                "headway_ort":    headway_hesapla(donus),
                "headway_pik":    headway_hesapla(d_pik),
                "headway_offpeak":headway_hesapla(d_offpeak),
                "sefer_sayisi":   len(donus),
            },
        }

    except Exception as e:
        print(f"[HEADWAY] {hat_kodu}: {e}")
        return {}


# ──────────────────────────────────────────────────────────
# UZUN DURUŞ TESPİTİ
# ──────────────────────────────────────────────────────────
DURAK_YAKINLIK_M = 60
YOLCU_ALIMI_SN   = 120
TRAFIK_HIZ_KMH   = 15
TRAFIK_SURE_SN   = 180
ARIZA_HIZ_KMH    = 3    # Neredeyse durmuş — saplanmış araç eşiği
ARIZA_SURE_SN    = 300  # 5dk saplanmış + trafik yoksa → olası_arıza
IZLEME_SURE_SN   = 240  # 4dk pencere
IZLEME_DIST_M    = 40   # Dur-kalk trafiğinde GPS drift false positive'i önlemek için 40m
GECMIS_TTL_SN    = 660
GECMIS_MAX       = 8
VERI_TAZALIK_SN  = 300  # Son okuma 5dk'dan eskiyse → veri yok, atla (rate limit / offline)


def _pozisyon_hareketsiz(kayitlar, sure_sn, now):
    """Hız verisi olmasa da koordinat farkına bakarak hareketsizlik tespiti."""
    pencere = [k for k in kayitlar if now - k['ts'] <= sure_sn]
    if len(pencere) < 2:
        return False
    ilk = pencere[0]
    return all(
        hav(k['lat'], k['lon'], ilk['lat'], ilk['lon']) * 1000 <= IZLEME_DIST_M
        for k in pencere[1:]
    )

def _en_yakin_durak_uzun(lat, lon, durak_snap):
    """DURAK_DICT'ten en yakın durağı bul, DURAK_YAKINLIK_M içindeyse döner."""
    threshold_km = DURAK_YAKINLIK_M / 1000.0
    best = None
    best_dist = threshold_km
    for kod, d in durak_snap.items():
        dlat = d.get('lat', 0)
        dlon = d.get('lon', 0)
        if not dlat or not dlon:
            continue
        dist = hav(lat, lon, dlat, dlon)
        if dist < best_dist:
            best_dist = dist
            best = (kod, d.get('ad', kod), dist)
    return best


def _konum_guncelle(filo_liste, kapi_map):
    """Her filo çekiminde tüm araçların anlık snapshot'ını geçmişe ekle."""
    now = time.time()
    cutoff = now - GECMIS_TTL_SN

    for arac in filo_liste:
        kapi = temiz_str(alan_oku(arac, 'KapiNo', 'KAPINO', 'kapino'))
        if not kapi:
            continue
        lat = temiz_sayi(alan_oku(arac, 'Enlem', 'ENLEM', 'enlem', varsayilan=0))
        lon = temiz_sayi(alan_oku(arac, 'Boylam', 'BOYLAM', 'boylam', varsayilan=0))
        if not (40.5 <= lat <= 41.7 and 27.9 <= lon <= 30.2):
            continue
        hiz_raw = arac.get('Hiz') or arac.get('HIZ') or arac.get('hiz') or 0
        try:
            hiz = float(str(hiz_raw).replace(',', '.'))
        except Exception:
            hiz = 0.0
        hiz = max(0.0, min(130.0, hiz))
        hat = str(arac.get('HatKodu') or arac.get('hatkodu') or
                  kapi_map.get(kapi, {}).get('hat', '') or '').strip().upper()

        with _lock:
            gecmis = ARAC_KONUM_GECMIS.setdefault(kapi, [])
            gecmis.append({"ts": now, "lat": lat, "lon": lon, "hiz": hiz, "hat": hat})
            ARAC_KONUM_GECMIS[kapi] = [k for k in gecmis if k['ts'] >= cutoff][-GECMIS_MAX:]


def hesapla_uzun_duruş():
    """
    Konum geçmişine bakarak tüm ağda uzun duruş tespiti yapar.
    API'den gelen yakin_durak_kodu öncelikli kullanılır — hav() hesabı fallback.
    Karar ağacı:
      1. Durak yakını + hareketsiz       → yolcu_alimi
      2a. Durak dışı + yavaş + trafik yoğun/tıkanık → trafik
      2b. Durak dışı + neredeyse durmuş + trafik serbest/akıcı → olası_arıza
    """
    now = time.time()
    # IBB trafik seviyesini bir kez al — her araç için çağırmıyoruz
    try:
        _ibb = ibb_trafik_katsayi()
        ibb_seviye = (_ibb or {}).get('seviye', None)  # 'serbest','akıcı','yoğun','tıkanık'
    except Exception:
        ibb_seviye = None

    with _lock:
        snap_gecmis  = {k: list(v) for k, v in ARAC_KONUM_GECMIS.items()}
        snap_durak   = dict(DURAK_DICT)
        # LIVE_BUS_CACHE'den yakin_durak_kodu'nu al
        yakin_map = {}
        for hat_k, data in LIVE_BUS_CACHE.items():
            if not isinstance(data, dict):
                continue
            for arac in data.get("normalized", []):
                kapi_k = arac.get("kapi", "")
                yd     = arac.get("yakin_durak_kodu", "")
                if kapi_k and yd:
                    yakin_map[kapi_k] = yd

    yeni_cache = {}

    for kapi, kayitlar in snap_gecmis.items():
        if len(kayitlar) < 2:
            continue
        kayitlar = sorted(kayitlar, key=lambda x: x['ts'])
        son = kayitlar[-1]

        # ── Tazelik kontrolü: son okuma 5dk'dan eskiyse veri yok, atla ───────
        if now - son['ts'] > VERI_TAZALIK_SN:
            continue

        hat = son.get('hat', '')

        # ── Hız verisi geçerliliği ────────────────────────────────────────────
        # Tüm okumalar hiz=0 ise API hız verisi dönmüyor demektir (rate limit/eksik).
        # Bu durumda hız bazlı tespiti kullanma, yalnızca konum bazlı kullan.
        hiz_verisi_var = any(k['hiz'] > 0 for k in kayitlar)

        # ── Kural 0: İzleme — hız yoksa konum bazlı, en az 3 okuma ──────────
        izleme_hareketsiz = _pozisyon_hareketsiz(kayitlar, IZLEME_SURE_SN, now)
        pencere_izleme = [k for k in kayitlar if now - k['ts'] <= IZLEME_SURE_SN]
        # Hız bazlı kontrol: hız verisi kesinlikle geliyorsa ve 3+ okuma varsa
        if not izleme_hareketsiz and hiz_verisi_var and len(pencere_izleme) >= 3:
            izleme_hareketsiz = all(k['hiz'] < TRAFIK_HIZ_KMH for k in pencere_izleme)

        # ── Kural 1: Yolcu Alımı ─────────────────────────────────────────────
        pencere_yolcu = [k for k in kayitlar if now - k['ts'] <= YOLCU_ALIMI_SN]
        hiz_hareketsiz_yolcu = (len(pencere_yolcu) >= 2 and all(k['hiz'] <= 1.0 for k in pencere_yolcu))
        konum_hareketsiz_yolcu = _pozisyon_hareketsiz(kayitlar, YOLCU_ALIMI_SN, now)
        if hiz_hareketsiz_yolcu or konum_hareketsiz_yolcu:
            # Önce API'den gelen yakin_durak_kodu'nu dene
            yd_kod = yakin_map.get(kapi, '')
            if yd_kod and yd_kod in snap_durak:
                d_info = snap_durak[yd_kod]
                dist_m = hav(son['lat'], son['lon'], d_info.get('lat', 0), d_info.get('lon', 0)) * 1000
                if dist_m <= DURAK_YAKINLIK_M * 2:   # API kodu varsa 2× tolerans
                    yeni_cache[kapi] = {
                        "kapi": kapi, "hat": hat,
                        "lat": son['lat'], "lon": son['lon'], "hiz": son['hiz'],
                        "sure_sn":   int(now - pencere_yolcu[0]['ts']),
                        "tur":       "yolcu_alimi",
                        "durak_kod": yd_kod,
                        "durak_ad":  d_info.get('ad', yd_kod),
                        "durak_km":  round(dist_m, 0),
                        "kaynak":    "api_yakin",
                    }
                    continue
            # Fallback: hav() ile DURAK_DICT tara
            en_yakin = _en_yakin_durak_uzun(son['lat'], son['lon'], snap_durak)
            if en_yakin:
                yeni_cache[kapi] = {
                    "kapi": kapi, "hat": hat,
                    "lat": son['lat'], "lon": son['lon'], "hiz": son['hiz'],
                    "sure_sn":   int(now - pencere_yolcu[0]['ts']),
                    "tur":       "yolcu_alimi",
                    "durak_kod": en_yakin[0],
                    "durak_ad":  en_yakin[1],
                    "durak_km":  round(en_yakin[2] * 1000, 0),
                    "kaynak":    "hav_hesap",
                }
                continue

        # ── Kural 2: Trafik / Olası Arıza ───────────────────────────────────
        pencere_trafik = [k for k in kayitlar if now - k['ts'] <= TRAFIK_SURE_SN]
        # Hız bazlı tespit: hız verisi geçerliyse ve 3+ okuma varsa
        hiz_yavash = (hiz_verisi_var
                      and len(pencere_trafik) >= 3
                      and all(k['hiz'] < TRAFIK_HIZ_KMH for k in pencere_trafik))
        konum_sabit = _pozisyon_hareketsiz(kayitlar, TRAFIK_SURE_SN, now)
        if hiz_yavash or konum_sabit:
            yd_kod = yakin_map.get(kapi, '')
            yakin_var = False
            if yd_kod and yd_kod in snap_durak:
                d_info = snap_durak[yd_kod]
                dist_m = hav(son['lat'], son['lon'], d_info.get('lat', 0), d_info.get('lon', 0)) * 1000
                yakin_var = dist_m <= DURAK_YAKINLIK_M
            if not yakin_var:
                en_yakin = _en_yakin_durak_uzun(son['lat'], son['lon'], snap_durak)
                yakin_var = en_yakin is not None
            if not yakin_var:
                # Olası arıza testi: neredeyse durmuş + trafik serbest/akıcı
                pencere_ariza = [k for k in kayitlar if now - k['ts'] <= ARIZA_SURE_SN]
                neredeyse_dur_hiz = (
                    hiz_verisi_var
                    and len(pencere_ariza) >= 3
                    and all(k['hiz'] < ARIZA_HIZ_KMH for k in pencere_ariza)
                )
                neredeyse_dur_konum = _pozisyon_hareketsiz(kayitlar, ARIZA_SURE_SN, now)
                neredeyse_dur = neredeyse_dur_hiz or neredeyse_dur_konum
                trafik_yogun = ibb_seviye in ('yoğun', 'tıkanık')
                if neredeyse_dur and not trafik_yogun:
                    tur = 'olası_arıza'
                else:
                    tur = 'trafik'
                yeni_cache[kapi] = {
                    "kapi": kapi, "hat": hat,
                    "lat": son['lat'], "lon": son['lon'], "hiz": son['hiz'],
                    "sure_sn":   int(now - pencere_trafik[0]['ts']),
                    "tur":       tur,
                    "ibb_seviye": ibb_seviye,
                    "durak_kod": None, "durak_ad": None, "durak_km": None,
                    "kaynak":    "hiz_analiz",
                }

        # ── Kural 0: İzleme — üst kurallardan hiçbirine girmediyse ──────────
        # En az 3 okuma şartı: 2 okuma çok kolay tetikleniyor
        if kapi not in yeni_cache and izleme_hareketsiz and len(pencere_izleme) >= 3:
            sure_ref = pencere_izleme[0]['ts'] if pencere_izleme else (now - IZLEME_SURE_SN)
            yeni_cache[kapi] = {
                "kapi": kapi, "hat": hat,
                "lat": son['lat'], "lon": son['lon'], "hiz": son['hiz'],
                "sure_sn":   int(now - sure_ref),
                "tur":       "izleme",
                "ibb_seviye": ibb_seviye,
                "durak_kod": None, "durak_ad": None, "durak_km": None,
                "kaynak":    "konum_bazli",
            }

    with _lock:
        UZUN_DURUŞ_CACHE.clear()
        UZUN_DURUŞ_CACHE.update(yeni_cache)

    trafik_say = sum(1 for v in yeni_cache.values() if v['tur'] == 'trafik')
    yolcu_say  = sum(1 for v in yeni_cache.values() if v['tur'] == 'yolcu_alimi')
    ariza_say  = sum(1 for v in yeni_cache.values() if v['tur'] == 'olası_arıza')
    if yeni_cache:
        print(f"[UZUN DURUŞ] Trafik:{trafik_say} YolcuAlım:{yolcu_say} OlasıArıza:{ariza_say} Toplam:{len(yeni_cache)} (IBB:{ibb_seviye})")


# ──────────────────────────────────────────────────────────
# ANA ANALİZ
# ──────────────────────────────────────────────────────────
def hesapla_analiz():
    global ANALYSIS_CACHE

    with _lock:
        filo_ts = FILO_CACHE["ts"]
        filo_list = list(FILO_CACHE["liste"])
        kapi_map = dict(FILO_CACHE["kapi_map"])

        kaza_v = list(OLAY_CACHE["kaza"]["veri"])
        ariza_v = list(OLAY_CACHE["ariza"]["veri"])
        duyuru_v = list(OLAY_CACHE["duyuru"]["veri"])

        hi_ort = dict(HAFTALIK.get("haftaici", {}))
        hs_ort = dict(HAFTALIK.get("haftasonu", {}))
        top_hi = list(HAFTALIK.get("top_hi", []))
        top_hs = list(HAFTALIK.get("top_hs", []))
        toplam_hi = HAFTALIK.get("toplam_hi", 0)
        toplam_hs = HAFTALIK.get("toplam_hs", 0)

        hat_gorev = dict(ARSIV_CACHE.get("hat_gorev", {}))

        snap_live = {
            h: data["normalized"]
            for h, data in LIVE_BUS_CACHE.items()
            if isinstance(data, dict) and data.get("normalized")
        }

        filo_durum = {}
        plana_uyum = {}
        sefer_zayi = {}

    now = time.time()
    veri_yasi = int(now - filo_ts) if filo_ts else 9999

    new = {
        "summary": {
            "passengers": 0,
            "active_buses": 0,
            "alerts": 0,
            "health": 0
        },
        "summary_display": {
            "passengers": "Yükleniyor…",
            "active_buses": "0",
            "alerts": "0",
            "health": "0"
        },
        "passenger": {
            "labels": [],
            "hi_vals": [],
            "hs_vals": []
        },
        "fleet": {
            "brands": {
                "labels": [],
                "values": [],
                "kaynak": "yok"
            },
            "density": {
                "labels": [],
                "values": []
            }
        },
        "risk_eff": {
            "risk": {
                "labels": [],
                "scores": [],
                "total": 0
            },
            "eff": {
                "labels": [],
                "scores": [],
                "aciklama": "yolcu/görev"
            }
        },
        "economy": {
            "labels": [],
            "fuel": [],
            "co2": [],
            "cost": [],
        },
        "kota": {
            "kullanilan": veri_yasi,
            "limit": 600,
            "kalan": max(0, 600 - veri_yasi)
        },
        "veri_yasi": veri_yasi,
        "operasyonel": {
            "plana_uyum_ort": plana_uyum.get("ort_uyum", 0),
            "zayi_sefer": sefer_zayi.get("toplam", 0),
            "aktif_arac": filo_durum.get("aktif", 0),
            "depoda_arac": filo_durum.get("depoda", 0),
            "ariza_arac": filo_durum.get("ariza", 0),
        },
        "gercek_zamanli": {
            "filo_durum": filo_durum,
            "kaza_bugun": len(kaza_v),
            "ariza_aktif": len(ariza_v),
            "sefer_oran": plana_uyum.get("ort_uyum", 0),
        },
    }

    # ─────────────────────────────────────────────────────
    # AKTİF ARAÇ SAYISI
    # ─────────────────────────────────────────────────────
    # Filo snapshot: GetFiloAracKonum_json'dan konum bildiren TÜM araçlar (garajdakiler dahil)
    # Operasyonel araç (yuk_ozet[toplam_aktif]): GetIettArsivGorev_json'dan 1+ saat sefer yapan
    # İki sayı farklı kaynaktan, farklı kavramı ölçer — ikisi de doğrudur.
    arac_say = len(filo_list) or sum(len(v) for v in snap_live.values())
    new["summary"]["active_buses"] = arac_say
    new["summary"]["active_buses_aciklama"] = "Anlık konum bildiren araçlar (filo snapshot)"
    new["summary_display"]["active_buses"] = f"{arac_say:,}".replace(",", ".")

    # ─────────────────────────────────────────────────────
    # MARKA DAĞILIMI
    # ─────────────────────────────────────────────────────
    markalar_gercek = Counter()
    markalar_tahmin = Counter()

    for kapi, info in kapi_map.items():
        m = temiz_str(info.get("marka", "")).upper().strip()
        t = temiz_str(info.get("tip", "")).upper().strip()
        combined = (m + " " + t).strip()

        if combined:
            if "MERCEDES" in combined or "CITARO" in combined:
                markalar_gercek["MERCEDES"] += 1
            elif "MAN" in combined:
                markalar_gercek["MAN"] += 1
            elif any(x in combined for x in ("OTOKAR", "KENT", "DORUK")):
                markalar_gercek["OTOKAR"] += 1
            elif any(x in combined for x in ("BMC", "PROCITY", "BELDE")):
                markalar_gercek["BMC"] += 1
            elif any(x in combined for x in ("KARSAN", "JEST", "ATAK")):
                markalar_gercek["KARSAN"] += 1
            elif any(x in combined for x in ("ISUZU", "İSUZU", "NOVOCITI")):
                markalar_gercek["İSUZU"] += 1
            elif any(x in combined for x in ("TEMSA", "ISTANBUL", "AVENUE")):
                markalar_gercek["TEMSA"] += 1
            else:
                markalar_gercek[combined[:16]] += 1
        else:
            k = temiz_str(kapi).upper()
            if k and k[0] in ("M", "C"):
                markalar_tahmin["MERCEDES*"] += 1
            elif k and k[0] == "O":
                markalar_tahmin["OTOKAR*"] += 1
            elif k and k[0] == "B":
                markalar_tahmin["BMC*"] += 1
            elif k and k[0] == "K":
                markalar_tahmin["KARSAN*"] += 1
            elif k and k[0] in ("I", "İ"):
                markalar_tahmin["İSUZU*"] += 1
            elif k and k[0] == "T":
                markalar_tahmin["TEMSA*"] += 1
            else:
                markalar_tahmin["DİĞER*"] += 1

    if markalar_gercek:
        mc = markalar_gercek.most_common(7)
        new["fleet"]["brands"] = {
            "labels": [m[0] for m in mc],
            "values": [m[1] for m in mc],
            "kaynak": "api"
        }
    elif markalar_tahmin:
        mc = markalar_tahmin.most_common(7)
        new["fleet"]["brands"] = {
            "labels": [m[0] for m in mc],
            "values": [m[1] for m in mc],
            "kaynak": "tahmin"
        }

    # ─────────────────────────────────────────────────────
    # YOĞUNLUK / EN YOĞUN HATLAR — haftalık + canlı araç
    # Sadece LIVE_BUS_CACHE'e bağlı değil; haritada aratılmamış
    # hatlar da dahil edilerek tüm ağ analiz edilir.
    # ─────────────────────────────────────────────────────
    all_hat_set = set(hi_ort.keys()) | set(snap_live.keys())
    dens_birlesik = []
    for h in all_hat_set:
        arac_canli   = len(snap_live.get(h, []))
        yolcu_haftaici = hi_ort.get(h, 0)
        # Sıralama önceliği: canlı araç sayısı, eşitlikte haftalık yolcu
        dens_birlesik.append((h, arac_canli, yolcu_haftaici))

    # Canlı araç önce, sonra haftalık yolcu ile sırala
    dens_birlesik.sort(key=lambda x: (x[1], x[2] // 1000), reverse=True)
    top10 = dens_birlesik[:10]

    new["fleet"]["density"] = {
        "labels": [x[0] for x in top10],
        # Canlı araç yoksa haftalık yolcudan tahmin (5000 yolcu ≈ 1 araç)
        "values": [x[1] if x[1] > 0 else max(1, x[2] // 5000) for x in top10]
    }

    # ─────────────────────────────────────────────────────
    # YOLCU ÖZETİ
    # ─────────────────────────────────────────────────────
    toplam = toplam_hi + toplam_hs
    new["summary"]["passengers"] = toplam

    if toplam > 1_000_000:
        new["summary_display"]["passengers"] = f"{toplam / 1_000_000:.1f}M"
    elif toplam > 0:
        new["summary_display"]["passengers"] = f"{toplam / 1000:.0f}K"
    else:
        new["summary_display"]["passengers"] = "Yükleniyor…"

    all_hats = list(dict.fromkeys(
        [x["hat"] for x in top_hi[:10]] +
        [x["hat"] for x in top_hs[:10]]
    ))[:12]

    new["passenger"]["labels"] = all_hats
    new["passenger"]["hi_vals"] = [hi_ort.get(h, 0) for h in all_hats]
    new["passenger"]["hs_vals"] = [hs_ort.get(h, 0) for h in all_hats]

    # ── Datathon yolcu agg alanlarını koru (canlı SQL'in üzerine yaz) ──
    # JSON şeması: YOLCULUK_AGG_ANALIZ.ipynb çıktısı (top_hatlar/saat_dagilim/ay_dagilim)
    _yolcu_agg = PANEL_DATA.get('yolcu_agg', {})
    if _yolcu_agg:
        _kpi    = _yolcu_agg.get('kpi', {})
        _aylik  = _yolcu_agg.get('ay_dagilim', [])
        _saat_l = _yolcu_agg.get('saat_dagilim', [])
        _hat_l  = _yolcu_agg.get('top_hatlar', [])
        _toplam = _kpi.get('toplam_yolculuk', 0)
        _sv     = [0] * 24
        for _s in _saat_l:
            _sno = int(_s.get('saat', 0) or 0)
            if 0 <= _sno < 24:
                _sv[_sno] = _s.get('yolculuk', 0)
        _maks = max(_sv) or 1
        _top_hats = sorted(
            [h for h in _hat_l
             if h.get('hat')
             and (h.get('hat') or '').strip().lower() != 'bilinmiyor'],
            key=lambda x: x.get('yolculuk', 0), reverse=True
        )[:12]
        # Hat cinsi haritası + tüm metrobüs hatları — yolcu tablosu (YOLCULUK kaynağı)
        try:
            _con2 = get_panel_db()
            _cur2 = _con2.cursor()
            _cur2.execute(
                "SELECT GUNCEL_HATKODU, GUNCEL_HATCINSI FROM yolcu "
                "WHERE GUNCEL_HATCINSI IS NOT NULL GROUP BY GUNCEL_HATKODU"
            )
            _hc_map = {r[0]: (r[1] or '').strip() for r in _cur2.fetchall()}
            _metro_kodlari = [k for k, v in _hc_map.items() if 'METROB' in v.upper()]
            _metro_rows = []
            if _metro_kodlari:
                _ph = ','.join('?' * len(_metro_kodlari))
                _cur2.execute(
                    f"SELECT GUNCEL_HATKODU, GUNCEL_HATADI, COUNT(*) as cnt "
                    f"FROM yolcu WHERE GUNCEL_HATKODU IN ({_ph}) "
                    f"GROUP BY GUNCEL_HATKODU ORDER BY cnt DESC",
                    _metro_kodlari
                )
                _metro_rows = _cur2.fetchall()
            _con2.close()
        except Exception as _e:
            print(f"[METRO] SQLite sorgu hatası: {_e}")
            _hc_map = {}
            _metro_rows = []
        new["passenger"]["labels"]          = [h['hat'] for h in _top_hats]
        new["passenger"]["hi_vals"]         = [int(h.get('yolculuk', 0) * 0.79) for h in _top_hats]
        new["passenger"]["hs_vals"]         = [int(h.get('yolculuk', 0) * 0.21) for h in _top_hats]
        new["passenger"]["hat_cinsi"]       = [_hc_map.get(h['hat'], '') for h in _top_hats]
        new["passenger"]["metro_hatlar"]    = [
            {'kod': r[0], 'ad': (r[1] or '').strip(), 'yolcu': r[2]}
            for r in _metro_rows if r[0]
        ]
        new["passenger"]["saat_norm"]       = [round(v / _maks, 3) for v in _sv]
        new["passenger"]["aylik"]           = [{'ay': a.get('ay'), 'yolcu': a.get('yolculuk', 0)} for a in _aylik]
        new["passenger"]["toplam"]          = _toplam
        new["passenger"]["haftalik"]        = _kpi.get('haftalik_ort') or (int(_toplam / 26) if _toplam else 0)
        new["passenger"]["benzersiz_hat"]   = _kpi.get('hat_sayisi', 0)
        new["passenger"]["benzersiz_durak"] = _kpi.get('durak_sayisi', 0)
        new["passenger"]["aktarma_pct"]     = _kpi.get('aktarma_orani_pct', 0)
        new["passenger"]["kaynak"]          = 'YOLCULUK CSV — H1 2025 ham agregat'
        new["summary"]["passengers"]        = new["passenger"]["haftalik"]
        new["summary_display"]["passengers"] = f"{_toplam / 1_000_000:.1f}M (6 ay)"

    # ─────────────────────────────────────────────────────
    # VERİMLİLİK / STRES GÖSTERGESİ
    # ─────────────────────────────────────────────────────
    eff = []

    for item in top_hi[:15]:
        h = item["hat"]
        yolcu = item["yolcu"]
        gorev = hat_gorev.get(h, 0)
        arac = len(snap_live.get(h, []))

        if gorev > 0:
            # Planlanan sefer sayısı — tutarlı ve sabit referans
            eff.append({"hat": h, "skor": int(yolcu / max(gorev, 1)), "kaynak": "planlanan_sefer"})
        elif arac > 0:
            # Canlı araç sayısı — sadece planlanan yoksa fallback
            eff.append({"hat": h, "skor": int(yolcu / max(arac, 1)), "kaynak": "live"})

    eff.sort(key=lambda x: x["skor"], reverse=True)

    new["risk_eff"]["eff"] = {
        "labels": [e["hat"] for e in eff[:10]],
        "scores": [e["skor"] for e in eff[:10]],
        "aciklama": "yolcu/planlananSefer" if any(e["kaynak"] == "planlanan_sefer" for e in eff) else "yolcu/araç"
    }

    # ─────────────────────────────────────────────────────
    # OLAYLAR / RİSK
    # ─────────────────────────────────────────────────────
    ks = len([x for x in kaza_v if isinstance(x, dict)])
    ar = len([x for x in ariza_v if isinstance(x, dict)])
    du = len([x for x in duyuru_v if isinstance(x, dict)])

    toplam_uyari = ks + ar + du
    new["summary"]["alerts"] = toplam_uyari
    new["summary_display"]["alerts"] = str(toplam_uyari)

    new["risk_eff"]["risk"] = {
        "labels": ["Kaza/Çarpışma", "Araç/Saha Arızası", "Güzergah Duyurusu"],
        "scores": [ks, ar, du],
        "total": toplam_uyari
    }

    # ─────────────────────────────────────────────────────
    # SİSTEM SAĞLIK SKORU
    # ─────────────────────────────────────────────────────
    taze_puan = 40 if veri_yasi < 300 else (30 if veri_yasi < 600 else (15 if veri_yasi < 1800 else 0))
    olay_puan = max(0, 30 - min(30, (ks + ar) * 3))
    arac_puan = 30 if arac_say > 2000 else (20 if arac_say > 1000 else (10 if arac_say > 300 else 0))

    health_score = taze_puan + olay_puan + arac_puan
    new["summary"]["health"] = health_score
    new["summary_display"]["health"] = str(health_score)

    with _lock:
        # Korunması gereken alanlar (startup'ta YOLCULUK CSV'den dolduruluyor,
        # hesapla_analiz canlı API verisini güncellerken bunlara dokunmamalı)
        _korumalik = {k: ANALYSIS_CACHE.get(k) for k in ('passenger',) if k in ANALYSIS_CACHE}
        ANALYSIS_CACHE.clear()
        ANALYSIS_CACHE.update(new)
        for k, v in _korumalik.items():
            ANALYSIS_CACHE[k] = v
# ──────────────────────────────────────────────────────────
# ZAMANLAYICI
# ──────────────────────────────────────────────────────────
def zamanlayici():
    print("⏳ [ZAMANLAYICI] İlk filo çekimi…")

    for i in range(5):
        if guncelle_filo(zorunlu=True):
            break
        print(f"⚠️  [ZAM] {i+1}/5 başarısız, 30s…")
        time.sleep(30)

    olay_guncelle("duyuru")
    guncelle_arsiv()  # Planlanan sefer sayıları ve kapi_map yön bilgisi


    with _lock:
        son_filo = FILO_CACHE["ts"] or time.time()

    son_kaza = 0
    son_ariza = 0
    son_duyuru = 0
    son_analiz = 0
    son_gecikme = 0
    son_yogunluk = 0

    hesapla_analiz()
    hesapla_gecikme_skorlari()
    hesapla_yogunluk()

    son_analiz = son_gecikme = son_yogunluk = time.time()

    while True:
        try:
            now = time.time()

            if now - son_filo >= FILO_ARALIK:
                if guncelle_filo():
                    son_filo = now
                else:
                    son_filo = now - FILO_ARALIK + 120

            if now - son_kaza >= 1200:
                olay_guncelle("kaza")
                son_kaza = now

            if now - son_ariza >= 1200:
                olay_guncelle("ariza")
                son_ariza = now

            if now - son_duyuru >= 300:
                olay_guncelle("duyuru")
                son_duyuru = now

                guncelle_kavsaklar()

            # Planlanan sefer sayısı ve yön haritası — saatte bir güncelle
            if now - ARSIV_CACHE.get("ts", 0) >= 3600:
                threading.Thread(target=guncelle_arsiv, daemon=True).start()

            if now - son_analiz >= 30:
                hesapla_analiz()
                son_analiz = now

            if now - son_gecikme >= 30:
                hesapla_gecikme_skorlari()
                son_gecikme = now

            if now - son_yogunluk >= 300:
                hesapla_yogunluk()
                son_yogunluk = now


        except Exception as e:
            print(f"⚠️ [ZAM] {e}")

        time.sleep(10)

def haftalik_dongu():
    while True:
        build_haftalik(); time.sleep(7*86400)

def start_background_threads():
    load_panel_data()   # JSON'lar senkron yüklenir (hızlı, ~2sn)
    threading.Thread(target=build_memory_db, daemon=True).start()
    threading.Thread(target=build_durak_dict, daemon=True).start()
    threading.Thread(target=zamanlayici, daemon=True).start()
    threading.Thread(target=haftalik_dongu, daemon=True).start()

# ══════════════════════════════════════════════════════════
# API ENDPOINTLERİ
# ══════════════════════════════════════════════════════════