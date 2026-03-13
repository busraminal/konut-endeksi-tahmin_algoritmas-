import pandas as pd
from prophet import Prophet
import matplotlib.pyplot as plt

from config import COLUMNS, CSV_DIR, DB_SCHEMA, TABLES, ensure_output_dirs, get_engine


# Bu dosya, ornek finans serileriyle hizli tahmin ve ozet rapor uretmek icin tutulur.
engine = get_engine()

query_borsa = 'SELECT "{date_col}" AS ds, "{stock_value_col}" AS y FROM {schema_name}."{stock_table}" ORDER BY "{date_col}" ASC'.format(
    date_col=COLUMNS["date"],
    stock_value_col=COLUMNS["stock_value"],
    schema_name=DB_SCHEMA,
    stock_table=TABLES["stock_index"],
)
query_enf = 'SELECT "{date_col}" AS ds, "{inflation_col}" AS enflasyon FROM {schema_name}."{inflation_table}" ORDER BY "{date_col}" ASC'.format(
    date_col=COLUMNS["date"],
    inflation_col=COLUMNS["inflation"],
    schema_name=DB_SCHEMA,
    inflation_table=TABLES["inflation"],
)
query_altin = 'SELECT "{date_col}" AS ds, "{gold_col}" AS altin_fiyat FROM {schema_name}."{fx_table}" ORDER BY "{date_col}" ASC'.format(
    date_col=COLUMNS["date"],
    gold_col=COLUMNS["gold"],
    schema_name=DB_SCHEMA,
    fx_table=TABLES["fx_gold"],
)

df_borsa = pd.read_sql(query_borsa, engine)
df_enf = pd.read_sql(query_enf, engine)
df_altin = pd.read_sql(query_altin, engine)

# Farkli kaynaklardan gelen serileri ortak tarih eksenine getiriyoruz.
for df_temp in [df_borsa, df_enf, df_altin]:
    df_temp["ds"] = pd.to_datetime(df_temp["ds"], utc=True).dt.tz_localize(None)
    df_temp.sort_values("ds", inplace=True)

df = pd.merge_asof(df_borsa, df_enf, on="ds", direction="backward")
df = pd.merge_asof(df, df_altin, on="ds", direction="backward")
df = df.ffill().fillna(0)

# Ana model, endeks serisini enflasyon ve altinla birlikte ogreniyor.
model = Prophet(changepoint_prior_scale=0.05, yearly_seasonality=True)
model.add_regressor("enflasyon")
model.add_regressor("altin_fiyat")
model.fit(df)

future = model.make_future_dataframe(periods=365)
future["enflasyon"] = df["enflasyon"].iloc[-1]
future["altin_fiyat"] = df["altin_fiyat"].iloc[-1]
forecast = model.predict(future)

model.plot(forecast)
plt.title("Ornek Finans Endeksi - Altin ve Enflasyon Tahmini")
plt.show()

# Altin icin ayri model cizerek ikinci seriyi de bagimsiz inceleyebiliyoruz.
model_altin = Prophet(yearly_seasonality=True, daily_seasonality=False)
model_altin.fit(df_altin.rename(columns={"altin_fiyat": "y"}))
future_altin = model_altin.make_future_dataframe(periods=365)
forecast_altin_kendi = model_altin.predict(future_altin)

bugun = pd.Timestamp.now().normalize()
bir_yil_sonra = bugun + pd.Timedelta(days=365)

f_borsa_12 = forecast[(forecast["ds"] >= bugun) & (forecast["ds"] <= bir_yil_sonra)].copy()
f_altin_12 = forecast_altin_kendi[(forecast_altin_kendi["ds"] >= bugun) & (forecast_altin_kendi["ds"] <= bir_yil_sonra)].copy()

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10), sharex=True)
ax1.plot(f_borsa_12["ds"], f_borsa_12["yhat"], color="blue", label="Beklenen Endeks", linewidth=2)
ax1.fill_between(f_borsa_12["ds"], f_borsa_12["yhat_lower"], f_borsa_12["yhat_upper"], color="blue", alpha=0.15)
ax1.set_title("Onumuzdeki 12 Ay Ornek Endeks Tahmini", fontsize=14)
ax1.grid(True, alpha=0.3)
ax1.legend()

ax2.plot(f_altin_12["ds"], f_altin_12["yhat"], color="orange", label="Beklenen Emtia", linewidth=2)
ax2.fill_between(f_altin_12["ds"], f_altin_12["yhat_lower"], f_altin_12["yhat_upper"], color="orange", alpha=0.15)
ax2.set_title("Onumuzdeki 12 Ay Ornek Emtia Tahmini", fontsize=14)
ax2.set_xlabel("Tarih")
ax2.grid(True, alpha=0.3)
ax2.legend()

plt.tight_layout()
plt.show()

# Iki farkli tahmin serisini tek tabloda ozetlemek icin merge kullaniyoruz.
tahmin_ozet = pd.merge(
    f_borsa_12[["ds", "yhat"]].rename(columns={"yhat": "Endeks_Tahmin"}),
    f_altin_12[["ds", "yhat"]].rename(columns={"yhat": "Emtia_Tahmin"}),
    on="ds",
    how="outer",
)

tahmin_ozet["Ay"] = tahmin_ozet["ds"].dt.to_period("M")
pivot_ozet = tahmin_ozet.groupby("Ay").mean(numeric_only=True).round(2)

print("\n--- Aylik Ortalama Tahmin Verileri ---")
print(pivot_ozet)

ensure_output_dirs()
csv_path = CSV_DIR / "veri_tahmin_ozeti.csv"
pivot_ozet.to_csv(csv_path, encoding="utf-8-sig")
print(f"\n'{csv_path}' dosyasi basariyla olusturuldu.")
