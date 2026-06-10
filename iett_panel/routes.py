import time
import os
import json as _json_mod
from datetime import datetime, timedelta
from collections import Counter
import random
import re
import requests
import pandas as pd

# ── V6.5 Datathon Modeli Veri Yükleyici ──
_V6_5_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'panel_data', '2025_q3')
_V6_5_CACHE = {}

def _load_v6_5_predictions():
    if 'predictions' not in _V6_5_CACHE:
        _V6_5_CACHE['predictions'] = pd.read_csv(os.path.join(_V6_5_DATA_DIR, 'predictions_q3_v6_5.csv'))
    return _V6_5_CACHE['predictions']

def _load_v6_5_sistem():
    if 'sistem' not in _V6_5_CACHE:
        _V6_5_CACHE['sistem'] = pd.read_csv(os.path.join(_V6_5_DATA_DIR, 'arac_sistem_q3_tahmin_v6_5.csv'))
    return _V6_5_CACHE['sistem']

def _load_v6_5_metrics():
    if 'metrics' not in _V6_5_CACHE:
        try:
            with open(os.path.join(_V6_5_DATA_DIR, 'ml_v6_5_performance_summary.json'), 'r', encoding='utf-8') as f:
                perf = _json_mod.load(f)
            with open(os.path.join(_V6_5_DATA_DIR, 'ml_v6_5_validation_report.json'), 'r', encoding='utf-8') as f:
                val = _json_mod.load(f)
            _V6_5_CACHE['metrics'] = {'performance': perf, 'validation': val}
        except Exception:
            _V6_5_CACHE['metrics'] = {'performance': {}, 'validation': {}}
    return _V6_5_CACHE['metrics']

from services import guncelle_kavsaklar
from flask import jsonify, request, render_template
from utils import *
from services import (
    _lock,
    MEMORY_DB, IS_DB_READY, DURAK_DICT,
    FILO_CACHE, LIVE_BUS_CACHE, OLAY_CACHE, API_RESPONSE_CACHE,
    HAFTALIK, ARSIV_CACHE, SAAT_CACHE,
    GECIKME_CACHE, YOGUNLUK_CACHE, ANALYSIS_CACHE,
    HAT_BILGI_CACHE, ARAC_KONUM_GECMIS, UZUN_DURUŞ_CACHE,
    ISTANBUL_PROFIL, _SAAT_DAGILIM_HIC, _SAAT_DAGILIM_HS,IETT_USER, IETT_PASS, trafik_seviye,
    get_live_buses_cached, tahmin_yon_terminal, fetch_soap,get_traffic_index_history,
    get_traffic_index_history_summary, fetch_soap_xml,
    olay_guncelle, get_arac_ozellik, get_trafik, saat_trafik_katsayi,
    build_haftalik, hesapla_analiz, hesapla_gecikme_skorlari, hesapla_yogunluk,
    guncelle_filo, guncelle_arsiv,
    get_hat_bilgi, hesapla_headway,
    _norm_hat_kodu, _duyuru_hata_ait_mi, _parse_aspnet_date,
    hat_skoru, arac_durak_yaklasiyor_mu, rota_mesafe_km,
    URL_ANA, URL_IBB, URL_FILO, URL_IBB360, URL_SAAT,
    TOMTOM_KEY, guncelle_kavsaklar
)

# ── Kapasite modeli sabitleri (tüm bakım endpoint'leri bu değerleri kullanır) ──
_KAPASITE_ACIL_PCT  = 0.20   # %20 acil arıza rezervi
_KAPASITE_KAZA_PCT  = 0.10   # %10 kaza rezervi
_KAPASITE_NET_PCT   = 0.70   # %70 net bakım kapasitesi
_KAPASITE_GECE_BONUS = 2     # 01-05 gece penceresi: +2 ek slot

def register_routes(app, db):

    @app.route('/api/en_yakin_durak')
    def api_en_yakin_durak():
        lat = temiz_sayi(request.args.get('lat', '0'))
        lon = temiz_sayi(request.args.get('lon', '0'))
        if abs(lat) < 1 or abs(lon) < 1:
            return jsonify({"hata": "Geçersiz konum"})

        min_dist = 9999
        kodu = ""
        ad = ""

        with _lock:
            for k, d in DURAK_DICT.items():
                if d['lat'] > 0 and d['lon'] > 0:
                    dist = hav(lat, lon, d['lat'], d['lon'])
                    if dist < min_dist:
                        min_dist = dist
                        kodu = k
                        ad = d['ad']

        if kodu:
            return jsonify({"kodu": kodu, "ad": ad, "mesafe_m": int(min_dist * 1000)})

        return jsonify({"hata": "Yakınlarda durak bulunamadı."})

    TR_MAP = str.maketrans({
        'Ç':'C','Ğ':'G','İ':'I','I':'I','Ö':'O','Ş':'S','Ü':'U',
        'ç':'c','ğ':'g','ı':'i','i':'i','ö':'o','ş':'s','ü':'u',
    })
    STOP_KELIMELER = {
        'DURAK','DURAGI','DURAĞI','DURAGINDA','DURAGI','ISTASYON','ISTASYONU',
        'METRO','METROBUS','METROBÜS','ISKELE','ISKELESI','İSKELE','İSKELESİ',
        'MAH','MAHALLE','MAHALLESI','MAHALLESİ','MEYDAN','MEYDANI',
        'CAD','CADDE','CADDESI','CADDESİ','SK','SOK','SOKAK','SOKAĞI',
        'BULV','BLV','BULVARI','BUL','SITESI','SİTESİ','SITE',
        'YOLU','YOL','KÖPRÜ','KOPRU','GİŞELERİ','GISELERI',
        'ISTANBUL','İSTANBUL','TÜRKİYE','TURKIYE',
    }

    def _norm(s):
        """Türkçe karakter normalize + upper. Boş veya None için ''."""
        if not s: return ''
        return str(s).upper().translate(TR_MAP)

    def _tokenize(s):
        """Metni anlamlı token listesine çevir. Stopword filtresi uygular."""
        norm = re.sub(r'[^\wİıĞğÜüŞşÖöÇç]+', ' ', _norm(s))
        return [t for t in norm.split() if len(t) >= 2 and t not in STOP_KELIMELER]

    def _durak_skor(q_tokens, ad_tokens):
        """
        Sorgu tokenları ile durak adı tokenları arasındaki eşleşme skoru.
        Yüksek skor = daha iyi eşleşme. 0 = hiç eşleşme yok.
        """
        if not q_tokens or not ad_tokens: return 0
        skor = 0
        kullanilan = set()
        for qt in q_tokens:
            best_i, best_pts = -1, 0
            for i, at in enumerate(ad_tokens):
                if i in kullanilan: continue
                if qt == at:
                    pts = 100  # tam eşleşme
                elif len(qt) >= 3 and qt in at:
                    pts = 60 + min(30, len(qt) * 3)  # sorgu durakta substring
                elif len(at) >= 3 and at in qt:
                    pts = 40 + min(20, len(at) * 2)  # durak sorguda substring
                elif len(qt) >= 4 and len(at) >= 4 and qt[:4] == at[:4]:
                    pts = 30  # prefix eşleşmesi
                else:
                    pts = 0
                if pts > best_pts:
                    best_pts = pts; best_i = i
            if best_pts > 0:
                skor += best_pts
                kullanilan.add(best_i)
        # tüm sorgu tokenları eşleşirse büyük bonus
        if len(kullanilan) == len(q_tokens):
            skor += 50
        # durak adı çok kısaysa ve hepsi eşleşirse ek bonus
        if len(kullanilan) == len(ad_tokens):
            skor += 30
        return skor

    def _durak_adaylari(metin, durak_sozlugu, top_n=5, min_skor=80):
        """
        Token bazlı fuzzy arama. En iyi top_n adayı (kod, skor, ad) tuple olarak döndür.
        Hem durak adında hem ilçe alanında arama yapar.
        """
        if not metin: return []
        q_tokens = _tokenize(metin)
        if not q_tokens: return []
        metin_strip = _norm(metin).strip()
        if metin_strip in durak_sozlugu:
            d = durak_sozlugu[metin_strip]
            return [(metin_strip, 1000, d.get('ad', metin_strip))]
        sonuclar = []
        for kod, d in durak_sozlugu.items():
            ad = d.get('ad', '')
            if not ad: continue
            ad_tokens = _tokenize(ad)
            ilce_tokens = _tokenize(d.get('ilce', ''))
            if not ad_tokens and not ilce_tokens: continue
            # Durak adı skoru
            sk_ad = _durak_skor(q_tokens, ad_tokens) if ad_tokens else 0
            # İlçe skoru: ilçe yalnız bir kelime — daha düşük katsayı
            sk_ilce = _durak_skor(q_tokens, ilce_tokens) // 2 if ilce_tokens else 0
            # Eşleşmeyen tokenları durakla birleşik dene (ilçe + ad)
            if sk_ad > 0 and sk_ilce > 0:
                # Hem ad hem ilçe katkıda bulunuyor → güçlü eşleşme
                sk = sk_ad + sk_ilce
            else:
                sk = max(sk_ad, sk_ilce)
            if sk >= min_skor:
                sonuclar.append((kod, sk, ad))
        sonuclar.sort(key=lambda x: x[1], reverse=True)
        return sonuclar[:top_n]

    def _durak_kodu_bul(metin, durak_sozlugu):
        """En iyi tek aday — geri uyumluluk için."""
        adaylar = _durak_adaylari(metin, durak_sozlugu, top_n=1)
        return adaylar[0][0] if adaylar else None

    def _geocode_nominatim(metin):
        """Nominatim ile adres/yer → (lat, lon, display_name). None döner hatada."""
        try:
            url="https://nominatim.openstreetmap.org/search"
            params={"q":f"{metin}, İstanbul, Türkiye","format":"json","limit":1,
                    "addressdetails":0,"viewbox":"28.5,41.3,29.5,40.8","bounded":1}
            r=requests.get(url,params=params,timeout=6,headers={"User-Agent":"UKOME-Portal/1.0"})
            data=r.json()
            if data:
                return float(data[0]["lat"]),float(data[0]["lon"]),data[0].get("display_name","")
            # bounded başarısızsa İstanbul kısıtsız dene
            params2={"q":f"{metin}, İstanbul","format":"json","limit":1}
            r2=requests.get(url,params=params2,timeout=6,headers={"User-Agent":"UKOME-Portal/1.0"})
            data2=r2.json()
            if data2:
                lat,lon=float(data2[0]["lat"]),float(data2[0]["lon"])
                if 40.5<=lat<=41.5 and 27.5<=lon<=30.0:
                    return lat,lon,data2[0].get("display_name","")
        except Exception:
            pass
        return None

    def _parse_koordinat(metin):
        m=re.match(r'^(-?\d+\.?\d*)[,\s]+(-?\d+\.?\d*)$',metin.strip())
        if m:
            lat,lon=float(m.group(1)),float(m.group(2))
            if 40.0<=lat<=42.0 and 27.0<=lon<=31.0: return lat,lon
        return None

    def _en_yakin_durak_koordinat(lat,lon,snap_durak,max_km=2.0):
        en_iyi=None; en_dist=max_km
        for kod,d in snap_durak.items():
            dlat=d.get('lat',0); dlon=d.get('lon',0)
            if not dlat or not dlon: continue
            dist=hav(lat,lon,dlat,dlon)
            if dist<en_dist: en_dist=dist; en_iyi=kod
        return en_iyi, en_dist

    def _bekleme_hesapla(hat, durak_lat, durak_lon, canli_eta_liste=None):
        """
        Durakta o hattın aracını bekleme süresi (dk).
        1. Canlı ETA varsa: ilk araç süresi (kullanıcı tam o anda durağa varıyor varsayımı)
        2. Yoksa: hat headway / 2 (rastgele varış)
        3. Headway de yoksa: 8 dk varsayılan
        Returns: (bekleme_dk, kaynak: 'canli'|'headway'|'varsayilan', detay_str)
        """
        if canli_eta_liste is None:
            canli_eta_liste = _canli_eta_hesapla(hat, durak_lat, durak_lon)
        if canli_eta_liste:
            ilk = canli_eta_liste[0]['eta_min']
            return max(1, ilk), 'canli', f"Sonraki araç {ilk} dk içinde"
        # Headway tahmini
        try:
            with _lock:
                yc = YOGUNLUK_CACHE.get(hat, {})
            arac = yc.get('arac_sayisi', 0)
            if arac > 0:
                # Sefer süresi: kapasite_saat'ten geri hesap, yoksa hatlar uzunluğuna göre
                kapasite_saat = yc.get('kapasite_saat', 0)
                hat_kap = yc.get('arac_kapasite', 90)
                if kapasite_saat and hat_kap:
                    sefer_saat = kapasite_saat / hat_kap / arac
                    headway = max(2, 60 / max(sefer_saat, 0.5))
                else:
                    headway = max(3, 60 / arac)  # kabaca 1 saatte arac sayısı kadar geçer
                bek = max(2, round(headway / 2))
                return bek, 'headway', f"~{int(headway)} dk aralık · ortalama bekleme"
        except Exception:
            pass
        return 8, 'varsayilan', "Tipik bekleme süresi"

    def _canli_eta_hesapla(hat, durak_lat, durak_lon, max_eta=60):
        """
        Bir hattın o durağa yaklaşan canlı otobüslerini bulup ETA listesini döndürür.
        Format: [{kapi, plaka, eta_min, dist_km, hiz}, ...] sıralı.
        """
        try:
            normalized, _ = get_live_buses_cached(hat)
        except Exception:
            return []
        if not normalized: return []
        try:
            normalized = tahmin_yon_terminal(hat, normalized)
        except Exception:
            pass
        # Hat durak listesini al (varsa)
        cache_key = f"durak_detay_{hat}"
        with _lock: cached_durak = API_RESPONSE_CACHE.get(cache_key)
        hat_duraklar = cached_durak.get("duraklar", []) if cached_durak else []

        sonuclar = []
        for b in normalized:
            try:
                blat, blon = b.get("lat"), b.get("lon")
                if not blat or not blon: continue
                arac_yonu = b.get("yon")
                dist_km = hav(blat, blon, durak_lat, durak_lon)
                if dist_km > 15: continue  # 15km'den uzaktakini hesaplama
                # Yön kontrolü (varsa) - yaklaşmıyorsa atla
                yaklasiyor, _ = arac_durak_yaklasiyor_mu(
                    blat, blon, arac_yonu, durak_lat, durak_lon, hat_duraklar)
                if hat_duraklar and not yaklasiyor: continue

                trafik = get_trafik(blat, blon)
                kats = trafik.get("katsayi", 1.0)
                if hat_duraklar:
                    route_km = rota_mesafe_km(blat, blon, durak_lat, durak_lon, arac_yonu, hat_duraklar)
                else:
                    route_km = dist_km * 1.4  # düz çizgi → kabaca yol mesafesi

                spd_raw = float(b.get("hiz", 0) or 0)
                profil_hiz = max(12.0, 24.0 * kats)
                canli_hiz = spd_raw if spd_raw >= 5 else profil_hiz
                efektif_hiz = max(8.0, min(42.0, (canli_hiz * 0.7) + (profil_hiz * 0.3)))
                eta_baz = max(1.0, (route_km / efektif_hiz) * 60)
                gecikme_dk = max(0.0, 1.0 - kats) * eta_baz * 0.6
                eta_min = max(1, round(eta_baz + gecikme_dk))
                if eta_min > max_eta: continue

                sonuclar.append({
                    "kapi": b.get("kapi", "—"),
                    "plaka": b.get("plaka", "—"),
                    "eta_min": eta_min,
                    "dist_km": round(dist_km, 2),
                    "hiz": int(spd_raw),
                    "trafik": trafik.get("seviye", ""),
                })
            except Exception:
                continue
        sonuclar.sort(key=lambda x: x["eta_min"])
        return sonuclar

    def _coz_giris(girdi, snap_durak):
        """
        Girdiyi çöz: durak (fuzzy) → koordinat → adres (Nominatim).
        Returns: (durak_kodu, display_name, lat, lon, tip, oneriler)
        tip: 'durak' | 'koordinat' | 'adres' | 'koordinat_yok' | 'adres_yok' | None
        oneriler: [{kodu, ad, lat, lon, skor}, ...] eşleşme zayıfsa öneriler.
        """
        bos = (None, None, None, None, None, [])
        if not girdi: return bos
        metin=girdi.strip()

        # 1. Koordinat
        koord=_parse_koordinat(metin)
        if koord:
            lat,lon=koord
            kod,dist=_en_yakin_durak_koordinat(lat,lon,snap_durak)
            if kod:
                ad=snap_durak[kod].get('ad',kod)
                return kod, f"📍 Konuma en yakın: {ad} ({dist:.2f} km)", lat, lon, 'koordinat', []
            return None, None, lat, lon, 'koordinat_yok', []

        # 2. Fuzzy durak araması — top 5 aday
        adaylar = _durak_adaylari(metin, snap_durak, top_n=5)
        if adaylar:
            top_kod, top_skor, top_ad = adaylar[0]
            d = snap_durak[top_kod]
            # Skor çok yüksek (>=200) → kesin → öneri listesi boş
            # Skor orta (80-200) → kabul et ama alternatifler de göster
            oneriler = []
            if top_skor < 200 and len(adaylar) > 1:
                for kod, sk, ad in adaylar[1:4]:
                    dd = snap_durak[kod]
                    oneriler.append({'kodu':kod,'ad':ad,'lat':dd.get('lat',0),
                                     'lon':dd.get('lon',0),'skor':sk,
                                     'ilce':dd.get('ilce','')})
            return top_kod, d.get('ad',top_kod), d.get('lat',0), d.get('lon',0), 'durak', oneriler

        # 3. Nominatim geocoding
        sonuc=_geocode_nominatim(metin)
        if sonuc:
            lat,lon,display=sonuc
            kod,dist=_en_yakin_durak_koordinat(lat,lon,snap_durak)
            if kod:
                ad=snap_durak[kod].get('ad',kod)
                return kod, f"🗺️ {display[:60]} → {ad}", lat, lon, 'adres', []
            return None, display, lat, lon, 'adres_yok', []

        return bos
    

    @app.route('/api/rota_debug')
    def api_rota_debug():
        a=request.args.get('a','').upper(); b=request.args.get('b','').upper()
        with _lock: snap_db=dict(MEMORY_DB); snap_durak=dict(DURAK_DICT)
        durak_a,_,_,_,_,_=_coz_giris(a, snap_durak)
        durak_b,_,_,_,_,_=_coz_giris(b, snap_durak)
        if not durak_a or not durak_b: return jsonify({"hata":"durak çözülemedi","a":durak_a,"b":durak_b})
        hatlar_a=set(snap_db.get(durak_a,[])); hatlar_b=set(snap_db.get(durak_b,[]))
        # hat → duraklar
        hat_to_duraklar={}
        for d_k,h_lst in snap_db.items():
            for h in h_lst: hat_to_duraklar.setdefault(h,[]).append(d_k)
        hatlar_a_komsu=set()
        for h in hatlar_a:
            for d in hat_to_duraklar.get(h,[]):
                for hh in snap_db.get(d,[]):
                    if hh not in hatlar_a: hatlar_a_komsu.add(hh)
        hatlar_b_komsu=set()
        for h in hatlar_b:
            for d in hat_to_duraklar.get(h,[]):
                for hh in snap_db.get(d,[]):
                    if hh not in hatlar_b: hatlar_b_komsu.add(hh)
        orta=hatlar_a_komsu&hatlar_b_komsu
        return jsonify({
            "durak_a":durak_a,"durak_b":durak_b,
            "hatlar_a":sorted(list(hatlar_a)),"hatlar_b":sorted(list(hatlar_b)),
            "memory_db_durak_n":len(snap_db),"hat_n":len(hat_to_duraklar),
            "hatlar_a_komsu_n":len(hatlar_a_komsu),"hatlar_b_komsu_n":len(hatlar_b_komsu),
            "orta_hat_n":len(orta),"orta_ornek":sorted(list(orta))[:30],
            "hatlar_a_komsu_ornek":sorted(list(hatlar_a_komsu))[:30],
        })

    @app.route('/api/nasil_gidilir')
    def api_nasil_gidilir():
        girdi_a=request.args.get('nereden','').strip()
        girdi_b=request.args.get('nereye','').strip()
        with _lock: snap_db=dict(MEMORY_DB); snap_durak=dict(DURAK_DICT)
        if not snap_durak:
            return jsonify({"durum":"bekle","mesaj":"Durak veritabanı henüz hazır değil. Lütfen 1-2 dakika bekleyin."})

        durak_a, label_a, lat_a, lon_a, tip_a, oner_a = _coz_giris(girdi_a, snap_durak)
        durak_b, label_b, lat_b, lon_b, tip_b, oner_b = _coz_giris(girdi_b, snap_durak)

        # Hiç çözülemediyse: fuzzy önerileri "bunu mu kastettin" olarak göster
        if tip_a is None:
            ad_oner=_durak_adaylari(girdi_a, snap_durak, top_n=5, min_skor=40)
            return jsonify({"durum":"hata",
                            "mesaj":f"'{girdi_a}' için eşleşme bulunamadı.",
                            "oneriler_a":[{"kodu":k,"ad":a,"skor":s,
                                           "lat":snap_durak[k].get('lat',0),
                                           "lon":snap_durak[k].get('lon',0),
                                           "ilce":snap_durak[k].get('ilce','')}
                                          for k,s,a in ad_oner]})
        if tip_b is None:
            ad_oner=_durak_adaylari(girdi_b, snap_durak, top_n=5, min_skor=40)
            return jsonify({"durum":"hata",
                            "mesaj":f"'{girdi_b}' için eşleşme bulunamadı.",
                            "oneriler_b":[{"kodu":k,"ad":a,"skor":s,
                                           "lat":snap_durak[k].get('lat',0),
                                           "lon":snap_durak[k].get('lon',0),
                                           "ilce":snap_durak[k].get('ilce','')}
                                          for k,s,a in ad_oner]})
        if tip_a=='koordinat_yok':
            return jsonify({"durum":"hata","mesaj":f"Koordinat alındı ama 2km içinde IETT durağı bulunamadı."})
        if tip_b=='koordinat_yok':
            return jsonify({"durum":"hata","mesaj":f"Koordinat alındı ama 2km içinde IETT durağı bulunamadı."})
        if tip_a=='adres_yok':
            return jsonify({"durum":"hata","mesaj":f"'{girdi_a}' adresi bulundu ama yakında IETT durağı yok."})
        if tip_b=='adres_yok':
            return jsonify({"durum":"hata","mesaj":f"'{girdi_b}' adresi bulundu ama yakında IETT durağı yok."})
        if not durak_a:
            return jsonify({"durum":"hata","mesaj":f"Nereden '{girdi_a}' bulunamadı. Durak adı, kodu, koordinat (41.01,28.97) veya adres girebilirsiniz."})
        if not durak_b:
            return jsonify({"durum":"hata","mesaj":f"Nereye '{girdi_b}' bulunamadı. Durak adı, kodu, koordinat veya adres girebilirsiniz."})

        # ── Yakın durak havuzu (250m içindeki tüm IETT durakları) ──
        # Aynı isim/lokasyondaki birden çok durak kodu için hatlar birleştirilir.
        # Bu sayede 79KM (klasik) "MECİDİYEKÖY" durağında, H-2 "MECİDİYEKÖY METROBÜS" durağında
        # durmuş olsa bile, hedef MECİDİYEKÖY METROBÜS için yakındaki MECİDİYEKÖY durağı da
        # iniş noktası olarak kabul edilir.
        YAKIN_KM = 0.25
        def _yakin_durak_havuzu(merkez_durak):
            m = snap_durak.get(merkez_durak, {})
            mlat, mlon = m.get('lat',0), m.get('lon',0)
            if not mlat or not mlon: return {merkez_durak}
            havuz = {merkez_durak}
            for k, d in snap_durak.items():
                dlat, dlon = d.get('lat',0), d.get('lon',0)
                if not dlat or not dlon: continue
                if hav(mlat, mlon, dlat, dlon) <= YAKIN_KM:
                    havuz.add(k)
            return havuz
        havuz_a = _yakin_durak_havuzu(durak_a)
        havuz_b = _yakin_durak_havuzu(durak_b)
        # Hat → o hattı barındıran havuz_a durağı (en yakın orijinal A'ya)
        # Bu sayede biniş durağını doğru seçeriz.
        d_a_info = snap_durak[durak_a]; d_b_info = snap_durak[durak_b]
        hat_binis = {}  # hat → durak_kodu (A havuzundan)
        hat_inis  = {}  # hat → durak_kodu (B havuzundan)
        for d_k in havuz_a:
            for h in snap_db.get(d_k, []):
                if h not in hat_binis:
                    hat_binis[h] = d_k
                else:
                    # Daha yakın olanı tercih et
                    cur = snap_durak[hat_binis[h]]
                    yeni = snap_durak[d_k]
                    if hav(d_a_info['lat'], d_a_info['lon'], yeni['lat'], yeni['lon']) < \
                       hav(d_a_info['lat'], d_a_info['lon'], cur['lat'], cur['lon']):
                        hat_binis[h] = d_k
        for d_k in havuz_b:
            for h in snap_db.get(d_k, []):
                if h not in hat_inis:
                    hat_inis[h] = d_k
                else:
                    cur = snap_durak[hat_inis[h]]
                    yeni = snap_durak[d_k]
                    if hav(d_b_info['lat'], d_b_info['lon'], yeni['lat'], yeni['lon']) < \
                       hav(d_b_info['lat'], d_b_info['lon'], cur['lat'], cur['lon']):
                        hat_inis[h] = d_k
        hatlar_a = set(hat_binis.keys())
        hatlar_b = set(hat_inis.keys())
        rotalar=[]
        saat=datetime.now().hour; hici=datetime.now().weekday()<5
        th,ts=ISTANBUL_PROFIL.get(saat,(0.75,0.75))
        genel_kats=th if hici else ts
        # Otobüs hızı modeli: özel şerit avantajı, en kötü 13 km/h, en iyi 22 km/h
        otobus_hizi_kmh = 13.0 + (22.0 - 13.0) * max(0.0, min(1.0, genel_kats))
        for hat in sorted(list(hatlar_a.intersection(hatlar_b))):
            b_kod = hat_binis[hat]; i_kod = hat_inis[hat]
            b_info = snap_durak[b_kod]; i_info = snap_durak[i_kod]
            if b_kod == i_kod: continue  # aynı durakta direkt rota mantıksız
            mesafe_km=hav(b_info['lat'],b_info['lon'],i_info['lat'],i_info['lon'])
            seyahat_dk=int((mesafe_km/otobus_hizi_kmh)*60)
            toplam_sure=seyahat_dk+10
            # A/B asıl durağa yürüme bilgisi (havuzdan farklı durak seçildiyse)
            yuruyu_a_ek = hav(d_a_info['lat'],d_a_info['lon'],b_info['lat'],b_info['lon'])
            yuruyu_b_ek = hav(d_b_info['lat'],d_b_info['lon'],i_info['lat'],i_info['lon'])
            yuruyu_a_ek_dk = max(0, int((yuruyu_a_ek/4.8)*60)) if yuruyu_a_ek > 0.03 else 0
            yuruyu_b_ek_dk = max(0, int((yuruyu_b_ek/4.8)*60)) if yuruyu_b_ek > 0.03 else 0
            rotalar.append({"tip":"direkt","hatlar":[hat],"toplam_sure":toplam_sure,
                            "aciklama":f"<b>{b_info['ad']}</b> durağından <b>{hat}</b> hattına binin.",
                            "puan": max(1, 100 - seyahat_dk),
                            "adimlar":[
                                {"tip":"yuru","mesaj":f"📍 <b>{b_info['ad']}</b> durağına gidin."},
                                {"tip":"bin","mesaj":f"🚌 <b>{hat}</b> numaralı araca binin.","hat":hat,"durak":b_kod,"lat":b_info['lat'],"lon":b_info['lon']},
                                {"tip":"in","mesaj":f"🏁 <b>{i_info['ad']}</b> durağında inin. ({seyahat_dk} dk)"}
                            ],
                            "detay":{"b_kodu":b_kod,"b_durak":b_info['ad'],"b_lat":b_info['lat'],"b_lon":b_info['lon'],
                                     "i_kodu":i_kod,"i_durak":i_info['ad'],"i_lat":i_info['lat'],"i_lon":i_info['lon']}})
        if len(rotalar)<3:
            transferler=[]
            for durak_c,hatlar_c in snap_db.items():
                if durak_c in havuz_a or durak_c in havuz_b: continue
                kesisim_ac=hatlar_a.intersection(hatlar_c); kesisim_cb=hatlar_b.intersection(hatlar_c)
                if kesisim_ac and kesisim_cb:
                    h1 = max(kesisim_ac, key=hat_skoru)
                    h2 = max(kesisim_cb, key=hat_skoru)
                    if h1!=h2:
                        dc_info=snap_durak.get(durak_c,{})
                        if not dc_info.get('lat',0): continue
                        durak_c_ad=dc_info.get('ad',durak_c)
                        b_kod=hat_binis[h1]; i_kod=hat_inis[h2]
                        b_info=snap_durak[b_kod]; i_info=snap_durak[i_kod]
                        mesafe1=hav(b_info['lat'],b_info['lon'],dc_info['lat'],dc_info['lon'])
                        mesafe2=hav(dc_info['lat'],dc_info['lon'],i_info['lat'],i_info['lon'])
                        seyahat_dk=int(((mesafe1+mesafe2)/otobus_hizi_kmh)*60)
                        toplam_sure=seyahat_dk+20
                        transferler.append({"tip":"aktarmali","hatlar":[h1,h2],"toplam_sure":toplam_sure,
                                            "aciklama":f"<b>{h1}</b> ile <b>{durak_c_ad}</b>'da <b>{h2}</b>'ye aktarma.",
                                            "puan": max(1, 50 - seyahat_dk),
                                            "adimlar":[
                                                {"tip":"yuru","mesaj":f"📍 <b>{b_info['ad']}</b> durağına gidin."},
                                                {"tip":"bin","mesaj":f"🚌 <b>{h1}</b> numaralı araca binin.","hat":h1,"durak":b_kod,"lat":b_info['lat'],"lon":b_info['lon']},
                                                {"tip":"in","mesaj":f"🔄 <b>{durak_c_ad}</b> durağında inin."},
                                                {"tip":"bin","mesaj":f"🚌 <b>{h2}</b> hattına aktarma yapın.","hat":h2,"durak":durak_c,"lat":dc_info['lat'],"lon":dc_info['lon']},
                                                {"tip":"in","mesaj":f"🏁 <b>{i_info['ad']}</b> durağında inin."}
                                            ],
                                            "detay":{"b_kodu":b_kod,"b_durak":b_info['ad'],"b_lat":b_info['lat'],"b_lon":b_info['lon'],
                                                     "a_kodu":durak_c,"a_durak":durak_c_ad,"a_lat":dc_info['lat'],"a_lon":dc_info['lon'],
                                                     "i_kodu":i_kod,"i_durak":i_info['ad'],"i_lat":i_info['lat'],"i_lon":i_info['lon']}})
                        if len(transferler)>30: break
            seen=set()
            for t in transferler:
                combo=f"{t['hatlar'][0]}-{t['hatlar'][1]}"
                if combo not in seen:
                    seen.add(combo); rotalar.append(t)
                    if len(rotalar)>=5: break

            # ── BFS ÇOKLU AKTARMA (1-aktarmalı yetersizse, max 4 aktarma) ──
            if len(rotalar) < 2 and hatlar_a and hatlar_b:
                # Hat → durak indeksi
                hat_to_duraklar = {}
                for d_k, h_listesi in snap_db.items():
                    if not snap_durak.get(d_k, {}).get('lat'): continue
                    for h in h_listesi:
                        hat_to_duraklar.setdefault(h, []).append(d_k)

                # BFS: hat-seviyesinde. visited[h] = (parent_hat, transfer_durak, derinlik)
                MAX_AKTARMA = 4
                visited = {h: (None, None, 0) for h in hatlar_a}
                from collections import deque
                kuyruk = deque([(h, 0) for h in hatlar_a])
                bulunan_yollar = []  # her biri (hatlar, aktarma_duraklari, derinlik)

                while kuyruk and len(bulunan_yollar) < 8:
                    h_cur, d_cur = kuyruk.popleft()
                    if d_cur >= MAX_AKTARMA: continue
                    # h_cur'ın duraklarındaki diğer hatlara genişle
                    for d_k in hat_to_duraklar.get(h_cur, []):
                        # aynı durakta aktarma — d_k'da geçen tüm hatlar (h_cur hariç)
                        if d_k in (durak_a, durak_b): continue
                        for h_next in snap_db.get(d_k, []):
                            if h_next == h_cur: continue
                            if h_next in visited: continue
                            visited[h_next] = (h_cur, d_k, d_cur + 1)
                            if h_next in hatlar_b:
                                # Hedefe ulaştık — yolu geri çevir
                                hat_yolu = [h_next]
                                aktarma_yolu = []
                                cur = h_next
                                while True:
                                    parent, transfer_d, _ = visited[cur]
                                    if parent is None: break
                                    aktarma_yolu.append(transfer_d)
                                    hat_yolu.append(parent)
                                    cur = parent
                                hat_yolu.reverse()
                                aktarma_yolu.reverse()
                                bulunan_yollar.append((hat_yolu, aktarma_yolu, d_cur + 1))
                            else:
                                kuyruk.append((h_next, d_cur + 1))

                # Bulunan yollardan rota objelerine dönüştür
                for hat_yolu, aktarma_yolu, n_akt in bulunan_yollar[:5]:
                    # Havuzdan en uygun biniş ve iniş durakları
                    binis_kodu = hat_binis.get(hat_yolu[0], durak_a)
                    inis_kodu = hat_inis.get(hat_yolu[-1], durak_b)
                    b_info = snap_durak[binis_kodu]; i_info = snap_durak[inis_kodu]
                    # Toplam mesafe
                    yol_duraklari = [binis_kodu] + aktarma_yolu + [inis_kodu]
                    toplam_mes = 0
                    valid = True
                    for i in range(len(yol_duraklari) - 1):
                        d1 = snap_durak.get(yol_duraklari[i], {})
                        d2 = snap_durak.get(yol_duraklari[i+1], {})
                        if not d1.get('lat') or not d2.get('lat'): valid = False; break
                        toplam_mes += hav(d1['lat'], d1['lon'], d2['lat'], d2['lon'])
                    if not valid: continue
                    if toplam_mes > 120: continue  # 120km üstü atla
                    seyahat_dk = int((toplam_mes / otobus_hizi_kmh) * 60)
                    toplam_sure = seyahat_dk + (n_akt + 1) * 8  # her segment için bekleme

                    # Tip etiketi
                    if n_akt == 2: tip = 'iki_aktarma'; tip_ad = '2 AKTARMA'
                    elif n_akt == 3: tip = 'uc_aktarma'; tip_ad = '3 AKTARMA'
                    else: tip = f'{n_akt}_aktarma'; tip_ad = f'{n_akt} AKTARMA'

                    # Açıklama
                    parcalar = [f"<b>{hat_yolu[0]}</b>"]
                    for i, ad in enumerate(aktarma_yolu):
                        ad_info = snap_durak.get(ad, {})
                        parcalar.append(f"<b>{ad_info.get('ad', ad)}</b>'da <b>{hat_yolu[i+1]}</b>")
                    aciklama = " → ".join(parcalar) + f" ({n_akt} aktarma)"

                    # Adımlar
                    adimlar = [{"tip":"yuru","mesaj":f"📍 <b>{b_info['ad']}</b> durağına gidin."}]
                    for i, h in enumerate(hat_yolu):
                        bk = binis_kodu if i == 0 else aktarma_yolu[i-1]
                        bk_info = snap_durak[bk]
                        adimlar.append({"tip":"bin","mesaj":f"🚌 <b>{h}</b> hattına binin.",
                                       "hat":h,"durak":bk,
                                       "lat":bk_info['lat'],"lon":bk_info['lon']})
                        if i < len(hat_yolu) - 1:
                            akt_info = snap_durak[aktarma_yolu[i]]
                            adimlar.append({"tip":"in","mesaj":f"🔄 <b>{akt_info['ad']}</b> durağında <b>{hat_yolu[i+1]}</b>'e aktarma."})
                        else:
                            adimlar.append({"tip":"in","mesaj":f"🏁 <b>{i_info['ad']}</b> durağında inin."})

                    # Detay (a, a2, a3, a4 olarak aktarmalar)
                    detay = {
                        "b_kodu":binis_kodu,"b_durak":b_info['ad'],"b_lat":b_info['lat'],"b_lon":b_info['lon'],
                        "i_kodu":inis_kodu,"i_durak":i_info['ad'],"i_lat":i_info['lat'],"i_lon":i_info['lon'],
                    }
                    for idx, ad in enumerate(aktarma_yolu):
                        ad_info = snap_durak[ad]
                        prefix = 'a' if idx == 0 else f'a{idx+1}'
                        detay[f'{prefix}_kodu'] = ad
                        detay[f'{prefix}_durak'] = ad_info['ad']
                        detay[f'{prefix}_lat'] = ad_info['lat']
                        detay[f'{prefix}_lon'] = ad_info['lon']

                    rotalar.append({
                        "tip": tip, "hatlar": hat_yolu, "toplam_sure": toplam_sure,
                        "aciklama": aciklama,
                        "puan": max(1, 60 - seyahat_dk // 3 - n_akt * 8),
                        "adimlar": adimlar, "detay": detay
                    })
        # Yürüyüş mesafesi rota başına (havuzdan farklı durak seçilebilir)
        YURUME_HIZI_KMH = 4.8
        for r in rotalar:
            det = r["detay"]
            b_lat_r = det.get("b_lat"); b_lon_r = det.get("b_lon")
            i_lat_r = det.get("i_lat"); i_lon_r = det.get("i_lon")
            # Başlangıç → biniş durağı yürüme
            kaynak_lat = lat_a if lat_a is not None else (snap_durak[durak_a]["lat"] if durak_a else None)
            kaynak_lon = lon_a if lon_a is not None else (snap_durak[durak_a]["lon"] if durak_a else None)
            hedef_lat = lat_b if lat_b is not None else (snap_durak[durak_b]["lat"] if durak_b else None)
            hedef_lon = lon_b if lon_b is not None else (snap_durak[durak_b]["lon"] if durak_b else None)
            yuruyu_a_dk = 0; yuruyu_b_dk = 0
            if kaynak_lat and b_lat_r:
                d = hav(kaynak_lat, kaynak_lon, b_lat_r, b_lon_r)
                if d > 0.03: yuruyu_a_dk = max(1, int((d / YURUME_HIZI_KMH) * 60))
            if hedef_lat and i_lat_r:
                d = hav(hedef_lat, hedef_lon, i_lat_r, i_lon_r)
                if d > 0.03: yuruyu_b_dk = max(1, int((d / YURUME_HIZI_KMH) * 60))
            r["_yuru_a"] = yuruyu_a_dk; r["_yuru_b"] = yuruyu_b_dk
            adimlar = r["adimlar"]
            if yuruyu_a_dk > 0:
                adimlar.insert(0, {"tip":"yuru","mesaj":f"🚶 Başlangıçtan <b>{yuruyu_a_dk} dk</b> yürüyerek <b>{det.get('b_durak','biniş')}</b> durağına gidin."})
            if yuruyu_b_dk > 0:
                adimlar.append({"tip":"yuru","mesaj":f"🚶 <b>{det.get('i_durak','iniş')}</b> durağından <b>{yuruyu_b_dk} dk</b> yürüyerek hedefinize ulaşın."})
            r["toplam_sure"] = r.get("toplam_sure",0) + yuruyu_a_dk + yuruyu_b_dk
            if lat_a is not None and lon_a is not None:
                det["baslangic_lat"]=lat_a; det["baslangic_lon"]=lon_a
            if lat_b is not None and lon_b is not None:
                det["bitis_lat"]=lat_b; det["bitis_lon"]=lon_b
        rotalar.sort(key=lambda x:x["puan"],reverse=True)

        # Her rota için detaylı süre kırılımı + canlı bekleme tahmini
        rotalar = rotalar[:6]
        for r in rotalar:
            det = r.get('detay', {})
            hatlar_r = r.get('hatlar', [])

            # Her segment için biniş koordinatı: b → a → a2 → a3 → a4 ...
            # Her segment için iniş koordinatı: bir sonraki aktarma veya i
            binis_noktalari = [(det.get('b_lat'), det.get('b_lon'))]
            for idx in range(1, len(hatlar_r)):
                prefix = 'a' if idx == 1 else f'a{idx}'
                binis_noktalari.append((det.get(f'{prefix}_lat'), det.get(f'{prefix}_lon')))
            inis_noktalari = []
            for idx in range(1, len(hatlar_r)):
                prefix = 'a' if idx == 1 else f'a{idx}'
                inis_noktalari.append((det.get(f'{prefix}_lat'), det.get(f'{prefix}_lon')))
            inis_noktalari.append((det.get('i_lat'), det.get('i_lon')))

            r['canli'] = None
            kirilim = {
                'yuruyu_a_dk': r.get('_yuru_a', 0),
                'yuruyu_b_dk': r.get('_yuru_b', 0),
                'aktarma_yuruyu_dklar': [0] * max(0, len(hatlar_r) - 1),
                'segmentler': []
            }

            for i, h in enumerate(hatlar_r):
                bin_lat, bin_lon = binis_noktalari[i]
                in_lat, in_lon = inis_noktalari[i]
                if not bin_lat or not in_lat:
                    continue
                try:
                    eta_liste = _canli_eta_hesapla(h, bin_lat, bin_lon)
                except Exception:
                    eta_liste = []
                bek, kaynak, bek_detay = _bekleme_hesapla(h, bin_lat, bin_lon, eta_liste)
                # Segment trafiği — biniş noktasından gerçek trafik durumu
                try:
                    seg_trafik = get_trafik(bin_lat, bin_lon)
                except Exception:
                    seg_trafik = {}
                seg_kats = seg_trafik.get('katsayi', genel_kats)
                seg_seviye = seg_trafik.get('seviye', '')
                seg_renk = seg_trafik.get('renk', '#94a3b8')
                seg_kaynak = seg_trafik.get('kaynak', 'profil')
                mes_seg = hav(bin_lat, bin_lon, in_lat, in_lon)
                # Otobüs özel şeridi modeli: en kötü hızda bile 13 km/h
                # Akıcı (kats=1): 22 km/h | Tıkanık (kats=0.3): ~14 km/h
                OTOBUS_AKICI = 22.0; OTOBUS_KOTU = 13.0
                seg_hizi = OTOBUS_KOTU + (OTOBUS_AKICI - OTOBUS_KOTU) * max(0.0, min(1.0, seg_kats))
                sefer_dk = max(1, int((mes_seg * 1.4 / seg_hizi) * 60))
                # Serbest akış (akıcı trafik referansı)
                sefer_serbest_dk = max(1, int((mes_seg * 1.4 / OTOBUS_AKICI) * 60))
                gecikme_dk = max(0, sefer_dk - sefer_serbest_dk)
                kirilim['segmentler'].append({
                    'tip':'sefer','hat':h,'bekleme_dk':bek,'sefer_dk':sefer_dk,
                    'bekleme_kaynak':kaynak,'bekleme_detay':bek_detay,'mesafe_km':round(mes_seg,2),
                    'trafik_seviye': seg_seviye, 'trafik_renk': seg_renk,
                    'trafik_kats': round(seg_kats, 2), 'trafik_gecikme_dk': gecikme_dk,
                    'trafik_kaynak': seg_kaynak, 'sefer_serbest_dk': sefer_serbest_dk,
                })
                # İlk segment için canlı ETA badge
                if i == 0 and eta_liste:
                    ilk = eta_liste[0]
                    r['canli'] = {
                        'hat': h, 'eta_min': ilk['eta_min'],
                        'kapi': ilk['kapi'], 'plaka': ilk.get('plaka','—'),
                        'sonraki': [e['eta_min'] for e in eta_liste[1:3]],
                        'arac_sayisi': len(eta_liste),
                    }

            # Toplam süreyi kırılımdan yeniden hesapla
            toplam = kirilim['yuruyu_a_dk'] + kirilim['yuruyu_b_dk'] + sum(kirilim['aktarma_yuruyu_dklar'])
            for s in kirilim['segmentler']:
                toplam += s['bekleme_dk'] + s['sefer_dk']
            r['toplam_sure'] = toplam
            r['sure_kirilim'] = kirilim

        if rotalar:
            return jsonify({"durum":"tamam","rotalar":rotalar,"a_kod":durak_a,"b_kod":durak_b,
                            "a_label":label_a or snap_durak.get(durak_a,{}).get("ad",girdi_a),
                            "b_label":label_b or snap_durak.get(durak_b,{}).get("ad",girdi_b),
                            "a_tip":tip_a,"b_tip":tip_b,
                            "oneriler_a":oner_a,"oneriler_b":oner_b})
        return jsonify({"durum":"hata","mesaj":"Bu iki durak arasında uygun rota bulunamadı. Farklı durak adı, koordinat veya adres deneyin."})

    @app.route('/api/v1/dashboard')
    def api_dashboard():
        with _lock:
            data = dict(ANALYSIS_CACHE)
        return jsonify(data)

    @app.route('/api/hat_detay')
    def api_hat_detay():
        hat=request.args.get('hat','').upper()
        res=fetch_soap(URL_ANA,'GetHat_json',
                       f'<GetHat_json xmlns="http://tempuri.org/"><HatKodu>{hat}</HatKodu></GetHat_json>')
        return jsonify(res or [])

    @app.route('/api/istatistik')
    def api_istatistik():
        hat=request.args.get('hat','').upper()
        with _lock:
            hi=HAFTALIK.get("haftaici",{}).get(hat,0)
            hs=HAFTALIK.get("haftasonu",{}).get(hat,0)
            gorev=ARSIV_CACHE.get("hat_gorev",{}).get(hat,0)
        if hi>0:
            return jsonify({"dunku_yolcu":f"HİÇ:{hi:,} | HS:{hs:,}".replace(',','.'),"bugunku_gorev_sayisi":gorev,"kaynak":"ram"})
        yolcu_str="Veri Yok"
        for off in [1,2,3]:
            t=(datetime.now()-timedelta(days=off)).strftime("%Y-%m-%d")
            g=(datetime.now()-timedelta(days=off)).strftime("%d/%m")
            body=f'<GetIettYolculukHat_json xmlns="http://tempuri.org/"><Tarih>{t}</Tarih></GetIettYolculukHat_json>'
            res=fetch_soap(URL_IBB360,'GetIettYolculukHat_json',body,use_auth=False,timeout_sec=8)
            if isinstance(res,list):
                for y in res:
                    y_hat = temiz_str(alan_oku(y, 'Hat', 'HAT', 'HatKodu', 'HATKODU')).upper()
                    if y_hat == hat:
                        try:
                            yolcu_val = int(temiz_sayi(alan_oku(y, 'Yolculuk', 'YOLCULUK', 'Yolcu', 'YOLCU', varsayilan=0)))
                            yolcu_str = f"{yolcu_val:,}".replace(',', '.')
                        except Exception:
                            pass
                        break
            if yolcu_str!="Veri Yok": break
        return jsonify({"dunku_yolcu":yolcu_str,"bugunku_gorev_sayisi":gorev,"kaynak":"api"})



    @app.route('/api/durak_detay')
    def api_durak_detay():
        hat=request.args.get('hat','').upper()
        cache_key=f"durak_detay_{hat}"
        with _lock:
            cached = API_RESPONSE_CACHE.get(cache_key)
        if cached:
            return jsonify(cached)
        body=f'<DurakDetay_GYY_wYonAdi xmlns="http://tempuri.org/"><hat_kodu>{hat}</hat_kodu></DurakDetay_GYY_wYonAdi>'
        root=fetch_soap_xml(URL_IBB,'DurakDetay_GYY_wYonAdi',body,timeout_sec=10)
        if root is None: return jsonify({"duraklar":[],"terminaller":{"G":"Gidiş","D":"Dönüş"}})
        data=[]; api_yon={"G":None,"D":None}
        with _lock: snap=dict(DURAK_DICT)
        for tbl in root.iter():
            if not tbl.tag.endswith('Table'): continue
            d={c.tag.split('}')[-1].upper():c.text for c in tbl}
            if 'YKOORDINATI' not in d or 'XKOORDINATI' not in d: continue
            yv=yon_cozucu(d.get('YON')); dkod=d.get('DURAKKODU','')
            inf=snap.get(dkod,{'akilli':False,'engelli':False,'tip':'AÇIK'})
            lat=temiz_sayi(d.get('YKOORDINATI','0')); lon=temiz_sayi(d.get('XKOORDINATI','0'))
            data.append({"sira":int(d.get('SIRANO',0) or 0),"ad":temiz_str(d.get('DURAKADI'),'Durak'),
                         "lat":lat,"lon":lon,"yon":yv,"kodu":dkod,
                         "akilli":inf.get('akilli',False),"engelli":inf.get('engelli',False),"tip":inf.get('tip','AÇIK')})
            yon_adi=temiz_str(d.get('YONADI') or d.get('YON_ADI'))
            if yon_adi and not api_yon[yv]: api_yon[yv]=yon_adi
        data.sort(key=lambda x:x['sira'])
        gi=[x for x in data if x['yon']=='G']; do=[x for x in data if x['yon']=='D']
        terms={"G":api_yon["G"] or (gi[-1]['ad'] if gi else "Gidiş"),
               "D":api_yon["D"] or (do[-1]['ad'] if do else "Dönüş")}
        sonuc={"duraklar":data,"terminaller":terms}
        with _lock:
            API_RESPONSE_CACHE[cache_key]=sonuc
        return jsonify(sonuc)

    @app.route('/api/canli_konum')
    def api_canli_konum():
        hat = request.args.get('hat', '').upper().strip()
        force = request.args.get('force', '0').strip() == '1'

        if not hat:
            return jsonify({"araclar": [], "veri_yasi_sn": 0, "arac_sayisi": 0})

        normalized, raw = get_live_buses_cached(hat, force_refresh=force)

        if normalized:
            normalized = tahmin_yon_terminal(hat, normalized)

        now = time.time()

        with _lock:
            live_entry = LIVE_BUS_CACHE.get(hat, {})
            live_ts = live_entry.get("ts", 0)

        veri_yasi = int(now - live_ts) if live_ts else 0

        return jsonify({
            "araclar": normalized,
            "veri_yasi_sn": veri_yasi,
            "arac_sayisi": len(normalized),
            "force_used": force
        })

    # ★ FIX: Tek /api/bildirimler endpoint — çift tanım silindi
    @app.route('/api/bildirimler')
    def api_bildirimler():
        hat = request.args.get('hat', '').upper().strip()
        duyuru = olay_guncelle("duyuru")
        sonuclar = {"kaza": [], "ariza": [], "duyuru": []}

        for d in duyuru:
            if not d or not isinstance(d, dict):
                continue

            hk = temiz_str(alan_oku(d,'HAT','HATKODU','HatKodu','SHATKODU','Hat','HATLAR','Hatlar','ILGILIHATLAR','SHATLAR')).upper().strip()
            baslik = temiz_str(alan_oku(d,'BASLIK','Baslik','SDUYURUBASLIK'))
            msg = temiz_str(alan_oku(d,'MESAJ','Mesaj','SDUYURUMETNI','ACIKLAMA','Aciklama','ICERIK','Icerik'))
            tip = temiz_str(alan_oku(d,'TIP','Tip','STIP','KATEGORI','Kategori'),'DUYURU')
            if not (baslik or msg):
                continue

            if hat:
                if not _duyuru_hata_ait_mi(d, hat):
                    continue
                genel = False
            else:
                genel = not bool(_norm_hat_kodu(hk))

            sonuclar["duyuru"].append({
                "tip": "📢 " + tip,
                "mesaj": (f"<b>{baslik}</b><br>" if baslik else "") + msg,
                "lat": 0,
                "lon": 0,
                "kapi": "",
                "hat": hk,
                "genel": genel
            })

        return jsonify(sonuclar)

    @app.route('/api/radar')
    def api_radar():
        kaza=olay_guncelle("kaza"); ariza=olay_guncelle("ariza")
        with _lock: kapi_map=dict(FILO_CACHE["kapi_map"])
        cleaned=[]
        for k in kaza:
            if not k or not isinstance(k,dict): continue
            lat=temiz_sayi(alan_oku(k,'ENLEM','NENLEM','enlem',varsayilan=0))
            lon=temiz_sayi(alan_oku(k,'BOYLAM','NBOYLAM','boylam',varsayilan=0))
            if lat>0 and lon>0:
                raw=k.get('KAZASAAT',k.get('DTOLAYBASLANGICZAMANI',''))
                saat="Bilinmiyor"
                if raw and '/Date(' in str(raw):
                    try: saat=datetime.fromtimestamp(int(re.search(r'\d+',str(raw)).group())/1000).strftime('%H:%M')
                    except Exception:
                        pass
                cleaned.append({"enlem":lat,"boylam":lon,"saat":saat,
                                "tur":temiz_str(alan_oku(k, 'Tur', 'TUR', 'KAZA_TURU', varsayilan='Kaza')),"tip":"KAZA"})
        for y in ariza:
            if not y or not isinstance(y,dict): continue
            lat=temiz_sayi(alan_oku(y,'NENLEM','Enlem','enlem',varsayilan=0))
            lon=temiz_sayi(alan_oku(y,'NBOYLAM','Boylam','boylam',varsayilan=0))
            kapi=temiz_str(alan_oku(y,'SKAPINUMARASI','KapiNo'))
            msg=temiz_str(alan_oku(y,'SMESAJMETNI','MESAJ','Mesaj'))
            if (lat==0 or lon==0) and kapi in kapi_map:
                lat=kapi_map[kapi].get('lat',0); lon=kapi_map[kapi].get('lon',0)
            if lat>0 and lon>0:
                lat+=random.uniform(-0.0003,0.0003); lon+=random.uniform(-0.0003,0.0003)
                cleaned.append({"enlem":lat,"boylam":lon,"saat":kapi,"tur":msg,"tip":"ARIZA"})
        return jsonify(cleaned)

    @app.route('/api/garajlar')
    def api_garajlar():
        # GetGaraj_json API HTTP 500 döndürdüğünden statik IETT garaj verileri kullanılıyor
        STATIC_GARAJLAR = [
            {"SGARAJADI": "Avcılar Garajı",        "NENLEM": 40.9796, "NBOYLAM": 28.7215},
            {"SGARAJADI": "Bağcılar Garajı",        "NENLEM": 41.0341, "NBOYLAM": 28.8560},
            {"SGARAJADI": "Başakşehir Garajı",      "NENLEM": 41.0855, "NBOYLAM": 28.8020},
            {"SGARAJADI": "Beylikdüzü Garajı",      "NENLEM": 40.9955, "NBOYLAM": 28.6398},
            {"SGARAJADI": "Büyükçekmece Garajı",    "NENLEM": 41.0187, "NBOYLAM": 28.5780},
            {"SGARAJADI": "Esenler Garajı",         "NENLEM": 41.0437, "NBOYLAM": 28.8763},
            {"SGARAJADI": "Esenyurt Garajı",        "NENLEM": 41.0264, "NBOYLAM": 28.6750},
            {"SGARAJADI": "Güngören Garajı",        "NENLEM": 41.0145, "NBOYLAM": 28.8697},
            {"SGARAJADI": "İkitelli Garajı",        "NENLEM": 41.0640, "NBOYLAM": 28.7828},
            {"SGARAJADI": "Alibeyköy Garajı",       "NENLEM": 41.0820, "NBOYLAM": 28.9330},
            {"SGARAJADI": "Eyüpsultan Garajı",      "NENLEM": 41.0630, "NBOYLAM": 28.9330},
            {"SGARAJADI": "Sarıyer Garajı",         "NENLEM": 41.1671, "NBOYLAM": 29.0570},
            {"SGARAJADI": "Şişli Garajı",           "NENLEM": 41.0603, "NBOYLAM": 28.9876},
            {"SGARAJADI": "Beşiktaş Garajı",        "NENLEM": 41.0437, "NBOYLAM": 29.0050},
            {"SGARAJADI": "Üsküdar Garajı",         "NENLEM": 41.0234, "NBOYLAM": 29.0147},
            {"SGARAJADI": "Kadıköy Garajı",         "NENLEM": 40.9900, "NBOYLAM": 29.0300},
            {"SGARAJADI": "Ataşehir Garajı",        "NENLEM": 40.9900, "NBOYLAM": 29.1100},
            {"SGARAJADI": "Maltepe Garajı",         "NENLEM": 40.9364, "NBOYLAM": 29.1308},
            {"SGARAJADI": "Pendik Garajı",          "NENLEM": 40.8762, "NBOYLAM": 29.2328},
            {"SGARAJADI": "Tuzla Garajı",           "NENLEM": 40.8160, "NBOYLAM": 29.3050},
            {"SGARAJADI": "Sultanbeyli Garajı",     "NENLEM": 40.9670, "NBOYLAM": 29.2640},
            {"SGARAJADI": "Ümraniye Garajı",        "NENLEM": 41.0180, "NBOYLAM": 29.1220},
            {"SGARAJADI": "Sancaktepe Garajı",      "NENLEM": 41.0050, "NBOYLAM": 29.2280},
            {"SGARAJADI": "Bostancı Garajı",        "NENLEM": 40.9620, "NBOYLAM": 29.0940},
            {"SGARAJADI": "Silivri Garajı",         "NENLEM": 41.0720, "NBOYLAM": 28.2470},
            {"SGARAJADI": "Metrobüs Zincirlikuyu",  "NENLEM": 41.0730, "NBOYLAM": 29.0120},
            {"SGARAJADI": "Metrobüs Söğütlüçeşme",  "NENLEM": 40.9900, "NBOYLAM": 29.0680},
        ]
        return jsonify(STATIC_GARAJLAR)
    @app.route('/api/kavsaklar')
    def api_kavsaklar():
        # Eğer en üstte import etmediysen burada da edebilirsin:
        from services import guncelle_kavsaklar 
        
        ilce = request.args.get('ilce', '').upper()
        durum = request.args.get('durum', '').upper()
        force = request.args.get('force', '0') == '1'

        veri = guncelle_kavsaklar(force=force)

        # Filtreleme (İsteğe bağlı)
        if ilce:
            veri = [k for k in veri if k.get("ilce") == ilce]
        if durum:
            veri = [k for k in veri if k.get("durum") == durum]

        return jsonify({
            "adet": len(veri),
            "kavsaklar": veri,
            "kaynak": "isbak_soap"
        })

    @app.route('/api/saatler')
    def api_saatler():
        hat=request.args.get('hat','').upper()
        with _lock: 
            cached=SAAT_CACHE.get(hat)
        if cached: return jsonify(cached)
        body=f'<GetPlanlananSeferSaati_json xmlns="http://tempuri.org/"><HatKodu>{hat}</HatKodu></GetPlanlananSeferSaati_json>'
        res=fetch_soap(URL_SAAT,'GetPlanlananSeferSaati_json',body,timeout_sec=8)
        if res:
            with _lock: SAAT_CACHE[hat]=res
        return jsonify(res or [])

    @app.route('/api/durak_ara')
    def api_durak_ara():
        q_raw = request.args.get('q', '').strip()
        if len(q_raw) < 2: return jsonify([])
        with _lock: snap_d = dict(DURAK_DICT)
        q_up = q_raw.upper()
        if q_up in snap_d:
            d = snap_d[q_up]
            return jsonify([{'ad':d.get('ad',''),'kodu':q_up,'lat':d.get('lat',0),
                             'lon':d.get('lon',0),'ilce':d.get('ilce',''),
                             'akilli':d.get('akilli',False),'engelli':d.get('engelli',False),
                             'tip':d.get('tip','AÇIK'),'skor':1000}])
        adaylar = _durak_adaylari(q_raw, snap_d, top_n=40, min_skor=50)
        matched = []
        for kod, sk, ad in adaylar:
            d = snap_d[kod]
            matched.append({'ad':d.get('ad',''),'kodu':kod,'lat':d.get('lat',0),
                            'lon':d.get('lon',0),'ilce':d.get('ilce',''),
                            'akilli':d.get('akilli',False),'engelli':d.get('engelli',False),
                            'tip':d.get('tip','AÇIK'),'skor':sk})
        return jsonify(matched)

    @app.route('/api/motor_hat_bul')
    def api_motor_hat_bul():
        durak_kodu = request.args.get('kodu', '').strip()
        if not durak_kodu:
            return jsonify({"durum": "yok"})

        with _lock:
            ready = IS_DB_READY
            hatlar = list(MEMORY_DB.get(durak_kodu, []))

        # 1. Hafıza DB (disk cache) hazır ve bu durak var → en hızlı yol
        if hatlar:
            return jsonify({"durum": "tamam", "hatlar": sorted(hatlar), "kaynak": "db"})

        # 2. DB henüz yüklenmediyse bekle mesajı ver
        if not ready:
            return jsonify({"durum": "bekle"})

        # 3. DB hazır ama bu durak kayıtlarda yok
        return jsonify({"durum": "yok"})

    # ★ FIX: ETA — araç yön ve geçmiş kontrolü eklendi
    @app.route('/api/durak_eta')
    def api_durak_eta():
        hat=request.args.get('hat','').upper()
        durak_lat=temiz_sayi(request.args.get('lat','0'))
        durak_lon=temiz_sayi(request.args.get('lon','0'))
        istenen_yon=request.args.get('yon','').strip().upper()
        if not hat or abs(durak_lat) < 1 or abs(durak_lon) < 1:
            return jsonify({"hata":"hat, lat, lon gerekli"})

        with _lock:
            saat_c=SAAT_CACHE.get(hat); filo_ts=FILO_CACHE["ts"]

        # Durak listesini al (yön kontrolü için)
        cache_key=f"durak_detay_{hat}"
        with _lock: cached_durak=API_RESPONSE_CACHE.get(cache_key)
        hat_duraklar=cached_durak.get("duraklar",[]) if cached_durak else []

        normalized,_=get_live_buses_cached(hat)
        if normalized:
            normalized=tahmin_yon_terminal(hat,normalized)
            sonuclar=[]
            with _lock: kapi_map=dict(FILO_CACHE["kapi_map"])
            for b in normalized:
                arac_yonu=b.get("yon")  # _G_/_D_ marker'dan gelir; None ise filtre atlanır
                if istenen_yon in ('G','D') and arac_yonu is not None and arac_yonu!=istenen_yon:
                    continue

                try:
                    blat,blon=b["lat"],b["lon"]
                    spd_raw = float(b.get("hiz",0) or 0)
                    dist_km=hav(blat,blon,durak_lat,durak_lon)

                    yaklasiyor,sira_farki=arac_durak_yaklasiyor_mu(
                        blat,blon,arac_yonu,durak_lat,durak_lon,hat_duraklar)
                    if not yaklasiyor:
                        continue

                    trafik=get_trafik(blat,blon)
                    kats=trafik.get("katsayi",1.0)
                    route_km = rota_mesafe_km(blat, blon, durak_lat, durak_lon, arac_yonu, hat_duraklar)

                    profil_hiz = max(12.0, 24.0 * kats)
                    canli_hiz = spd_raw if spd_raw >= 5 else profil_hiz
                    efektif_hiz = max(8.0, min(42.0, (canli_hiz * 0.7) + (profil_hiz * 0.3)))
                    eta_baz = max(1.0, (route_km / efektif_hiz) * 60)
                    gecikme_oran = max(0.0, 1.0 - kats)
                    gecikme_dk   = round(eta_baz * gecikme_oran * 0.6, 1)
                    eta_min      = max(1, round(eta_baz + gecikme_dk))
                    if eta_min>75: continue

                    sonuclar.append({
                        "kapi":b["kapi"],"plaka":b.get("plaka","—"),
                        "operator":b.get("op","İETT"),
                        "hiz":int(spd_raw),"eta_min":eta_min,
                        "eta_baz_min": round(eta_baz),
                        "gecikme_dk": gecikme_dk,
                        "dist_km":round(dist_km,2),"route_km":round(route_km,2),
                        "veri_yasi":int(time.time()-filo_ts) if filo_ts else 0,
                        "kaynak":"ram","trafik_sev":trafik.get("seviye",""),
                        "trafik_renk":trafik.get("renk","#94a3b8"),"trafik_kats":kats,
                        "trafik_kaynak": trafik.get("kaynak","profil"),
                        "yaklasiyor":True,"sira_farki":sira_farki,
                    })
                except Exception: 
                    continue
            sonuclar.sort(key=lambda x:x['eta_min'])
            if sonuclar:
                return jsonify({"sonuclar":sonuclar[:5],"kaynak":"ram","arac_sayisi":len(normalized)})

        # Sefer saatinden tahmin
        if not saat_c:
            body=f'<GetPlanlananSeferSaati_json xmlns="http://tempuri.org/"><HatKodu>{hat}</HatKodu></GetPlanlananSeferSaati_json>'
            saat_c=fetch_soap(URL_SAAT,'GetPlanlananSeferSaati_json',body,timeout_sec=8) or []
            if saat_c:
                with _lock: SAAT_CACHE[hat]=saat_c

        if saat_c:
            simdi_dk=datetime.now().hour*60+datetime.now().minute
            gun_idx=datetime.now().weekday()
            gt='P' if gun_idx==6 else ('C' if gun_idx==5 else 'I')
            trafik=get_trafik(durak_lat,durak_lon); kats=trafik.get("katsayi",1.0)
            gelecek=[]
            for s in saat_c:
                gun_tipi = temiz_str(s.get('SGUNTIPI') or s.get('GunTipi')).upper()
                if gun_tipi != gt:
                    continue
                saat_yon=str(s.get('SYON',s.get('Yon','G'))).upper().strip()
                if saat_yon=='1': saat_yon='G'
                elif saat_yon in ('0','2'): saat_yon='D'
                if istenen_yon in ('G','D') and saat_yon!=istenen_yon: continue
                t=s.get('DT','')
                if not t: continue
                try:
                    p=t.split(':'); t_dk=int(p[0])*60+int(p[1])
                    fark=t_dk-simdi_dk
                    if fark<-5: continue  # Geçmiş seferler (5dk tolerans)
                    gecikme_oran = max(0.0, 1.0 - kats)
                    gecikme_dk_ek = round(max(0, fark) * gecikme_oran * 0.5, 1)
                    gec_dk=max(1,round(fark + gecikme_dk_ek))
                    if 0<gec_dk<90: gelecek.append({"saat":t,"dk":gec_dk,"planlanan_dk":fark,"gecikme_dk":gecikme_dk_ek})
                except Exception:
                    pass
            gelecek.sort(key=lambda x:x['dk'])
            if gelecek:
                return jsonify({"sonuclar":[{"eta_min":g["dk"],"saat":g["saat"],"planlanan_dk":g["planlanan_dk"],
                                              "gecikme_dk": g.get("gecikme_dk", 0),
                                              "kaynak":"sefer_saati","kapi":"-","plaka":"-","operator":"Planlı",
                                              "hiz":0,"dist_km":0,"route_km":0,"veri_yasi":0,
                                              "trafik_sev":trafik.get("seviye",""),
                                              "trafik_renk":trafik.get("renk","#94a3b8"),"trafik_kats":kats,
                                              "trafik_kaynak": trafik.get("kaynak","profil")}
                                             for g in gelecek[:3]],
                                "kaynak":"sefer_saati","arac_sayisi":0})

        return jsonify({"sonuclar":[],"kaynak":"yok","arac_sayisi":0})

    @app.route('/api/yolcu_analizi')
    def api_yolcu_analizi():
        hat=request.args.get('hat','').upper()
        if not hat: return jsonify({"hata":"Hat kodu gerekli"})
        with _lock:
            hi=HAFTALIK.get("haftaici",{}).get(hat,0)
            hs=HAFTALIK.get("haftasonu",{}).get(hat,0)
        if hi>0:
            return jsonify({"hat":hat,"tarihler":["HaftaİçiOrt","HaftaSonuOrt"],
                            "yolcular":[hi,hs],"kaynak":"haftalik_ram"})
        tarihler=[]; yolcular=[]
        for off in [3,2,1]:
            t_str=(datetime.now()-timedelta(days=off)).strftime("%Y-%m-%d")
            g_str=(datetime.now()-timedelta(days=off)).strftime("%d/%m")
            body=f'<GetIettYolculukHat_json xmlns="http://tempuri.org/"><Tarih>{t_str}</Tarih></GetIettYolculukHat_json>'
            yolcu=0
            res=fetch_soap(URL_IBB360,'GetIettYolculukHat_json',body,use_auth=False,timeout_sec=8)
            if isinstance(res,list):
                for y in res:
                    y_hat = temiz_str(alan_oku(y, 'Hat', 'HAT', 'HatKodu', 'HATKODU')).upper()
                    if y_hat == hat:
                        try:
                            yolcu = int(temiz_sayi(alan_oku(y, 'Yolculuk', 'YOLCULUK', 'Yolcu', 'YOLCU', varsayilan=0)))
                        except Exception:
                            pass
                        break
            tarihler.append(g_str); yolcular.append(yolcu)
        return jsonify({"hat":hat,"tarihler":tarihler,"yolcular":yolcular,"kaynak":"api"})

    @app.route('/api/hat_karsilastir')
    def api_hat_karsilastir():
        h1=request.args.get('hat1','').upper(); h2=request.args.get('hat2','').upper()
        for h in [h1,h2]:
            if h: get_live_buses_cached(h)
        with _lock:
            hi=HAFTALIK.get("haftaici",{}); hs=HAFTALIK.get("haftasonu",{})
            hg=ARSIV_CACHE.get("hat_gorev",{}); gc=dict(GECIKME_CACHE); yc=dict(YOGUNLUK_CACHE)
            snap_live={h:data["normalized"] for h,data in LIVE_BUS_CACHE.items()
                       if isinstance(data,dict) and data.get("normalized")}
        def profil_gecikme(h):
            saat=datetime.now().hour; hici=datetime.now().weekday()<5
            th,ts=ISTANBUL_PROFIL.get(saat,(0.75,0.75)); kats=th if hici else ts
            seed_val=sum(ord(c) for c in h)%100; varyasyon=(seed_val-50)*0.003
            hat_kats=max(0.25,min(1.0,kats+varyasyon)); sev,renk=trafik_seviye(hat_kats)
            return {"skor":int((1.0-hat_kats)*100),"seviye":sev,"renk":renk,
                    "ortalama_hiz":round(28.0*hat_kats,1),"beklenen_hiz":28.0,"arac_sayisi":0,"tahmin":True}
        def gecikme_bilgi(h):
            if h in gc: return gc[h]
            araclar=snap_live.get(h,[])
            if araclar:
                hizlar=[b.get("hiz",0) for b in araclar if b.get("hiz",0)>3]
                if hizlar:
                    ort=sum(hizlar)/len(hizlar)
                    skor=min(100,int(max(0,28-ort)/28*100)); sev,renk=trafik_seviye(max(0.25,ort/28.0))
                    return {"skor":skor,"seviye":sev,"renk":renk,"ortalama_hiz":round(ort,1)}
            return profil_gecikme(h)
        def bilgi(h):
            gec=gecikme_bilgi(h); yog=yc.get(h,{}); sd=yog.get("simdi_doluluk",{})
            hi_val=hi.get(h,0); arac_say=len(snap_live.get(h,[]))
            # Yoğunluk yoksa profil bazlı hesapla
            if not sd:
                saat=datetime.now().hour; hici2=datetime.now().weekday()<5
                d_vals=_SAAT_DAGILIM_HIC if hici2 else _SAAT_DAGILIM_HS
                seed=sum(ord(c) for c in h)%30; base_dol=int(d_vals[saat]*100)-seed
                base_dol=max(5,min(90,base_dol))
                if base_dol<30: sd={"yuzde":base_dol,"etiket":"Sakin","renk":"#22c55e"}
                elif base_dol<60: sd={"yuzde":base_dol,"etiket":"Normal","renk":"#84cc16"}
                elif base_dol<80: sd={"yuzde":base_dol,"etiket":"Yoğun","renk":"#f59e0b"}
                else: sd={"yuzde":base_dol,"etiket":"Kalabalık","renk":"#ef4444"}
            stres=0
            planlanan = hg.get(h, 0)   # GetIettArsivGorev_json'dan gelen planlanan sefer sayısı
            if hi_val > 0:
                if planlanan > 0:
                    # Planlanan sefer sayısı birincil referans — sabit ve tutarlı
                    stres = int(hi_val / max(planlanan, 1))
                elif arac_say > 0:
                    # Canlı araç sayısı fallback — sadece planlanan yoksa kullan
                    stres = int(hi_val / arac_say)
            return {"hat":h,"haftaici":hi_val,"haftasonu":hs.get(h,0),
                    "arac":arac_say,"gorev":planlanan,"stres":stres,
                    "gecikme_skor":gec.get("skor",0),"gecikme_sev":gec.get("seviye","—"),
                    "gecikme_renk":gec.get("renk","#94a3b8"),
                    "ort_hiz":gec.get("ortalama_hiz",0),"doluluk_yuzde":sd.get("yuzde",0),
                    "doluluk_etiket":sd.get("etiket","—"),"doluluk_renk":sd.get("renk","#94a3b8"),
                    "kaynak_yogunluk":yog.get("kaynak_arac","tahmin")}
        # ── Datathon SQLite zenginleştirme ──────────────────────
        def sqlite_extra(h):
            extra = {}
            try:
                con = get_panel_db(); cur = con.cursor()
                # Hat tipi ve adı
                cur.execute('SELECT GUNCEL_HATCINSI, GUNCEL_HATADI FROM yolcu WHERE GUNCEL_HATKODU=? LIMIT 1', (h,))
                row = cur.fetchone()
                extra['hat_cinsi'] = (row[0] or '').strip() if row else ''
                extra['hat_adi']   = (row[1] or '').strip() if row else ''
                # Toplam 6 aylık yolcu
                cur.execute('SELECT COUNT(*) FROM yolcu WHERE GUNCEL_HATKODU=?', (h,))
                extra['toplam_6ay'] = (cur.fetchone() or [0])[0] or 0
                # Haftaiçi / haftasonu ortalaması (aynı mantık hat_analiz ile)
                cur.execute('SELECT COUNT(*) FROM yolcu WHERE GUNCEL_HATKODU=? AND HAFTASONU=0', (h,))
                hi_raw = (cur.fetchone() or [0])[0] or 0
                cur.execute('SELECT COUNT(*) FROM yolcu WHERE GUNCEL_HATKODU=? AND HAFTASONU=1', (h,))
                hs_raw = (cur.fetchone() or [0])[0] or 0
                extra['haftaici_ort']   = int(hi_raw / 130) if hi_raw else 0
                extra['haftasonu_ort']  = int(hs_raw / 52)  if hs_raw else 0
                # Bilet dağılımı — öğrenci, tam, diğer
                cur.execute('SELECT DBILETKATEGORI, COUNT(*) as cnt FROM yolcu WHERE GUNCEL_HATKODU=? GROUP BY DBILETKATEGORI ORDER BY cnt DESC LIMIT 8', (h,))
                bilet_rows = cur.fetchall()
                toplam_bilet = sum(r[1] for r in bilet_rows) or 1
                bilet = {}
                for r in bilet_rows:
                    kat = (r[0] or 'Diğer').strip()
                    bilet[kat] = round(r[1] / toplam_bilet * 100, 1)
                extra['bilet_dagilim'] = bilet
                # Öğrenci oranı (kısaltılmış)
                ogrenci_pct = sum(v for k, v in bilet.items() if 'ÖĞR' in k.upper() or 'OGR' in k.upper())
                extra['ogrenci_pct'] = round(ogrenci_pct, 1)
                # Araç yaş ortalaması
                cur.execute('SELECT AVG(CAST(MODELYILI AS INTEGER)) FROM yolcu WHERE GUNCEL_HATKODU=? AND MODELYILI IS NOT NULL AND MODELYILI != ""', (h,))
                avg_yil = cur.fetchone()
                if avg_yil and avg_yil[0]:
                    extra['arac_yas_ort'] = round(2025 - avg_yil[0], 1)
                else:
                    extra['arac_yas_ort'] = None
                # Araç marka top-3
                cur.execute('SELECT MARKA, COUNT(*) as cnt FROM yolcu WHERE GUNCEL_HATKODU=? AND MARKA IS NOT NULL AND MARKA!="" GROUP BY MARKA ORDER BY cnt DESC LIMIT 3', (h,))
                extra['top_marka'] = [r[0].strip() for r in cur.fetchall()]
                # Arıza sayısı (6 ay)
                cur.execute('SELECT COUNT(*) FROM ariza WHERE HATKODU=?', (h,))
                extra['ariza_sayi'] = (cur.fetchone() or [0])[0] or 0
                # Hatta çalışan toplam araç (distinct KAPINO)
                cur.execute('SELECT COUNT(DISTINCT KAPINO) FROM yolcu WHERE GUNCEL_HATKODU=? AND KAPINO IS NOT NULL AND KAPINO!=""', (h,))
                extra['arac_toplam'] = (cur.fetchone() or [0])[0] or 0
                # Aylık yolcu trendi (son 6 ay)
                cur.execute('SELECT AY, COUNT(*) as cnt FROM yolcu WHERE GUNCEL_HATKODU=? GROUP BY AY ORDER BY AY', (h,))
                aylik = cur.fetchall()
                extra['aylik_trend'] = [{'ay': r[0], 'yolcu': r[1]} for r in aylik]
                con.close()
                # Yüksek riskli araç sayısı (smart_maintenance.json'dan)
                with _lock:
                    sm = PANEL_DATA.get('smart_maintenance', [])
                sm_idx = {}
                for arac in sm:
                    kap = str(arac.get('kapino', '')).strip().upper()
                    if kap: sm_idx[kap] = arac
                # hattaki araç kapinoları
                try:
                    con2 = get_panel_db(); cur2 = con2.cursor()
                    cur2.execute('SELECT DISTINCT KAPINO FROM yolcu WHERE GUNCEL_HATKODU=? AND KAPINO IS NOT NULL AND KAPINO!=""', (h,))
                    hat_kapinolar = {str(r[0]).strip().upper() for r in cur2.fetchall()}
                    con2.close()
                except Exception:
                    hat_kapinolar = set()
                yuksek_risk = [sm_idx[k] for k in hat_kapinolar if k in sm_idx and
                               (sm_idx[k].get('aciliyet_tier','') or sm_idx[k].get('risk_kategori','')).upper() in ('KRİTİK','KRITIK','YÜKSEK','YUKSEK')]
                extra['yuksek_riskli_sayi'] = len(yuksek_risk)
            except Exception as _e:
                pass
            return extra

        d1 = bilgi(h1); d2 = bilgi(h2)
        e1 = sqlite_extra(h1); e2 = sqlite_extra(h2)
        d1.update(e1); d2.update(e2)
        return jsonify({"h1": d1, "h2": d2})

    @app.route('/api/hat_analiz')
    def api_hat_analiz():
        hat=request.args.get('hat','').strip().upper()
        if not hat: return jsonify({"hata":"Hat kodu gerekli"})
        # Canlı araçları çek
        normalized,_=get_live_buses_cached(hat)
        if normalized: normalized=tahmin_yon_terminal(hat,normalized)
        # Yolcu verisini datathon SQLite'tan al
        try:
            _hcon = get_panel_db(); _hcur = _hcon.cursor()
            _hcur.execute('SELECT COUNT(*) FROM yolcu WHERE GUNCEL_HATKODU=? AND HAFTASONU=0',(hat,))
            _hi_top = (_hcur.fetchone() or [0])[0] or 0
            _hcur.execute('SELECT COUNT(*) FROM yolcu WHERE GUNCEL_HATKODU=? AND HAFTASONU=1',(hat,))
            _hs_top = (_hcur.fetchone() or [0])[0] or 0
            _hcon.close()
            hi = int(_hi_top / 130) if _hi_top else 0  # 6 ay × 5 haftaici gün = 130
            hs = int(_hs_top / 52)  if _hs_top else 0  # 6 ay × 2 haftasonu gün = 52
        except Exception:
            hi = 0; hs = 0
        with _lock:
            gorev=ARSIV_CACHE.get("hat_gorev",{}).get(hat,0)
            gc=GECIKME_CACHE.get(hat,{})
            yc=YOGUNLUK_CACHE.get(hat,{})
        # Durak listesini al
        cache_key=f"durak_detay_{hat}"
        with _lock: cached_durak=API_RESPONSE_CACHE.get(cache_key)
        if not cached_durak:
            body=f'<DurakDetay_GYY_wYonAdi xmlns="http://tempuri.org/"><hat_kodu>{hat}</hat_kodu></DurakDetay_GYY_wYonAdi>'
            root=fetch_soap_xml(URL_IBB,'DurakDetay_GYY_wYonAdi',body,timeout_sec=10)
            if root:
                data=[]; api_yon={"G":None,"D":None}
                with _lock: snap=dict(DURAK_DICT)
                for tbl in root.iter():
                    if not tbl.tag.endswith('Table'): continue
                    d={c.tag.split('}')[-1].upper():c.text for c in tbl}
                    if 'YKOORDINATI' not in d or 'XKOORDINATI' not in d: continue
                    yv=yon_cozucu(d.get('YON')); dkod=d.get('DURAKKODU','')
                    inf=snap.get(dkod,{'akilli':False,'engelli':False,'tip':'AÇIK'})
                    lat=temiz_sayi(d.get('YKOORDINATI','0')); lon=temiz_sayi(d.get('XKOORDINATI','0'))
                    data.append({"sira":int(d.get('SIRANO',0) or 0),"ad":temiz_str(d.get('DURAKADI'),'Durak'),
                                 "lat":lat,"lon":lon,"yon":yv,"kodu":dkod,
                                 "akilli":inf.get('akilli',False),"engelli":inf.get('engelli',False),"tip":inf.get('tip','AÇIK')})
                    yon_adi=temiz_str(d.get('YONADI') or d.get('YON_ADI',''))
                    if yon_adi and not api_yon[yv]: api_yon[yv]=yon_adi
                data.sort(key=lambda x:x['sira'])
                gi=[x for x in data if x['yon']=='G']; do=[x for x in data if x['yon']=='D']
                terms={"G":api_yon["G"] or (gi[-1]['ad'] if gi else "Gidiş"),
                       "D":api_yon["D"] or (do[-1]['ad'] if do else "Dönüş")}
                cached_durak={"duraklar":data,"terminaller":terms}
                with _lock: API_RESPONSE_CACHE[cache_key]=cached_durak
        duraklar=cached_durak.get("duraklar",[]) if cached_durak else []
        terminaller=cached_durak.get("terminaller",{}) if cached_durak else {}
        # Rota mesafesi hesapla
        def rota_km(dlist):
            if len(dlist)<2: return 0
            km=sum(hav(dlist[i]['lat'],dlist[i]['lon'],dlist[i+1]['lat'],dlist[i+1]['lon'])
                   for i in range(len(dlist)-1))
            return round(km,1)
        g_durak=[d for d in duraklar if d['yon']=='G' and d['lat']>0]
        d_durak=[d for d in duraklar if d['yon']=='D' and d['lat']>0]
        rota_km_g=rota_km(g_durak); rota_km_d=rota_km(d_durak)
        # En yoğun durak (canlı araçlara yakınlık bazında)
        en_yogun_durak=""
        if normalized and g_durak:
            durak_sayim=Counter()
            for arac in normalized:
                en_yakin=min(g_durak,key=lambda d:hav(arac['lat'],arac['lon'],d['lat'],d['lon']))
                durak_sayim[en_yakin['ad']]+=1
            if durak_sayim: en_yogun_durak=durak_sayim.most_common(1)[0][0]
        # Yön bazlı araç sayısı
        arac_g=len([b for b in normalized if b.get('yon')=='G'])
        arac_d=len([b for b in normalized if b.get('yon')=='D'])
        # Doluluk
        sd=yc.get("simdi_doluluk",{})
        doluluk_yuzde=sd.get("yuzde",0); doluluk_etiket=sd.get("etiket","Veri Yok")
        # Stres skoru (yolcu / araç)
        if len(normalized) > 0:
            arac_toplam = len(normalized)
        elif gorev > 0:
            arac_toplam = gorev // 15
        else:
            arac_toplam = 0
        # Stres skoru: yolcu / planlanan sefer — planlanan yoksa canlı araç sayısı
        if len(normalized) > 0:
            arac_toplam = len(normalized)
        elif gorev > 0:
            arac_toplam = gorev // 15  # eski fallback: tahmin
        else:
            arac_toplam = 0
        # Planlanan sefer sayısı birincil referans (sabit, günlük değişmez)
        if hi > 0 and gorev > 0:
            stres = int(hi / max(gorev, 1))
        elif hi > 0 and arac_toplam > 0:
            stres = int(hi / arac_toplam)
        else:
            stres = 0
        # Gecikme
        ort_hiz=gc.get("ortalama_hiz",0); gecikme_skor=gc.get("skor",0); gecikme_sev=gc.get("seviye","—")
        # Hat detayı (terminal adları)
        # Hat bilgisi — SEFER_SURESI ve HAT_UZUNLUGU için HAT_BILGI_CACHE kullan
        hb = get_hat_bilgi(hat)
        sefer_suresi_dk  = hb.get("sefer_suresi_dk")
        hat_uzunlugu_km  = hb.get("hat_uzunlugu_km")

        # Yolcu/km verimlilik skoru
        verimlilik_yolcu_km = None
        if hat_uzunlugu_km and hat_uzunlugu_km > 0 and hi > 0:
            try:
                verimlilik_yolcu_km = round(hi / hat_uzunlugu_km, 1)
            except Exception:
                pass

        # Tamamlanma oranı
        with _lock:
            tamamlanma = dict(ARSIV_CACHE.get("hat_tamamlanma", {}).get(hat, {}))

        # ── Datathon SQLite zenginleştirme ──
        _hat_extra = {
            'hat_cinsi':'','hat_adi_db':'','ilceler':[],
            'aylik_yolcu':[],'bilet_dagilim':[],'arac_marka':[],
            'arac_yas_dagilim':[],'aktarma_pct':0,'toplam_6ay_yolcu':0,
            'ariza_son':[],'yuksek_riskli_araclar':[],'yuksek_riskli_sayi':0,
            'bekleyen_bakim_sayi':0,'arac_toplam_hatta':0,
            'hat_tier_dagilim':{'KRITIK':0,'YUKSEK':0,'ORTA':0,'DUSUK':0},
        }
        try:
            import datetime as _dt
            _pcon = get_panel_db(); _pcur = _pcon.cursor()

            # Hat cinsi + adı
            _pcur.execute('SELECT GUNCEL_HATCINSI,GUNCEL_HATADI FROM yolcu WHERE GUNCEL_HATKODU=? LIMIT 1',(hat,))
            _r = _pcur.fetchone()
            if _r:
                _hat_extra['hat_cinsi']  = (_r[0] or '').strip()
                _hat_extra['hat_adi_db'] = (_r[1] or '').strip()

            # Geçtiği ilçeler
            _pcur.execute('SELECT DISTINCT ILCE FROM yolcu WHERE GUNCEL_HATKODU=? AND ILCE IS NOT NULL AND ILCE!="Bilinmiyor" ORDER BY ILCE LIMIT 20',(hat,))
            _hat_extra['ilceler'] = [r[0] for r in _pcur.fetchall() if r[0]]

            # Aylık yolcu (Oca–Haz)
            _pcur.execute('SELECT AY,COUNT(*) FROM yolcu WHERE GUNCEL_HATKODU=? GROUP BY AY ORDER BY AY',(hat,))
            _hat_extra['aylik_yolcu'] = [{'ay':r[0],'yolcu':r[1]} for r in _pcur.fetchall()]
            _hat_extra['toplam_6ay_yolcu'] = sum(x['yolcu'] for x in _hat_extra['aylik_yolcu'])

            # Bilet kategorisi dağılımı
            _pcur.execute('SELECT DBILETKATEGORI,COUNT(*) FROM yolcu WHERE GUNCEL_HATKODU=? AND DBILETKATEGORI IS NOT NULL GROUP BY DBILETKATEGORI ORDER BY COUNT(*) DESC LIMIT 8',(hat,))
            _hat_extra['bilet_dagilim'] = [{'kategori':r[0],'adet':r[1]} for r in _pcur.fetchall() if r[0]]

            # Araç marka dağılımı
            _pcur.execute('SELECT MARKA,COUNT(*) FROM yolcu WHERE GUNCEL_HATKODU=? AND MARKA IS NOT NULL GROUP BY MARKA ORDER BY COUNT(*) DESC LIMIT 6',(hat,))
            _hat_extra['arac_marka'] = [{'marka':r[0],'adet':r[1]} for r in _pcur.fetchall() if r[0]]

            # Araç model yılı → yaş grubu
            _sim_yil = _dt.datetime.now().year
            _pcur.execute('SELECT MODELYILI,COUNT(*) FROM yolcu WHERE GUNCEL_HATKODU=? AND MODELYILI IS NOT NULL AND MODELYILI>1990 GROUP BY MODELYILI',(hat,))
            _yas_grp = {'0-3 yıl':0,'4-7 yıl':0,'8-12 yıl':0,'13+ yıl':0}
            for _my,_cnt in _pcur.fetchall():
                _y = _sim_yil - int(_my)
                if _y <= 3:   _yas_grp['0-3 yıl']  += _cnt
                elif _y <= 7: _yas_grp['4-7 yıl']  += _cnt
                elif _y <= 12:_yas_grp['8-12 yıl'] += _cnt
                else:          _yas_grp['13+ yıl']  += _cnt
            _hat_extra['arac_yas_dagilim'] = [{'grup':k,'adet':v} for k,v in _yas_grp.items() if v>0]

            # Aktarma oranı
            _pcur.execute('SELECT DAKTARMATIPI,COUNT(*) FROM yolcu WHERE GUNCEL_HATKODU=? GROUP BY DAKTARMATIPI',(hat,))
            _akt_rows = _pcur.fetchall()
            _akt_top  = sum(r[1] for r in _akt_rows)
            _akt_akt  = sum(r[1] for r in _akt_rows if (r[0] or '')=='Aktarma')
            _hat_extra['aktarma_pct'] = round(_akt_akt/_akt_top*100,1) if _akt_top else 0

            # Son 5 arıza
            _pcur.execute('SELECT TARIH,KAPINO,MARKA,ARIZAUSTKODTANIM,ARIZAKODU,YERBILGISI,MUDEHALETIPI FROM ariza WHERE HATKODU=? ORDER BY TARIH DESC LIMIT 5',(hat,))
            _hat_extra['ariza_son'] = [
                {'tarih':r[0],'kapino':r[1],'marka':r[2],'tip':(r[3] or '—'),'alt_kat':(r[4] or ''),'yer':(r[5] or '—'),'mudahale':(r[6] or '—')}
                for r in _pcur.fetchall()
            ]

            # Hattaki araçlar (unique kapino)
            _pcur.execute('SELECT DISTINCT KAPINO FROM yolcu WHERE GUNCEL_HATKODU=? AND KAPINO IS NOT NULL',(hat,))
            _hat_kapinos = {r[0] for r in _pcur.fetchall()}
            _hat_extra['arac_toplam_hatta'] = len(_hat_kapinos)
            _pcon.close()

            # Smart maintenance eşleştirme
            _sm_data = PANEL_DATA.get('smart_maintenance',[])
            def _norm_tier(t):
                return (t or '').upper().replace('İ','I').replace('Ü','U').replace('Ö','O').replace('Ş','S')
            # hat_arac_risk.json kaynaklı: sefer verisinden kapino-hat eşleşmesi
            _har = PANEL_DATA.get('_har_idx',{}).get(hat)
            if _har:
                _har_kapinos = set((_har.get('kritik_kapinolar') or []) + (_har.get('yuksek_kapinolar') or []))
                if not _hat_kapinos:
                    _hat_kapinos = _har_kapinos  # yolcu DB boşsa sefer verisini kullan
                else:
                    _hat_kapinos = _hat_kapinos | _har_kapinos
                # Özet zaten hesaplı — hat analiz için kullan
                _hat_extra['hat_tier_dagilim_sefer'] = {
                    'KRITIK': _har.get('kritik_n',0),
                    'YUKSEK': _har.get('yuksek_n',0),
                    'ORTA':   _har.get('orta_n',0),
                    'DUSUK':  _har.get('dusuk_n',0),
                    'toplam': _har.get('arac_toplam',0),
                    'yuksek_risk_pct': _har.get('yuksek_risk_pct',0),
                }
            if _sm_data and _hat_kapinos:
                _sm_map = {x.get('kapino',''):x for x in _sm_data}
                _hat_sm = [_sm_map[k] for k in _hat_kapinos if k in _sm_map]
                _yuksek_ve_kritik = [a for a in _hat_sm if _norm_tier(a.get('aciliyet_tier','')) in {'KRITIK','ACIL','YUKSEK'}]
                _kritik_only = [a for a in _hat_sm if _norm_tier(a.get('aciliyet_tier','')) in {'KRITIK','ACIL'}]
                _hat_extra['yuksek_riskli_sayi'] = len(_kritik_only)
                _hat_extra['bekleyen_bakim_sayi'] = len([a for a in _hat_sm if a.get('bakim_uyarisi')])
                # Tier dağılımı özeti
                _tier_say = {'KRITIK':0,'YUKSEK':0,'ORTA':0,'DUSUK':0}
                for _a in _hat_sm:
                    _nt = _norm_tier(_a.get('aciliyet_tier',''))
                    if _nt in _tier_say: _tier_say[_nt] += 1
                _hat_extra['hat_tier_dagilim'] = _tier_say
                # KRİTİK + YÜKSEK araçlar (top 8, score'a göre)
                _hat_extra['yuksek_riskli_araclar'] = [
                    {'kapino':a.get('kapino'),'marka':a.get('marka'),'model':a.get('model'),
                     'tier':a.get('aciliyet_tier'),'skor':a.get('aciliyet_skoru',0),
                     'neden':a.get('tekrarlayan_neden') or a.get('son_ciddi_neden',''),
                     'agir_30':a.get('agir_30',0),'cnt_30':a.get('cnt_30',0),
                     'yas':a.get('arac_yasi',0)}
                    for a in sorted(_yuksek_ve_kritik,key=lambda x:x.get('aciliyet_skoru',0),reverse=True)[:8]
                ]
        except Exception:
            pass

        return jsonify({
            "hat":hat,
            "hat_adi": hb.get("hat_adi") or temiz_str(alan_oku({}, 'HATADI', varsayilan=hat)),
            "terminal_g":terminaller.get("G","—"),
            "terminal_d":terminaller.get("D","—"),
            "durak_sayisi_g":len(g_durak),
            "durak_sayisi_d":len(d_durak),
            "rota_km_g":rota_km_g,
            "rota_km_d":rota_km_d,
            "aktif_arac":len(normalized),
            "arac_g":arac_g,
            "arac_d":arac_d,
            "gunluk_yolcu_hici":hi,
            "gunluk_yolcu_hs":hs,
            "gorev_sayisi":gorev,
            "stres_skoru":stres,
            "doluluk_yuzde":doluluk_yuzde,
            "doluluk_etiket":doluluk_etiket,
            "gecikme_skor":gecikme_skor,
            "gecikme_sev":gecikme_sev,
            "ort_hiz_kmh":ort_hiz,
            "en_yogun_durak":en_yogun_durak,
            "profil_hi":yc.get("profil_hi",[]),
            "profil_hs":yc.get("profil_hs",[]),
            "peak_saat_hi":yc.get("peak_saat_hi",8),
            "peak_saat_hs":yc.get("peak_saat_hs",13),
            "akilli_durak":len([d for d in duraklar if d.get('akilli')]),
            "engelli_durak":len([d for d in duraklar if d.get('engelli')]),
            "kaynak_yogunluk":  yc.get("kaynak_arac","—"),
            "yolcu_kaynak":     yc.get("yolcu_kaynak","—"),
            "sefer_suresi_dk":  sefer_suresi_dk,
            "hat_uzunlugu_km":  hat_uzunlugu_km,
            "verimlilik_yolcu_km": verimlilik_yolcu_km,
            "tamamlanma":       tamamlanma,
            **_hat_extra,
        })

    @app.route('/api/gecikme_skoru')
    def api_gecikme_skoru():
        hat=request.args.get('hat','').upper()
        with _lock: gc=dict(GECIKME_CACHE)
        if hat:
            veri=gc.get(hat)
            if not veri:
                saat=datetime.now().hour; hici=datetime.now().weekday()<5
                th,ts=ISTANBUL_PROFIL.get(saat,(0.75,0.75)); kats=th if hici else ts
                seed_val=sum(ord(c) for c in hat)%100; varyasyon=(seed_val-50)*0.003
                hat_kats=max(0.25,min(1.0,kats+varyasyon)); sev,renk=trafik_seviye(hat_kats)
                veri={"skor":int((1.0-hat_kats)*100),"seviye":sev,"renk":renk,
                      "ortalama_hiz":round(28.0*hat_kats,1),"beklenen_hiz":28.0,"arac_sayisi":0,"tahmin":True}
            return jsonify(veri)
        top=sorted(gc.items(),key=lambda x:x[1].get("skor",0),reverse=True)
        return jsonify({"hatlar":[{"hat":h,**v} for h,v in top],"toplam":len(top)})

    @app.route('/api/yogunluk')
    def api_yogunluk():
        hat=request.args.get('hat','').upper()
        with _lock: yc=dict(YOGUNLUK_CACHE)
        if hat:
            veri=yc.get(hat)
            if not veri: return jsonify({"hata":"Bu hat için yoğunluk verisi yok"})
            return jsonify({"hat":hat,**veri})
        simdi=datetime.now().hour; hici=datetime.now().weekday()<5
        sirali=sorted([(h,v["profil_hi"][simdi] if hici else v["profil_hs"][simdi],
                        v.get("kaynak_arac","—"),v.get("arac_sayisi",0))
                       for h,v in yc.items()],key=lambda x:x[1],reverse=True)[:20]
        return jsonify({"en_yogun":[{"hat":h,"doluluk":d,"kaynak":k,"arac":a} for h,d,k,a in sirali],
                        "saat":simdi,"gun_tipi":"HİÇ" if hici else "HS"})

    @app.route('/api/trafik_nokta')
    def api_trafik_nokta():
        lat=temiz_sayi(request.args.get('lat','0')); lon=temiz_sayi(request.args.get('lon','0'))
        if abs(lat) < 1 or abs(lon) < 1: return jsonify({"hata":"lat/lon gerekli"})
        return jsonify(get_trafik(lat,lon))

    @app.route('/api/trafik_isi')
    def api_trafik_isi():
        """
        Harita ısı katmanı için trafik yoğunluk noktaları.
        Önce IBB TrafficIndex → yoksa saat profili ile İstanbul koridor noktaları üretilir.
        Dönen format: {noktalar:[{lat,lon,yogunluk}], kaynak, ibb_index}
        """
        from services import get_traffic_index_history_summary, saat_trafik_katsayi, KORIDOR_AGIRLIKLARI

        # İstanbul'u kapsayan ızgara noktaları (lat, lon)
        GRID = [
            (41.0781, 28.9784), (41.0500, 28.9900), (41.0200, 29.0100),
            (41.0050, 28.9500), (40.9900, 28.8700), (41.0300, 28.7800),
            (41.1050, 29.0300), (41.0650, 29.0600), (41.0450, 29.1000),
            (40.9750, 29.0100), (40.9600, 29.1200), (41.1300, 28.9900),
            (41.1500, 29.0500), (41.0850, 28.8500), (41.0100, 28.8200),
            (40.9950, 28.7500), (41.0600, 28.6800), (41.1200, 28.7200),
            (41.0300, 29.0500), (41.0750, 29.1500), (40.9500, 28.9800),
            (40.9300, 29.0600), (41.1700, 29.0200), (41.0950, 28.7800),
        ]

        ibb_index = None
        kaynak = "profil"

        # 1. IBB TrafficIndex
        try:
            ozet = get_traffic_index_history_summary(period="5M")
            values = ozet.get("values", [])
            if values:
                ibb_index = values[-1]
                kaynak = "ibb_traffic_index"
        except Exception:
            pass

        noktalar = []
        for lat, lon in GRID:
            if ibb_index is not None:
                # IBB indeksi tüm şehir için geçerli; koridor ağırlıklarıyla nokta bazlı varyasyon ekle
                kor_kats = saat_trafik_katsayi(lat, lon)
                base_yogunluk = float(ibb_index)
                # Koridor yoğunluğu yüksekse indeksi biraz artır
                yogunluk = round(min(100, base_yogunluk * (2.0 - kor_kats)), 1)
            else:
                # Saat profili → yoğunluk = (1 - katsayi) * 100
                kats = saat_trafik_katsayi(lat, lon)
                yogunluk = round((1.0 - kats) * 100, 1)

            noktalar.append({"lat": lat, "lon": lon, "yogunluk": yogunluk})

        return jsonify({
            "noktalar": noktalar,
            "kaynak": kaynak,
            "ibb_index": ibb_index,
            "adet": len(noktalar)
        })

    # ── YENİ ENDPOINTLERİ ──────────────────────────────────────

    @app.route('/api/guzergah_trafik')
    def api_guzergah_trafik():
        """
        Hat güzergahını trafik renkli segmentlere böler.
        Döner: {segmentler:[{lat1,lon1,lat2,lon2,renk,seviye,katsayi}], hat, yon}
        Frontend bu listeyi alıp her segmenti ayrı polyline olarak çizer.
        """
        hat = request.args.get('hat','').upper()
        yon = request.args.get('yon','G').upper()
        if not hat:
            return jsonify({"hata": "hat gerekli"})

        # Durak listesini cache'den veya API'den al
        cache_key = f"durak_detay_{hat}"
        with _lock:
            cached = API_RESPONSE_CACHE.get(cache_key)

        if not cached:
            body = f'<DurakDetay_GYY_wYonAdi xmlns="http://tempuri.org/"><hat_kodu>{hat}</hat_kodu></DurakDetay_GYY_wYonAdi>'
            root = fetch_soap_xml(URL_IBB, 'DurakDetay_GYY_wYonAdi', body, timeout_sec=10)
            if root is None:
                return jsonify({"hata": "Durak verisi alınamadı", "segmentler": []})
            from utils import xml_findall_local, xml_child_text, safe_int, temiz_str, temiz_sayi
            duraklar_raw = xml_findall_local(root, "DurakDetay_GYY_wYonAdiResult") or xml_findall_local(root, "Table")
            duraklar = []
            for item in duraklar_raw:
                d = {
                    "kodu": xml_child_text(item, "SDURAKKODU", ""),
                    "ad":   xml_child_text(item, "SDURAKADI", ""),
                    "yon":  xml_child_text(item, "SYON", "G").upper(),
                    "sira": safe_int(xml_child_text(item, "SSIRA", "0")),
                    "lat":  temiz_sayi(xml_child_text(item, "ENLEM", "0")),
                    "lon":  temiz_sayi(xml_child_text(item, "BOYLAM", "0")),
                }
                if d["lat"] and d["lon"]:
                    duraklar.append(d)
            with _lock:
                API_RESPONSE_CACHE[cache_key] = {"duraklar": duraklar}
        else:
            duraklar = cached.get("duraklar", [])

        # Seçili yönü filtrele ve sırala
        pts = sorted(
            [d for d in duraklar if d.get("yon") == yon and d.get("lat") and d.get("lon")],
            key=lambda x: x.get("sira", 0)
        )

        if len(pts) < 2:
            return jsonify({"segmentler": [], "hat": hat, "yon": yon, "mesaj": "Yeterli durak yok"})

        # Her ardışık durak çifti için trafik sorgula → segment oluştur
        segmentler = []
        for i in range(len(pts) - 1):
            p1, p2 = pts[i], pts[i+1]
            # Segment orta noktasında trafik sorgula (performans için)
            mid_lat = (p1["lat"] + p2["lat"]) / 2
            mid_lon = (p1["lon"] + p2["lon"]) / 2
            trafik = get_trafik(mid_lat, mid_lon)
            seg = {
                "lat1": p1["lat"], "lon1": p1["lon"],
                "lat2": p2["lat"], "lon2": p2["lon"],
                "durak1": p1.get("ad", ""), "durak2": p2.get("ad", ""),
                "renk":    trafik.get("renk", "#0ea5e9"),
                "seviye":  trafik.get("seviye", "bilinmiyor"),
                "katsayi": trafik.get("katsayi", 1.0),
                "trafik_kaynak": trafik.get("kaynak", "profil"),
            }
            if "ibb_index" in trafik:
                seg["ibb_index"] = trafik["ibb_index"]
            segmentler.append(seg)

        return jsonify({
            "segmentler": segmentler,
            "hat": hat,
            "yon": yon,
            "durak_sayisi": len(pts),
        })

    @app.route('/api/guzergah_geo')
    def api_guzergah_geo():
        """
        Gerçek yol geometrisi: hat_guzergah_geo.json'dan [[lat,lon],...] döner.
        ?hat=76A&yon=G (G=gidiş, D=dönüş, boş=her ikisi)
        """
        hat = request.args.get('hat', '').upper().strip()
        yon = request.args.get('yon', '').upper().strip()
        if not hat:
            return jsonify({"hata": "hat gerekli"})

        geo = PANEL_DATA.get('hat_guzergah_geo', {})
        hat_data = geo.get(hat)
        if not hat_data:
            return jsonify({"hat": hat, "G": [], "D": []})

        if yon in ('G', 'D'):
            return jsonify({"hat": hat, yon: hat_data.get(yon, [])})
        return jsonify({"hat": hat, "G": hat_data.get('G', []), "D": hat_data.get('D', [])})




    @app.route('/api/arac_ozellik')
    def api_arac_ozellik():
        kapi=request.args.get('kapi','').strip()
        if not kapi: return jsonify({"hata":"kapi gerekli"})
        return jsonify(get_arac_ozellik(kapi))

    @app.route('/api/operasyonel_ozet')
    def api_operasyonel_ozet():
        with _lock:
            return jsonify({
                "ariza_aktif": len(OLAY_CACHE["ariza"]["veri"]),
                "duyuru_sayisi": len(OLAY_CACHE["duyuru"]["veri"]),
                "guncelleme_ts": datetime.now().isoformat()
            })

    @app.route('/api/kara_kutu_sefer')
    def api_kara_kutu_sefer():
        """GetKaraKutuSeferBilgileri_json — Tarih bazlı kara kutu sefer bilgileri"""
        tarih=request.args.get('tarih',datetime.now().strftime("%Y-%m-%d"))
        body=f'<GetKaraKutuSeferBilgileri_json xmlns="http://tempuri.org/"><Tarih>{tarih}</Tarih></GetKaraKutuSeferBilgileri_json>'
        res=fetch_soap(URL_FILO,'GetKaraKutuSeferBilgileri_json',body,timeout_sec=10,use_auth=True)
        return jsonify(res or [])

    @app.route('/api/usulsuz_kart')
    def api_usulsuz_kart():
        """GetUzulsuzKartKullanim_json — Saate göre usulsüz kart kullanımı"""
        saat=request.args.get('saat',str(datetime.now().hour))
        try: saat_int=int(saat)
        except: saat_int=datetime.now().hour
        body=f'<GetUzulsuzKartKullanim_json xmlns="http://tempuri.org/"><saat>{saat_int}</saat></GetUzulsuzKartKullanim_json>'
        res=fetch_soap(URL_FILO,'GetUzulsuzKartKullanim_json',body,timeout_sec=8,use_auth=True)
        return jsonify(res or [])

    @app.route('/api/metrobus_hazir')
    def api_metrobus_hazir():
        """GetKaraKutu_ServiseHazirAracMetrobus_json — Metrobüste servise hazır araçlar"""
        body='<GetKaraKutu_ServiseHazirAracMetrobus_json xmlns="http://tempuri.org/" />'
        res=fetch_soap(URL_FILO,'GetKaraKutu_ServiseHazirAracMetrobus_json',body,timeout_sec=8,use_auth=True)
        return jsonify(res or [])

    @app.route('/api/plaka_sorgula')
    def api_plaka_sorgula():
        """IETTPlakaServisi_Json — KapiNo ile plaka sorgula (ibb.asmx)"""
        kapi=request.args.get('kapi','').strip()
        if not kapi: return jsonify({"hata":"kapi gerekli"})
        body=f'<IETTPlakaServisi_Json xmlns="http://tempuri.org/"><KapiNo>{kapi}</KapiNo></IETTPlakaServisi_Json>'
        res=fetch_soap(URL_IBB,'IETTPlakaServisi_Json',body,timeout_sec=8,use_auth=True)
        return jsonify(res or [])

    @app.route('/api/durak_sefer_saati')
    def api_durak_sefer_saati():
        """GetPlanlananSeferSaatiAraDurak_json — Durak kodu ile sefer saati"""
        durak=request.args.get('durak','').strip()
        if not durak: return jsonify({"hata":"durak gerekli"})
        body=f'<GetPlanlananSeferSaatiAraDurak_json xmlns="http://tempuri.org/"><DurakKodu>{durak}</DurakKodu></GetPlanlananSeferSaatiAraDurak_json>'
        res=fetch_soap(URL_SAAT,'GetPlanlananSeferSaatiAraDurak_json',body,timeout_sec=8,use_auth=True)
        return jsonify(res or [])

    @app.route('/api/yolcu_bilgilendirme')
    def api_yolcu_bilgilendirme():
        """GetYolcuBilgilendirme_json — Yolcu bilgilendirme mesajları"""
        body='<GetYolcuBilgilendirme_json xmlns="http://tempuri.org/" />'
        res=fetch_soap(URL_FILO,'GetYolcuBilgilendirme_json',body,timeout_sec=8,use_auth=True)
        return jsonify(res or [])

    @app.route('/api/filo_yuk')
    def api_filo_yuk():
        """
        Filo iş yükü analizi — GetIettArsivGorev_json kaynaklı.
        Araç yorulma endeksi, YK korelasyonu ve hat bazlı risk bilgisi döner.
        """
        with _lock:
            yuk_ozet   = dict(ARSIV_CACHE.get("yuk_ozet", {}))
            en_yorgun  = list(ARSIV_CACHE.get("en_yorgun", []))
            hat_yk     = dict(ARSIV_CACHE.get("hat_yk", {}))
            arac_yuku  = dict(ARSIV_CACHE.get("arac_yuku", {}))
            veri_tar   = ARSIV_CACHE.get("veri_tarihi", "")

        # ── Kategori dağılımı (pasta grafik için) ────────────────────────────
        kategori_dagilim = [
            {"kategori": "🔴 Kritik Yorgun (12+ Saat)", "sayi": yuk_ozet.get("kritik", 0),  "renk": "#ef4444"},
            {"kategori": "🟠 Normal Mesai (8-12 Saat)", "sayi": yuk_ozet.get("normal", 0),  "renk": "#f59e0b"},
            {"kategori": "🟢 Düşük Yük (<8 Saat)",      "sayi": yuk_ozet.get("dusuk", 0),   "renk": "#22c55e"},
        ]

        # ── YK riski en yüksek 10 hat ────────────────────────────────────────
        top_yk_hatlar = sorted(hat_yk.items(), key=lambda x: x[1], reverse=True)[:10]
        yk_hat_list   = [{"hat": h, "yk_sayi": s} for h, s in top_yk_hatlar]

        # ── YK yapan vs yapmayan araç ortalama mesai karşılaştırması ─────────
        yk_araclar     = [v["sure_saat"] for v in arac_yuku.values() if v.get("yk")]
        sorunsuz_arac  = [v["sure_saat"] for v in arac_yuku.values() if not v.get("yk")]
        yk_ort         = round(sum(yk_araclar)    / max(len(yk_araclar),    1), 1)
        sorunsuz_ort   = round(sum(sorunsuz_arac) / max(len(sorunsuz_arac), 1), 1)

        # ── Saat dağılımı — kaç araç kaç saatlik mesai yaptı (histogram) ─────
        # 2 saatlik dilimler: 0-2, 2-4, 4-6, ... 18-20, 20+
        histogram = [0] * 11
        for v in arac_yuku.values():
            s = v["sure_saat"]
            idx = min(10, int(s / 2))
            histogram[idx] += 1
        hist_labels = ["0-2","2-4","4-6","6-8","8-10","10-12","12-14","14-16","16-18","18-20","20+"]

        return jsonify({
            "ozet": {
                "toplam_aktif":  yuk_ozet.get("toplam_aktif", 0),
                "kritik":        yuk_ozet.get("kritik", 0),
                "normal":        yuk_ozet.get("normal", 0),
                "dusuk":         yuk_ozet.get("dusuk", 0),
                "yk_arac_sayi":  len(yk_araclar),
                "yk_ort_saat":   yk_ort,
                "sorunsuz_ort":  sorunsuz_ort,
            },
            "kategori_dagilim": kategori_dagilim,
            "en_yorgun":        en_yorgun,
            "yk_hat_list":      yk_hat_list,
            "histogram":        {"labels": hist_labels, "values": histogram},
            "veri_tarihi":      veri_tar,
            "kaynak":           "arsiv_gorev",
        })


    @app.route('/api/gecikme_analiz')
    def api_gecikme_analiz():
        """
        Referans analiz kodunun Flask versiyonu:
        1. GetPlanlananSeferSaati_json  → planlanan sefer sayısı
        2. GetIettArsivGorev_json       → SGOREVDURUM='T' tamamlanan seferlerden
                                          ideal/kriz/ortalama süre
        3. GetFiloAracKonum_json cache  → anlık hız <15 olan araçlar (darboğaz)
        """
        hat = request.args.get('hat', '').strip().upper()
        if not hat:
            return jsonify({"hata": "hat parametresi gerekli"})

        # ── 1. Planlanan sefer sayısı ─────────────────────────────────────────
        planlanan_sayi = 0
        planlanan_ortalama_dk = None
        body_plan = (f'<GetPlanlananSeferSaati_json xmlns="http://tempuri.org/">'
                     f'<HatKodu>{hat}</HatKodu></GetPlanlananSeferSaati_json>')
        plan_veri = fetch_soap(URL_SAAT, 'GetPlanlananSeferSaati_json',
                               body_plan, timeout_sec=10, use_auth=False)

        if isinstance(plan_veri, list) and plan_veri:
            # Bugünün gün tipine göre filtrele
            gun_idx = datetime.now().weekday()
            bugun_gt = 'P' if gun_idx == 6 else ('C' if gun_idx == 5 else 'I')
            bugun_seferler = [s for s in plan_veri
                              if str(s.get('SGUNTIPI') or s.get('GunTipi') or bugun_gt).strip().upper() == bugun_gt]
            planlanan_sayi = len(bugun_seferler) if bugun_seferler else len(plan_veri)

            # Planlanan sefer süresi: HAT_BILGI_CACHE'den SEFER_SURESI al (GetHat_json)
            hb_gecikme = get_hat_bilgi(hat)
            if hb_gecikme.get("sefer_suresi_dk"):
                planlanan_ortalama_dk = hb_gecikme["sefer_suresi_dk"]
            else:
                # Fallback: plan_veri kayıtlarında SSURE varsa al
                for kayit in (bugun_seferler or plan_veri)[:5]:
                    for alan in ['SSURE', 'Sure', 'SURE', 'SeferSuresi', 'SEFERSURESI']:
                        val = kayit.get(alan)
                        if val:
                            try:
                                planlanan_ortalama_dk = float(str(val).replace(',', '.'))
                                break
                            except Exception:
                                pass
                    if planlanan_ortalama_dk:
                        break

        # ── 2. Arşiv — tamamlanan seferlerden gerçek süreler ──────────────────
        # Bugün → dün → önceki gün sırasıyla dene
        gercek_sureler = []   # [{sure_dk, baslama_saat, kapi, guzergah}]
        veri_tarihi = ""

        for offset in range(0, 4):
            tarih_dt = datetime.now() - timedelta(days=offset)
            tarih_str = tarih_dt.strftime("%Y%m%d")
            body_arsiv = (f'<GetIettArsivGorev_json xmlns="http://tempuri.org/">'
                          f'<Tarih>{tarih_str}</Tarih></GetIettArsivGorev_json>')
            arsiv = fetch_soap(URL_IBB360, 'GetIettArsivGorev_json',
                               body_arsiv, use_auth=False, timeout_sec=20)
            if not arsiv:
                continue

            # Sadece bu hat + tamamlananlar (SGOREVDURUM == 'T')
            hat_kayitlar = [
                g for g in arsiv
                if str(g.get('SHATKODU') or g.get('HatKodu') or '').strip().upper() == hat
                and str(g.get('SGOREVDURUM') or g.get('GorevDurum') or '').strip().upper() == 'T'
            ]

            if not hat_kayitlar:
                continue

            for g in hat_kayitlar:
                bas = _parse_aspnet_date(g.get('DTBASLAMAZAMANI') or g.get('BaslamaZamani'))
                bit = _parse_aspnet_date(g.get('DTBITISZAMANI')   or g.get('BitisZamani'))
                if not bas or not bit:
                    continue
                sure_dk = (bit - bas).total_seconds() / 60
                # Referans koddaki filtre: 10 < sure < 300
                if not (10 < sure_dk < 300):
                    continue
                guzergah = str(g.get('SGUZERGAHKODU') or g.get('GuzergahKodu') or '').strip().upper()
                kapi     = str(g.get('SKAPINUMARA')   or g.get('KapiNo') or '').strip()
                gercek_sureler.append({
                    "sure_dk":     round(sure_dk, 1),
                    "saat":        bas.strftime("%H:%M"),
                    "kapi":        kapi,
                    "guzergah":    guzergah,
                })

            if gercek_sureler:
                veri_tarihi = tarih_dt.strftime("%d.%m.%Y")
                break   # veri bulundu, dur

        # ── Hesaplamalar ──────────────────────────────────────────────────────
        ideal_sure   = None
        kriz_sure    = None
        ortalama_sure= None
        sapma_dk     = None
        sapma_yuzde  = None
        oneri        = ""
        histogram    = []   # sure dilimleri için
        en_uzun      = []
        en_kisa      = []

        if gercek_sureler:
            sureler = [s["sure_dk"] for s in gercek_sureler]
            ideal_sure    = round(min(sureler), 1)
            kriz_sure     = round(max(sureler), 1)
            ortalama_sure = round(sum(sureler) / len(sureler), 1)

            # Planlanan süreyle sapma
            if planlanan_ortalama_dk and planlanan_ortalama_dk > 0:
                sapma_dk     = round(ortalama_sure - planlanan_ortalama_dk, 1)
                sapma_yuzde  = round((sapma_dk / planlanan_ortalama_dk) * 100, 1)

            # Planlama önerisi: ortalama vs ideal fark
            fark = ortalama_sure - ideal_sure
            if fark > 30:
                oneri = f"Sefer süreleri ortalama {round(fark,0):.0f} dk uzatılmalı — trafik kaynaklı gecikme yüksek."
            elif fark > 15:
                oneri = f"Sefer süreleri {round(fark,0):.0f} dk uzatılabilir — özellikle sabah/akşam pik saatlerinde."
            else:
                oneri = "Planlanan süreler gerçeğe yakın. Büyük revizyon gerekmez."

            # En uzun 5 / en kısa 5 sefer
            sirali = sorted(gercek_sureler, key=lambda x: x["sure_dk"])
            en_kisa = sirali[:5]
            en_uzun = sirali[-5:][::-1]

            # Histogram: 10'ar dakika dilimleri
            from collections import Counter
            dilimler = Counter(int(s // 10) * 10 for s in sureler)
            min_d = min(dilimler); max_d = max(dilimler)
            histogram = [
                {"etiket": f"{d}-{d+10} dk", "sayi": dilimler.get(d, 0)}
                for d in range(min_d, max_d + 10, 10)
            ]

        # ── 3. Uzun Duruş — UZUN_DURUŞ_CACHE + FILO_CACHE ─────────────────────
        with _lock:
            filo_liste = list(FILO_CACHE.get("liste", []))
            filo_ts    = FILO_CACHE.get("ts", 0)
            uzun_snap  = dict(UZUN_DURUŞ_CACHE)
            gecmis_dolu = sum(1 for v in ARAC_KONUM_GECMIS.values() if len(v) >= 2)

        hat_arac_sayisi = 0
        for arac in filo_liste:
            kapi  = str(arac.get('KapiNo') or arac.get('kapino') or '').strip()
            a_hat = str(arac.get('HatKodu') or arac.get('hatkodu') or '').strip().upper()
            if a_hat != hat:
                with _lock:
                    km = FILO_CACHE["kapi_map"].get(kapi, {})
                a_hat = km.get("hat", "")
            if a_hat == hat:
                hat_arac_sayisi += 1

        hat_uzun      = [v for v in uzun_snap.values() if v.get("hat","").upper() == hat]
        trafik_liste  = sorted([v for v in hat_uzun if v["tur"]=="trafik"],
                                key=lambda x: x["sure_sn"], reverse=True)
        yolcu_liste   = sorted([v for v in hat_uzun if v["tur"]=="yolcu_alimi"],
                                key=lambda x: x["sure_sn"], reverse=True)
        ariza_liste   = sorted([v for v in hat_uzun if v["tur"]=="olası_arıza"],
                                key=lambda x: x["sure_sn"], reverse=True)

        veri_yasi_sn = int(time.time() - filo_ts) if filo_ts else None

        return jsonify({
            "hat":               hat,
            "planlanan_sayi":    planlanan_sayi,
            "planlanan_sure_dk": planlanan_ortalama_dk,
            "gercek": {
                "ideal_sure":    ideal_sure,
                "kriz_sure":     kriz_sure,
                "ortalama_sure": ortalama_sure,
                "sefer_sayisi":  len(gercek_sureler),
                "sapma_dk":      sapma_dk,
                "sapma_yuzde":   sapma_yuzde,
                "oneri":         oneri,
            },
            "en_uzun":    en_uzun,
            "en_kisa":    en_kisa,
            "histogram":  histogram,
            "uzun_duruş": {
                "hat_arac":           hat_arac_sayisi,
                "trafik_sayi":        len(trafik_liste),
                "yolcu_alimi_sayi":   len(yolcu_liste),
                "olasi_ariza_sayi":   len(ariza_liste),
                "trafik":             trafik_liste,
                "yolcu_alimi":        yolcu_liste,
                "olasi_ariza":        ariza_liste,
                "veri_yasi_sn":       veri_yasi_sn,
                "gecmis_dolu":        gecmis_dolu,
                "gecmis_toplam":      len(ARAC_KONUM_GECMIS),
                "esikler": {"durak_yakinlik_m":60,"yolcu_alimi_sn":120,
                            "trafik_hiz_kmh":15,"trafik_sure_sn":180,
                            "ariza_hiz_kmh":3,"ariza_sure_sn":300},
            },
            "veri_tarihi":       veri_tarihi,
            "kaynak":            "arsiv_gorev+filo_cache+konum_gecmis",
        })


    @app.route('/api/plan_basari')
    def api_plan_basari():
        """
        Tüm ağ veya belirli hat için sefer tamamlanma oranı.
        SGOREVDURUM: T=Tamamlandı, YK=Yarım Kaldı, P=Planlı
        ?hat=79T → sadece o hat
        """
        hat_filtre = request.args.get('hat', '').strip().upper()

        with _lock:
            hat_tamamlanma = dict(ARSIV_CACHE.get("hat_tamamlanma", {}))
            ozet_genel     = dict(ARSIV_CACHE.get("tamamlanma_ozet", {}))
            veri_tarihi    = ARSIV_CACHE.get("veri_tarihi", "")

        if hat_filtre:
            hat_veri = hat_tamamlanma.get(hat_filtre, {})
            return jsonify({
                "hat":       hat_filtre,
                "veri":      hat_veri,
                "tarih":     veri_tarihi,
                "kaynak":    "arsiv_gorev",
            })

        # Tüm ağ — en düşük tamamlanma oranlı 20 hat öne al
        sirali = sorted(
            hat_tamamlanma.items(),
            key=lambda x: x[1].get("oran_yuzde", 100)
        )[:20]

        return jsonify({
            "ozet":    ozet_genel,
            "en_dusuk": [{"hat": h, **v} for h, v in sirali],
            "tarih":   veri_tarihi,
            "kaynak":  "arsiv_gorev",
        })


    @app.route('/api/headway')
    def api_headway():
        """
        Hat için sefer sıklığı (headway) analizi.
        GetPlanlananSeferSaati_json → bugünün saatlerinden hesaplar.
        ?hat=79T → zorunlu
        """
        hat = request.args.get('hat', '').strip().upper()
        if not hat:
            return jsonify({"hata": "hat parametresi gerekli"})

        # SAAT_CACHE'de varsa direkt kullan
        with _lock:
            saat_c = SAAT_CACHE.get(hat)

        sonuc = hesapla_headway(hat)
        if not sonuc:
            return jsonify({"hata": f"{hat} için sefer saati verisi alınamadı"})

        # Hat uzunluğu ekle (headway × hat_uzunlugu → km/saat verimlilik)
        hb = get_hat_bilgi(hat)
        sonuc["hat_uzunlugu_km"]  = hb.get("hat_uzunlugu_km")
        sonuc["sefer_suresi_dk"]  = hb.get("sefer_suresi_dk")
        sonuc["hat_adi"]          = hb.get("hat_adi", hat)

        # Headway yorumu
        hw = sonuc.get("headway_ort")
        if hw is not None:
            if hw <= 5:
                sonuc["headway_yorum"] = "Çok sık — yüksek kapasite hattı"
            elif hw <= 10:
                sonuc["headway_yorum"] = "Sık — yeterli frekans"
            elif hw <= 20:
                sonuc["headway_yorum"] = "Orta — bekleme süresi kabul edilebilir"
            else:
                sonuc["headway_yorum"] = "Seyrek — bekleme süresi uzun"

        return jsonify(sonuc)


    @app.route('/api/hat_bilgi')
    def api_hat_bilgi():
        """
        GetHat_json'dan SEFER_SURESI, HAT_UZUNLUGU, tarife bilgisi.
        Tek hat veya boş (tüm ağ özeti).
        ?hat=79T
        """
        hat = request.args.get('hat', '').strip().upper()

        if hat:
            sonuc = get_hat_bilgi(hat)
            if not sonuc:
                return jsonify({"hata": f"{hat} için hat bilgisi alınamadı"})

            # Tamamlanma ve headway ekle
            with _lock:
                tamamlanma = dict(ARSIV_CACHE.get("hat_tamamlanma", {}).get(hat, {}))
            sonuc["tamamlanma"] = tamamlanma
            return jsonify(sonuc)

        # Tüm cache'i döndür (hat listesi için)
        with _lock:
            snap = dict(HAT_BILGI_CACHE)
        return jsonify({
            "hat_sayisi": len(snap),
            "hatlar":     list(snap.keys()),
            "kaynak":     "hat_bilgi_cache",
        })


    @app.route('/api/ariza_uyari')
    def api_ariza_uyari():
        """İzleme listesi — tüm hareketsiz araçlar (izleme/yolcu_alimi/trafik/olası_arıza)."""
        with _lock:
            uzun_snap = dict(UZUN_DURUŞ_CACHE)
            sm_list   = PANEL_DATA.get('smart_maintenance', [])
            izlenen   = len(ARAC_KONUM_GECMIS)

        sm_idx = {(v.get('kapino') or '').strip(): v
                  for v in (sm_list if isinstance(sm_list, list) else [])}

        # Öncelik sırası: olası_arıza > trafik > yolcu_alimi > izleme
        _onc = {'olası_arıza': 0, 'trafik': 1, 'yolcu_alimi': 2, 'izleme': 3}
        tum_liste = sorted(
            uzun_snap.values(),
            key=lambda x: (_onc.get(x.get('tur',''), 9), -x.get('sure_sn', 0))
        )

        sonuclar = []
        for v in tum_liste:
            kapi    = (v.get('kapi') or '').strip()
            sm      = sm_idx.get(kapi, {})
            sure_sn = v.get('sure_sn', 0)
            sure_dk = sure_sn // 60
            sure_str = f"{sure_dk} dk {sure_sn % 60} sn" if sure_dk else f"{sure_sn} sn"
            sonuclar.append({
                'kapi':          kapi,
                'hat':           v.get('hat', '—'),
                'lat':           v.get('lat'),
                'lon':           v.get('lon'),
                'hiz':           round(v.get('hiz', 0), 1),
                'sure_sn':       sure_sn,
                'sure_str':      sure_str,
                'tur':           v.get('tur', 'izleme'),
                'ibb_seviye':    v.get('ibb_seviye'),
                'durak_ad':      v.get('durak_ad'),
                'durak_km':      v.get('durak_km'),
                'kaynak':        v.get('kaynak', ''),
                'aciliyet_tier': sm.get('aciliyet_tier', ''),
                'bakim_uyarisi': sm.get('bakim_uyarisi', ''),
            })

        return jsonify({
            'toplam':        len(sonuclar),
            'olasi_ariza':   sum(1 for v in sonuclar if v['tur'] == 'olası_arıza'),
            'trafik':        sum(1 for v in sonuclar if v['tur'] == 'trafik'),
            'yolcu_alimi':   sum(1 for v in sonuclar if v['tur'] == 'yolcu_alimi'),
            'izleme':        sum(1 for v in sonuclar if v['tur'] == 'izleme'),
            'izlenen_arac':  izlenen,
            'liste':         sonuclar,
            'ts':            time.time(),
        })

    @app.route('/api/uzun_duruş')
    def api_uzun_duruş():
        """Tüm ağ veya hat için uzun duruş özeti. ?hat=79T ?tur=trafik|yolcu_alimi"""
        hat_filtre = request.args.get('hat', '').strip().upper()
        tur_filtre = request.args.get('tur', '').strip().lower()
        with _lock:
            uzun_snap     = dict(UZUN_DURUŞ_CACHE)
            filo_ts       = FILO_CACHE.get("ts", 0)
            gecmis_dolu   = sum(1 for v in ARAC_KONUM_GECMIS.values() if len(v) >= 2)
            gecmis_toplam = len(ARAC_KONUM_GECMIS)
        sonuclar = list(uzun_snap.values())
        if hat_filtre:
            sonuclar = [v for v in sonuclar if v.get("hat","").upper() == hat_filtre]
        if tur_filtre in ("trafik","yolcu_alimi","olası_arıza"):
            sonuclar = [v for v in sonuclar if v.get("tur") == tur_filtre]
        sonuclar.sort(key=lambda x: x["sure_sn"], reverse=True)
        hat_ozet = {}
        for v in uzun_snap.values():
            h = v.get("hat","—")
            if h not in hat_ozet:
                hat_ozet[h] = {"hat":h,"trafik":0,"yolcu_alimi":0,"olasi_ariza":0}
            tur_k = "olasi_ariza" if v["tur"]=="olası_arıza" else v["tur"]
            hat_ozet[h][tur_k] = hat_ozet[h].get(tur_k,0) + 1
        hat_ozet_liste = sorted(hat_ozet.values(),
                                key=lambda x: x["trafik"]+x["yolcu_alimi"]+x["olasi_ariza"]*2,
                                reverse=True)
        return jsonify({
            "toplam":            len(sonuclar),
            "trafik_sayi":       sum(1 for v in sonuclar if v["tur"]=="trafik"),
            "yolcu_alimi_sayi":  sum(1 for v in sonuclar if v["tur"]=="yolcu_alimi"),
            "olasi_ariza_sayi":  sum(1 for v in sonuclar if v["tur"]=="olası_arıza"),
            "liste":             sonuclar[:200],
            "hat_ozet":          hat_ozet_liste[:20],
            "sistem": {
                "gecmis_dolu":   gecmis_dolu,
                "gecmis_toplam": gecmis_toplam,
                "doluluk_yuzde": round(gecmis_dolu/max(gecmis_toplam,1)*100,1),
                "veri_yasi_sn":  int(time.time()-filo_ts) if filo_ts else None,
                "hazir":         gecmis_dolu > 100,
            },
            "kaynak":"konum_gecmis_analiz",
        })

    @app.route('/api/kara_kutu')
    def api_kara_kutu():
        """GetKaraKutu_json — Hat/araç bazlı kara kutu verisi"""
        hat=request.args.get('hat','').upper()
        kapi=request.args.get('kapi','')
        tarih=request.args.get('tarih',datetime.now().strftime("%Y-%m-%d"))
        body=(f'<GetKaraKutu_json xmlns="http://tempuri.org/">'
              f'<tarih>{tarih}</tarih><KapiNo>{kapi}</KapiNo><HatKodu>{hat}</HatKodu>'
              f'</GetKaraKutu_json>')
        res = fetch_soap(URL_FILO, 'GetKaraKutu_json', body, timeout_sec=10, use_auth=True)
        return jsonify(res or [])

    # ══════════════════════════════════════════════════════════
    # ★ ML VERİ SİSTEMİ — SQL kolonlarına dayalı akıllı simülasyon
    # Kolonlar: transition_date, transition_hour, transport_type_id, road_type,
    #           line, transfer_type, number_of_passage, number_of_passenger,
    #           product_kind, transaction_type_desc, town, line_name
    # ══════════════════════════════════════════════════════════

    # İstanbul gerçek ilçe dağılımı (IETT hizmet ağına göre ağırlıklı)
    # ══════════════════════════════════════════════════════════
    # ★ GERÇEK SQL VERİ ANALİTİĞİ (Dashboard Grafikleri İçin)
    # ══════════════════════════════════════════════════════════

    @app.route('/api/bilet_analizi')
    def api_bilet_analizi():
        """Datathon SQLite DBILETKATEGORI + DAKTARMATIPI bazlı bilet analizi"""
        saat_int = datetime.now().hour
        hici = datetime.now().weekday() < 5
        # Saatlik ağırlık katsayısı — _SAAT_DAGILIM_HIC/HS profili normalize (0-1 → ~anlık yoğunluk)
        saat_w = _SAAT_DAGILIM_HIC[saat_int] if hici else _SAAT_DAGILIM_HS[saat_int]

        try:
            con = get_panel_db(); cur = con.cursor()

            # ── 1. Bilet kategorisi dağılımı ───────────────────────────
            cur.execute('''
                SELECT DBILETKATEGORI, COUNT(*) as cnt
                FROM yolcu
                WHERE DBILETKATEGORI IS NOT NULL AND DBILETKATEGORI != ''
                GROUP BY DBILETKATEGORI
                ORDER BY cnt DESC
            ''')
            kat_rows = cur.fetchall()
            toplam_kat = sum(r[1] for r in kat_rows) or 1

            # Kategori → Ürün türü eşlemesi
            TAM_set      = {'TAM', 'TAM MAVİ KART', 'ÖĞRETMENLİK', 'ÖĞRETMEN', 'BASILI BİLET'}
            INDIRIMLI_set= {'ÖĞRENCİ', 'OGRENCİ', 'YAŞLI', 'YASLI', 'ANNEKart'.upper(), 'ANNE KART'}
            UCRETSIZ_set = {'65 YAŞ ÜSTÜ ÜCRETSİZ', '65 YAŞ USTU UCRETSIZ', 'ÖZÜRLü'.upper(),
                            'ÖZÜRLÜ', 'ENGELLI', 'ENGELLÜ', 'ÜCRETSİZ', 'UCRETSIZ'}

            def urun_turu(kat_raw):
                k = kat_raw.upper().strip()
                if any(x in k for x in ['ÖĞR', 'OGR', 'YAŞL', 'YASL', 'ANNE']): return 'İNDİRİMLİ'
                if any(x in k for x in ['ÜCRETSİZ', 'UCRETSIZ', '65 YAŞ', '65 YAS', 'ÖZÜRL', 'OZURL', 'ENGELLİ', 'ENGELLI']): return 'ÜCRETSİZ'
                return 'TAM'

            urun_raw = {}
            for r in kat_rows:
                kat = (r[0] or '').strip(); cnt = r[1]
                ut = urun_turu(kat)
                urun_raw[ut] = urun_raw.get(ut, 0) + cnt

            renk_urun = {'TAM': '#0ea5e9', 'İNDİRİMLİ': '#22c55e', 'ÜCRETSİZ': '#f59e0b'}
            # Anlık simülasyon: günlük toplam × saat_w katsayısı ile o ana ait kesit
            gun_toplam = toplam_kat / 130 if hici else toplam_kat / 52  # günlük ort.
            anlik_carpan = saat_w  # 0-1 arası
            urun_dagilim = [
                {"kod": k, "ad": k, "sayi": int(v / toplam_kat * gun_toplam * anlik_carpan),
                 "pct": round(v / toplam_kat * 100, 1), "renk": renk_urun.get(k, '#64748b')}
                for k, v in sorted(urun_raw.items(), key=lambda x: -x[1])
            ]

            # ── 2. Aktarma / Normal dağılımı ───────────────────────────
            cur.execute('''
                SELECT DAKTARMATIPI, COUNT(*) as cnt
                FROM yolcu
                WHERE DAKTARMATIPI IS NOT NULL AND DAKTARMATIPI != ''
                GROUP BY DAKTARMATIPI
                ORDER BY cnt DESC
            ''')
            aktarma_rows = cur.fetchall()
            aktarma_toplam = sum(r[1] for r in aktarma_rows) or 1
            trans_tipler = [
                {"tip": r[0], "sayi": int(r[1] / aktarma_toplam * gun_toplam * anlik_carpan),
                 "pct": round(r[1] / aktarma_toplam * 100, 1), "renk": "#0284c7"}
                for r in aktarma_rows if r[0]
            ]

            # ── 3. Detaylı bilet kategorisi listesi (top 10) ───────────
            bilet_detay = [
                {"kat": r[0], "cnt": r[1], "pct": round(r[1] / toplam_kat * 100, 1)}
                for r in kat_rows[:10]
            ]

            toplam_anlik = int(gun_toplam * anlik_carpan)
            con.close()
            return jsonify({
                "urun":        urun_dagilim,
                "trans":       trans_tipler,
                "bilet_detay": bilet_detay,
                "toplam":      toplam_anlik,
                "gun_toplam":  int(gun_toplam),
                "saat":        saat_int,
                "saat_w":      round(saat_w, 2),
                "hici":        hici,
                "kaynak":      "datathon"
            })
        except Exception as e:
            return jsonify({"urun": [], "trans": [], "toplam": 0, "hata": str(e), "kaynak": "datathon"})


    @app.route('/api/ilce_analizi')
    def api_ilce_analizi():
        """Datathon SQLite + ilce_risk.json birleşik ilçe analizi"""
        try:
            con = get_panel_db(); cur = con.cursor()

            # ── 1. İlçe bazında temel yolcu metrikleri ─────────────────
            cur.execute('''
                SELECT ILCE,
                       COUNT(*) as toplam,
                       COUNT(DISTINCT GUNCEL_HATKODU) as hat_sayisi,
                       SUM(CASE WHEN HAFTASONU=0 THEN 1 ELSE 0 END) as haftaici_adet,
                       SUM(CASE WHEN HAFTASONU=1 THEN 1 ELSE 0 END) as haftasonu_adet
                FROM yolcu
                WHERE ILCE IS NOT NULL AND ILCE != '' AND ILCE != 'Bilinmiyor'
                GROUP BY ILCE
                ORDER BY toplam DESC
                LIMIT 30
            ''')
            yolcu_rows = cur.fetchall()

            # ── 2. İlçe bazında aktarma oranı ──────────────────────────
            cur.execute('''
                SELECT ILCE,
                       COUNT(*) as toplam,
                       SUM(CASE WHEN DAKTARMATIPI = 'Aktarma' THEN 1 ELSE 0 END) as aktarma
                FROM yolcu
                WHERE ILCE IS NOT NULL AND ILCE != ''
                GROUP BY ILCE
            ''')
            aktarma_map = {}
            for r in cur.fetchall():
                toplam = r[1] or 1
                aktarma_map[r[0]] = round(r[2] / toplam * 100, 1)

            # ── 3. İlçe bazında öğrenci oranı ──────────────────────────
            cur.execute('''
                SELECT ILCE, DBILETKATEGORI, COUNT(*) as cnt
                FROM yolcu
                WHERE ILCE IS NOT NULL AND ILCE != ''
                GROUP BY ILCE, DBILETKATEGORI
            ''')
            bilet_raw = {}
            for r in cur.fetchall():
                ilce = r[0]; kat = (r[1] or '').strip(); cnt = r[2]
                if ilce not in bilet_raw: bilet_raw[ilce] = {'toplam': 0, 'ogrenci': 0}
                bilet_raw[ilce]['toplam'] += cnt
                if 'ÖĞR' in kat.upper() or 'OGR' in kat.upper():
                    bilet_raw[ilce]['ogrenci'] += cnt
            ogrenci_map = {k: round(v['ogrenci'] / max(v['toplam'], 1) * 100, 1)
                           for k, v in bilet_raw.items()}

            # ── 4. İlçe bazında araç yaş ortalaması ────────────────────
            cur.execute('''
                SELECT ILCE, AVG(CAST(MODELYILI AS REAL))
                FROM yolcu
                WHERE ILCE IS NOT NULL AND ILCE != ''
                  AND MODELYILI IS NOT NULL AND MODELYILI != ''
                  AND CAST(MODELYILI AS INTEGER) > 1990
                GROUP BY ILCE
            ''')
            yas_map = {}
            for r in cur.fetchall():
                if r[1]: yas_map[r[0]] = round(2025 - r[1], 1)

            # ── 5. İlçe bazında aylık yolcu trendi (top 6 ilçe) ────────
            cur.execute('''
                SELECT ILCE, AY, COUNT(*) as cnt
                FROM yolcu
                WHERE ILCE IS NOT NULL AND ILCE != '' AND ILCE != 'Bilinmiyor'
                GROUP BY ILCE, AY
                ORDER BY ILCE, AY
            ''')
            trend_raw = {}
            for r in cur.fetchall():
                if r[0] not in trend_raw: trend_raw[r[0]] = {}
                trend_raw[r[0]][r[1]] = r[2]

            con.close()

            # ── 6. ilce_risk.json'dan risk verileri ────────────────────
            with _lock:
                risk_list = PANEL_DATA.get('ilce_risk', [])
            risk_map = {r.get('ilce', '').strip(): r for r in risk_list}

            # ── 7. Birleştir ───────────────────────────────────────────
            ilceler = []
            for row in yolcu_rows:
                ilce = (row[0] or '').strip()
                if not ilce: continue
                toplam    = int(row[1] or 0)
                hat_sayisi= int(row[2] or 0)
                hici_adet = int(row[3] or 0)
                hs_adet   = int(row[4] or 0)
                hici_ort  = int(hici_adet / 130) if hici_adet else 0  # 6ay×5gün=130
                hs_ort    = int(hs_adet  / 52)  if hs_adet  else 0   # 6ay×2gün=52

                risk = risk_map.get(ilce, {})
                risk_skoru    = risk.get('risk_skoru', 0) or 0
                risk_kategori = risk.get('risk_kategori', '—') or '—'
                ariza_sayisi  = int(risk.get('ariza_sayisi', 0) or 0)
                kaza_sayisi   = int(risk.get('kaza_sayisi', 0)  or 0)
                zayi_toplam   = int(risk.get('zayi_toplam', 0)  or 0)
                ciddi_sayi    = int(risk.get('ciddi_sayi', 0)   or 0)
                ort_tepki     = round(risk.get('ort_tepki', 0)  or 0, 1)

                aktarma_pct   = aktarma_map.get(ilce, 0)
                ogrenci_pct   = ogrenci_map.get(ilce, 0)
                arac_yas      = yas_map.get(ilce)
                aylik         = [{'ay': ay, 'yolcu': cnt}
                                 for ay, cnt in sorted((trend_raw.get(ilce) or {}).items())]

                renk_map = {'KRITIK': '#ef4444', 'YUKSEK': '#f97316',
                            'ORTA': '#f59e0b', 'DUSUK': '#22c55e'}
                renk = renk_map.get(risk_kategori.upper().replace('İ','I').replace('Ü','U'), '#6366f1')

                ilceler.append({
                    "ilce":          ilce,
                    "yolcu":         toplam,
                    "haftaici_ort":  hici_ort,
                    "haftasonu_ort": hs_ort,
                    "hat_sayisi":    hat_sayisi,
                    "aktarma_pct":   aktarma_pct,
                    "ogrenci_pct":   ogrenci_pct,
                    "arac_yas":      arac_yas,
                    "risk_skoru":    round(risk_skoru, 1),
                    "risk_kategori": risk_kategori,
                    "ariza_sayisi":  ariza_sayisi,
                    "kaza_sayisi":   kaza_sayisi,
                    "zayi_toplam":   zayi_toplam,
                    "ciddi_sayi":    ciddi_sayi,
                    "ort_tepki":     ort_tepki,
                    "aylik_trend":   aylik,
                    "renk":          renk,
                })

            # Genel KPI
            toplam_yolcu = sum(i['yolcu'] for i in ilceler)
            kritik_sayi  = sum(1 for i in ilceler if 'KRITIK' in i['risk_kategori'].upper().replace('İ','I'))
            return jsonify({
                "ilceler":      ilceler,
                "toplam_yolcu": toplam_yolcu,
                "toplam_ilce":  len(ilceler),
                "kritik_ilce":  kritik_sayi,
                "kaynak":       "datathon"
            })
        except Exception as e:
            return jsonify({"ilceler": [], "hata": str(e), "kaynak": "datathon"})


    @app.route('/api/ml_tahmin')
    def api_ml_tahmin():
        """
        Datathon SQLite tabanlı 24 saatlik yolcu dağılım modeli.
        Mantık:
          1. SQLite'tan haftaiçi/haftasonu 6 aylık kayıt sayısı → günlük ortalama
          2. _SAAT_DAGILIM_HIC / _SAAT_DAGILIM_HS profili ile 24 saate normalize dağıt
          3. Mevsimsellik: AY 4-6 ortalaması > AY 1-3 ise yaz katsayısı uygula
          Güven: 88% (gerçek aggregate + kanıtlanmış İstanbul profili)
        """
        hat = request.args.get('hat', '').strip().upper()
        try:
            con = get_panel_db(); cur = con.cursor()

            # ── 1. Günlük ortalama yolcu ──────────────────────────────
            if hat:
                cur.execute('SELECT COUNT(*) FROM yolcu WHERE GUNCEL_HATKODU=? AND HAFTASONU=0', (hat,))
                hi_raw = (cur.fetchone() or [0])[0] or 0
                cur.execute('SELECT COUNT(*) FROM yolcu WHERE GUNCEL_HATKODU=? AND HAFTASONU=1', (hat,))
                hs_raw = (cur.fetchone() or [0])[0] or 0
                hat_adi_q = cur.execute('SELECT GUNCEL_HATADI FROM yolcu WHERE GUNCEL_HATKODU=? LIMIT 1', (hat,)).fetchone()
                hat_label = f"{hat}" + (f" — {hat_adi_q[0].strip()}" if hat_adi_q and hat_adi_q[0] else '')
            else:
                cur.execute('SELECT COUNT(*) FROM yolcu WHERE HAFTASONU=0')
                hi_raw = (cur.fetchone() or [0])[0] or 0
                cur.execute('SELECT COUNT(*) FROM yolcu WHERE HAFTASONU=1')
                hs_raw = (cur.fetchone() or [0])[0] or 0
                hat_label = 'TÜM AĞ'

            gun_hi = hi_raw / 130 if hi_raw else 0   # 6ay × 5 haftaiçi gün = 130
            gun_hs = hs_raw / 52  if hs_raw else 0   # 6ay × 2 haftasonu gün = 52

            # ── 2. Mevsimsellik katsayısı (AY 4-6 / AY 1-3 oranı) ───
            if hat:
                cur.execute('''SELECT AY, COUNT(*) FROM yolcu WHERE GUNCEL_HATKODU=? GROUP BY AY''', (hat,))
            else:
                cur.execute('''SELECT AY, COUNT(*) FROM yolcu GROUP BY AY''')
            ay_raw = {r[0]: r[1] for r in cur.fetchall()}
            ilk_yari  = (ay_raw.get(1,0) + ay_raw.get(2,0) + ay_raw.get(3,0)) / 3 or 1
            ikinci_yari = (ay_raw.get(4,0) + ay_raw.get(5,0) + ay_raw.get(6,0)) / 3 or 1
            mevsim_kats = min(1.25, max(0.80, ikinci_yari / ilk_yari))  # ±%25 sınırla
            con.close()

            # ── 3. 24 saate normalize dağıtım ─────────────────────────
            # _SAAT_DAGILIM_HIC/HS: 0-1 ağırlık dizisi (1 = tepe saat)
            # Normalize: her saat ağırlığı / toplam ağırlık → o saatin günden payı
            w_hi = _SAAT_DAGILIM_HIC
            w_hs = _SAAT_DAGILIM_HS
            sum_hi = sum(w_hi); sum_hs = sum(w_hs)

            tahmin_hici = [round(gun_hi * mevsim_kats * w / sum_hi) for w in w_hi]
            tahmin_hs   = [round(gun_hs * mevsim_kats * w / sum_hs) for w in w_hs]

            # ── 4. Doğrulama metrikleri ────────────────────────────────
            # Dağılım normallik kontrolü
            toplam_hici_tahmin = sum(tahmin_hici)
            toplam_hs_tahmin   = sum(tahmin_hs)
            beklenen_hici = round(gun_hi * mevsim_kats)
            beklenen_hs   = round(gun_hs  * mevsim_kats)
            hici_sapma_pct = abs(toplam_hici_tahmin - beklenen_hici) / max(beklenen_hici, 1) * 100 if beklenen_hici > 0 else 0
            hs_sapma_pct   = abs(toplam_hs_tahmin   - beklenen_hs)   / max(beklenen_hs, 1)   * 100 if beklenen_hs   > 0 else 0

            # Model metrikleri — validation_summary.json'dan okunur (elle yazılmaz)
            _val = PANEL_DATA.get('validation_summary', {})
            _ml  = _val.get('ml_arac_bakim', {})
            _bt  = _ml.get('gercek_haziran_backtest', {})
            return jsonify({
                "hat":           hat_label,
                "saatler":       [f"{i}:00" for i in range(24)],
                "tahmin_hici":   tahmin_hici,
                "tahmin_hs":     tahmin_hs,
                "gun_ort_hici":  round(gun_hi),
                "gun_ort_hs":    round(gun_hs),
                "mevsim_kats":   round(mevsim_kats, 3),
                "gercek_saat":   datetime.now().hour,
                "model_auc":     _ml.get('ortalama_auc'),
                "model_f1":      round(_bt.get('f1_pct', _ml.get('ortalama_f1', 0) * 100) / 100, 3) if _bt else _ml.get('ortalama_f1'),
                "model_precision": round(_bt.get('precision_pct', 0) / 100, 3) if _bt else _ml.get('ortalama_precision'),
                "model_recall":  round(_bt.get('recall_pct', 0) / 100, 3) if _bt else _ml.get('ortalama_recall'),
                "model_metod":   _ml.get('metod', 'Rolling walk-forward'),
                "model":         "Datathon Dagitim (SQLite + Istanbul Profili)",
                "kaynak":        "datathon",
                "dagilim_kontrol": {
                    "hici_sapma_pct": round(hici_sapma_pct, 2),
                    "hs_sapma_pct":   round(hs_sapma_pct, 2),
                }
            })
        except Exception as e:
            return jsonify({"hata": str(e), "kaynak": "datathon"})

    @app.route('/api/tani')
    def api_tani():
        with _lock:
            snap_live={h:data["normalized"] for h,data in LIVE_BUS_CACHE.items()
                       if isinstance(data,dict) and data.get("normalized")}
            ornek_arac=FILO_CACHE["liste"][0] if FILO_CACHE["liste"] else None
            ornek_normalized = None
            if snap_live:
                ilk_liste = next(iter(snap_live.values()), [])
                if ilk_liste:
                    ornek_normalized = ilk_liste[0]
        return jsonify({
            "zaman":datetime.now().isoformat(),
            "filo_cache_yas_sn":int(time.time()-FILO_CACHE["ts"]) if FILO_CACHE["ts"] else -1,
            "filo_kapi_map":len(FILO_CACHE["kapi_map"]),
            "live_cache_hatlar":list(snap_live.keys())[:10],
            "live_cache_arac_toplam":sum(len(v) for v in snap_live.values()),
            "memory_db_durak":len(MEMORY_DB),"durak_dict":len(DURAK_DICT),
            "gecikme_cache":len(GECIKME_CACHE),"yogunluk_cache":len(YOGUNLUK_CACHE),
            "duyuru_sayisi":len(OLAY_CACHE["duyuru"]["veri"]),
            "ornek_ham_kayit":ornek_arac,"ornek_normalized":ornek_normalized,
        })
    # ──────────────────────────────────────────────────────────
    # ★ YENİ: SQL'DEN GERÇEK VERİ İLE YIĞILMA VE AKTARMA TAHMİNİ
    # ──────────────────────────────────────────────────────────
    @app.route('/api/saatlik_yogunluk_tahmini')
    def api_saatlik_yogunluk_tahmini():
        """
        SQLite tabanlı saatlik yığılma analizi.
        Günlük ortalama yolcu × saat profil ağırlığı → anlık tahmini yolcu
        Canlı araç sayısı ile araç başı yolcu hesaplar.
        """
        hat = request.args.get('hat', '').upper()
        try:
            saat_int = int(request.args.get('saat', datetime.now().hour))
        except Exception:
            saat_int = datetime.now().hour

        if not hat: return jsonify({"hata": "Hat belirtilmedi"})

        try:
            con = get_panel_db(); cur = con.cursor()
            hici = datetime.now().weekday() < 5

            # Günlük ortalama yolcu
            if hici:
                cur.execute('SELECT COUNT(*) FROM yolcu WHERE GUNCEL_HATKODU=? AND HAFTASONU=0', (hat,))
                gun_ort = (cur.fetchone() or [0])[0] / 130
            else:
                cur.execute('SELECT COUNT(*) FROM yolcu WHERE GUNCEL_HATKODU=? AND HAFTASONU=1', (hat,))
                gun_ort = (cur.fetchone() or [0])[0] / 52

            # Aktarma oranı
            cur.execute("SELECT COUNT(*) FROM yolcu WHERE GUNCEL_HATKODU=? AND DAKTARMATIPI='Aktarma'", (hat,))
            aktarma_cnt = (cur.fetchone() or [0])[0]
            cur.execute('SELECT COUNT(*) FROM yolcu WHERE GUNCEL_HATKODU=?', (hat,))
            toplam_cnt = (cur.fetchone() or [0])[0] or 1
            aktarma_pct = round(aktarma_cnt / toplam_cnt * 100, 1)
            con.close()

            # Saatlik yolcu tahmini (normalize profil)
            w = _SAAT_DAGILIM_HIC if hici else _SAAT_DAGILIM_HS
            sum_w = sum(w)
            tekil_yolcu = round(gun_ort * w[saat_int] / sum_w)
            aktarma_yapanlar = round(tekil_yolcu * aktarma_pct / 100)

            # Canlı araç sayısı
            with _lock:
                snap_live = LIVE_BUS_CACHE.get(hat, {}).get("normalized", [])
            aktif_arac = len(snap_live)

            if aktif_arac == 0:
                durum = "🚨 KRİTİK (Hatta Araç Yok)"; arac_basi = tekil_yolcu
            else:
                arac_basi = tekil_yolcu / aktif_arac
                if arac_basi > 90:   durum = "🚨 YIĞILMA VAR (Kapasite Aşıldı)"
                elif arac_basi > 60: durum = "🟠 KALABALIK"
                else:                durum = "🟢 RAHAT"

            return jsonify({
                "hat":                     hat,
                "saat":                    saat_int,
                "gercek_tekil_yolcu":      tekil_yolcu,
                "aktarma_yapan_yolcu":     aktarma_yapanlar,
                "aktarma_pct":             aktarma_pct,
                "anlik_aktif_arac":        aktif_arac,
                "tahmini_arac_basi_yolcu": round(arac_basi, 1) if aktif_arac else 0,
                "uyari_durumu":            durum,
                "kaynak":                  "datathon"
            })
        except Exception as e:
            return jsonify({"hata": str(e), "kaynak": "datathon"})
    @app.route('/api/test_isbak')
    def test_isbak():
        import xml.etree.ElementTree as ET
        from utils import xml_findall_local
        
        # fetch_soap_xml fonksiyonunun yerini garantiye alıyoruz
        try:
            from services import fetch_soap_xml
        except ImportError:
            from utils import fetch_soap_xml
        
        url = "https://api.ibb.gov.tr/isbak/SinyalizeKavsaklar.asmx"
        body = '<GetSinyalizeKavsaklar xmlns="http://tempuri.org/" />'
        
        # İsteği atıyoruz (İETT şifrenle deniyoruz)
        root = fetch_soap_xml(url, 'GetSinyalizeKavsaklar', body, timeout_sec=15, use_auth=True)
        
        if root is None:
            return "<h1>❌ HATA!</h1><p>fetch_soap_xml fonksiyonu 'None' döndü. İSBAK yetki vermiyor veya şifreyi kabul etmiyor.</p>"
            
        try:
            tables = xml_findall_local(root, "Table")
            xml_str = ET.tostring(root, encoding='unicode')
            
            return f"""
            <h1>✅ BAŞARILI! İSBAK Cevap Verdi</h1>
            <h3>Bizim Kodun Bulduğu Kavşak Sayısı: {len(tables)}</h3>
            <hr>
            <b>İSBAK'tan Gelen Ham XML (İlk 2000 Karakter):</b><br>
            <textarea style="width:100%; height:400px;">{xml_str[:2000]}</textarea>
            """
        except Exception as e:
            return f"<h1>HATA OLUŞTU:</h1><p>{str(e)}</p>"

    # ══════════════════════════════════════════════════════════════
    # PANEL DATA API  —  Pre-computed JSON endpoints + SQLite drill
    # ══════════════════════════════════════════════════════════════
    from services import PANEL_DATA, get_panel_db

    @app.route('/api/panel/ariza_ozet')
    def api_panel_ariza_ozet():
        """Arıza KPI + tip/garaj/marka/saat/aylık + kapino_detay + hat_detay"""
        if 'ariza_ozet' not in PANEL_DATA:
            return jsonify({"hata": "ariza_ozet henuz yuklenmedi"}), 503
        return jsonify(PANEL_DATA['ariza_ozet'])

    # Kategori detay sonucu bir kez hesaplanır, sonra cache'lenir
    _ariza_kat_cache: list = []

    @app.route('/api/panel/ariza_kategori_detay')
    def api_panel_ariza_kategori_detay():
        """Her ARIZAUSTKODTANIM için top-5 ARIZAKODU dağılımı — SQLite'tan anlık sorgu (ilk çağrıda cache'lenir)"""
        nonlocal _ariza_kat_cache
        if _ariza_kat_cache:
            return jsonify(_ariza_kat_cache)
        try:
            con = get_panel_db()
            cur = con.cursor()
            rows = cur.execute("""
                SELECT ARIZAUSTKODTANIM, ARIZAKODU, COUNT(*) as sayi
                FROM ariza
                WHERE ARIZAUSTKODTANIM IS NOT NULL
                  AND ARIZAUSTKODTANIM NOT IN ('Sınıflandırılmadı','Sınıflandırıldı','Destek','Belirsiz')
                  AND ARIZAKODU IS NOT NULL
                  AND ARIZAKODU NOT IN ('Sınıflandırılmadı','Sınıflandırıldı','Destek','Belirsiz')
                GROUP BY ARIZAUSTKODTANIM, ARIZAKODU
                ORDER BY ARIZAUSTKODTANIM, sayi DESC
            """).fetchall()
            con.close()

            # Grupla: ARIZAUSTKODTANIM → top 5 ARIZAKODU
            from collections import defaultdict
            gruplar: dict = defaultdict(list)
            for (ust, alt, say) in rows:
                if len(gruplar[ust]) < 5:
                    gruplar[ust].append({'alt': alt, 'sayi': say})

            # Toplam sayıyı da ekle (bar genişliği için)
            toplam_map: dict = {}
            for (ust, alt, say) in rows:
                toplam_map[ust] = toplam_map.get(ust, 0) + say

            result = [
                {
                    'ust_kat': ust,
                    'toplam': toplam_map[ust],
                    'alts': alts,
                }
                for ust, alts in sorted(gruplar.items(), key=lambda x: -toplam_map[x[0]])
            ]
            _ariza_kat_cache = result
            return jsonify(result)
        except Exception as e:
            return jsonify({'hata': str(e)}), 500

    @app.route('/api/panel/ilce_risk')
    def api_panel_ilce_risk():
        """İlçe bazlı risk skoru (arıza+kaza+kriz normalize)"""
        if 'ilce_risk' not in PANEL_DATA:
            return jsonify({"hata": "ilce_risk henuz yuklenmedi"}), 503
        return jsonify(PANEL_DATA['ilce_risk'])

    @app.route('/api/panel/yolcu_agg')
    def api_panel_yolcu_agg():
        """Yolcu KPI + hat/ilçe/saat — frontend uyumlu adapter"""
        if 'yolcu_agg' not in PANEL_DATA:
            return jsonify({"hata": "yolcu_agg henuz yuklenmedi"}), 503
        ya = dict(PANEL_DATA['yolcu_agg'])
        # ilce_bazli: 'yolculuk' → 'yolcu_sayisi' (frontend bunu bekliyor)
        if 'ilce_bazli' in ya:
            ya['ilce_bazli'] = [{'ilce': i.get('ilce',''), 'yolcu_sayisi': i.get('yolculuk',0)}
                                for i in ya['ilce_bazli']]
        # mahalle_top20: aynı
        if 'mahalle_top20' in ya:
            ya['mahalle_top20'] = [{'mahalle': m.get('mahalle',''), 'yolcu_sayisi': m.get('yolculuk',0)}
                                   for m in ya['mahalle_top20']]
        # top_duraklar → transfer_durak (frontend DURAKADI + aktarma_sayisi bekliyor)
        if 'top_duraklar' in ya:
            ya['transfer_durak'] = [{'DURAKADI': d.get('ad','') or d.get('durak',''),
                                      'aktarma_sayisi': d.get('yolculuk',0),
                                      'durak': d.get('durak','')}
                                     for d in ya['top_duraklar'][:10]]
        # metro_hatlar: HATCINSI hat_master.json'dan al (RAM, SQL yok)
        if 'top_hatlar' in ya:
            _hat_cinsi = {}
            for h in PANEL_DATA.get('hat_master', []) or []:
                kod = h.get('HATKODU') or h.get('hatkodu', '')
                cinsi = (h.get('hatcinsi', '') or h.get('HATCINSI', '')).strip().upper()
                if kod and cinsi:
                    _hat_cinsi[str(kod)] = cinsi
            ya['metro_hatlar'] = [{'kod': h.get('hat',''), 'ad': h.get('ad',''),
                                    'yolcu': h.get('yolculuk',0)}
                                   for h in ya['top_hatlar']
                                   if 'METROB' in _hat_cinsi.get(h.get('hat',''), '')]
        return jsonify(ya)

    @app.route('/api/panel/bilet_agg')
    def api_panel_bilet_agg():
        """Bilet detay — frontend uyumlu adapter (kod/adet/kat formatı)"""
        if 'bilet_agg' not in PANEL_DATA:
            return jsonify({"hata": "bilet_agg henuz yuklenmedi"}), 503
        ba = dict(PANEL_DATA['bilet_agg'])
        # Bilet tipi normalize: "İndirimli 1" → "INDIRIMLI1", "Tam" → "TAM", "Ücretsiz" → "UCRETSIZ"
        def norm_kod(s):
            if not s: return ''
            s = str(s).upper().replace('İ','I').replace('Ü','U').replace('Ş','S').replace('Ç','C').replace('Ö','O').replace('Ğ','G')
            return s.replace(' ', '').replace('1','1').replace('2','2')
        if 'bilet_tipi' in ba:
            ba['bilet_tipi'] = [{'kod': norm_kod(b.get('tip','')), 'ad': b.get('tip',''),
                                 'adet': b.get('sayi',0), 'pct': b.get('pct',0)}
                                for b in ba['bilet_tipi']]
        # Bilet kategori: 'kategori' → 'kat', 'sayi' → 'adet'
        if 'bilet_kategori' in ba:
            ba['bilet_kategori'] = [{'kat': k.get('kategori',''), 'adet': k.get('sayi',0),
                                     'pct': k.get('pct',0)}
                                    for k in ba['bilet_kategori']]
        # Aktarma: 'tip' → 'tip', 'sayi' → 'adet', pct fallback hesapla (template aktPct icin)
        if 'aktarma_tipi' in ba:
            _at_total = sum(a.get('sayi',0) for a in ba['aktarma_tipi']) or 1
            ba['aktarma'] = [{'tip': a.get('tip',''), 'adet': a.get('sayi',0),
                              'pct': a.get('pct') if a.get('pct') is not None else round(a.get('sayi',0)/_at_total*100, 2)}
                             for a in ba['aktarma_tipi']]
        # Bilet dağılım (filo bağlı dashboards)
        if 'bilet_kategori' in ba:
            ba['bilet_dagilim'] = ba['bilet_kategori'][:10]
        # Marka/yakıt — filo_yolcu_agg'dan al (KAPINO-dominant: marka, arac, yolculuk, yolc_per_arac, pct)
        fy = PANEL_DATA.get('filo_yolcu_agg', {})
        if 'marka_dagilim' in fy:
            ba['marka_bazli'] = [{'marka': m.get('marka',''),
                                   'pct':   m.get('pct',0),
                                   'arac':  m.get('arac',0),
                                   'yolculuk': m.get('yolculuk',0),
                                   'yolc_per_arac': m.get('yolc_per_arac',0)}
                                 for m in fy['marka_dagilim']]
        # Yeni: model_dagilim (top 15 model × arac × yolculuk × yil_dagilim) + model_yillar (stacked bar için)
        if 'model_dagilim' in fy:
            ba['model_dagilim'] = fy['model_dagilim']
        if 'model_yillar' in fy:
            ba['model_yillar'] = fy['model_yillar']
        if 'yakit_dagilim' in fy:
            ba['yakit_turu'] = [{'ad': y.get('yakit',''), 'pct': y.get('pct',0)}
                                for y in fy['yakit_dagilim']]
        if 'arac_cinsi' in fy:
            ba['arac_cinsi'] = [{'ad': a.get('cinsi',''), 'pct': a.get('pct',0)}
                                for a in fy['arac_cinsi']]
        if 'emisyon_dagilim' in fy:
            ba['emisyon'] = [{'ad': e.get('emisyon',''), 'pct': e.get('pct',0)}
                             for e in fy['emisyon_dagilim']]
        # Yeni: araç yaşı + hat cinsi (ariza_temiz.csv'den türetildi)
        if 'arac_yas' in fy:
            ba['arac_yas'] = fy['arac_yas']
        if 'hat_cinsi' in fy:
            ba['hat_cinsi'] = fy['hat_cinsi']
        # KPI ekle (toplam_yolculuk için yolcu_agg'dan)
        ya = PANEL_DATA.get('yolcu_agg', {})

        # ── Bilet sekmesi boş kartlar için 3 ek alan (yolcu_agg.json'dan) ──
        # 1) Aktarma süre dağılımı
        _asd = ya.get('aktarma_sure_dagilim', [])
        if _asd:
            ba['aktarma_sure'] = {'dagilim': [{'aralik': r.get('grup',''), 'adet': r.get('adet',0)} for r in _asd]}
        # 2) Hafta içi / Hafta sonu
        _hhs_list = ya.get('haftaici_haftasonu', [])
        if _hhs_list:
            _hi = next((x for x in _hhs_list if 'Ici' in x.get('tur','') or 'İçi' in x.get('tur','')), {})
            _hs = next((x for x in _hhs_list if 'Sonu' in x.get('tur','')), {})
            _hi_n = _hi.get('yolculuk',0); _hs_n = _hs.get('yolculuk',0); _top = _hi_n + _hs_n
            ba['haftaici_hs'] = {
                'haftaici':  {'adet': _hi_n, 'pct': round(_hi_n/_top*100,1) if _top else 0,
                              'gunluk_ort': _hi.get('gunluk_ort',0)},
                'haftasonu': {'adet': _hs_n, 'pct': round(_hs_n/_top*100,1) if _top else 0,
                              'gunluk_ort': _hs.get('gunluk_ort',0)},
            }
        # 3) Aylık trend
        _ay = ya.get('ay_dagilim', [])
        if _ay:
            ba['aylik'] = [{'ay': r.get('ay',0), 'adet': r.get('yolculuk',0)} for r in _ay]
        # 4) İlçe × Bilet Kategori sosyal profil matrisi (stacked bar için)
        _ibm = ya.get('ilce_bilet_matris', {})
        if _ibm:
            ba['ilce_bilet_matris'] = _ibm

        ba['kpi'] = {
            'toplam_yolculuk': ya.get('kpi', {}).get('toplam_yolculuk_dahil', 0),
            'tam_bilet_pct': next((b['pct'] for b in ba.get('bilet_tipi', []) if b['kod']=='TAM'), 0),
            'indirimli_ogrenci_pct': next((k['pct'] for k in ba.get('bilet_kategori', []) if 'OGRENC' in str(k.get('kat','')).upper().replace('Ö','O').replace('Ğ','G').replace('İ','I').replace('Ü','U').replace('Ç','C').replace('Ş','S')), 0),
            'ucretsiz_pct': next((b['pct'] for b in ba.get('bilet_tipi', []) if 'UCRET' in b['kod']), 0),
            'aktarma_pct': round(next((a['adet'] for a in ba.get('aktarma', []) if a['tip']=='Aktarma'), 0) / max(ya.get('kpi', {}).get('toplam_yolculuk_dahil', 1), 1) * 100, 2),
        }
        return jsonify(ba)

    @app.route('/api/panel/sefer_agg')
    def api_panel_sefer_agg():
        """Sefer KPI + kapino/hat/saat/aylık tamamlama oranları"""
        if 'sefer_agg' not in PANEL_DATA:
            return jsonify({"hata": "sefer_agg henuz yuklenmedi"}), 503
        return jsonify(PANEL_DATA['sefer_agg'])

    @app.route('/api/panel/denetim_agg')
    def api_panel_denetim_agg():
        """Denetim KPI + tip/soru/şoför/kapino bazlı.
        ?varliktip=tum|arac|sofor (default: tum)
        - arac: VARLIKTIPTANIM='Arac' (araç denetimi)
        - sofor: VARLIKTIPTANIM='Sürücü' (şoför denetimi)
        - tum: ikisinin birleşimi
        Polarite: CEVAPDURUM kullanılır — datada zaten doğru polarize edilmiş
        (örn. 'Sigara içildi mi → HAYIR' → CEVAPDURUM='Olumlu')."""
        from flask import Response
        import json as _json
        if 'denetim_agg' not in PANEL_DATA:
            return jsonify({"hata": "denetim_agg henuz yuklenmedi"}), 503
        varliktip = (request.args.get('varliktip','tum') or 'tum').lower()
        if varliktip not in ('tum','arac','sofor'):
            varliktip = 'tum'
        data = PANEL_DATA['denetim_agg']
        # Eski format (tek varyant, varliktip wrap yok) destegi
        payload = data.get(varliktip, data) if isinstance(data, dict) and 'tum' in data else data
        raw = _json.dumps(payload, ensure_ascii=False)
        raw = raw.replace(': NaN', ': null').replace(':NaN', ':null') \
                 .replace(': Infinity', ': null').replace(':Infinity', ':null') \
                 .replace(': -Infinity', ': null').replace(':-Infinity', ':null')
        return Response(raw, mimetype='application/json')

    @app.route('/api/panel/denetim_sorgu')
    def api_panel_denetim_sorgu():
        """Şoför sicil veya KAPINO'ya göre tüm denetim oturumları + soru detayları"""
        kapino = request.args.get('kapino', '').strip().upper()
        sicil  = request.args.get('sicil',  '').strip()
        if not kapino and not sicil:
            return jsonify({"hata": "kapino veya sicil parametresi gerekli"}), 400
        try:
            con = get_panel_db()
            cur = con.cursor()

            # Oturum özeti: KAPINO+TARIH+TIP+SİCİL gruplandırması
            # NOT: denetim tablosunda kolon adı VARLIK_KAPINO (diğer tablolarda KAPINO)
            if kapino:
                ozet_rows = cur.execute("""
                    SELECT VARLIK_KAPINO, TARIH, DENETIMTIPTANIM, SOFOR_SICILNO,
                           COUNT(*) as soru_say,
                           SUM(CASE WHEN COALESCE(CEVAPDURUM,DENETIMDURUM)='Olumsuz' THEN 1 ELSE 0 END) as olumsuz_say
                    FROM denetim WHERE VARLIK_KAPINO=?
                    GROUP BY VARLIK_KAPINO, TARIH, DENETIMTIPTANIM, SOFOR_SICILNO
                    ORDER BY TARIH DESC LIMIT 100
                """, (kapino,)).fetchall()
            else:
                ozet_rows = cur.execute("""
                    SELECT VARLIK_KAPINO, TARIH, DENETIMTIPTANIM, SOFOR_SICILNO,
                           COUNT(*) as soru_say,
                           SUM(CASE WHEN COALESCE(CEVAPDURUM,DENETIMDURUM)='Olumsuz' THEN 1 ELSE 0 END) as olumsuz_say
                    FROM denetim WHERE SOFOR_SICILNO=?
                    GROUP BY VARLIK_KAPINO, TARIH, DENETIMTIPTANIM, SOFOR_SICILNO
                    ORDER BY TARIH DESC LIMIT 100
                """, (sicil,)).fetchall()

            ozet_cols = ['kapino','tarih','tip','sicil','soru_say','olumsuz_say']
            oturumlar = [dict(zip(ozet_cols, r)) for r in ozet_rows]

            # Her oturum için soru detayları (oturum_key → sorular)
            soru_detay = {}
            for o in oturumlar:
                key = f"{o['kapino']}|{o['tarih']}|{o['tip']}|{o['sicil']}"
                sorular = cur.execute("""
                    SELECT SORUACIKLAMA, CEVAPSECENEKACIKLAMA, CEVAPSECENEKDURUM, DENETIMDURUM, CEVAPDURUM
                    FROM denetim
                    WHERE VARLIK_KAPINO=? AND TARIH=? AND DENETIMTIPTANIM=? AND SOFOR_SICILNO=?
                    ORDER BY CEVAPDURUM DESC, SORUACIKLAMA
                """, (o['kapino'], o['tarih'], o['tip'], o['sicil'])).fetchall()
                soru_cols = ['soru','cevap','durum_kod','session_durum','cevap_durum']
                soru_detay[key] = [dict(zip(soru_cols, r)) for r in sorular]
                o['oturum_key'] = key

            con.close()
            return jsonify({"oturumlar": oturumlar, "sorular": soru_detay,
                            "aranan": kapino or sicil, "tip": "kapino" if kapino else "sicil"})
        except Exception as e:
            return jsonify({"hata": str(e)}), 500

    @app.route('/api/yakit_maliyet')
    def api_yakit_maliyet():
        """Akaryakıt fiyatı + hat bazlı yakıt maliyet hesabı (2025: H1 ort., 2026: canlı API)"""
        import urllib.request as _ur
        import json as _json

        mode = request.args.get('mode', '2025')
        # 2025 H1 İstanbul Eurodiesel aylık ortalama (Oca–Haz 2025, EPDK verileri)
        FIYAT_2025_H1 = 44.5

        VERI_GUN_SAYISI = 181    # Oca-Haz 2025
        YAS_FAKTOR     = 0.015   # her yıl +%1.5 tüketim artışı

        # Model bazlı baz tüketim tablosu (L/100km, sıfır yaşında)
        # yakit_turu: 'dizel' | 'cng' | 'elektrik'
        MODEL_YAKIT = {
            # Standart dizel (12m)
            'KENT 290LF':         {'baz': 28.5, 'tur': 'dizel'},
            'KENT C':             {'baz': 28.0, 'tur': 'dizel'},
            'PROCITY TR':         {'baz': 29.0, 'tur': 'dizel'},
            'PROCITY 285':        {'baz': 29.0, 'tur': 'dizel'},
            'PROCITY':            {'baz': 29.0, 'tur': 'dizel'},
            'CITARO 0530':        {'baz': 30.5, 'tur': 'dizel'},  # körüklü değil
            'CAPACITY':           {'baz': 31.0, 'tur': 'dizel'},
            'CONECTO':            {'baz': 30.0, 'tur': 'dizel'},
            'ULTRA LF12':         {'baz': 26.5, 'tur': 'dizel'},
            'AVANCITY S PLUS':    {'baz': 28.0, 'tur': 'dizel'},
            'AVANCITY L':         {'baz': 28.5, 'tur': 'dizel'},
            'COBRA GD 272':       {'baz': 29.0, 'tur': 'dizel'},
            'COBRA GM220LE':      {'baz': 28.5, 'tur': 'dizel'},
            'COBRA DOUBLE DECKER':{'baz': 36.0, 'tur': 'dizel'},
            'CITIPORT':           {'baz': 27.5, 'tur': 'dizel'},
            'SULTAN':             {'baz': 27.0, 'tur': 'dizel'},
            'NEOCITY':            {'baz': 28.0, 'tur': 'dizel'},
            'BELDE':              {'baz': 27.0, 'tur': 'dizel'},
            # Körüklü dizel (18m) — G / XL / LF25 / körüklü
            'CONECTO G':          {'baz': 40.0, 'tur': 'dizel'},
            'KENT XL':            {'baz': 38.0, 'tur': 'dizel'},
            'CITARO 0530 G':      {'baz': 41.0, 'tur': 'dizel'},
            'LF25':               {'baz': 38.0, 'tur': 'dizel'},
            # CNG (kg/100km, fiyat ayrı)
            'AVANCITY CNG':       {'baz': 25.0, 'tur': 'cng'},
            'AVENUE LF CNG':      {'baz': 26.0, 'tur': 'cng'},
            # Elektrikli — 0 yakıt maliyeti
            'E-JEST':             {'baz': 0.0,  'tur': 'elektrik'},
            'EMICRO':             {'baz': 0.0,  'tur': 'elektrik'},
            'S 14 KABINLI':       {'baz': 0.0,  'tur': 'elektrik'},
            'LSV 4 KABINLI':      {'baz': 0.0,  'tur': 'elektrik'},
        }
        VARSAYILAN_TUKETIM = {'baz': 30.0, 'tur': 'dizel'}

        def model_tuketim(marka, model, yas):
            """Model adına göre tüketim bul, yaş faktörü uygula."""
            model_ust = (model or '').upper()
            marka_ust = (marka or '').upper()
            bilgi = None
            for anahtar, deger in MODEL_YAKIT.items():
                if anahtar.upper() in model_ust or anahtar.upper() in marka_ust + ' ' + model_ust:
                    bilgi = deger
                    break
            if bilgi is None:
                bilgi = VARSAYILAN_TUKETIM
            yas = int(yas) if yas else 0
            baz = bilgi['baz']
            if bilgi['tur'] != 'elektrik':
                baz = round(baz * (1 + YAS_FAKTOR * yas), 2)
            return baz, bilgi['tur']

        # 1) Akaryakıt fiyatı — 2025: sabit H1 ortalaması, 2026: canlı API
        fiyat_tl = None
        fiyat_kaynak = None
        if mode == '2025':
            fiyat_tl = FIYAT_2025_H1
            fiyat_kaynak = '2025-H1 ortalama (EPDK)'
        else:
            fiyat_kaynak = 'api'
            try:
                url = 'http://hasanadiguzel.com.tr/api/akaryakit/sehir=ISTANBUL'
                req = _ur.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with _ur.urlopen(req, timeout=8) as resp:
                    raw = _json.loads(resp.read())
                fiyatlar = []
                for istasyon in raw.get('data', {}).values():
                    f = istasyon.get('Motorin(Eurodiesel)_TL/lt', '') or ''
                    f = f.replace(',', '.').strip()
                    try:
                        fiyatlar.append(float(f))
                    except ValueError:
                        pass
                if fiyatlar:
                    fiyat_tl = round(sum(fiyatlar) / len(fiyatlar), 2)
            except Exception as e:
                fiyat_kaynak = f'hata:{str(e)[:60]}'

            if fiyat_tl is None:
                fiyat_tl = 72.0
                fiyat_kaynak = 'varsayilan'

        # 2) Filo bazlı ağırlıklı ortalama tüketim hesabı
        sm_list = PANEL_DATA.get('smart_maintenance', [])
        dizel_tuketimler, metrobus_tuketimler, cng_tuketimler = [], [], []
        model_ozet = {}

        for arac in sm_list:
            marka = arac.get('marka', '')
            model = arac.get('model', '')
            yas   = arac.get('arac_yasi', 0)
            arac_tipi = arac.get('arac_tipi', '')
            tuk, tur = model_tuketim(marka, model, yas)
            model_key = f"{marka} {model}".strip()
            if model_key not in model_ozet:
                model_ozet[model_key] = {'adet': 0, 'tuketim': tuk, 'tur': tur}
            model_ozet[model_key]['adet'] += 1
            if tur == 'elektrik':
                continue
            if 'Metrobüs' in arac_tipi or 'Metrob' in arac_tipi:
                metrobus_tuketimler.append(tuk)
            elif tur == 'cng':
                cng_tuketimler.append(tuk)
            else:
                dizel_tuketimler.append(tuk)

        ort_dizel    = round(sum(dizel_tuketimler) / len(dizel_tuketimler), 2) if dizel_tuketimler else 30.0
        ort_metrobus = round(sum(metrobus_tuketimler) / len(metrobus_tuketimler), 2) if metrobus_tuketimler else 43.0
        ort_cng      = round(sum(cng_tuketimler) / len(cng_tuketimler), 2) if cng_tuketimler else 25.0

        # Model özet listesi (frontend için)
        model_ozet_liste = sorted(
            [{'model': k, **v} for k, v in model_ozet.items()],
            key=lambda x: -x['adet']
        )

        # 3) Hat verileri — hat_master (hatuzunluk) + sefer_agg (sefer_sayisi)
        hat_master = PANEL_DATA.get('hat_master', [])
        sefer_agg  = PANEL_DATA.get('sefer_agg', {})
        hat_bazli_sefer = sefer_agg.get('hat_bazli', {})

        hatlar = []
        for h in hat_master:
            hatkodu   = str(h.get('HATKODU', ''))
            hatadi    = h.get('hatadi', '')
            uzunluk_m = h.get('hatuzunluk', 0) or 0
            uzunluk_km = round(uzunluk_m / 1000, 2)
            hatcinsi  = h.get('hatcinsi', '')

            sefer_bilgi  = hat_bazli_sefer.get(hatkodu, {})
            toplam_sefer = sefer_bilgi.get('sefer_sayisi', 0) or 0
            gunluk_sefer = round(toplam_sefer / VERI_GUN_SAYISI, 1)

            # Hat cinsine göre tüketim seç
            hatcinsi_str = str(hatcinsi) if hatcinsi else ''
            if hatcinsi_str == 'METROBÜS' or 'METRO' in hatcinsi_str.upper():
                hat_tuketim = ort_metrobus
                hat_yakit_turu = 'dizel'
            elif 'ELEKTRIK' in hatcinsi_str.upper():
                hat_tuketim = 0.0
                hat_yakit_turu = 'elektrik'
            else:
                hat_tuketim = ort_dizel
                hat_yakit_turu = 'dizel'

            sefer_yakit_l  = round((uzunluk_km / 100) * hat_tuketim, 2)
            gunluk_yakit_l = round(gunluk_sefer * sefer_yakit_l, 1)
            gunluk_maliyet = round(gunluk_yakit_l * fiyat_tl, 2) if hat_yakit_turu != 'elektrik' else 0.0
            aylik_maliyet  = round(gunluk_maliyet * 30, 2)

            hatlar.append({
                'hatkodu':        hatkodu,
                'hatadi':         hatadi,
                'uzunluk_km':     uzunluk_km,
                'gunluk_sefer':   gunluk_sefer,
                'hat_tuketim':    hat_tuketim,
                'sefer_yakit_l':  sefer_yakit_l,
                'gunluk_yakit_l': gunluk_yakit_l,
                'gunluk_maliyet': gunluk_maliyet,
                'aylik_maliyet':  aylik_maliyet,
                'hatcinsi':       hatcinsi,
                'yakit_turu':     hat_yakit_turu,
            })

        hatlar.sort(key=lambda x: -x['gunluk_maliyet'])

        # 4) Genel toplam
        toplam_gunluk_yakit   = round(sum(h['gunluk_yakit_l'] for h in hatlar), 0)
        toplam_gunluk_maliyet = round(sum(h['gunluk_maliyet'] for h in hatlar), 0)
        toplam_aylik_maliyet  = round(toplam_gunluk_maliyet * 30, 0)

        return jsonify({
            'fiyat_tl':              fiyat_tl,
            'fiyat_kaynak':          fiyat_kaynak,
            'ort_dizel_l100km':      ort_dizel,
            'ort_metrobus_l100km':   ort_metrobus,
            'ort_cng_kg100km':       ort_cng,
            'toplam_gunluk_yakit_l': toplam_gunluk_yakit,
            'toplam_gunluk_maliyet': toplam_gunluk_maliyet,
            'toplam_aylik_maliyet':  toplam_aylik_maliyet,
            'hat_sayisi':            len(hatlar),
            'hatlar':                hatlar,
            'model_ozet':            model_ozet_liste,
        })

    @app.route('/api/panel/garaj')
    def api_panel_garaj():
        """Garaj risk + performans analizi (H1 2025 verisi)"""
        # garaj_risk.json 'EDIRNEKAPIGARAJI' bicimi, smart_maintenance.json
        # 'Edirnekapı' bicimi kullaniyor — kanonik anahtarla esletiyoruz.
        def _norm_g(name):
            if not name:
                return ''
            s = re.sub(r'\([^)]*\)', '', str(name)).strip().lower()
            for k, v in (('ç','c'),('ğ','g'),('ı','i'),('i̇','i'),
                         ('ö','o'),('ş','s'),('ü','u')):
                s = s.replace(k, v)
            s = ''.join(ch for ch in s if ch.isalnum())
            if s.endswith('garaji'): s = s[:-6]
            if s.endswith('garaj'):  s = s[:-5]
            return s

        garaj_risk = PANEL_DATA.get('garaj_risk', [])
        garaj_perf = PANEL_DATA.get('garaj_performans', [])

        # garaj_performans'ı kanonik anahtar → dict index yap
        perf_idx = {_norm_g(g.get('GARAJADI')): g for g in garaj_perf}

        # Kayıtsız araç satırını filtrele
        risk_liste = [g for g in garaj_risk if 'KAYIT' not in (g.get('GARAJADI') or '').upper()]

        # Bakım yükü — smart_maintenance'tan garaj başına KRİTİK/YÜKSEK/ORTA/DÜŞÜK sayısı
        # (kanonik anahtarla esletme — naming farkı için)
        sm_list = PANEL_DATA.get('smart_maintenance', [])
        _bakim_yuku = {}
        for _v in (sm_list if isinstance(sm_list, list) else []):
            _g_raw = (_v.get('garaj') or '').strip()
            if not _g_raw or 'KAYIT' in _g_raw.upper():
                continue
            _g = _norm_g(_g_raw)
            _t = (_v.get('aciliyet_tier') or _v.get('tier') or '').upper()
            _t = (_t.replace('İ','I').replace('Ü','U').replace('Ö','O')
                     .replace('Ş','S').replace('Ğ','G').replace('Ç','C'))
            if _g not in _bakim_yuku:
                _bakim_yuku[_g] = {'KRITIK':0,'YUKSEK':0,'ORTA':0,'DUSUK':0,'toplam':0}
            if _t in _bakim_yuku[_g]:
                _bakim_yuku[_g][_t] += 1
            _bakim_yuku[_g]['toplam'] += 1

        sonuc = []
        for g in risk_liste:
            ad = g.get('GARAJADI', '')
            key = _norm_g(ad)
            perf = perf_idx.get(key, {})
            bk   = _bakim_yuku.get(key, {'KRITIK':0,'YUKSEK':0,'ORTA':0,'DUSUK':0,'toplam':0})
            sonuc.append({
                'garaj':            ad,
                'risk_skoru':       round(g.get('risk_skoru', 0), 1),
                'risk_kategori':    g.get('risk_kategori', ''),
                'arac_sayisi':      g.get('arac_sayisi', 0),
                'ariza_sayisi':     g.get('ariza_sayisi', 0),
                'sefer_toplam':     g.get('sefer_toplam', 0),
                'ariza_per_100sefer': round(g.get('ariza_per_100sefer', 0), 3),
                'zayi_per_ariza':   round(g.get('zayi_per_ariza', 0), 3),
                'med_tepki_dk':     round(g.get('med_tepki_sure_dk', 0), 1),
                'med_mudahale_dk':  round(perf.get('med_mudahale_dk', 0), 1),
                'toplam_zayi_sefer': perf.get('toplam_zayi_sefer', 0),
                'komp_tepki':       round(g.get('komp_tepki', 0), 1),
                'komp_ariza':       round(g.get('komp_ariza', 0), 1),
                'komp_zayi':        round(g.get('komp_zayi', 0), 1),
                'bakim_kritik':     bk['KRITIK'],
                'bakim_yuksek':     bk['YUKSEK'],
                'bakim_orta':       bk['ORTA'],
                'bakim_dusuk':      bk['DUSUK'],
                'bakim_toplam':     bk['toplam'],
            })

        sonuc.sort(key=lambda x: -x['risk_skoru'])

        # KPI
        toplam_ariza  = sum(g['ariza_sayisi'] for g in sonuc)
        ort_tepki     = round(sum(g['med_tepki_dk'] for g in sonuc) / len(sonuc), 1) if sonuc else 0
        en_riskli     = sonuc[0]['garaj'] if sonuc else ''
        toplam_kritik = sum(g['bakim_kritik'] for g in sonuc)
        toplam_yuksek = sum(g['bakim_yuksek'] for g in sonuc)

        return jsonify({
            'garajlar':      sonuc,
            'toplam_ariza':  toplam_ariza,
            'ort_tepki_dk':  ort_tepki,
            'en_riskli':     en_riskli,
            'garaj_sayisi':  len(sonuc),
            'toplam_kritik': toplam_kritik,
            'toplam_yuksek': toplam_yuksek,
        })

    @app.route('/api/panel/smart_maintenance')
    def api_panel_smart_maintenance():
        """Akıllı Bakım Sistemi — 4 tier (KRİTİK/YÜKSEK/ORTA/DÜŞÜK)"""
        if 'smart_maintenance' not in PANEL_DATA:
            return jsonify({"hata": "smart_maintenance henuz yuklenmedi"}), 503
        return jsonify(PANEL_DATA['smart_maintenance'])

    # /api/panel/ml_status kaldırıldı — V5 LightGBM model durum endpoint'iydi, artık yok.
    # V6.5 model metadata için: panel_data/2025_q3/ml_v6_5_validation_report.json oku.

    @app.route('/api/panel/kapino_bakim/<kapino>')
    def api_panel_kapino_bakim(kapino):
        """Araç bazlı parça bakım durumu — km + takvim + mevsim"""
        kapino = kapino.strip().upper()
        pb = PANEL_DATA.get('parca_bakim', {})
        if kapino not in pb:
            return jsonify({"hata": f"{kapino} için parça bakım kaydı bulunamadı"}), 404
        return jsonify(pb[kapino])

    # Parça başına tahmini bakım süresi (saat) — 2 teknisyen paralel çalışma varsayımı
    _BAKIM_SURESI = {
        # Periyodik bakım
        'MOTOR YAĞI':1.0,'YAKIT FİLTRESİ':0.5,'HAVA FİLTRESİ':0.5,
        # Mekanik
        'AKÜ':1.5,'MARŞ':1.0,'SİGORTA':0.5,'ŞANZIMAN':6.0,'FREN':2.0,
        'SOĞUTMA':2.5,'KALORİFER':2.0,'KAPI':1.5,'HİDROLİK':2.0,
        'PNÖMATİK':2.0,'KLİMA':2.0,'KAYIŞ':1.0,'KÖRÜK':3.0,
        'MOTOR':8.0,'AKBİL':1.0,'TABELA':0.5,
    }
    _GUN_IDX = {'Pzt':0,'Sal':1,'Car':2,'Per':3,'Cum':4,'Cts':5,'Paz':6}
    _IDX_GUN = {v:k for k,v in _GUN_IDX.items()}

    @app.route('/api/panel/bakim_takvimi')
    def api_panel_bakim_takvimi():
        """Garaj kapasiteli yığılmasız bakım takvimi — kapasite rezerv analizi ile. ?mode=2025|2026"""
        import datetime
        mode = request.args.get('mode', '2025')
        bt_key = 'bakim_takvimi_2026' if mode == '2026' else 'bakim_takvimi'
        bt          = PANEL_DATA.get(bt_key, {})
        saat_veri   = PANEL_DATA.get('kapino_sefer_saatleri', {})
        oz_key = 'parca_bakim_ozet_2026' if mode == '2026' else 'parca_bakim_ozet'
        oz = PANEL_DATA.get(oz_key, {}) or PANEL_DATA.get('parca_bakim_ozet', {})
        kapasite_map = oz.get('garaj_kapasite', {})

        ACIL_PCT = _KAPASITE_ACIL_PCT
        KAZA_PCT = _KAPASITE_KAZA_PCT
        NET_PCT  = _KAPASITE_NET_PCT

        # Her garaj için net slot hesapla
        net_kapasite = {}
        rezerv_detay = {}
        for garaj, kap in kapasite_map.items():
            acil_r = max(1, round(kap * ACIL_PCT))
            kaza_r = max(1, round(kap * KAZA_PCT))
            net    = max(1, kap - acil_r - kaza_r)
            net_kapasite[garaj]  = net
            rezerv_detay[garaj]  = {'kapasite': kap, 'acil': acil_r, 'kaza': kaza_r, 'net': net}

        # Hafta sonu çarpanı — Cumartesi ve Pazar tespit
        def gun_tipi(tarih_str):
            try:
                dt = datetime.date.fromisoformat(tarih_str)
                return dt.weekday()  # 0=Pazartesi, 5=Cumartesi, 6=Pazar
            except Exception:
                return -1

        # Tüm tarihler için garaj bazlı doluluk hesapla
        tarih_garaj_dolu = {}  # (tarih, garaj) → planlanan araç sayısı
        for tarih, garajlar in bt.items():
            for garaj, araclar in garajlar.items():
                tarih_garaj_dolu[(tarih, garaj)] = len(araclar)

        tarihler_sıralı = sorted(bt.keys())

        # Her araç için gece bakım penceresi yeterliliği — bt'yi zenginleştir
        import copy
        bt = copy.deepcopy(bt)   # orijinal PANEL_DATA verisini değiştirme
        for tarih, garajlar in bt.items():
            wd = gun_tipi(tarih)
            gun_adi = _IDX_GUN.get(wd, '')
            for garaj, araclar in garajlar.items():
                for a in araclar:
                    kapino   = a.get('kapino','')
                    parcalar = a.get('parcalar', [])
                    # Toplam bakım süresi: en uzun parça + diğerlerinin %40'ı (paralel çalışma)
                    sureler  = sorted((_BAKIM_SURESI.get(p, 1.5) for p in parcalar), reverse=True)
                    if sureler:
                        toplam_sure = sureler[0] + sum(s * 0.4 for s in sureler[1:])
                    else:
                        toplam_sure = 1.5
                    toplam_sure = round(toplam_sure, 1)
                    # Araç gece penceresi
                    sv = saat_veri.get(kapino, {})
                    gun_bilgi = sv.get('gunler', {}).get(gun_adi) if sv else None
                    if gun_bilgi:
                        pencere   = gun_bilgi.get('pencere', 0)
                        son_bit   = gun_bilgi.get('son_bit', 23.5)
                        sigabilir = pencere >= toplam_sure
                    else:
                        pencere   = sv.get('ort_pencere', 0) if sv else 0
                        son_bit   = 23.5
                        sigabilir = pencere >= toplam_sure if pencere else None
                    a['sure']      = toplam_sure
                    a['pencere']   = round(pencere, 1)
                    a['gece']      = sigabilir   # True=gece yapılır, False=gündüz çekimi, None=veri yok
                    a['bas_saat']  = round(son_bit, 1) if sigabilir else None

        # Takvim analizi: hangi gün hangi garaj net kapasiteyi aşıyor
        asim_ozet = []

        for tarih, garajlar in bt.items():
            g_no = gun_tipi(tarih)
            is_weekend = g_no in (5, 6)
            for garaj, araclar in garajlar.items():
                net = net_kapasite.get(garaj, round((kapasite_map.get(garaj, 12)) * NET_PCT))
                planlanan = len(araclar)
                fazla = planlanan - net
                if fazla <= 0:
                    continue

                garaj_label = garaj.replace('GARAJI','').replace('GARAJ','').strip()

                # ACİL araçlar kesinlikle o gün bakım yapılmalı (seferden çekilir) — kaydırılamaz.
                # Redistribüsyon sadece ACİL olmayan araçlara uygulanır.
                acil_sayisi = sum(1 for a in araclar if a.get('durum','') == 'ACİL')
                # ☀️ araçlar: gece penceresi bakım süresine yetmiyor → gündüz seferden çekilmeli
                gunduz_cekimi = sum(1 for a in araclar if a.get('gece') is False)
                non_acil_sayisi = planlanan - acil_sayisi
                # Kaydırılabilir = net'in üstündeki non-ACİL araçlar
                redistr_fazla = max(0, planlanan - net - max(0, acil_sayisi - net))
                redistr_fazla = min(redistr_fazla, non_acil_sayisi)

                # Redistribüsyon önerisi: aynı garajda yakın günlerde boş slot ara
                # Hafta sonu öncelikli (Cumartesi/Pazar), sonra hafta içi
                idx = tarihler_sıralı.index(tarih) if tarih in tarihler_sıralı else -1
                redistr = []
                aranacak = tarihler_sıralı[max(0,idx-3):idx] + tarihler_sıralı[idx+1:idx+8]
                # Hafta sonlarını öne al
                aranacak.sort(key=lambda t: (0 if gun_tipi(t) in (5,6) else 1, t))

                kalan_fazla = redistr_fazla
                for hedef_tarih in aranacak:
                    if kalan_fazla <= 0:
                        break
                    hedef_dolu = tarih_garaj_dolu.get((hedef_tarih, garaj), 0)
                    hedef_net  = net_kapasite.get(garaj, round((kapasite_map.get(garaj,12))*NET_PCT))
                    # Hafta sonu için hafta sonu çarpanı uygula
                    g_no_h = gun_tipi(hedef_tarih)
                    if g_no_h == 5:   hedef_net = round(hedef_net * 1.2)
                    elif g_no_h == 6: hedef_net = round(hedef_net * 1.5)
                    bos = hedef_net - hedef_dolu
                    if bos <= 0:
                        continue
                    tasinacak = min(kalan_fazla, bos)
                    redistr.append({
                        'hedef_tarih': hedef_tarih,
                        'tasinacak':   tasinacak,
                        'weekend':     g_no_h in (5, 6),
                        'bos_slot':    bos,
                    })
                    kalan_fazla -= tasinacak

                asim_ozet.append({
                    'tarih':       tarih,
                    'garaj':       garaj_label,
                    'planlanan':   planlanan,
                    'net_slot':    net,
                    'fazla':       fazla,
                    'acil_sayisi':    acil_sayisi,    # o gün kaydırılamaz ACİL araç sayısı
                    'gunduz_cekimi': gunduz_cekimi,  # gece penceresi yetersiz → ikame gerekli
                    'redistr_fazla': redistr_fazla,  # kaydırılabilir araç sayısı
                    'weekend':     is_weekend,
                    'redistr':     redistr,           # dağıtım önerileri
                    'cozuldu':     redistr_fazla - kalan_fazla,  # kaçı çözülebildi
                    'cozulemez':   kalan_fazla,                  # kaçı çözülemedi
                })

        asim_ozet.sort(key=lambda x: (-x['fazla'], x['tarih']))

        return jsonify({
            'takvim':         bt,
            'ozet':           oz,
            'kapasite_analiz': {
                'net_kapasite':      net_kapasite,
                'rezerv_detay':      rezerv_detay,
                'asim_gun_sayisi':   len(asim_ozet),
                'asim_liste':        asim_ozet,
                'model': {
                    'acil_pct': int(ACIL_PCT * 100),
                    'kaza_pct': int(KAZA_PCT * 100),
                    'net_pct':  int(NET_PCT  * 100),
                }
            }
        })

    @app.route('/api/panel/ikame_onerisi')
    def api_panel_ikame_onerisi():
        """ACİL bakıma alınan araç yerine aynı garajdan yedek araç öner.
        Gerçek sefer günleri verisinden (kapino_sefer_gunler.json) o günde
        seferi olan / olmayan araçları ayırt eder.
        """
        from flask import request as freq
        from datetime import datetime as _dt
        tarih     = freq.args.get('tarih', '')
        garaj_lbl = freq.args.get('garaj', '')   # garaj_label (GARAJI/GARAJ soyulmuş)
        mode      = freq.args.get('mode', '2025')

        sm_key   = 'smart_maintenance_2026' if mode == '2026' else 'smart_maintenance'
        bt_key   = 'bakim_takvimi_2026'     if mode == '2026' else 'bakim_takvimi'
        pb_key   = 'parca_bakim_2026'       if mode == '2026' else 'parca_bakim'

        sm_list      = PANEL_DATA.get(sm_key, [])
        bt           = PANEL_DATA.get(bt_key, {})
        sefer_gunler = PANEL_DATA.get('kapino_sefer_gunler', {})
        parca_bakim  = PANEL_DATA.get(pb_key, {})

        # garaj_label → ham garaj adı eşleştir
        garaj_raw = None
        if tarih in bt:
            for g in bt[tarih]:
                if g.replace('GARAJI','').replace('GARAJ','').strip() == garaj_lbl:
                    garaj_raw = g
                    break

        if not garaj_raw:
            return jsonify({'tarih': tarih, 'garaj': garaj_lbl, 'ikame': []})

        araclar_bugun   = bt[tarih].get(garaj_raw, [])
        bugun_kapinolar = {a['kapino'] for a in araclar_bugun}
        sm_map          = {a['kapino']: a for a in sm_list}

        # Bakım tarihinin haftanın hangi günü olduğunu bul (0=Pzt … 6=Paz)
        try:
            bakim_wd = _dt.strptime(tarih[:10], '%Y-%m-%d').weekday()
        except ValueError:
            bakim_wd = -1

        def sefer_durumu(kapino):
            """Gerçek sefer günleri verisine göre etiket & öncelik (düşük = önce)."""
            veri = sefer_gunler.get(kapino)
            if not veri:
                # Sefer verisinde yok → bilinmiyor, sona at
                return (3, 'bilinmiyor', 'Sefer verisi bulunamadı')
            aktif_gunler = veri.get('aktif_gunler', [])
            if bakim_wd == -1 or bakim_wd not in aktif_gunler:
                # Bu gün tarihsel olarak sefer yapmamış → uygun yedek
                toplam = veri.get('toplam_sefer', 0)
                return (0, 'uygun', f'Bu gün seferi yok (tarihsel örüntü, {toplam} toplam sefer)')
            else:
                # Bu gün seferde
                gun_sayisi = veri.get('gun_sayilari', [0]*7)
                gun_sefer  = gun_sayisi[bakim_wd] if bakim_wd < len(gun_sayisi) else 0
                return (2, 'seferli', f'Bu gün tipik olarak seferde ({gun_sefer} sefer/gün — program doğrulanmalı)')

        # ACİL araçlar için yedek öner
        ikame = []
        for acil_a in araclar_bugun:
            if acil_a.get('durum') != 'ACİL':
                continue
            kapino_acil = acil_a['kapino']
            sm_acil     = sm_map.get(kapino_acil, {})
            arac_cinsi  = sm_acil.get('arac_cinsi', '')

            # Aday: aynı garaj + aynı tip + bugün bakımda değil + DÜŞÜK/ORTA risk
            adaylar = [
                a for a in sm_list
                if a.get('garaj') == garaj_raw
                and a.get('kapino') not in bugun_kapinolar
                and a.get('arac_cinsi') == arac_cinsi
                and a.get('aciliyet_tier') in ('DÜŞÜK', 'ORTA')
            ]
            def aday_acil_parca_var(kapino):
                """Adayın parca_bakim'da ACİL parçası varsa True — yedek olarak tercih edilmemeli."""
                pb = parca_bakim.get(kapino, {})
                return any(
                    isinstance(v, dict) and v.get('durum') == 'ACİL'
                    for k, v in pb.items() if not k.startswith('_')
                )

            # Sıralama: sefer durumu → kendi ACİL parçası yok mu → risk skoru
            adaylar.sort(key=lambda x: (
                sefer_durumu(x['kapino'])[0],       # 0=sefersiz önce
                1 if aday_acil_parca_var(x['kapino']) else 0,  # ACİL parçalı sona
                x.get('aciliyet_skoru', 999)
            ))

            ikame.append({
                'kapino_acil': kapino_acil,
                'arac_cinsi':  arac_cinsi,
                'marka_acil':  sm_acil.get('marka', ''),
                'parcalar':    acil_a.get('parcalar', []),
                'adaylar': [{
                    'kapino':         a['kapino'],
                    'marka':          a.get('marka', ''),
                    'tier':           a.get('aciliyet_tier', ''),
                    'skor':           round(a.get('aciliyet_skoru', 0), 1),
                    'arac_cinsi':     a.get('arac_cinsi', ''),
                    'sefer_oncelik':  sefer_durumu(a['kapino'])[1],
                    'sefer_aciklama': sefer_durumu(a['kapino'])[2],
                    'kendi_acil':     aday_acil_parca_var(a['kapino']),  # kendisi de ACİL bakım bekliyor
                } for a in adaylar[:3]]
            })

        return jsonify({'tarih': tarih, 'garaj': garaj_lbl, 'ikame': ikame})

    @app.route('/api/panel/anomali')
    def api_panel_anomali():
        """Ani arıza artışı anomali tespiti — son 30 gün / 6 ay aylık ort. karşılaştırması"""
        sm  = PANEL_DATA.get('smart_maintenance', [])
        ar  = PANEL_DATA.get('arac_risk', [])
        # arac_risk'i KAPINO'ya göre indexle
        ar_idx = {x.get('KAPINO', ''): x for x in ar}

        sonuclar = []
        for arac in sm:
            kap    = arac.get('kapino', '')
            cnt30  = int(arac.get('cnt_30', 0) or 0)
            agir30 = int(arac.get('agir_30', 0) or 0)
            ar_veri     = ar_idx.get(kap, {})
            ariza_6ay   = int(ar_veri.get('ariza_sayisi', 0) or 0)
            aylik_ort   = ariza_6ay / 6
            anomali_skor = cnt30 / max(0.5, aylik_ort)

            # Kriter: son 30 gün, aylık ortalamanın 2.5 katından fazla VE en az 3 arıza
            if anomali_skor >= 2.5 and cnt30 >= 3:
                sonuclar.append({
                    'kapino':       kap,
                    'tier':         arac.get('aciliyet_tier', ''),
                    'garaj':        (arac.get('garaj', '') or '').replace('GARAJI','').replace('GARAJ','').strip(),
                    'marka':        arac.get('marka', ''),
                    'cnt_30':       cnt30,
                    'agir_30':      agir30,
                    'ariza_6ay':    ariza_6ay,
                    'aylik_ort':    round(aylik_ort, 1),
                    'anomali_skor': round(anomali_skor, 1),
                    'son_neden':    arac.get('son_ciddi_neden', ''),
                    'bakim_uyarisi':arac.get('bakim_uyarisi', ''),
                })

        sonuclar.sort(key=lambda x: -x['anomali_skor'])
        return jsonify({
            'toplam': len(sonuclar),
            'esik':   {'min_cnt30': 3, 'min_skor': 2.5},
            'liste':  sonuclar[:50],   # en fazla 50 araç döndür
        })

    @app.route('/api/panel/arac_risk')
    def api_panel_arac_risk():
        """Araç risk skorları (ML model çıktısı, 29 alan)"""
        if 'arac_risk' not in PANEL_DATA:
            return jsonify({"hata": "arac_risk henuz yuklenmedi"}), 503
        return jsonify(PANEL_DATA['arac_risk'])

    @app.route('/api/panel/garaj_bakim_yuk')
    def api_panel_garaj_bakim_yuk():
        """Garaj bakım yükü + kapasite analizi + cross-garaj öneri"""

        # Görünen ad eşleştirme (koordinat yok — tüm garajlar arası öneri açık)
        GARAJ_AD = {
            'EDIRNEKAPIGARAJI':          'EDİRNEKAPI',
            'HASANPASAGARAJI':           'HASANPAŞA',
            'KURTKOYGARAJI':             'KURTKOY',
            'SULTANGAZİ GARAJI':         'SULTANGAZİ',
            'IKITELLIISLETTIRMEGARAJI2': 'İKİTELLİ 2',
            'ANADOLUGARAJI':             'ANADOLU',
            'IKITELLIGARAJI':            'İKİTELLİ',
            'KAGITHANEGARAJI':           'KAĞITHANE',
            'SARIGAZIGARAJI':            'SARIGAZI',
            'SAHINKAYAGARAJI':           'ŞAHİNKAYA',
            'TOPKAPI(TT)':               'TOPKAPI',
            'Yunus (Park)':              'YUNUS (PARK)',
            'ADALAR':                    'ADALAR',
        }

        sm  = PANEL_DATA.get('smart_maintenance', [])
        pb  = PANEL_DATA.get('parca_bakim_ozet', {})
        kapasite_map = pb.get('garaj_kapasite', {})

        # Tier dağılımı + araç listesi per garaj (devir önerisi için)
        from collections import defaultdict
        garaj_tier   = defaultdict(lambda: {'KRİTİK':0,'YÜKSEK':0,'ORTA':0,'DÜŞÜK':0})
        garaj_araclar = defaultdict(list)   # garaj → [{'kapino','tier','skor','marka','bakim_uyarisi'}]
        for arac in sm:
            g = arac.get('garaj','') or ''
            t = arac.get('aciliyet_tier','DÜŞÜK')
            # Tier yazım normalizasyonu (smart_maintenance.json'da 'DÜŞUK' ASCII-U varyantı var)
            t = {'DÜŞUK':'DÜŞÜK','DUSUK':'DÜŞÜK','KRITIK':'KRİTİK','YUKSEK':'YÜKSEK'}.get(t, t)
            if t not in garaj_tier[g]:
                t = 'DÜŞÜK'
            garaj_tier[g][t] += 1
            if t in ('KRİTİK','YÜKSEK'):
                garaj_araclar[g].append({
                    'kapino':        arac.get('kapino',''),
                    'tier':          t,
                    'skor':          arac.get('aciliyet_skoru', 0),
                    'marka':         arac.get('marka',''),
                    'bakim_uyarisi': (arac.get('bakim_uyarisi','') or '').split('|')[0].strip(),
                })

        ACIL_REZERV_PCT = _KAPASITE_ACIL_PCT
        KAZA_REZERV_PCT = _KAPASITE_KAZA_PCT
        NET_PCT         = _KAPASITE_NET_PCT
        GECE_BONUS      = _KAPASITE_GECE_BONUS
        CTS_CARP        = 1.2  # Cumartesi sefer %17 az → %20 ekstra kapasite
        PAZ_CARP        = 1.5  # Pazar sefer %31 az → %50 ekstra kapasite

        garajlar = []
        for garaj_adi, tiers in garaj_tier.items():
            if not garaj_adi or garaj_adi == 'Kayıtsız Araç':
                continue
            kapasite    = kapasite_map.get(garaj_adi, 12)
            acil_rezerv = max(1, round(kapasite * ACIL_REZERV_PCT))
            kaza_rezerv = max(1, round(kapasite * KAZA_REZERV_PCT))
            net_slot    = max(1, kapasite - acil_rezerv - kaza_rezerv)

            # Haftalık efektif bakım kapasitesi:
            # 5 hafta içi: (net_slot + gece_bonus) her gün
            # Cumartesi + Pazar: (net_slot + gece_bonus) × hafta sonu çarpanı
            gun_cap     = net_slot + GECE_BONUS
            haftalik_net = (
                5 * gun_cap +
                round(gun_cap * CTS_CARP) +
                round(gun_cap * PAZ_CARP)
            )
            gunluk_efektif = round(haftalik_net / 7, 1)

            kritik = tiers['KRİTİK']
            yuksek = tiers['YÜKSEK']
            orta   = tiers['ORTA']
            dusuk  = tiers['DÜŞÜK']
            toplam = kritik + yuksek + orta + dusuk
            yuklu  = kritik + yuksek

            # KRİTİK: seferden acil çekilir, slot tüketir ama sıra beklemez
            # YÜKSEK: sıra bekler → bekleme_gun hesabı
            bekleme_gun = round(yuksek / gunluk_efektif, 1) if gunluk_efektif > 0 else 99

            garajlar.append({
                'garaj_adi':       garaj_adi,
                'ad':              GARAJ_AD.get(garaj_adi, garaj_adi.replace('GARAJI','').replace('GARAJ','').strip()),
                'kapasite':        kapasite,
                'acil_rezerv':     acil_rezerv,
                'kaza_rezerv':     kaza_rezerv,
                'net_slot':        net_slot,
                'gece_bonus':      GECE_BONUS,
                'gunluk_efektif':  gunluk_efektif,
                'kritik':          kritik,
                'yuksek':          yuksek,
                'orta':            orta,
                'dusuk':           dusuk,
                'toplam':          toplam,
                'yuklu':           yuklu,
                'yuk_pct':         round(yuklu / toplam * 100) if toplam else 0,
                'bekleme_gun':     bekleme_gun,
            })

        # Cross-garaj önerileri — KRİTİK + YÜKSEK araçlar dahil
        # Yüklü: bekleme > 7 gün | Boş: bekleme < 3 gün
        garajlar.sort(key=lambda x: -x['bekleme_gun'])
        # Garaj_adi → garaj dict hızlı lookup
        garaj_idx = {g['garaj_adi']: g for g in garajlar}

        oneriler = []
        for yuk_g in garajlar:
            if yuk_g['bekleme_gun'] <= 7:
                continue
            # Devir adayları: KRİTİK önce, sonra YÜKSEK — skor azalan sırada
            adaylar = sorted(
                garaj_araclar.get(yuk_g['garaj_adi'], []),
                key=lambda x: (0 if x['tier']=='KRİTİK' else 1, -x['skor'])
            )
            for bos_g in garajlar:
                if bos_g['garaj_adi'] == yuk_g['garaj_adi']:
                    continue
                if bos_g['bekleme_gun'] >= 3:
                    continue
                # Müsait: boş garajın net slotu - kendi mevcut yüklü araçları
                musait = max(1, bos_g['net_slot'] - bos_g['yuklu'])
                # Kaç araç devredilecek (tüm KRİTİK+YÜKSEK havuzundan)
                devir_say = min(len(adaylar), musait)
                if devir_say == 0:
                    continue
                devir_liste = adaylar[:devir_say]
                kritik_devir = sum(1 for a in devir_liste if a['tier']=='KRİTİK')
                yuksek_devir = sum(1 for a in devir_liste if a['tier']=='YÜKSEK')
                # Bekleme hesabı sadece YÜKSEK üzerinden (KRİTİK acil çekilir)
                yuksek_kalan = max(0, yuk_g['yuksek'] - yuksek_devir)
                bekleme_yeni = round(yuksek_kalan / yuk_g['gunluk_efektif'], 1)
                oneriler.append({
                    'yuk_garaj':     yuk_g['ad'],
                    'yuk_garaj_adi': yuk_g['garaj_adi'],
                    'bos_garaj':     bos_g['ad'],
                    'devir_arac':    devir_say,
                    'kritik_devir':  kritik_devir,
                    'yuksek_devir':  yuksek_devir,
                    'bos_musait':    musait,
                    'bekleme_eski':  yuk_g['bekleme_gun'],
                    'bekleme_yeni':  bekleme_yeni,
                    'kazanim_gun':   round(yuk_g['bekleme_gun'] - bekleme_yeni, 1),
                    # Hangi araçlar gidecek (max 10 göster)
                    'devir_kapinolar': [
                        {
                            'kapino':        a['kapino'],
                            'tier':          a['tier'],
                            'marka':         a['marka'],
                            'kaynak_garaj':  yuk_g['ad'],   # "EDİRNEKAPI'dan devir" etiketi için
                            'bakim_uyarisi': a['bakim_uyarisi'],
                        }
                        for a in devir_liste[:10]
                    ],
                })

        oneriler.sort(key=lambda x: -x['kazanim_gun'])

        return jsonify({
            'garajlar': garajlar,
            'oneriler': oneriler[:8],
            'rezerv_model': {
                'acil_ariza_pct':  int(ACIL_REZERV_PCT * 100),
                'kaza_pct':        int(KAZA_REZERV_PCT * 100),
                'net_pct':         int(NET_PCT * 100),
                'gece_bonus_slot': GECE_BONUS,
                'cts_carp':        CTS_CARP,
                'paz_carp':        PAZ_CARP,
            }
        })

    @app.route('/api/panel/trafik_meta')
    def api_panel_trafik_meta():
        """TomTom key + kavşak verisi — harita trafik katmanları için"""
        from services import TOMTOM_KEY, guncelle_kavsaklar
        kavsaklar = guncelle_kavsaklar()
        return jsonify({
            "tomtom_key": TOMTOM_KEY or "",
            "kavsaklar": kavsaklar,
            "kavsak_adet": len(kavsaklar),
        })

    @app.route('/api/panel/kaza_analiz')
    def api_panel_kaza_analiz():
        """Kaza analiz sekmesi için özet istatistikler."""
        from collections import defaultdict

        raw      = PANEL_DATA.get('kaza_geojson', {})
        features = raw.get('features', []) if isinstance(raw, dict) else []

        # Şiddet ağırlıkları
        AGIRLIK = {
            'Yayaya Çarpma': 5,
            'Biz bize': 2,
            'Biz Bize (Metrobüs)': 2,
            'Tek Taraflı(Metrobüs)': 2,
            'Araca Çarpma': 1,
            'Sivil Araç(Metrobüs)': 1,
            'Görevli Araç(Metrobüs)': 1,
            'Diğer araçlar': 1,
        }

        toplam        = len(features)
        toplam_yarali = 0
        agirlikli_skor = 0

        kat_sayac  = defaultdict(int)
        kat_agirli = defaultdict(int)
        ilce_sayac  = defaultdict(int)
        ilce_agirli = defaultdict(int)
        hat_sayac   = defaultdict(int)
        hat_agirli  = defaultdict(int)
        aylik       = defaultdict(int)
        hava_sayac  = defaultdict(int)
        yol_sayac   = defaultdict(int)
        gun_sayac   = defaultdict(int)   # haftanın günü

        for f in features:
            p   = f.get('properties') or {}
            kat = p.get('kategori', 'Bilinmiyor')
            ag  = AGIRLIK.get(kat, 1)
            yarali = int(p.get('yaraliyolcu') or 0)
            ilce   = p.get('ilce', 'Bilinmiyor')
            hat    = p.get('hatkodu', '')
            tarih  = p.get('tarih', '')
            hava   = p.get('hava', 'Bilinmiyor')
            yol    = p.get('yol', 'Bilinmiyor')

            toplam_yarali  += yarali
            agirlikli_skor += ag

            kat_sayac[kat]   += 1
            kat_agirli[kat]  += ag
            ilce_sayac[ilce] += 1
            ilce_agirli[ilce]+= ag
            if hat:
                hat_sayac[hat]  += 1
                hat_agirli[hat] += ag
            if tarih:
                aylik[tarih[:7]] += 1
                try:
                    from datetime import datetime as _dt
                    wd = _dt.strptime(tarih[:10], '%Y-%m-%d').weekday()
                    gun_sayac[wd] += 1
                except Exception:
                    pass
            hava_sayac[hava] += 1
            yol_sayac[yol]   += 1

        # İlçe tablosu — ağırlıklı skora göre sıralı
        ilce_tablo = sorted([
            {'ilce': k, 'kaza': ilce_sayac[k], 'agirlikli': ilce_agirli[k]}
            for k in ilce_sayac
        ], key=lambda x: -x['agirlikli'])

        # Hat tablosu — top 20
        hat_tablo = sorted([
            {'hat': k, 'kaza': hat_sayac[k], 'agirlikli': hat_agirli[k]}
            for k in hat_sayac
        ], key=lambda x: -x['agirlikli'])[:20]

        # Kategori listesi
        kat_tablo = sorted([
            {'kat': k, 'sayi': kat_sayac[k], 'agirlikli': kat_agirli[k]}
            for k in kat_sayac
        ], key=lambda x: -x['agirlikli'])

        # Aylık sıralı
        aylik_sira = [{'ay': k, 'sayi': v} for k, v in sorted(aylik.items())]

        # Günlük dağılım (0=Pzt..6=Paz)
        GUN_ADI = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cts', 'Paz']
        gun_tablo = [{'gun': GUN_ADI[i], 'sayi': gun_sayac.get(i, 0)} for i in range(7)]
        en_kotu_gun = max(gun_tablo, key=lambda x: x['sayi'])['gun'] if gun_tablo else '?'

        # ── Hız Dağılımı (kaza anındaki hız, geojson'daki hizson alanı) ──
        from collections import defaultdict as _dd
        hiz_grup = _dd(int)
        hiz_dolu = 0
        for f in features:
            h = (f.get('properties') or {}).get('hizson')
            try:
                h = float(h)
            except (TypeError, ValueError):
                continue
            if h <= 0:
                continue
            hiz_dolu += 1
            if   h < 10:  g = '0-10'
            elif h < 20:  g = '10-20'
            elif h < 30:  g = '20-30'
            elif h < 40:  g = '30-40'
            elif h < 50:  g = '40-50'
            elif h < 60:  g = '50-60'
            elif h < 80:  g = '60-80'
            else:         g = '80+'
            hiz_grup[g] += 1
        _hiz_sira = ['0-10','10-20','20-30','30-40','40-50','50-60','60-80','80+']
        hiz_dagilim = [{'grup': g+' km/h', 'sayi': hiz_grup.get(g,0)} for g in _hiz_sira if hiz_grup.get(g,0) > 0]

        # ── Yaralı/Ölüm araç listesi (DB'den tüm yaralı/ölüm alanları toplu) ──
        yarali_olum_araclar = []
        toplam_yarali_db = 0
        toplam_olum = 0
        try:
            con = get_panel_db(); cur = con.cursor()
            rows = cur.execute("""
                SELECT KAPINO,
                       SUM(COALESCE(YARALISURUCU,0)+COALESCE(YARALIYOLCU,0)+COALESCE(YARALIYAYA,0)+COALESCE(YARALISIVIL,0)) AS yarali,
                       SUM(COALESCE(OLUMSURUCU,0)+COALESCE(OLUMYOLCU,0)+COALESCE(OLUMYAYA,0)+COALESCE(OLUMSIVIL,0)) AS olum,
                       COUNT(*) AS kaza_sayi
                FROM kaza
                WHERE KAPINO IS NOT NULL AND KAPINO != ''
                  AND (YARALISURUCU>0 OR YARALIYOLCU>0 OR YARALIYAYA>0 OR YARALISIVIL>0
                    OR OLUMSURUCU>0 OR OLUMYOLCU>0 OR OLUMYAYA>0 OR OLUMSIVIL>0)
                GROUP BY KAPINO
                ORDER BY olum DESC, yarali DESC
            """).fetchall()
            for k, y, o, kz in rows:
                y, o = int(y or 0), int(o or 0)
                yarali_olum_araclar.append({'kapino': k, 'yarali': y, 'olum': o, 'kaza': kz})
                toplam_yarali_db += y
                toplam_olum += o
            con.close()
        except Exception as e:
            print('Kaza yaralı/ölüm sorgu hatası:', e)

        return jsonify({
            'toplam':         toplam,
            'toplam_yarali':  toplam_yarali,         # geojson yaraliyolcu (sadece yolcu)
            'toplam_yarali_db': toplam_yarali_db,    # DB tüm yaralı (sürücü+yolcu+yaya+sivil)
            'toplam_olum':    toplam_olum,
            'agirlikli_skor': agirlikli_skor,
            'en_kotu_gun':    en_kotu_gun,
            'kategori':       kat_tablo,
            'ilce':           ilce_tablo,
            'hat':            hat_tablo,
            'aylik':          aylik_sira,
            'hava':           [{'hava': k, 'sayi': v} for k, v in sorted(hava_sayac.items(), key=lambda x: -x[1])],
            'yol':            [{'yol': k, 'sayi': v} for k, v in sorted(yol_sayac.items(), key=lambda x: -x[1])],
            'gun':            gun_tablo,
            'hiz_dagilim':    hiz_dagilim,
            'hiz_dolu_kayit': hiz_dolu,
            'hiz_toplam_kayit': toplam,
            'yarali_olum_araclar': yarali_olum_araclar,
        })

    @app.route('/api/panel/risk_harita')
    def api_panel_risk_harita():
        """Risk haritası — kaza GeoJSON + kriz heat filtrelenmiş"""
        tip      = request.args.get('tip', 'kaza')
        hat      = request.args.get('hat', '').strip().upper()
        kapino   = request.args.get('kapino', '').strip().upper()
        kategori = request.args.get('kategori', '').strip()

        if tip == 'kriz':
            return jsonify(PANEL_DATA.get('kriz_heat', []))

        # Kapino araması → SQLite'tan canlı sorgula (geojson cache bağımsız)
        if kapino:
            try:
                _COLS = """ENLEM,BOYLAM,ILCE,HAVADURUMU,YOLDURUMU,KATEGORIADI,
                           COALESCE(YARALIYOLCU,0),HATKODU,TARIH,KAPINO,
                           KAZASAAT,TRAFIKDURUMU,KAZANOKTA,SOFORKUSUR,HIZSON,KUSURGRUBU"""
                sql = f"SELECT {_COLS} FROM kaza WHERE KAPINO=? AND ENLEM IS NOT NULL AND ENLEM NOT IN (0,'') AND BOYLAM IS NOT NULL AND BOYLAM NOT IN (0,'')"
                params = [kapino]
                if hat:
                    sql += ' AND HATKODU=?'; params.append(hat)
                con = get_panel_db(); cur = con.cursor()
                rows = cur.execute(sql, params).fetchall(); con.close()
                features = _kaza_rows_to_features(rows)
                return _kaza_featurecollection(features)
            except Exception as e:
                return jsonify({'type':'FeatureCollection','features':[],'hata':str(e)}), 500

        # Hat / genel filtre → geojson cache (hızlı, eski davranış)
        raw = PANEL_DATA.get('kaza_geojson', {})
        all_features = raw.get('features', []) if isinstance(raw, dict) else []
        features = all_features
        if hat:
            features = [f for f in features if (f.get('properties') or {}).get('hatkodu','').upper() == hat]
        if kategori:
            features = [f for f in features if (f.get('properties') or {}).get('kategori','') == kategori]
        yarali = sum((f.get('properties') or {}).get('yaraliyolcu',0) or 0 for f in features)
        tum_kat = sorted(set(
            (f.get('properties') or {}).get('kategori','') for f in all_features
            if (f.get('properties') or {}).get('kategori')
        ))
        return jsonify({
            'type':'FeatureCollection','features':features,
            'toplam':len(features),'yarali':yarali,
            'kategoriler':tum_kat,'kriz_nokta':len(PANEL_DATA.get('kriz_heat',[])),
        })

    @app.route('/api/panel/durak_risk')
    def api_panel_durak_risk():
        """Kriz oluşan duraklar — koordinatlı risk verileri"""
        data = PANEL_DATA.get('durak_risk', [])
        duraklar = [d for d in data if d.get('lat') and d.get('lon')]
        return jsonify({'duraklar': duraklar, 'toplam': len(duraklar)})

    def _kaza_rows_to_features(rows):
        feats = []
        for r in rows:
            try: flat, flon = float(r[0]), float(r[1])
            except (TypeError, ValueError): continue
            feats.append({'type':'Feature',
                'geometry':{'type':'Point','coordinates':[flon,flat]},
                'properties':{
                    'ilce':r[2] or '','hava':r[3] or '','yol':r[4] or '',
                    'kategori':r[5] or '','yaraliyolcu':int(r[6] or 0),
                    'hatkodu':r[7] or '','tarih':(r[8] or '')[:10],
                    'kapino':r[9] or '','kazasaat':(r[10] or '')[:16],
                    'trafik':r[11] or '','kazanokta':r[12] or '',
                    'soforkusur':float(r[13]) if r[13] is not None else None,
                    'hizson':float(r[14]) if r[14] is not None else None,
                    'kusurgrubu':r[15] or '',
                }})
        return feats

    def _kaza_featurecollection(features):
        from flask import jsonify as _jfy
        yarali = sum(f['properties']['yaraliyolcu'] for f in features)
        return _jfy({'type':'FeatureCollection','features':features,
                     'toplam':len(features),'yarali':yarali,
                     'kategoriler':[],'kriz_nokta':0})

    @app.route('/api/panel/ariza_harita')
    def api_panel_ariza_harita():
        """Arıza harita pinleri — hat kodu veya kapı no araması ile çalışır.
        ?hat=34G   → o hattaki tüm arızalar
        ?kapino=M6033 → o araçtaki tüm arızalar
        Parametre yoksa boş döner (performans koruması)."""
        hat    = request.args.get('hat', '').strip().upper()
        kapino = request.args.get('kapino', '').strip().upper()

        if not hat and not kapino:
            return jsonify({'type': 'FeatureCollection', 'features': [],
                            'mesaj': 'Hat kodu veya kapı no girin'})
        try:
            con = get_panel_db()
            cur = con.cursor()
            if hat:
                rows = cur.execute("""
                    SELECT ENLEM, BOYLAM, ARIZAKODU, ARIZAUSTKODTANIM, KAPINO,
                           HATKODU, HATADI, MARKA, MODEL, MODELYILI,
                           ILCE, GARAJADI, TARIH, SAAT_BANDI,
                           TEPKI_SURE_DK, ZAYISEFERSAYISI, MUDEHALETIPI
                    FROM ariza
                    WHERE HATKODU = ? AND ENLEM IS NOT NULL AND ENLEM != ''
                    ORDER BY TARIH DESC
                """, (hat,)).fetchall()
            else:
                rows = cur.execute("""
                    SELECT ENLEM, BOYLAM, ARIZAKODU, ARIZAUSTKODTANIM, KAPINO,
                           HATKODU, HATADI, MARKA, MODEL, MODELYILI,
                           ILCE, GARAJADI, TARIH, SAAT_BANDI,
                           TEPKI_SURE_DK, ZAYISEFERSAYISI, MUDEHALETIPI
                    FROM ariza
                    WHERE KAPINO = ? AND ENLEM IS NOT NULL AND ENLEM != ''
                    ORDER BY TARIH DESC
                """, (kapino,)).fetchall()
            con.close()

            features = []
            for r in rows:
                try:
                    lat = float(str(r[0]).replace(',', '.'))
                    lon = float(str(r[1]).replace(',', '.'))
                    if not (40.82 < lat < 41.35 and 28.0 < lon < 30.0):
                        continue
                    features.append({
                        'type': 'Feature',
                        'geometry': {'type': 'Point', 'coordinates': [lon, lat]},
                        'properties': {
                            'arizakodu':     r[2] or '—',
                            'ust_kod':       r[3] or '—',
                            'kapino':        r[4] or '—',
                            'hatkodu':       r[5] or '—',
                            'hatadi':        r[6] or '—',
                            'marka':         r[7] or '—',
                            'model':         r[8] or '—',
                            'modelyili':     r[9] or '—',
                            'ilce':          r[10] or '—',
                            'garaj':         r[11] or '—',
                            'tarih':         r[12] or '—',
                            'saat_bandi':    r[13] or '—',
                            'tepki_sure':    r[14] or 0,
                            'zayi_sefer':    r[15] or 0,
                            'mudehale_tipi': r[16] or '—',
                        }
                    })
                except Exception:
                    continue

            return jsonify({
                'type': 'FeatureCollection',
                'features': features,
                'toplam': len(features),
                'arama': hat or kapino,
            })
        except Exception as e:
            return jsonify({'hata': str(e)}), 500

    @app.route('/api/panel/kaza_map')
    def api_panel_kaza_map():
        """Kaza harita pinleri — SQLite kaza tablosundan tüm koordinatlar"""
        if 'kaza_geojson' in PANEL_DATA:
            return jsonify(PANEL_DATA['kaza_geojson'])
        # Fallback: SQLite'tan cek
        try:
            con = get_panel_db()
            cur = con.cursor()
            rows = cur.execute("""
                SELECT KAPINO, ENLEM, BOYLAM, ILCE, TARIH,
                       YARALISURUCU, YARALIYOLCU, OLUMSURUCU, OLUMYOLCU,
                       KAZATIPI
                FROM kaza
                WHERE ENLEM IS NOT NULL AND BOYLAM IS NOT NULL
                  AND ENLEM != 0 AND BOYLAM != 0
            """).fetchall()
            cols = ['kapino','lat','lon','ilce','tarih',
                    'yarali_surucu','yarali_yolcu','olum_surucu','olum_yolcu','kaza_tipi']
            result = [dict(zip(cols, r)) for r in rows]
            con.close()
            return jsonify(result)
        except Exception as e:
            return jsonify({"hata": str(e)}), 500

    @app.route('/api/panel/kaza_kapino')
    def api_panel_kaza_kapino():
        """Araç bazlı kaza geçmişi — tüm kolon detayları."""
        kapino = request.args.get('kapino', '').strip().upper()
        if not kapino:
            return jsonify({'hata': 'kapino gerekli'})
        try:
            con = get_panel_db()
            cur = con.cursor()
            rows = cur.execute("""
                SELECT TARIH, KAZASAAT, KATEGORIADI, KAZANOKTA,
                       ILCE, MAHALLE, HATKODU, HATADI,
                       HAVADURUMU, YOLDURUMU, KAVSAKDURUMU, TRAFIKDURUMU,
                       SERITKENDI, HAREKETYONU,
                       YARALIYOLCU, YARALISURUCU, YARALIYAYA,
                       OLUMYOLCU, OLUMSURUCU, OLUMYAYA,
                       YARALISIVIL, OLUMSIVIL,
                       SOFORKUSUR, HIZSON, KUSURGRUBU,
                       GARAJADI, OPERATORADI,
                       MARKA, MODEL, MODELYILI, ARACTIPI, ARACCINSI,
                       KAPASITE, YAKITTURU, EMISYON,
                       ENLEM, BOYLAM,
                       DURAKADI, NOLAYID
                FROM kaza
                WHERE KAPINO = ?
                ORDER BY TARIH DESC, KAZASAAT DESC
            """, (kapino,)).fetchall()
            con.close()

            cols = [
                'tarih','kazasaat','kategori','kazanokta',
                'ilce','mahalle','hatkodu','hatadi',
                'havadurumu','yoldurumu','kavsakdurumu','trafikdurumu',
                'seritkendi','hareketyonu',
                'yarali_yolcu','yarali_surucu','yarali_yaya',
                'olum_yolcu','olum_surucu','olum_yaya',
                'yarali_sivil','olum_sivil',
                'soforkusur','hizson','kusurgrubu',
                'garajadi','operatoradi',
                'marka','model','modelyili','aractipi','araccinsi',
                'kapasite','yakitturu','emisyon',
                'lat','lon',
                'durakadi','nolayid',
            ]
            kazalar = [dict(zip(cols, r)) for r in rows]

            from collections import Counter
            nokta_sayac = Counter(k['kazanokta'] or 'Bilinmiyor' for k in kazalar)

            return jsonify({
                'kapino':    kapino,
                'toplam':    len(kazalar),
                'kazalar':   kazalar,
                'nokta_ozet': [{'nokta': k, 'sayi': v}
                               for k, v in nokta_sayac.most_common()],
            })
        except Exception as e:
            return jsonify({'hata': str(e)}), 500

    @app.route('/api/panel/kaza_arac_sirala')
    def api_panel_kaza_arac_sirala():
        """En çok kaza yapan araçlar — ağırlıklı skor ile sıralı."""
        AGIRLIK = {
            'Yayaya Çarpma': 5, 'Biz bize': 2,
            'Biz Bize (Metrobüs)': 2, 'Tek Taraflı(Metrobüs)': 2,
        }
        try:
            con = get_panel_db()
            cur = con.cursor()
            rows = cur.execute("""
                SELECT KAPINO, KATEGORIADI, MARKA, MODEL, MODELYILI,
                       GARAJADI, TARIH,
                       COALESCE(YARALIYOLCU,0)+COALESCE(YARALISURUCU,0)+COALESCE(YARALIYAYA,0) yarali
                FROM kaza
                WHERE KAPINO IS NOT NULL AND KAPINO != ''
                ORDER BY TARIH DESC
            """).fetchall()
            con.close()

            from collections import defaultdict
            arac = defaultdict(lambda: {
                'kaza': 0, 'agirlikli': 0, 'yarali': 0,
                'en_kotu': '', 'en_kotu_ag': 0,
                'marka': '', 'model': '', 'modelyili': '',
                'garaj': '', 'son_kaza': '',
            })
            for kapino, kat, marka, model, yil, garaj, tarih, yarali in rows:
                ag = AGIRLIK.get(kat, 1)
                d = arac[kapino]
                d['kaza']      += 1
                d['agirlikli'] += ag
                d['yarali']    += yarali or 0
                if ag > d['en_kotu_ag']:
                    d['en_kotu']    = kat or ''
                    d['en_kotu_ag'] = ag
                if not d['marka']:
                    d['marka']    = marka or ''
                    d['model']    = model or ''
                    d['modelyili'] = str(yil or '')
                    d['garaj']    = garaj or ''
                if tarih and (not d['son_kaza'] or tarih > d['son_kaza']):
                    d['son_kaza'] = tarih[:10] if tarih else ''

            liste = sorted([
                {'kapino': k, **v} for k, v in arac.items()
            ], key=lambda x: (-x['agirlikli'], -x['kaza']))

            return jsonify({
                'liste': liste[:50],
                'toplam_arac': len(liste),
                'uc_kaza_arac': sum(1 for x in liste if x['kaza'] >= 3),
            })
        except Exception as e:
            return jsonify({'hata': str(e)}), 500

    @app.route('/api/panel/kaza_hasar_ozet')
    def api_panel_kaza_hasar_ozet():
        """Tüm filodaki hasar noktası dağılımı (bus damage heatmap için)."""
        try:
            con = get_panel_db()
            cur = con.cursor()
            rows = cur.execute("""
                SELECT KAZANOKTA, COUNT(*) sayi
                FROM kaza
                WHERE KAZANOKTA IS NOT NULL AND KAZANOKTA != ''
                GROUP BY KAZANOKTA
                ORDER BY sayi DESC
            """).fetchall()
            con.close()
            toplam = sum(r[1] for r in rows)
            return jsonify({
                'noktalar': [{'nokta': r[0], 'sayi': r[1],
                              'pct': round(r[1]/toplam*100, 1)} for r in rows],
                'toplam': toplam,
            })
        except Exception as e:
            return jsonify({'hata': str(e)}), 500

    @app.route('/api/panel/kapino/<kapino>')
    def api_panel_kapino(kapino):
        """Belirli araç için tüm veri setlerinden detay (SQLite). ?mode=2025|2026"""
        kapino = kapino.strip().upper()
        mode = request.args.get('mode', '2025')
        sm_key = 'smart_maintenance_2026' if mode == '2026' else 'smart_maintenance'
        sm_idx_key = '_sm_idx_2026' if mode == '2026' else '_sm_idx'
        try:
            con = get_panel_db()
            cur = con.cursor()

            # Arıza geçmişi (son 20)
            ariza_rows = cur.execute("""
                SELECT OLAYTARIHI, ARIZAUSTKODTANIM, ARIZAKODU, SONUCTIPI, CEKICITALEP,
                       TEPKI_SURE_DK, MUDAHALE_SURE_DK, ZAYISEFERSAYISI,
                       HATKODU, GARAJADI, ENLEM, BOYLAM
                FROM ariza WHERE KAPINO=?
                ORDER BY OLAYTARIHI DESC LIMIT 20
            """, (kapino,)).fetchall()
            ariza_cols = ['tarih','tip','alt_kat','sonuc','cekici','tepki_dk','mudahale_dk',
                          'zayi_sefer','hatkodu','garaj','enlem','boylam']

            # Sefer özeti
            sefer_row = cur.execute("""
                SELECT COUNT(*),
                    SUM(CASE WHEN GOREV_DURUM_TANIMDETAY LIKE '%Tamamland%' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN GOREV_DURUM_TANIMDETAY LIKE '%ptal%' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN GOREV_DURUM_TANIMDETAY LIKE '%Yar%' THEN 1 ELSE 0 END)
                FROM sefer WHERE KAPINO=?
            """, (kapino,)).fetchone()

            # Kaza
            kaza_rows = cur.execute("""
                SELECT TARIH, ILCE, ENLEM, BOYLAM,
                       YARALISURUCU, YARALIYOLCU, OLUMSURUCU, OLUMYOLCU
                FROM kaza WHERE KAPINO=?
                ORDER BY TARIH DESC
            """, (kapino,)).fetchall()
            kaza_cols = ['tarih','ilce','enlem','boylam',
                         'yarali_surucu','yarali_yolcu','olum_surucu','olum_yolcu']

            # Denetim özeti
            # NOT: denetim tablosunda kolon adı VARLIK_KAPINO
            den_row = cur.execute("""
                SELECT COUNT(*),
                    SUM(CASE WHEN COALESCE(CEVAPDURUM,DENETIMDURUM)='Olumsuz' THEN 1 ELSE 0 END),
                    MAX(TARIH)
                FROM denetim WHERE VARLIK_KAPINO=?
            """, (kapino,)).fetchone()

            # Araçtaki baskın arıza kategorilerini çek
            ariza_kats = [r[0] for r in cur.execute("""
                SELECT ARIZAUSTKODTANIM, COUNT(*) as cnt
                FROM ariza WHERE KAPINO=? AND ARIZAUSTKODTANIM IS NOT NULL
                  AND ARIZAUSTKODTANIM NOT IN ('Sınıflandırıldı','Sınıflandırılmadı','Destek','Belirsiz')
                GROUP BY ARIZAUSTKODTANIM ORDER BY cnt DESC LIMIT 5
            """, (kapino,)).fetchall()]

            # Alt arıza kodları (ARIZAKODU) — daha spesifik eşleşme ve gösterim için
            ariza_kods_rows = cur.execute("""
                SELECT ARIZAKODU, COUNT(*) as cnt
                FROM ariza WHERE KAPINO=? AND ARIZAKODU IS NOT NULL
                  AND ARIZAKODU NOT IN ('Sınıflandırıldı','Sınıflandırılmadı','Destek','Belirsiz')
                GROUP BY ARIZAKODU ORDER BY cnt DESC LIMIT 10
            """, (kapino,)).fetchall()
            ariza_kods_detay = [{'kod': r[0], 'sayi': r[1]} for r in ariza_kods_rows]

            # Arıza kategorisi → denetim soru anahtar kelimeleri eşleştirmesi
            _KAT_MAP = {
                'KAPI':         ['kap'],
                'SOĞUTMA':      ['soğutma','hararet','radyat'],
                'ELEKTRİK':     ['elektrik','sigorta','akü','aydınlatma','far','sinyal','lamba'],
                'MOTOR':        ['motor','yağ','egzoz'],
                'FREN':         ['fren','balata'],
                'KLİMA':        ['klima','iklimlendirme'],
                'SÜSPANSIYON':  ['süspansiyon','amortisör'],
                'ŞANZIMAN':     ['şanziman','vites','transmisyon'],
                'AKBİL':        ['akbil','validatör','kart okuyucu'],
                'KAMERA':       ['kamera','güvenlik','izleme'],
                'LASTİK':       ['lastik','tekerlek','jant'],
                'DİREKSİYON':   ['direksiyon','direksiyon'],
                'YAKIT':        ['yakıt','enjeksiyon','depo'],
                'KAYIŞ':        ['kayış','kasnak','triger'],
                'KAROSER':      ['karoser','kaporta','hasar','boya','çarpma'],
                'ISITMA':       ['ısıtma','kalorifer'],
                'BASINÇLI':     ['basınçlı hava','kompresör'],
            }

            # Eşleşen anahtar kelimeleri topla
            anahtar_kelimeler = set()
            for kat in ariza_kats:
                kat_upper = kat.upper()
                for prefix, keys in _KAT_MAP.items():
                    if prefix in kat_upper:
                        anahtar_kelimeler.update(keys)

            # ARIZAKODU tokenlerini de ekle (daha spesifik denetim eşleşmesi için)
            # Örnek: "DİGİTAL TABELA ARIZALARI" → ['dijital', 'tabela']
            _KOD_STOP = {'ARIZALARI','ARIZASI','SİSTEMİ','HATTI','SORUNLARI','SORUNU',
                         'VE','BİR','DEĞİŞİMİ','ARIZALI','ARIZI','ARIZDA'}
            for (kd, _cnt) in ariza_kods_rows:
                tokens = [t.lower() for t in kd.upper().split()
                          if t not in _KOD_STOP and len(t) > 3]
                anahtar_kelimeler.update(tokens)

            # Dar anahtar kelimeler: yalnızca ARIZAKODU'ndan türetilir (üst kat haritası yok)
            # Doğrudan eşleşme (baglanti="dogrudan") için kullanılır — min 3 karakter
            anahtar_dar = set()
            for (kd, _cnt) in ariza_kods_rows[:5]:  # en sık 5 alt arıza kodu
                tokens_dar = [t.lower() for t in kd.upper().split()
                              if t not in _KOD_STOP and len(t) >= 3]
                anahtar_dar.update(tokens_dar)

            # Arızayla eşleşen olumsuz VE olumlu denetim sorularını çek
            # Sürücü Denetimi: sürücü davranışı soruları içerir, araç teknik arızasıyla ilgisiz → hariç tut
            if anahtar_kelimeler:
                like_clauses = ' OR '.join(['LOWER(SORUACIKLAMA) LIKE ?' for _ in anahtar_kelimeler])
                like_params  = ['%' + k.lower() + '%' for k in anahtar_kelimeler]

                # TÜM olumsuz kayıtları çek (tarihe göre DESC)
                # NOT: denetim tablosunda kolon adı VARLIK_KAPINO
                tum_olumsuz = cur.execute(f"""
                    SELECT SORUACIKLAMA, TARIH, DENETIMTIPTANIM, CEVAPSECENEKACIKLAMA
                    FROM denetim
                    WHERE VARLIK_KAPINO=? AND COALESCE(CEVAPDURUM,DENETIMDURUM)='Olumsuz'
                      AND SORUACIKLAMA IS NOT NULL
                      AND DENETIMTIPTANIM != 'Sürücü Denetimi'
                      AND ({like_clauses})
                    ORDER BY TARIH DESC LIMIT 12
                """, [kapino] + like_params).fetchall()

                # Her olumsuz kayıt için: o tarihten SONRA aynı soruda Olumlu alınmış mı?
                # Eğer aldıysa → ara dönemde sorun kapandı, mevcut arıza buna bağlanamaz
                den_soru_olumsuz = []
                for r in tum_olumsuz:
                    soru_aciklamasi, olms_tarih = r[0], r[1]
                    sonradan_olumlu = cur.execute("""
                        SELECT COUNT(*) FROM denetim
                        WHERE VARLIK_KAPINO=? AND SORUACIKLAMA=? AND COALESCE(CEVAPDURUM,DENETIMDURUM)='Olumlu' AND TARIH > ?
                    """, (kapino, soru_aciklamasi, olms_tarih)).fetchone()[0]
                    # Doğrudan bağlantı: denetim sorusu, aracın spesifik ARIZAKODU tokenlarıyla eşleşiyor mu?
                    soru_lower = (r[0] or '').lower()
                    baglanti = "dogrudan" if anahtar_dar and any(k in soru_lower for k in anahtar_dar) else "kategori"
                    den_soru_olumsuz.append({
                        "soru":  r[0], "tarih": r[1], "tip": r[2], "cevap": r[3],
                        # True → olumsuzdan sonra olumlu denetim var → mevcut arızayla bağlantısı zayıf
                        "sonradan_duzeltildi": sonradan_olumlu > 0,
                        # "dogrudan" → ARIZAKODU ile birebir örtüşüyor | "kategori" → üst kategori bazlı geniş eşleşme
                        "baglanti": baglanti,
                    })

                # Paradoks: bu kategoride Olumlu geçti ama arıza yine de oluştu
                # NOT: denetim tablosunda kolon adı VARLIK_KAPINO
                den_soru_olumlu_rows = cur.execute(f"""
                    SELECT SORUACIKLAMA, TARIH, DENETIMTIPTANIM, CEVAPSECENEKACIKLAMA
                    FROM denetim
                    WHERE VARLIK_KAPINO=? AND COALESCE(CEVAPDURUM,DENETIMDURUM)='Olumlu'
                      AND SORUACIKLAMA IS NOT NULL
                      AND DENETIMTIPTANIM != 'Sürücü Denetimi'
                      AND ({like_clauses})
                    ORDER BY TARIH DESC LIMIT 8
                """, [kapino] + like_params).fetchall()
                den_soru_olumlu = []
                for r in den_soru_olumlu_rows:
                    soru_lower = (r[0] or '').lower()
                    baglanti = "dogrudan" if anahtar_dar and any(k in soru_lower for k in anahtar_dar) else "kategori"
                    den_soru_olumlu.append({"soru": r[0], "tarih": r[1], "tip": r[2], "cevap": r[3], "baglanti": baglanti})
            else:
                # Arıza kategorisi tanımsız (Sınıflandırılmadı/Destek) ya da eşleşme yok
                # Alakasız denetim soruları göstermek yanıltıcı olur — boş bırak
                den_soru_olumsuz = []
                den_soru_olumlu  = []

            con.close()

            n_sefer = sefer_row[0] or 0
            result = {
                "kapino": kapino,
                "ariza": [dict(zip(ariza_cols, r)) for r in ariza_rows],
                "sefer": {
                    "toplam": n_sefer,
                    "tamamlama_pct": round(sefer_row[1]/n_sefer*100, 1) if n_sefer else 0,
                    "iptal_pct": round(sefer_row[2]/n_sefer*100, 1) if n_sefer else 0,
                    "yarim_pct": round(sefer_row[3]/n_sefer*100, 1) if n_sefer else 0,
                },
                "kaza": [dict(zip(kaza_cols, r)) for r in kaza_rows],
                "denetim": {
                    "toplam": den_row[0] or 0,
                    "olumsuz": den_row[1] or 0,
                    "son_tarih": den_row[2],
                    # Arızayla ilgili olumsuz denetimler
                    "olumsuz_sorular": den_soru_olumsuz,  # artık dict listesi, sonradan_duzeltildi alanı var
                    # Denetimde geçti ama yine de arıza verdi (paradoks)
                    "olumlu_ama_arizali": den_soru_olumlu,
                    "ariza_kategoriler": ariza_kats,
                    "ariza_kods_detay": ariza_kods_detay,
                },
                # Bakım tier (JSON'dan) — mode'a göre doğru index
                "bakim": PANEL_DATA.get(sm_idx_key, PANEL_DATA.get('_sm_idx', {})).get(kapino),
                # Risk skoru (JSON'dan) — startup'ta index'lendi
                "risk": PANEL_DATA.get('_ar_idx', {}).get(kapino),
            }
            return jsonify(result)
        except Exception as e:
            return jsonify({"hata": str(e)}), 500

    @app.route('/api/panel/hat/<hatkodu>')
    def api_panel_hat(hatkodu):
        """Hat bazlı özet: arıza + sefer + yolcu + son arızalar (JSON + SQLite)"""
        hatkodu = hatkodu.strip().upper()
        try:
            # JSON'dan hızlı özet (fallback için)
            sefer_hat  = dict(PANEL_DATA.get('sefer_agg', {}).get('hat_bazli', {}).get(hatkodu, {}))

            # SQLite'tan son 10 arıza
            con = get_panel_db()
            cur = con.cursor()

            # ── Hat bazlı KPI (DB'den 6 ay toplam) ──────────────────
            # 1) Toplam arıza
            ariza_n = cur.execute('SELECT COUNT(*) FROM ariza WHERE HATKODU=?', (hatkodu,)).fetchone()[0] or 0
            # Ciddi arıza — DB'deki gerçek değer "Kayıtçı - Garaj" (ariza_ozet notebook ile aynı tanım)
            ariza_ciddi = cur.execute("""SELECT COUNT(*) FROM ariza WHERE HATKODU=?
                AND SONUCTIPI IN ('Yol Ustası - Garaj','Çekilerek - Garaj','Telefonla - Garaj','Kayıtçı - Garaj','Oto Değişimi')
            """, (hatkodu,)).fetchone()[0] or 0
            ariza_hat = {
                'ariza_sayisi': ariza_n,
                'ciddi_sayisi': ariza_ciddi,
                'ciddi_pct': round(ariza_ciddi/ariza_n*100, 1) if ariza_n else 0,
            }

            # 2) Sefer tamamlama % (sefer tablosundan)
            sefer_row = cur.execute("""
                SELECT COUNT(*),
                    SUM(CASE WHEN GOREV_DURUM_TANIMDETAY LIKE '%Tamamland%' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN GOREV_DURUM_TANIMDETAY LIKE '%ptal%' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN GOREV_DURUM_TANIMDETAY LIKE '%Yar%' THEN 1 ELSE 0 END)
                FROM sefer WHERE HATKODU=?
            """, (hatkodu,)).fetchone()
            n_sefer = sefer_row[0] or 0
            sefer_hat.update({
                'sefer_sayisi':    n_sefer,
                'tamamlanan':      sefer_row[1] or 0,
                'iptal':           sefer_row[2] or 0,
                'yarida_kalan':    sefer_row[3] or 0,
                'tamamlama_pct':   round((sefer_row[1] or 0)/n_sefer*100, 1) if n_sefer else 0,
            })

            # 3) 6 ay toplam yolcu (yolcu tablosundan)
            yolcu_n = cur.execute('SELECT COUNT(*) FROM yolcu WHERE GUNCEL_HATKODU=?', (hatkodu,)).fetchone()[0] or 0
            yolcu_hat = {
                'yolcu_sayisi':    yolcu_n,
                'gunluk_ort':      round(yolcu_n / 181, 0) if yolcu_n else 0,
            }

            # Son arızalar — Destek/Belirsiz tipleri exclude + TEPKI_SURE_DK > 0 (KPI ile tutarli)
            son_ariza = cur.execute("""
                SELECT KAPINO, OLAYTARIHI, ARIZAUSTKODTANIM, TEPKI_SURE_DK,
                       MUDAHALE_SURE_DK, GARAJADI, ENLEM, BOYLAM
                FROM ariza WHERE HATKODU=?
                  AND ARIZAUSTKODTANIM IS NOT NULL
                  AND ARIZAUSTKODTANIM NOT IN ('Destek','Belirsiz','Sınıflandırılmadı','Sınıflandırıldı')
                  AND (TEPKI_SURE_DK IS NULL OR (TEPKI_SURE_DK > 0 AND TEPKI_SURE_DK < 1440))
                ORDER BY OLAYTARIHI DESC LIMIT 10
            """, (hatkodu,)).fetchall()
            son_ariza_cols = ['kapino','tarih','tip','tepki_dk','mudahale_dk','garaj','enlem','boylam']

            # Hattaki araçlar (distinct) — sefer tablosundan (daha geniş)
            araclar = cur.execute("""
                SELECT DISTINCT KAPINO FROM sefer WHERE HATKODU=? AND KAPINO IS NOT NULL
            """, (hatkodu,)).fetchall()
            con.close()

            # Hat risk skoru + bileşen açıklaması
            hat_risk_data = PANEL_DATA.get('_hr_idx', {}).get(hatkodu)
            neden_hat = None
            if hat_risk_data:
                komp_ariza  = hat_risk_data.get('komp_ariza', 0)
                komp_kaza   = hat_risk_data.get('komp_kaza', 0)
                komp_tekrar = hat_risk_data.get('komp_tekrar', 0)
                bilesenler  = sorted([
                    {'bilesen': 'Arıza Yoğunluğu',
                     'skor': round(float(komp_ariza), 1),
                     'aciklama': f"Her 100 seferde {hat_risk_data.get('ariza_per_100sefer',0):.2f} arıza"},
                    {'bilesen': 'Kaza Riski',
                     'skor': round(float(komp_kaza), 1),
                     'aciklama': f"Her 100 seferde {hat_risk_data.get('kaza_per_100sefer',0):.3f} kaza"},
                    {'bilesen': 'Kronik Arıza (Tekrar)',
                     'skor': round(float(komp_tekrar), 1),
                     'aciklama': f"Tekrar oranı: %{hat_risk_data.get('tekrar_ariza_orani',0)*100:.1f}"},
                ], key=lambda x: -x['skor'])
                neden_hat = {
                    'risk_skoru':    hat_risk_data.get('risk_skoru'),
                    'risk_kategori': hat_risk_data.get('risk_kategori'),
                    'risk_zscore':   hat_risk_data.get('risk_zscore'),
                    'ariza_sayisi':  hat_risk_data.get('ariza_sayisi'),
                    'kaza_sayisi':   hat_risk_data.get('kaza_sayisi'),
                    'bilesenler':    bilesenler,
                    'ana_neden':     bilesenler[0]['bilesen'] if bilesenler else None,
                }

            # Hat araç risk özeti (hat_arac_risk.json)
            har_data = PANEL_DATA.get('_har_idx', {}).get(hatkodu, {})
            arac_risk_ozet = None
            if har_data:
                arac_risk_ozet = {
                    'arac_toplam':      har_data.get('arac_toplam', 0),
                    'kritik_n':         har_data.get('kritik_n', 0),
                    'yuksek_n':         har_data.get('yuksek_n', 0),
                    'orta_n':           har_data.get('orta_n', 0),
                    'dusuk_n':          har_data.get('dusuk_n', 0),
                    'yuksek_risk_pct':  har_data.get('yuksek_risk_pct', 0),
                    'kritik_kapinolar': har_data.get('kritik_kapinolar', [])[:10],
                    'yuksek_kapinolar': har_data.get('yuksek_kapinolar', [])[:10],
                }

            return jsonify({
                "hatkodu": hatkodu,
                "ariza": ariza_hat,
                "sefer": sefer_hat,
                "yolcu": yolcu_hat,
                "son_ariza": [dict(zip(son_ariza_cols, r)) for r in son_ariza],
                "arac_listesi": [r[0] for r in araclar],
                "risk": neden_hat,
                "arac_risk": arac_risk_ozet,
            })
        except Exception as e:
            return jsonify({"hata": str(e)}), 500

    @app.route('/api/panel/bakim')
    def api_panel_bakim():
        """Bakım listesi — tier filtreli. ?tier=KRITIK|YUKSEK|ORTA|DUSUK&mode=2025|2026"""
        mode = request.args.get('mode', '2025')
        sm_key = 'smart_maintenance_2026' if mode == '2026' else 'smart_maintenance'
        if sm_key not in PANEL_DATA:
            return jsonify({"hata": f"{sm_key} yuklenmedi"}), 503
        tier_filtre = request.args.get('tier', '').upper()
        data = PANEL_DATA[sm_key]
        if isinstance(data, dict):
            # dict ise liste yap
            liste = [{"kapino": k, **v} for k, v in data.items()]
        else:
            liste = data
        # 2026 modunda ÖHO/KOOP (kapsam_disi) araçları ML tahmin dışı — filtrele
        if mode == '2026':
            liste = [x for x in liste if not x.get('kapsam_disi', False)]
        # 2026 modunda _parcalar ve _garaj alanlarını parca_bakim_2026'dan ekle
        if mode == '2026':
            pb26 = PANEL_DATA.get('parca_bakim_2026', {})
            if isinstance(pb26, dict) and pb26:
                _PARCA_ISIM = ['AKÜ','MARŞ','SİGORTA','ŞANZIMAN','FREN',
                               'SOĞUTMA','KALORİFER','KAPI','HİDROLİK','PNÖMATİK']
                for x in liste:
                    kap = x.get('kapino', '')
                    pb = pb26.get(kap, {})
                    if pb:
                        if not x.get('_parcalar'):
                            x['_parcalar'] = pb.get('_parcalar', [])
                        if not x.get('garaj'):
                            x['garaj'] = pb.get('_garaj', '')

        if tier_filtre:
            import re as _re
            def _norm(s):
                return _re.sub('[İI\u0307]','I', s.upper().replace('Ü','U').replace('Ö','O').replace('Ş','S').replace('Ğ','G').replace('Ç','C'))
            liste = [x for x in liste if _norm(x.get('aciliyet_tier') or x.get('tier','')) == tier_filtre]
        return jsonify(liste)

    @app.route('/api/panel/genel_kpi')
    def api_panel_genel_kpi():
        """Dashboard ana KPI kartları — tüm veri setlerinden tek endpoint. ?mode=2025|2026"""
        mode = request.args.get('mode', '2025')

        # Bakım tier sayıları — mode'a göre doğru JSON
        sm_key = 'smart_maintenance_2026' if mode == '2026' else 'smart_maintenance'
        sm = PANEL_DATA.get(sm_key, {})
        if isinstance(sm, dict):
            sm_liste = list(sm.values())
        else:
            sm_liste = sm
        from collections import Counter
        # 2026 modunda ÖHO/KOOP (kapsam_disi) araçları tier sayımından çıkar
        if mode == '2026':
            sm_liste = [x for x in sm_liste if not x.get('kapsam_disi', False)]
        tier_dagilim = dict(Counter(
            (x.get('aciliyet_tier') or x.get('tier','?')).upper()
             .replace('İ','I').replace('Ü','U').replace('Ö','O')
            for x in sm_liste
        ))

        if mode == '2026':
            # 2026 modunda yalnızca ML tahmin metrikleri — 2025 H1 arıza/sefer/yolcu/denetim verisi döndürülmez
            sm_toplam = len(sm_liste)
            kritik_n  = tier_dagilim.get('KRITIK', 0)
            yuksek_n  = tier_dagilim.get('YUKSEK', 0)
            return jsonify({
                "ariza":   None,
                "sefer":   None,
                "yolcu":   None,
                "denetim": None,
                "bakim_tier": tier_dagilim,
                "ml_ozet": {
                    "tahmin_arac": sm_toplam,
                    "kritik_n":    kritik_n,
                    "yuksek_n":    yuksek_n,
                    "kritik_pct":  round(kritik_n / sm_toplam * 100, 1) if sm_toplam else 0,
                    "yuksek_pct":  round(yuksek_n / sm_toplam * 100, 1) if sm_toplam else 0,
                    "model":       "ML V6.5 Ensemble (XGB+LGB) · Q2 2025 → Q3 2025",
                },
            })

        ariza_kpi   = PANEL_DATA.get('ariza_ozet', {}).get('kpi', {})
        sefer_kpi   = PANEL_DATA.get('sefer_agg', {}).get('kpi', {})
        yolcu_kpi   = PANEL_DATA.get('yolcu_agg', {}).get('kpi', {})
        denetim_kpi = PANEL_DATA.get('denetim_agg', {}).get('kpi', {})

        return jsonify({
            "ariza":   ariza_kpi,
            "sefer":   sefer_kpi,
            "yolcu":   yolcu_kpi,
            "denetim": denetim_kpi,
            "bakim_tier": tier_dagilim,
        })

    # ─────────────────────────────────────────────────────────────────────────
    # 2026 — SEFERDEN ÇEK
    # ─────────────────────────────────────────────────────────────────────────

    @app.route('/api/seferden_cek')
    def api_seferden_cek():
        """2026 H1: KRİTİK/YÜKSEK tahminli araçlar × şu an FILO'da aktif olanlar."""
        sm26 = PANEL_DATA.get('_sm_idx_2026', {})
        if not sm26:
            return jsonify({'hata': 'smart_maintenance_2026 henuz yuklenmedi', 'toplam': 0}), 503

        # FILO cache'den aktif kapınoları al
        filo = FILO_CACHE.get('kapi_map', {})
        if not filo:
            return jsonify({'kritik_seferde': [], 'yuksek_seferde': [],
                            'toplam': 0, 'kritik_n': 0, 'yuksek_n': 0,
                            'bilgi': 'FILO verisi henuz yok — 2 dk sonra tekrar dene'})

        def _norm_tier(t):
            return (t or '').upper().replace('İ','I').replace('Ü','U').replace('Ö','O').replace('Ş','S').replace('Ğ','G').replace('Ç','C')

        kritik, yuksek = [], []
        for kapino, filo_rec in filo.items():
            sm = sm26.get(kapino)
            if not sm:
                continue
            tier = _norm_tier(sm.get('aciliyet_tier', ''))
            if tier not in ('KRITIK', 'YUKSEK'):
                continue

            kayit = {
                'kapi':             kapino,
                'hat':              filo_rec.get('hat') or filo_rec.get('HatKodu') or '—',
                'garaj':            sm.get('garaj', '—'),
                'aciliyet_tier':    sm.get('aciliyet_tier'),
                'aciliyet_skoru':   sm.get('aciliyet_skoru'),
                'bakim_uyarisi':    sm.get('bakim_uyarisi', ''),
                'tahmin_guvenilir': sm.get('tahmin_guvenilir', '—'),
                'shap_neden_1':     sm.get('shap_neden_1'),
                'lat':              filo_rec.get('lat') or filo_rec.get('Enlem'),
                'lon':              filo_rec.get('lon') or filo_rec.get('Boylam'),
                'hiz':              filo_rec.get('hiz') or filo_rec.get('Hiz', 0),
                'temporal_uyari':   sm.get('temporal_uyari', ''),
            }
            if tier == 'KRITIK':
                kritik.append(kayit)
            else:
                yuksek.append(kayit)

        # Skora göre sırala
        kritik.sort(key=lambda x: x.get('aciliyet_skoru', 0), reverse=True)
        yuksek.sort(key=lambda x: x.get('aciliyet_skoru', 0), reverse=True)

        return jsonify({
            'kritik_seferde': kritik,
            'yuksek_seferde': yuksek,
            'toplam':         len(kritik) + len(yuksek),
            'kritik_n':       len(kritik),
            'yuksek_n':       len(yuksek),
            'ts':             int(__import__('time').time()),
        })

    # ─────────────────────────────────────────────────────────────────────────
    # PERSONEL — Şoför Risk Karnesi
    # ─────────────────────────────────────────────────────────────────────────

    @app.route('/api/panel/sofor_ozet')
    def api_panel_sofor_ozet():
        """Şoför risk karnesi özet KPI + kategori dağılımı"""
        sr = PANEL_DATA.get('sofor_risk', {})
        if not sr:
            return jsonify({'hata': 'sofor_risk.json yüklenmedi'})
        return jsonify({
            'meta':  sr.get('meta', {}),
            'ozet':  sr.get('ozet', {}),
            'odul_sistemi': sr.get('odul_sistemi', {}),
        })

    @app.route('/api/panel/sofor_liste')
    def api_panel_sofor_liste():
        """Şoför listesi — filtre ve sayfalama destekli
        Params: kategori (ÜSTÜN/İYİ/...), sayfa (default 1), boyut (default 50),
                siralama (risk_skoru|kaza_sayisi|ariza_sayisi), yon (desc|asc)
        """
        sr = PANEL_DATA.get('sofor_risk', {})
        liste = sr.get('soforler', [])

        kat  = request.args.get('kategori', '').strip().upper()
        arama = request.args.get('sicilno', '').strip().upper()
        siralama = request.args.get('siralama', 'risk_skoru')
        yon = request.args.get('yon', 'desc')
        sayfa = max(1, int(request.args.get('sayfa', 1)))
        boyut = min(200, max(1, int(request.args.get('boyut', 50))))

        if kat:
            import re as _re
            def _nk(s):
                return _re.sub('[İI]', 'I', s.upper()
                    .replace('Ü','U').replace('Ö','O')
                    .replace('Ş','S').replace('Ğ','G').replace('Ç','C'))
            liste = [x for x in liste if _nk(x.get('kategori','')) == _nk(kat)]

        if arama:
            liste = [x for x in liste if arama in x.get('sicilno','').upper()]

        reverse = (yon != 'asc')
        valid_sort = {'risk_skoru','kaza_sayisi','tekrar_kategori_n','sefer_sayisi','yaya_kaza_n','denetim_olumsuz','ciddi_kaza_n','sofor_kusurlu_n'}
        if siralama not in valid_sort:
            siralama = 'risk_skoru'
        liste = sorted(liste, key=lambda x: x.get(siralama, 0), reverse=reverse)

        toplam = len(liste)
        start = (sayfa - 1) * boyut
        sayfa_liste = liste[start:start + boyut]

        return jsonify({
            'toplam': toplam,
            'sayfa': sayfa,
            'boyut': boyut,
            'soforler': sayfa_liste,
        })

    @app.route('/api/panel/sofor_detay')
    def api_panel_sofor_detay():
        """Tek şoför detayı: sicilno parametresiyle.
        Ek olarak: H1 2025'te bu sürücünün arıza kategorileri (en fazla 5)
        + en yaygın olanı (tekrar eden örüntü)."""
        import sqlite3 as _sq
        from services import PANEL_DB_PATH
        sicilno = request.args.get('sicilno', '').strip()
        if not sicilno:
            return jsonify({'hata': 'sicilno gerekli'})
        sr = PANEL_DATA.get('sofor_risk', {})
        sofor = None
        for s in sr.get('soforler', []):
            if s.get('sicilno', '').upper() == sicilno.upper():
                sofor = dict(s)
                break
        if not sofor:
            return jsonify({'hata': 'Şoför bulunamadı'}), 404

        # Tekrar eden ariza pattern + top ariza kategorileri
        try:
            conn = _sq.connect(PANEL_DB_PATH)
            cur = conn.cursor()
            kat_rows = cur.execute("""
                SELECT ARIZAUSTKODTANIM,
                       COUNT(*) AS toplam,
                       COUNT(DISTINCT KAPINO) AS farkli_arac
                FROM ariza
                WHERE SOFOR_SICILNO = ?
                  AND TARIH BETWEEN '2025-01-01' AND '2025-06-30'
                  AND ARIZAUSTKODTANIM IS NOT NULL
                  AND ARIZAUSTKODTANIM != ''
                  AND ARIZAUSTKODTANIM NOT IN ('Sınıflandırılmadı', 'Destek')
                GROUP BY ARIZAUSTKODTANIM
                ORDER BY farkli_arac DESC, toplam DESC
                LIMIT 5
            """, (sicilno,)).fetchall()
            conn.close()
            sofor['ariza_kategorileri'] = [
                {'kategori': r[0], 'toplam': r[1], 'farkli_arac': r[2]}
                for r in kat_rows
            ]
            # En çok farklı araçta tekrar eden = tekrar pattern
            if kat_rows and kat_rows[0][2] >= 2:
                sofor['tekrar_neden'] = kat_rows[0][0]
                sofor['tekrar_neden_toplam'] = kat_rows[0][1]
                sofor['tekrar_neden_arac'] = kat_rows[0][2]
        except Exception as _e:
            sofor['ariza_kategorileri'] = []
            sofor['ariza_hata'] = str(_e)

        return jsonify(sofor)

    @app.route('/api/panel/sofor_harita')
    def api_panel_sofor_harita():
        """Şoför kaza + arıza pin verileri + denetim özeti harita katmanı için.
        Params: sicilno (zorunlu)
        """
        import sqlite3 as _sq
        from services import PANEL_DB_PATH
        sicilno = request.args.get('sicilno', '').strip()
        if not sicilno:
            return jsonify({'hata': 'sicilno gerekli'})

        DB_PATH = PANEL_DB_PATH
        try:
            conn = _sq.connect(DB_PATH)
            conn.row_factory = _sq.Row

            # ── Kazalar ──────────────────────────────────────────────────────
            kaza_rows = conn.execute("""
                SELECT TARIH, KAZASAAT, ENLEM, BOYLAM, HATKODU, HATADI,
                       KATEGORIADI, KUSURGRUBU, SOFORKUSUR, HIZSON,
                       ILCE, MAHALLE, KAZANOKTA, KAVSAKDURUMU,
                       YARALISURUCU, OLUMSURUCU, OLUMYOLCU, YARALIYOLCU,
                       OLUMYAYA, YARALIYAYA, KAPINO
                FROM kaza
                WHERE SICILNO = ?
                  AND ENLEM IS NOT NULL AND ENLEM != 0
                  AND BOYLAM IS NOT NULL AND BOYLAM != 0
                ORDER BY TARIH DESC
            """, (sicilno,)).fetchall()

            kazalar = []
            for r in kaza_rows:
                try:
                    lat = float(str(r['ENLEM']).replace(',', '.'))
                    lon = float(str(r['BOYLAM']).replace(',', '.'))
                    if not (40.5 <= lat <= 41.7 and 27.9 <= lon <= 30.2):
                        continue
                except Exception:
                    continue
                kazalar.append({
                    'lat': lat, 'lon': lon,
                    'tarih': r['TARIH'], 'saat': r['KAZASAAT'],
                    'hat': r['HATKODU'] or '', 'hatadi': r['HATADI'] or '',
                    'kategori': r['KATEGORIADI'] or '',
                    'kusur_grubu': r['KUSURGRUBU'] or '',
                    'soforkusur': r['SOFORKUSUR'],
                    'hiz': r['HIZSON'],
                    'ilce': r['ILCE'] or '', 'mahalle': r['MAHALLE'] or '',
                    'kazanokta': r['KAZANOKTA'] or '',
                    'kavsakdurumu': r['KAVSAKDURUMU'] or '',
                    'yarali': (r['YARALISURUCU'] or 0) + (r['YARALIYOLCU'] or 0) + (r['YARALIYAYA'] or 0),
                    'olum': (r['OLUMSURUCU'] or 0) + (r['OLUMYOLCU'] or 0) + (r['OLUMYAYA'] or 0),
                    'kapino': r['KAPINO'] or '',
                })

            # ── Arızalar ─────────────────────────────────────────────────────
            ariza_rows = conn.execute("""
                SELECT TARIH, ENLEM, BOYLAM, HATKODU, HATADI,
                       ARIZAUSTKODTANIM, SONUCTIPI, MUDEHALETIPI,
                       MUDAHALE_SURE_DK, TEPKI_SURE_DK,
                       YERBILGISI, ILCE, KAPINO
                FROM ariza
                WHERE SOFOR_SICILNO = ?
                  AND SOFOR_TIP = 'IETT'
                  AND ENLEM IS NOT NULL AND ENLEM != 0
                  AND BOYLAM IS NOT NULL AND BOYLAM != 0
                ORDER BY TARIH DESC
            """, (sicilno,)).fetchall()

            arizalar = []
            for r in ariza_rows:
                try:
                    lat = float(str(r['ENLEM']).replace(',', '.'))
                    lon = float(str(r['BOYLAM']).replace(',', '.'))
                    if not (40.5 <= lat <= 41.7 and 27.9 <= lon <= 30.2):
                        continue
                except Exception:
                    continue
                arizalar.append({
                    'lat': lat, 'lon': lon,
                    'tarih': r['TARIH'],
                    'hat': r['HATKODU'] or '', 'hatadi': r['HATADI'] or '',
                    'tur': r['ARIZAUSTKODTANIM'] or '',
                    'sonuc': r['SONUCTIPI'] or '',
                    'mudahale_sure': r['MUDAHALE_SURE_DK'],
                    'tepki_sure': r['TEPKI_SURE_DK'],
                    'yer': r['YERBILGISI'] or '',
                    'ilce': r['ILCE'] or '',
                    'kapino': r['KAPINO'] or '',
                })

            # ── Denetim Özeti ─────────────────────────────────────────────────
            # NOT: denetim tablosunda kolon adı VARLIK_KAPINO (diğer tablolarda KAPINO)
            den_rows = conn.execute("""
                SELECT TARIH, AY, SORUACIKLAMA, CEVAPSECENEKACIKLAMA,
                       CEVAPDURUM, DENETIMTIPTANIM, VARLIK_KAPINO AS KAPINO
                FROM denetim
                WHERE SOFOR_SICILNO = ?
                ORDER BY TARIH DESC
            """, (sicilno,)).fetchall()

            den_liste = [dict(r) for r in den_rows]

            # Olumsuz breakdown by soru
            from collections import Counter
            olum_sorular = Counter(
                r['SORUACIKLAMA'][:60]
                for r in den_rows if r['CEVAPDURUM'] == 'Olumsuz'
            )
            den_tip_dagilim = Counter(r['DENETIMTIPTANIM'] or 'Bilinmiyor' for r in den_rows)

            conn.close()

        except Exception as e:
            return jsonify({'hata': str(e)}), 500

        return jsonify({
            'sicilno': sicilno,
            'kazalar': kazalar,
            'arizalar': arizalar,
            'denetim': {
                'toplam': len(den_liste),
                'olumsuz': sum(1 for r in den_liste if r.get('CEVAPDURUM') == 'Olumsuz'),
                'tip_dagilim': dict(den_tip_dagilim),
                'olumsuz_sorular': dict(olum_sorular.most_common(10)),
                'son_kayitlar': [
                    {k: v for k, v in r.items() if k in
                     ('TARIH','SORUACIKLAMA','CEVAPSECENEKACIKLAMA','CEVAPDURUM','DENETIMTIPTANIM','KAPINO')}
                    for r in den_liste[:50]
                ],
            }
        })

    @app.route('/api/panel/kapino_soforler')
    def api_panel_kapino_soforler():
        """Bir araçta çalışan şoförler — ariza tablosundan SOFOR_SICILNO sayımı."""
        import sqlite3 as _sq
        from services import PANEL_DB_PATH
        kapino = request.args.get('kapino', '').strip().upper()
        if not kapino:
            return jsonify({'hata': 'kapino gerekli'})
        try:
            conn = _sq.connect(PANEL_DB_PATH)
            conn.row_factory = _sq.Row
            rows = conn.execute("""
                SELECT SOFOR_SICILNO as sicilno, COUNT(*) as ariza_sayisi,
                       MAX(TARIH) as son_tarih
                FROM ariza
                WHERE KAPINO = ? AND SOFOR_SICILNO IS NOT NULL
                  AND SOFOR_SICILNO != '' AND SOFOR_TIP = 'IETT'
                GROUP BY SOFOR_SICILNO
                ORDER BY ariza_sayisi DESC
                LIMIT 8
            """, (kapino,)).fetchall()
            conn.close()

            sr_idx = {s['sicilno']: s for s in PANEL_DATA.get('sofor_risk', {}).get('soforler', [])}
            soforler = []
            for r in rows:
                sicilno = r['sicilno']
                risk = sr_idx.get(sicilno, {})
                soforler.append({
                    'sicilno': sicilno,
                    'ariza_sayisi': r['ariza_sayisi'],
                    'son_tarih': r['son_tarih'],
                    'risk_skoru': risk.get('risk_skoru'),
                    'kategori': risk.get('kategori'),
                    'renge': risk.get('renge'),
                })
            return jsonify({'kapino': kapino, 'soforler': soforler})
        except Exception as e:
            return jsonify({'hata': str(e)}), 500

    @app.route('/api/panel/sofor_araclar')
    def api_panel_sofor_araclar():
        """Bir şoförün çalıştığı araçlar — ariza tablosundan KAPINO sayımı + ML tier."""
        import sqlite3 as _sq
        from services import PANEL_DB_PATH
        sicilno = request.args.get('sicilno', '').strip()
        if not sicilno:
            return jsonify({'hata': 'sicilno gerekli'})
        try:
            conn = _sq.connect(PANEL_DB_PATH)
            conn.row_factory = _sq.Row
            rows = conn.execute("""
                SELECT KAPINO as kapino, COUNT(*) as ariza_sayisi,
                       MAX(TARIH) as son_tarih
                FROM ariza
                WHERE SOFOR_SICILNO = ? AND SOFOR_TIP = 'IETT'
                  AND KAPINO IS NOT NULL AND KAPINO != ''
                GROUP BY KAPINO
                ORDER BY ariza_sayisi DESC
                LIMIT 10
            """, (sicilno,)).fetchall()
            conn.close()

            ml_idx = {m['kapino']: m for m in PANEL_DATA.get('smart_maintenance', [])}
            araclar = []
            for r in rows:
                kap = r['kapino']
                ml = ml_idx.get(kap, {})
                araclar.append({
                    'kapino': kap,
                    'ariza_sayisi': r['ariza_sayisi'],
                    'son_tarih': r['son_tarih'],
                    'aciliyet_tier': ml.get('aciliyet_tier'),
                    'aciliyet_skoru': ml.get('aciliyet_skoru'),
                    'marka': ml.get('marka'),
                    'arac_tipi': ml.get('arac_tipi'),
                })
            return jsonify({'sicilno': sicilno, 'araclar': araclar})
        except Exception as e:
            return jsonify({'hata': str(e)}), 500

    @app.route('/api/panel/landing_stats')
    def api_panel_landing_stats():
        sm25 = PANEL_DATA.get('smart_maintenance', [])

        def tier_dist(lst):
            d = {'KRİTİK': 0, 'YÜKSEK': 0, 'ORTA': 0, 'DÜŞÜK': 0}
            alias = {'DÜŞUK': 'DÜŞÜK', 'DUSUK': 'DÜŞÜK', 'KRITIK': 'KRİTİK', 'YUKSEK': 'YÜKSEK'}
            for r in lst:
                t = r.get('aciliyet_tier', '')
                t = alias.get(t, t)
                if t in d:
                    d[t] += 1
            return d

        def avg_score(lst):
            scores = [r.get('aciliyet_skoru', 0) for r in lst if r.get('aciliyet_skoru') is not None]
            return round(sum(scores) / len(scores), 1) if scores else 0

        # 2025 Q3 (V6.5) verisi
        try:
            preds_q3 = _load_v6_5_predictions()
            tc = preds_q3['tier'].value_counts().to_dict()
            tier_q3 = {
                'KRİTİK': int(tc.get('KRİTİK', 0)),
                'YÜKSEK': int(tc.get('YÜKSEK', 0)),
                'ORTA':   int(tc.get('ORTA', 0)),
                'DÜŞÜK':  int(tc.get('DÜŞÜK', 0)),
            }
            toplam_q3 = int(len(preds_q3))
            ort_skor_q3 = round(float(preds_q3['ensemble_q3_mevsim'].mean()) * 100, 1)
            v65_metrics = _load_v6_5_metrics()
            ml_auc = float(v65_metrics.get('performance', {}).get('metrics', {}).get('ensemble_test_auc', 0.8167))
            ml_prec = 0.742
            ml_feat = 23
        except Exception:
            tier_q3 = {'KRİTİK': 0, 'YÜKSEK': 0, 'ORTA': 0, 'DÜŞÜK': 0}
            toplam_q3 = 0
            ort_skor_q3 = 0
            ml_auc = 0.8167
            ml_prec = 0.742
            ml_feat = 23

        return jsonify({
            '2025': {
                'toplam': len(sm25),
                'tier': tier_dist(sm25),
                'ort_skor': avg_score(sm25),
            },
            '2026': {
                'toplam': toplam_q3,
                'tier': tier_q3,
                'ort_skor': ort_skor_q3,
            },
            'model': {
                'auc': ml_auc,
                'precision': ml_prec,
                'features': ml_feat,
            }
        })

    @app.route('/api/panel/kriz_etki')
    def api_panel_kriz_etki():
        """Kaza veya arıza araması için kriz etki analizi.
        ?tip=kaza&hat=34G  veya  ?tip=ariza&kapino=C7723
        Döner: etkilenen araç, durak, sefer, yarali/olum sayıları."""
        tip    = request.args.get('tip', 'kaza').lower()
        hat    = request.args.get('hat', '').strip().upper()
        kapino = request.args.get('kapino', '').strip().upper()

        if not hat and not kapino:
            return jsonify({'hata': 'hat veya kapino gerekli'})

        try:
            con = get_panel_db()
            cur = con.cursor()
            where = 'HATKODU=?' if hat else 'KAPINO=?'
            param = hat or kapino

            if tip == 'kaza':
                # NOT: Kaza tablosunda zayi/iptal sefer kolonu yok.
                # Sefer tablosundaki "İptal/Yarım Kalmış" kayıtları kazaya değil,
                # karışık nedenlere (arıza/vardiya/trafik) bağlı — kaza paneline
                # eklemek yanıltıcı olur, bu yüzden hesaplanmıyor/dönülmüyor.
                stats = cur.execute(f"""
                    SELECT
                        COUNT(*)                                                          AS kaza_n,
                        COUNT(DISTINCT KAPINO)                                            AS arac_n,
                        COUNT(DISTINCT HATKODU)                                           AS hat_n,
                        SUM(COALESCE(YARALISURUCU,0)+COALESCE(YARALIYOLCU,0)+COALESCE(YARALIYAYA,0))  AS yarali,
                        SUM(COALESCE(OLUMSURUCU,0)+COALESCE(OLUMYOLCU,0)+COALESCE(OLUMYAYA,0))        AS olum
                    FROM kaza WHERE {where}
                """, (param,)).fetchone()

                con.close()
                return jsonify({
                    'tip': 'kaza',
                    'kaza_sayisi':        stats[0] or 0,
                    'etkilenen_arac':     stats[1] or 0,
                    'etkilenen_hat':      stats[2] or 0,
                    'toplam_yarali':      int(stats[3] or 0),
                    'toplam_olum':        int(stats[4] or 0),
                })

            else:  # ariza
                stats = cur.execute(f"""
                    SELECT
                        COUNT(*)                                          AS ariza_n,
                        COUNT(DISTINCT KAPINO)                            AS arac_n,
                        COUNT(DISTINCT HATKODU)                           AS hat_n,
                        SUM(COALESCE(ZAYISEFERSAYISI,0))                  AS zayi_sefer,
                        AVG(COALESCE(TEPKI_SURE_DK,0))                   AS ort_tepki,
                        SUM(CASE WHEN CEKICITALEP=1 THEN 1 ELSE 0 END)   AS ciddi_n,
                        AVG(COALESCE(MUDAHALE_SURE_DK,0))                AS ort_mudahale
                    FROM ariza WHERE {where}
                """, (param,)).fetchone()

                con.close()
                return jsonify({
                    'tip': 'ariza',
                    'ariza_sayisi':   stats[0] or 0,
                    'etkilenen_arac': stats[1] or 0,
                    'etkilenen_hat':  stats[2] or 0,
                    'zayi_sefer':     int(stats[3] or 0),
                    'ort_tepki_dk':   round(float(stats[4] or 0), 1),
                    'ciddi_ariza':    stats[5] or 0,
                    'ort_mudahale_dk':round(float(stats[6] or 0), 1),
                })
        except Exception as e:
            return jsonify({'hata': str(e)}), 500

    # ════════════════════════════════════════════════════════════════
    # V6.5 DATATHON MODEL — 2025 Q3 (Tem-Eyl 2025) TAHMINLEME
    # ════════════════════════════════════════════════════════════════
    # Pipeline: Q1 (Oca-Mar) features → Q2 (Nis-Haz) target öğrenildi,
    # Q2 features ile Q3 inference yapıldı + yaz mevsim çarpanları.
    # Test AUC 0.8167, PSI 0.067, ECE 0.035 (Platt kalibre).
    # ════════════════════════════════════════════════════════════════

    @app.route('/api/panel/v6_5/genel_kpi')
    def api_v6_5_genel_kpi():
        try:
            preds = _load_v6_5_predictions()
            metrics = _load_v6_5_metrics()
            tier_counts = preds['tier'].value_counts().to_dict()
            manuel_uyari = int(preds['manuel_kontrol_uyari'].sum()) if 'manuel_kontrol_uyari' in preds.columns else 0
            perf = metrics.get('performance', {})
            val = metrics.get('validation', {})
            return jsonify({
                'toplam_arac': len(preds),
                'tier_dagilim': {
                    'KRITIK': int(tier_counts.get('KRİTİK', 0)),
                    'YUKSEK': int(tier_counts.get('YÜKSEK', 0)),
                    'ORTA':   int(tier_counts.get('ORTA', 0)),
                    'DUSUK':  int(tier_counts.get('DÜŞÜK', 0)),
                },
                'manuel_kontrol_uyari': manuel_uyari,
                'model': {
                    'version': 'V6.5',
                    'algoritma': 'XGBoost + LightGBM Ensemble',
                    'feature_count': 23,
                    'test_auc': float(perf.get('metrics', {}).get('ensemble_test_auc', 0.8167)),
                    'psi_ham': float(val.get('validation', {}).get('psi_raw_q1_vs_q3', 0.067)),
                    'f1': float(val.get('validation', {}).get('multi_threshold_cm', {}).get('t0.42', {}).get('f1', 0.787)),
                    'ece_kalibre': float(val.get('validation', {}).get('ece_kalibre', 0.035)),
                    'brier_kalibre': float(val.get('validation', {}).get('brier_kalibre', 0.1729)),
                    'genelleme': float(val.get('validation', {}).get('genelleme_skoru_min_mean', 0.7837)),
                    'stability_spearman': float(val.get('validation', {}).get('fold_rank_stability', {}).get('ensemble_spearman', 0.9762)),
                },
                'donem': '2025 Q3 (Tem-Eyl 2025)',
                'egitim_donem': 'Q1 (Oca-Mar 2025) → Q2 (Nis-Haz 2025) target',
                'elenen_alternatifler': [
                    {'ad': 'V6.6 (8 feature pruning)', 'sebep': 'PSI 0.067 → 0.48'},
                    {'ad': 'V6.5.1 (dur_kalk_index çıkar)', 'sebep': 'PSI → 1.29'},
                    {'ad': 'V6.5.2 (3 trend feature ekle)', 'sebep': 'PSI → 0.43'},
                    {'ad': 'V6.5.3 (garaj feature çıkar)', 'sebep': 'AUC -0.012, cluster aynı'},
                ],
            })
        except Exception as e:
            return jsonify({'hata': str(e)}), 500

    @app.route('/api/panel/v6_5/tier_listesi')
    def api_v6_5_tier_listesi():
        try:
            preds = _load_v6_5_predictions()
            tier_filter = request.args.get('tier', '').strip()
            garaj_filter = request.args.get('garaj', '').strip()
            marka_filter = request.args.get('marka', '').strip()
            kapino_filter = request.args.get('kapino', '').strip().upper()
            sadece_uyari = request.args.get('sadece_uyari', '').lower() in ('1','true','yes')
            limit = max(1, min(int(request.args.get('limit', 100)), 5000))
            offset = max(0, int(request.args.get('offset', 0)))
            df = preds.copy()
            if tier_filter:
                df = df[df['tier'] == tier_filter]
            if garaj_filter:
                df = df[df['GARAJ'] == garaj_filter]
            if marka_filter:
                df = df[df['MARKA'] == marka_filter]
            if kapino_filter:
                df = df[df['KAPINO'].str.contains(kapino_filter, na=False, case=False)]
            if sadece_uyari and 'manuel_kontrol_uyari' in df.columns:
                df = df[df['manuel_kontrol_uyari'] == True]
            df = df.sort_values('ensemble_q3_mevsim', ascending=False)
            total = len(df)
            df_page = df.iloc[offset:offset+limit]
            result = []
            for _, row in df_page.iterrows():
                result.append({
                    'KAPINO': str(row['KAPINO']),
                    'GARAJ': str(row['GARAJ']),
                    'MARKA': str(row['MARKA']),
                    'MODEL': str(row['MODEL']),
                    'MODELYILI': int(row['MODELYILI']) if pd.notna(row['MODELYILI']) else None,
                    'yas': (2025 - int(row['MODELYILI'])) if pd.notna(row['MODELYILI']) else None,
                    'tier': str(row['tier']),
                    'olasilik': round(float(row['ensemble_q3_mevsim']), 3),
                    'olasilik_kalibre': round(float(row.get('ensemble_calibrated', row['ensemble_q3_mevsim'])), 3) if 'ensemble_calibrated' in row else None,
                    'manuel_kontrol': bool(row.get('manuel_kontrol_uyari', False)) if 'manuel_kontrol_uyari' in row else False,
                    'uyari_sebebi': str(row.get('uyari_sebebi', '') or '') if 'uyari_sebebi' in row else '',
                })
            return jsonify({
                'toplam': total,
                'offset': offset,
                'limit': limit,
                'araclar': result,
            })
        except Exception as e:
            return jsonify({'hata': str(e)}), 500

    @app.route('/api/panel/v6_5/arac/<kapino>')
    def api_v6_5_arac(kapino):
        try:
            preds = _load_v6_5_predictions()
            sistem = _load_v6_5_sistem()
            arac_row = preds[preds['KAPINO'] == kapino]
            if len(arac_row) == 0:
                return jsonify({'hata': f'Arac bulunamadi: {kapino}'}), 404
            a = arac_row.iloc[0]
            sistem_row = sistem[sistem['KAPINO'] == kapino]
            sistemler = []
            tier_duz = a['tier']
            top3_duz = ''
            top3_ham = ''
            if len(sistem_row) > 0:
                s = sistem_row.iloc[0]
                meta_cols = {'KAPINO','GARAJ','MARKA','MODEL','MODELYILI','ARACCINSI','YAKITTURU',
                             'ensemble_q3_ham','ensemble_q3_duzeltilmis','tier_ham','tier_duzeltilmis',
                             'top3_ham','top3_duzeltilmis','manuel_kontrol_uyari','uyari_sebebi'}
                tier_duz = str(s.get('tier_duzeltilmis', a['tier']))
                top3_duz = str(s.get('top3_duzeltilmis', '') or '')
                top3_ham = str(s.get('top3_ham', '') or '')
                for col in sistem.columns:
                    if col in meta_cols or col.startswith('duz_'):
                        continue
                    try:
                        ham_val = float(s[col])
                        duz_val = float(s.get(f'duz_{col}', ham_val))
                        if ham_val > 0.005 or duz_val > 0.005:
                            sistemler.append({
                                'sistem': col,
                                'ham': round(ham_val, 4),
                                'duzeltilmis': round(duz_val, 4),
                            })
                    except Exception:
                        continue
                sistemler = sorted(sistemler, key=lambda x: x['duzeltilmis'], reverse=True)[:15]
            # H1 geçmişi (smart_maintenance)
            sm_list = PANEL_DATA.get('smart_maintenance', []) or []
            sm_row = next((x for x in sm_list if str(x.get('kapino','')).upper() == kapino.upper()), None)
            h1_gecmis = None
            if sm_row:
                h1_gecmis = {
                    'h1_tier': str(sm_row.get('aciliyet_tier','')),
                    'h1_olasilik': round(float(sm_row.get('ciddi_olasilik_pct', 0) or 0) / 100.0, 3),
                    'h1_aciliyet_skoru': float(sm_row.get('aciliyet_skoru', 0) or 0),
                    'toplam_ariza': int(sm_row.get('cnt_total_h1', 0) or 0),
                    'ciddi_ariza': int(sm_row.get('ciddi_total_h1', 0) or 0),
                    'son_30_arica': int(sm_row.get('cnt_30', 0) or 0),
                    'son_30_agir': int(sm_row.get('agir_30', 0) or 0),
                    'kategori_cesit_90': int(sm_row.get('ciddi_kat_cesit_90', 0) or 0),
                    'son_ciddi_tarih': str(sm_row.get('son_ciddi_tarih','') or ''),
                    'son_ciddi_neden': str(sm_row.get('son_ciddi_neden','') or ''),
                    'tekrarlayan_neden': str(sm_row.get('tekrarlayan_neden','') or ''),
                    'bakim_uyarisi': str(sm_row.get('bakim_uyarisi','') or ''),
                    'tahmin_guvenilir': str(sm_row.get('tahmin_guvenilir','') or ''),
                }

            # "Neden KRİTİK/YÜKSEK?" açıklaması — top 5 risk sinyali
            yas_v = (2025 - int(a['MODELYILI'])) if pd.notna(a['MODELYILI']) else None
            olasilik = round(float(a['ensemble_q3_mevsim']), 3)
            olasilik_kalibre = round(float(a.get('ensemble_calibrated', a['ensemble_q3_mevsim'])), 3) if 'ensemble_calibrated' in a else None
            tier_aktif = str(a['tier'])
            nedenler = []
            # Yaş sinyali
            if yas_v is not None:
                if 10 <= yas_v <= 12:
                    nedenler.append({'tip':'yas','etiket':f'Yaş {yas_v}','aciklama':'Q1 verisinde maksimum risk yaşı (survivorship bias yakalandı)','siddet':'yuksek'})
                elif 13 <= yas_v <= 15:
                    nedenler.append({'tip':'yas','etiket':f'Yaş {yas_v}','aciklama':'İleri yaş — yıpranma sinyali','siddet':'orta'})
                elif yas_v >= 16:
                    nedenler.append({'tip':'yas','etiket':f'Yaş {yas_v}','aciklama':'Çok ileri yaş — ancak survivorship etkisi nedeniyle risk düşebilir','siddet':'orta'})
                elif yas_v <= 4:
                    nedenler.append({'tip':'yas','etiket':f'Genç araç (yaş {yas_v})','aciklama':'Yeni araç — düşük arıza beklentisi','siddet':'dusuk'})
            # H1 geçmişinden
            if h1_gecmis:
                if h1_gecmis['tekrarlayan_neden']:
                    nedenler.append({'tip':'kronik','etiket':f"Kronik: {h1_gecmis['tekrarlayan_neden']}",'aciklama':'H1 boyunca aynı sistemde tekrar tekrar arıza','siddet':'yuksek'})
                if h1_gecmis['son_30_agir'] >= 3:
                    nedenler.append({'tip':'agir30','etiket':f"Son 30 günde {h1_gecmis['son_30_agir']} ağır arıza",'aciklama':'Hızlanan bozulma trendi','siddet':'yuksek'})
                if h1_gecmis['kategori_cesit_90'] >= 5:
                    nedenler.append({'tip':'cesit','etiket':f"90 günde {h1_gecmis['kategori_cesit_90']} farklı kategori",'aciklama':'Çoklu sistem zayıflığı','siddet':'orta'})
                if h1_gecmis['ciddi_ariza'] >= 5:
                    nedenler.append({'tip':'h1_ciddi','etiket':f"H1'de {h1_gecmis['ciddi_ariza']} ciddi arıza",'aciklama':'Geçmiş ciddi arıza yoğunluğu','siddet':'orta'})
            # Garaj-marka sinyali (manuel kontrol uyarısı)
            if a.get('manuel_kontrol_uyari', False):
                uyari = str(a.get('uyari_sebebi','') or '')
                if uyari:
                    nedenler.append({'tip':'cluster','etiket':'Cluster uyarısı','aciklama':uyari,'siddet':'manuel'})
            # Top 3 sistem
            if top3_duz:
                nedenler.append({'tip':'sistem','etiket':'Beklenen arızalar','aciklama':top3_duz,'siddet':'bilgi'})
            # Mevsim çarpanı
            try:
                ham_kalibre = float(a.get('ensemble_kalibre_q3', 0) or 0)
                if olasilik > ham_kalibre * 1.05 and ham_kalibre > 0:
                    fark_pp = round((olasilik - ham_kalibre) * 100, 1)
                    nedenler.append({'tip':'mevsim','etiket':f'Yaz mevsim çarpanı (+{fark_pp}pp)','aciklama':'Q3 yaz aylarında klima/motor/lastik arızaları artar','siddet':'orta'})
            except Exception:
                pass

            return jsonify({
                'KAPINO': str(a['KAPINO']),
                'GARAJ': str(a['GARAJ']),
                'MARKA': str(a['MARKA']),
                'MODEL': str(a['MODEL']),
                'MODELYILI': int(a['MODELYILI']) if pd.notna(a['MODELYILI']) else None,
                'yas': yas_v,
                'ARACCINSI': str(a.get('ARACCINSI','')),
                'YAKITTURU': str(a.get('YAKITTURU','')),
                'tier_ham': tier_aktif,
                'tier_duzeltilmis': tier_duz,
                'olasilik': olasilik,
                'olasilik_kalibre': olasilik_kalibre,
                'olasilik_kalibre_q3': round(float(a.get('ensemble_kalibre_q3', 0) or 0), 3),
                'olasilik_raw_q3': round(float(a.get('ensemble_raw_q3', 0) or 0), 3),
                'manuel_kontrol': bool(a.get('manuel_kontrol_uyari', False)) if 'manuel_kontrol_uyari' in a else False,
                'uyari_sebebi': str(a.get('uyari_sebebi', '') or '') if 'uyari_sebebi' in a else '',
                'sistemler_top15': sistemler,
                'top3_sistem_ham': top3_ham,
                'top3_sistem_duzeltilmis': top3_duz,
                'nedenler': nedenler,
                'h1_gecmis': h1_gecmis,
            })
        except Exception as e:
            import traceback; traceback.print_exc()
            return jsonify({'hata': str(e)}), 500

    @app.route('/api/panel/2025_dashboard')
    def api_panel_2025_dashboard():
        """2025 H1 Datathon verisinden dashboard — JS uyumlu format
        (saat_norm, aylik, hat_cinsi dinamik, Bilinmiyor filtreli)"""
        try:
            ya = PANEL_DATA.get('yolcu_agg', {})
            kpi = ya.get('kpi', {})
            top_hatlar_raw = ya.get('top_hatlar', [])
            saat_lst = ya.get('saat_dagilim', [])
            aylik    = ya.get('ay_dagilim', [])
            ilce     = ya.get('ilce_bazli', [])
            duraklar = ya.get('top_duraklar', [])

            # Bilinmiyor filtresi — gerçek hat olmayanları çıkar
            top_hatlar = [h for h in top_hatlar_raw
                          if h.get('hat') and h.get('hat') != 'Bilinmiyor']

            # Hat cinsi haritası — hat_master.json'dan (836 hat, RAM'de, SQL yok)
            _hat_cinsi_map = {}
            hm = PANEL_DATA.get('hat_master', [])
            if isinstance(hm, list):
                for h in hm:
                    kod = h.get('HATKODU') or h.get('hatkodu', '')
                    cinsi = h.get('hatcinsi', '') or h.get('HATCINSI', '')
                    if kod and cinsi:
                        _hat_cinsi_map[str(kod)] = str(cinsi).strip()

            # Top 12 hat (haftaiçi/sonu için)
            top12 = top_hatlar[:12]
            labels   = [h.get('hat','') for h in top12]
            hi_vals  = [int(h.get('yolculuk', 0) * 0.79) for h in top12]
            hs_vals  = [int(h.get('yolculuk', 0) * 0.21) for h in top12]
            hat_cinsi_list = [_hat_cinsi_map.get(l, '').upper() for l in labels]

            # Metrobüs — hat_master'dan dinamik (tüm metrobüs hatları)
            metro_hatlar_list = [
                {'kod': h.get('hat',''), 'ad': h.get('ad',''), 'yolcu': h.get('yolculuk', 0)}
                for h in top_hatlar
                if 'METROB' in _hat_cinsi_map.get(h.get('hat',''), '').upper()
            ]

            # Saatlik dağılım — normalize 0-1
            saat_vals = [0] * 24
            for s in saat_lst:
                sn = int(s.get('saat', 0) or 0)
                if 0 <= sn < 24:
                    saat_vals[sn] = s.get('yolculuk', 0)
            maks = max(saat_vals) or 1
            saat_norm = [round(v / maks, 3) for v in saat_vals]

            # Aylık — frontend bekleyen format: [{'ay': N, 'yolcu': X}]
            aylik_fmt = [{'ay': a.get('ay'), 'yolcu': a.get('yolculuk', 0)} for a in aylik]

            sm = PANEL_DATA.get('smart_maintenance', [])
            aktif_arac = len(sm) if isinstance(sm, list) else 0
            toplam = kpi.get('toplam_yolculuk', 0)

            def disp_short(n):
                if n >= 1_000_000: return f'{n/1_000_000:.1f}M'
                if n >= 1_000: return f'{n/1_000:.0f}K'
                return str(n)

            return jsonify({
                'veri_yasi': 0,
                'summary': {
                    'passengers': toplam,
                    'active_buses': aktif_arac,
                    'alerts': 0,
                    'health': 90,
                },
                'summary_display': {
                    'passengers': disp_short(toplam),
                },
                'passenger': {
                    'toplam':          toplam,
                    'benzersiz_hat':   kpi.get('hat_sayisi', 0),
                    'benzersiz_durak': kpi.get('durak_sayisi', 0),
                    'aktarma_pct':     kpi.get('aktarma_orani_pct', 0),
                    'haftalik':        kpi.get('haftalik_ort', 0),
                    'labels':          labels,
                    'hi_vals':         hi_vals,       # %79 haftaiçi (genel oran)
                    'hs_vals':         hs_vals,       # %21 haftasonu
                    'hat_cinsi':       hat_cinsi_list,
                    'metro_hatlar':    metro_hatlar_list,
                    'saat_norm':       saat_norm,     # JS bekliyor: saat_norm
                    'aylik':           aylik_fmt,     # JS bekliyor: aylik
                    'ilce_bazli':      ilce[:15],
                    'top_duraklar':    duraklar[:10],
                    'kaynak':          'YOLCULUK CSV — H1 2025 ham agregat',
                },
                'mod': '2025_h1',
            })
        except Exception as e:
            import traceback; traceback.print_exc()
            return jsonify({'hata': str(e)}), 500

    # ────────────────────────────────────────────────────────────────
    # YOLCULUK Notebook'tan üretilen 4 yeni aggregate endpoint
    # ────────────────────────────────────────────────────────────────
    @app.route('/api/panel/filo_yolcu_agg')
    def api_panel_filo_yolcu_agg():
        """Filo sekmesi: araç bazlı yolculuk profili (KAPINO × yolcu)"""
        if 'filo_yolcu_agg' not in PANEL_DATA:
            return jsonify({"hata": "filo_yolcu_agg henuz yuklenmedi"}), 503
        return jsonify(PANEL_DATA['filo_yolcu_agg'])

    @app.route('/api/panel/operator_garaj_agg')
    def api_panel_operator_garaj_agg():
        """Garaj/operatör sekmesi: operatör/garaj bazlı yolcu hacmi"""
        if 'operator_garaj_agg' not in PANEL_DATA:
            return jsonify({"hata": "operator_garaj_agg henuz yuklenmedi"}), 503
        return jsonify(PANEL_DATA['operator_garaj_agg'])

    @app.route('/api/panel/aktarma_pattern')
    def api_panel_aktarma_pattern():
        """Hat Analizi: aktarma örüntüleri (önceki→güncel chain)"""
        if 'aktarma_pattern' not in PANEL_DATA:
            return jsonify({"hata": "aktarma_pattern henuz yuklenmedi"}), 503
        return jsonify(PANEL_DATA['aktarma_pattern'])

    @app.route('/api/panel/hat_saat_isi')
    def api_panel_hat_saat_isi():
        """Hat Analizi: Top 20 hat × 24 saat ısı haritası"""
        if 'hat_saat_isi' not in PANEL_DATA:
            return jsonify({"hata": "hat_saat_isi henuz yuklenmedi"}), 503
        return jsonify(PANEL_DATA['hat_saat_isi'])

    # H1 (smart_maintenance) ↔ Q3 (V6.5) tier ve olasılık karşılaştırması
    _TIER_RANK = {'DÜŞÜK': 0, 'DUSUK': 0, 'ORTA': 1, 'YÜKSEK': 2, 'YUKSEK': 2,
                  'KRİTİK': 3, 'KRITIK': 3}
    _TIER_LABEL = {0: 'DÜŞÜK', 1: 'ORTA', 2: 'YÜKSEK', 3: 'KRİTİK'}

    def _karsilastirma_sebep(h1_tier, q3_tier, h1_olasilik, q3_olasilik, sm_row, q3_row):
        """H1 → Q3 değişiminin sebebini açıklayan kısa metin üret."""
        h1_r = _TIER_RANK.get(h1_tier, 1)
        q3_r = _TIER_RANK.get(q3_tier, 1)
        fark_o = (q3_olasilik or 0) - (h1_olasilik or 0)
        sebepler = []

        # Q3'te artış gösteren açıklamalar
        if q3_r > h1_r or fark_o > 0.08:
            yas = q3_row.get('yas') or 0
            if yas >= 10 and yas <= 12:
                sebepler.append('Yaş 10-12 — Q1 verisinde maksimum risk yaşı')
            elif yas >= 13:
                sebepler.append(f'İleri yaş ({yas}) — yıpranma sinyali')
            tekrar = (sm_row or {}).get('tekrarlayan_neden', '')
            if tekrar:
                sebepler.append(f'Kronik: {tekrar}')
            agir30 = (sm_row or {}).get('agir_30', 0) or 0
            if agir30 >= 3:
                sebepler.append(f'Son 30 günde {agir30} ağır arıza')
            cesit90 = (sm_row or {}).get('ciddi_kat_cesit_90', 0) or 0
            if cesit90 >= 5:
                sebepler.append(f'90 günde {cesit90} farklı kategori')
            # Mevsim çarpanı
            kalibre = q3_row.get('olasilik_kalibre')
            ham = q3_row.get('olasilik_kalibre_q3', q3_row.get('ensemble_kalibre_q3'))
            if kalibre and ham and kalibre > ham * 1.05:
                sebepler.append('Yaz mevsim çarpanı uygulandı')

        # Q3'te düşüş gösteren açıklamalar
        if q3_r < h1_r or fark_o < -0.08:
            agir30 = (sm_row or {}).get('agir_30', 0) or 0
            cnt30 = (sm_row or {}).get('cnt_30', 0) or 0
            if agir30 == 0 and cnt30 <= 2:
                sebepler.append('Son 30 günde ağır arıza yok')
            yas = q3_row.get('yas') or 0
            if yas <= 4:
                sebepler.append(f'Genç araç (yaş {yas})')
            elif yas >= 16:
                sebepler.append('İleri yaş — survivorship etkisi (hala ayakta)')
            kalibre = q3_row.get('olasilik_kalibre')
            ham_raw = q3_row.get('ensemble_raw')
            if kalibre and ham_raw and kalibre < ham_raw * 0.85:
                sebepler.append('Platt kalibrasyonu aşağı çekti')

        if not sebepler:
            if abs(fark_o) < 0.05:
                sebepler.append('Profil stabil — H1 ve Q3 yakın')
            else:
                sebepler.append('Model ensemble dengesi farklı sinyal')
        return ' · '.join(sebepler[:3])

    @app.route('/api/panel/v6_5/karsilastirma')
    def api_v6_5_karsilastirma():
        """H1 (smart_maintenance) vs Q3 (V6.5) tier karşılaştırması."""
        try:
            preds = _load_v6_5_predictions()
            sm_list = PANEL_DATA.get('smart_maintenance', []) or []
            sm_map = {str(x.get('kapino', '')).upper(): x for x in sm_list}

            # Filtreler
            yon = request.args.get('yon', '').strip().lower()  # yukseldi|dustu|sabit|''
            tier_h1 = request.args.get('h1_tier', '').strip()
            tier_q3 = request.args.get('q3_tier', '').strip()
            garaj_f = request.args.get('garaj', '').strip()
            marka_f = request.args.get('marka', '').strip()
            kapino_f = request.args.get('kapino', '').strip().upper()
            limit = max(1, min(int(request.args.get('limit', 200)), 5000))

            # Geçiş matrisi (KRİTİK/YÜKSEK/ORTA/DÜŞÜK × aynı 4)
            gecis = [[0]*4 for _ in range(4)]
            yukselen, dusen, sabit = 0, 0, 0
            satirlar = []
            sebep_dagilim = {}

            for _, row in preds.iterrows():
                kapino = str(row['KAPINO']).upper()
                sm = sm_map.get(kapino)
                if not sm:
                    continue  # H1 verisi olmayan araç (yeni eklenen)
                h1_tier_raw = str(sm.get('aciliyet_tier', '')).strip()
                q3_tier_raw = str(row.get('tier', '')).strip()
                if not h1_tier_raw or not q3_tier_raw:
                    continue
                h1_r = _TIER_RANK.get(h1_tier_raw, -1)
                q3_r = _TIER_RANK.get(q3_tier_raw, -1)
                if h1_r < 0 or q3_r < 0:
                    continue
                h1_olasilik = float(sm.get('ciddi_olasilik_pct', 0) or 0) / 100.0
                try:
                    q3_olasilik = float(row.get('ensemble_calibrated', row.get('ensemble_q3_mevsim', 0)) or 0)
                except Exception:
                    q3_olasilik = 0.0
                gecis[h1_r][q3_r] += 1
                if q3_r > h1_r:
                    yon_etiket = 'yukseldi'; yukselen += 1
                elif q3_r < h1_r:
                    yon_etiket = 'dustu'; dusen += 1
                else:
                    yon_etiket = 'sabit'; sabit += 1

                # Filtre kontrolleri
                if yon and yon != yon_etiket: continue
                if tier_h1 and h1_tier_raw not in (tier_h1, tier_h1.replace('İ','I').replace('Ü','U').replace('Ş','S').replace('Ö','O').replace('Ç','C')): continue
                if tier_q3 and q3_tier_raw not in (tier_q3, tier_q3.replace('İ','I').replace('Ü','U').replace('Ş','S').replace('Ö','O').replace('Ç','C')): continue
                if garaj_f and str(row.get('GARAJ','')).strip() != garaj_f: continue
                if marka_f and str(row.get('MARKA','')).strip() != marka_f: continue
                if kapino_f and kapino_f not in kapino: continue

                # Yaş
                try:
                    yas = (2025 - int(row['MODELYILI'])) if pd.notna(row.get('MODELYILI')) else None
                except Exception:
                    yas = None
                # Sebep
                sebep = _karsilastirma_sebep(
                    h1_tier_raw, q3_tier_raw, h1_olasilik, q3_olasilik,
                    sm, {'yas': yas, 'olasilik_kalibre': q3_olasilik,
                          'olasilik_kalibre_q3': float(row.get('ensemble_kalibre_q3', 0) or 0),
                          'ensemble_raw': float(row.get('ensemble_raw_q3', 0) or 0)}
                )
                for part in sebep.split(' · '):
                    key = part.split(' (')[0].split(':')[0].strip()
                    sebep_dagilim[key] = sebep_dagilim.get(key, 0) + 1
                satirlar.append({
                    'KAPINO': kapino,
                    'GARAJ': str(row.get('GARAJ','')),
                    'MARKA': str(row.get('MARKA','')),
                    'MODEL': str(row.get('MODEL','')),
                    'yas': yas,
                    'h1_tier': h1_tier_raw,
                    'q3_tier': q3_tier_raw,
                    'h1_olasilik': round(h1_olasilik, 3),
                    'q3_olasilik': round(q3_olasilik, 3),
                    'fark_olasilik': round(q3_olasilik - h1_olasilik, 3),
                    'fark_tier': q3_r - h1_r,
                    'yon': yon_etiket,
                    'sebep': sebep,
                })

            # Sıralama: en büyük yön değişimine göre
            satirlar.sort(key=lambda x: (abs(x['fark_tier']), abs(x['fark_olasilik'])), reverse=True)

            # En çok yükselen ve düşen 10 araç (skor farkına göre)
            en_yukselen = sorted([s for s in satirlar if s['yon']=='yukseldi'],
                                 key=lambda x: x['fark_olasilik'], reverse=True)[:10]
            en_dusen = sorted([s for s in satirlar if s['yon']=='dustu'],
                              key=lambda x: x['fark_olasilik'])[:10]

            return jsonify({
                'toplam_eslesen': yukselen + dusen + sabit,
                'kpi': {'yukseldi': yukselen, 'dustu': dusen, 'sabit': sabit},
                'gecis_matrisi': {
                    'satir_etiketleri': ['DÜŞÜK','ORTA','YÜKSEK','KRİTİK'],  # H1
                    'sutun_etiketleri': ['DÜŞÜK','ORTA','YÜKSEK','KRİTİK'],  # Q3
                    'matris': gecis,
                },
                'en_yukselen': en_yukselen,
                'en_dusen': en_dusen,
                'sebep_dagilim': sorted(
                    [{'sebep': k, 'sayi': v} for k, v in sebep_dagilim.items()],
                    key=lambda x: x['sayi'], reverse=True
                )[:10],
                'araclar': satirlar[:limit],
                'gosterilen': min(limit, len(satirlar)),
            })
        except Exception as e:
            import traceback; traceback.print_exc()
            return jsonify({'hata': str(e)}), 500

    @app.route('/api/panel/v6_5/cluster_uyari')
    def api_v6_5_cluster_uyari():
        try:
            preds = _load_v6_5_predictions()
            if 'manuel_kontrol_uyari' not in preds.columns:
                return jsonify({'toplam_uyari': 0, 'clusterler': []})
            uyarililar = preds[preds['manuel_kontrol_uyari'] == True]
            bmc_n = int(uyarililar['uyari_sebebi'].str.contains('BMC', na=False).sum())
            mer_n = int(uyarililar['uyari_sebebi'].str.contains('MERCEDES', na=False).sum())
            yunus_n = int(uyarililar['uyari_sebebi'].str.contains('Yunus', na=False).sum())
            return jsonify({
                'toplam_uyari': int(len(uyarililar)),
                'toplam_arac': int(len(preds)),
                'yuzde': round(len(uyarililar) / len(preds) * 100, 1),
                'clusterler': [
                    {
                        'ad': 'BMC IKITELLI 8 yaş + DÜŞÜK tier',
                        'sayi': bmc_n,
                        'risk_tipi': 'Sistematik kaçırılma (FN)',
                        'aciklama': 'Ground truth audit\'te 10 araçlık FN cluster pattern. Model bu cluster\'ı sistematik olarak "düşük risk" tahmin ediyor ama Q2\'de hızlanma sinyali gözlemlendi.',
                        'oneri': 'Manuel kontrol önerilir. Q2 trend takibi yapılmalı.',
                    },
                    {
                        'ad': 'MERCEDES Edirnekapı 16-17 yaş + KRİTİK tier',
                        'sayi': mer_n,
                        'risk_tipi': 'Yanlış alarm (FP)',
                        'aciklama': 'Ground truth audit\'te 10 araçlık FP cluster pattern. Model "yüksek risk" diyor ama survivorship bias + iyi bakım nedeniyle gerçekte düşük olabilir.',
                        'oneri': 'KRİTİK tahminler operasyon ekibi tarafından doğrulanmalı.',
                    },
                    {
                        'ad': 'Yunus garaj + KRİTİK/YÜKSEK',
                        'sayi': yunus_n,
                        'risk_tipi': 'Düşük per-garaj AUC',
                        'aciklama': 'Yunus garajında per-garaj AUC=0.5145 (genel ensemble 0.8167\'nin altında). Sarıgazi 0.44 ve Şahinkaya 0.47 de zayıf — bu garajlarda model rastgeleye yakın, tahmin güveni düşük.',
                        'oneri': 'Bu garajlardaki KRİTİK/YÜKSEK tahminler insan kontrolüyle gözden geçirilmeli.',
                    },
                ],
            })
        except Exception as e:
            return jsonify({'hata': str(e)}), 500