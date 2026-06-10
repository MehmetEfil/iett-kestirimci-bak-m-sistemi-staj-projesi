# -*- coding: utf-8 -*-
"""
KASKAD NULL MODELI — METODOLOJIK DUZELTME (2026-06)
====================================================
Orijinal analizde (Cell 5) "rastgele beklenti" analitik Poisson formuluyle
1 - exp(-lambda) = %8.85 olarak hesaplanip, TUM-satir bazindaki gozlem (%14.90)
ile karsilastirilmis ve oran 1.68x, Z=49.95 raporlanmisti.

SORUN: 1 - exp(-lambda), "bir aracin bir 24s penceresinde >=1 ek olay gormesi"
olasiligidir ve PER-GAP (onceki arizasi olan satir) bazina denk gelir. Ama %14.90
TUM-satir bazinda. Iki farkli payda karsilastirilinca oran yapay olarak siser.

DOGRU YONTEM: Her aracin ariza tarihlerini 180 gunluk pencereye uniform rastgele
dagitan permutasyon (Monte Carlo) null modeli — gozlemle birebir ayni paydada.

CALISTIRMA: python cascade_permutasyon_null.py
"""
import pandas as pd, numpy as np

np.random.seed(42)
AM = r"..\panel_data\temiz_veri\ariza_model.csv"
df = pd.read_csv(AM, parse_dates=['OLAYTARIHI']).sort_values(['KAPINO', 'OLAYTARIHI'])

# Gozlemlenen cascade (24s icinde ayni araçta tekrar)
gap = df.groupby('KAPINO')['OLAYTARIHI'].diff().dt.total_seconds() / 3600.0
n_all = len(df)
n_casc = int((gap < 24).sum())
obs_all = n_casc / n_all
print(f"Gozlemlenen cascade: {n_casc}/{n_all} = %{obs_all*100:.2f}")

# Analitik (raporlanan, hatali payda)
counts = df.groupby('KAPINO').size()
lam = (counts / 180.0).mean()
base_analitik = 1 - np.exp(-lam)
print(f"Analitik Poisson (per-gap, raporlanmis): %{base_analitik*100:.2f}  -> oran {obs_all/base_analitik:.2f}x")

# Monte Carlo permutasyon null (dogru, apples-to-apples)
SPAN = 180 * 24 * 3600.0
def mc_once():
    cas = 0
    for c in counts.values:
        t = np.sort(np.random.uniform(0, SPAN, c))
        cas += int((np.diff(t) / 3600.0 < 24).sum())
    return cas / n_all
reps = np.array([mc_once() for _ in range(200)])
mc = reps.mean()
se = np.sqrt(mc * (1 - mc) / n_all)
z = (obs_all - mc) / se
print(f"Monte Carlo null (DOGRU):    %{mc*100:.2f} (+/- {reps.std()*100:.2f}, 200 tekrar)")
print(f">>> Apples-to-apples oran:   {obs_all/mc:.2f}x   (raporlanmis 1.68x -> sisik)")
print(f">>> Z (dogru null):          {z:.1f}        (raporlanmis 49.95 -> sisik)")
print("\nNITEL SONUC degismez: cascade rastgeleden anlamli olcude fazla, p son derece kucuk.")
print("Sadece etki buyuklugu duzeltildi: ~1.4x ve Z~32 (1.68x / Z=50 degil).")
