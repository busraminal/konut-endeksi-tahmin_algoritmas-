import pandas as pd
from prophet import Prophet
import matplotlib.pyplot as plt

from config import COLUMNS, CSV_DIR, DB_SCHEMA, TABLES, ensure_output_dirs, get_engine


# Bu dosya, belirli bir test yilinda Prophet performansini hizli gormek icin kullanilir.
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

# Tum seriler ayni tarih tipine cevrilir ve merge_asof ile eslestirilir.
for df_temp in [df_borsa, df_enf, df_altin]:
    df_temp["ds"] = pd.to_datetime(df_temp["ds"], utc=True).dt.tz_localize(None)
    df_temp.sort_values("ds", inplace=True)

df = pd.merge_asof(df_borsa, df_enf, on="ds", direction="backward")
df = pd.merge_asof(df, df_altin, on="ds", direction="backward")
df = df.ffill().fillna(0)

# Burada 2025 yilini test, onceki donemi train olarak kullaniyoruz.
train_df = df[(df["ds"] >= "2022-01-01") & (df["ds"] <= "2024-12-31")].copy()
test_df = df[(df["ds"] >= "2025-01-01") & (df["ds"] <= "2025-12-31")].copy()

if test_df.empty:
    print("UYARI: 2025 yilina ait veri bulunamadi. Test analizi yapilamiyor.")
else:
    # Tek modelle 2025 backtest tahmini uretilir.
    model = Prophet(
        changepoint_prior_scale=0.2,
        yearly_seasonality=True,
        weekly_seasonality=True,
        daily_seasonality=False,
    )
    model.add_regressor("enflasyon")
    model.add_regressor("altin_fiyat")
    model.fit(train_df)

    forecast_tmp = model.predict(test_df[["ds", "enflasyon", "altin_fiyat"]])
    eval_df = pd.merge(
        test_df[["ds", "y"]],
        forecast_tmp[["ds", "yhat", "yhat_lower", "yhat_upper"]],
        on="ds",
    )

    hata = eval_df["y"] - eval_df["yhat"]
    mae = hata.abs().mean()
    rmse = (hata ** 2).mean() ** 0.5
    mape = (hata.abs() / eval_df["y"].replace(0, float("nan"))).mean() * 100

    print("\n--- 2025 Test Yili Analizi ---")
    print(f"MAE: {mae:.2f}")
    print(f"RMSE: {rmse:.2f}")
    if not pd.isna(mape):
        print(f"MAPE: {mape:.2f}%")

    plt.figure(figsize=(14, 7))
    plt.plot(eval_df["ds"], eval_df["y"], label="Gercek Veri (2025)", color="black", linewidth=1.5, marker="o", markersize=2)
    plt.plot(eval_df["ds"], eval_df["yhat"], label="Prophet Tahmini (2025)", color="blue", linewidth=2)
    plt.fill_between(eval_df["ds"], eval_df["yhat_lower"], eval_df["yhat_upper"], color="blue", alpha=0.15, label="Guven Araligi")
    plt.title("2025 Yili: Gerceklesen vs Prophet Tahmini", fontsize=14)
    plt.xlabel("Tarih")
    plt.ylabel("Endeks Degeri")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.show()

    # Aylik rapor, yonetici ozetlerinde daha kolay okunmasi icin ayrica uretlir.
    eval_df["Ay"] = eval_df["ds"].dt.to_period("M")
    aylik_rapor = eval_df.groupby("Ay").mean(numeric_only=True).round(2)
    aylik_rapor.columns = ["Gercek_Endeks_Ort", "Prophet_Tahmin_Ort", "Prophet_En_Dusuk", "Prophet_En_Yuksek"]

    ensure_output_dirs()
    csv_path = CSV_DIR / "finans_2025_analiz_raporu_prophet.csv"
    aylik_rapor.to_csv(csv_path, encoding="utf-8-sig")

    print("\n--- 2025 Yili Aylik Prophet Tahmin ve Gerceklesme Ozeti ---")
    print(aylik_rapor)
    print(f"\n'{csv_path}' dosyasi basariyla olusturuldu.")
