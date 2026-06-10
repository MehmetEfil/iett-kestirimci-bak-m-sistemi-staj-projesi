import pandas as pd
import numpy as np

# Load data
df = pd.read_csv('c:/Users/asus/Desktop/Datathon/analiz_8/analiz8_tam_liste.csv', encoding='utf-8')

# Calculate Garage Peer Z-Score
garaj_stats = df.groupby('GARAJ')['gecmis_ciddi_oran'].agg(['mean', 'std']).reset_index()
garaj_stats.columns = ['GARAJ', 'garaj_mean', 'garaj_std']
df = df.merge(garaj_stats, on='GARAJ', how='left')
df['z_garaj'] = (df['gecmis_ciddi_oran'] - df['garaj_mean']) / df['garaj_std'].replace(0, 1)

# Calculate Age Peer Z-Score
yas_stats = df.groupby('yas')['gecmis_ciddi_oran'].agg(['mean', 'std']).reset_index()
yas_stats.columns = ['yas', 'yas_mean', 'yas_std']
df = df.merge(yas_stats, on='yas', how='left')
df['z_yas'] = (df['gecmis_ciddi_oran'] - df['yas_mean']) / df['yas_std'].replace(0, 1)

# Calculate new kompozit skor
df['yeni_skor'] = df['z_garaj'] * 0.6 + df['z_yas'] * 0.4
# Normalize to 0-100 scale for presentation
min_s = df['yeni_skor'].min()
max_s = df['yeni_skor'].max()
df['kritiklik_skoru_yeni'] = ((df['yeni_skor'] - min_s) / (max_s - min_s)) * 100

# Sort and get top 50
df = df.sort_values('kritiklik_skoru_yeni', ascending=False)
top50 = df.head(50)

print("Top 50 Garaj Dağılımı:")
print(top50['GARAJ'].value_counts())
print("\nTop 50 Yaş Ortalaması:")
print(top50['yas'].mean())
print("\nTop 10 Araçlar:")
print(top50[['KAPINO', 'GARAJ', 'yas', 'gecmis_ciddi_oran', 'kritiklik_skoru_yeni']].head(10))
