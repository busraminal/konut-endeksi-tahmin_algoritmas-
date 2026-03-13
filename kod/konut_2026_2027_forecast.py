import pandas as pd
from prophet import Prophet
from test_raporu_uret import veri_yukle
from config import CSV_DIR, ensure_output_dirs


def konut_2026_2027_tahmin(bolge_kodu: str = "TP.KFE.TR10") -> pd.DataFrame:
    """
    Seçilen bölge için (varsayılan: İstanbul) 2018–2025 arasındaki tüm verilerle modeli eğitir,
    ardından 2026 ve 2027 yılları için aylık konut endeksi tahmini üretir.

    Model mimarisi:
    - Prophet
    - Regressorler: insaat_maliyet, enflasyon
      (2025 test yılında en yüksek katkıyı veren iki değişken)
    """
    # Veri seti, test scriptiyle ayni veri hazirlama mantigini kullanir.
    df = veri_yukle(bolge_kodu)
    df = df.sort_values("ds").reset_index(drop=True)

    # Eğitim dönemi: mevcut tüm veriler
    train = df.copy()

    # 2025 testinde en anlamli bulunan iki degiskenle son tahmin modeli kurulur.
    model = Prophet(
        changepoint_prior_scale=0.2,
        yearly_seasonality=True,
        weekly_seasonality=False,
        daily_seasonality=False,
    )

    for reg in ["insaat_maliyet", "enflasyon"]:
        model.add_regressor(reg)

    model.fit(train)

    # Gelecek 24 ay (2026–2027) için tarih çerçevesi
    future = model.make_future_dataframe(periods=24, freq="M")

    # Regressor değerlerini geçmiş df'ten kopyala, ileri/geri doldur
    future = future.merge(
        train[["ds", "insaat_maliyet", "enflasyon"]],
        on="ds",
        how="left",
    )

    for col in ["insaat_maliyet", "enflasyon"]:
        son_deger = train[col].iloc[-1]
        future[col] = future[col].ffill().bfill().fillna(son_deger)

    forecast = model.predict(future)

    # Sadece 2026–2027 aralığını filtrele
    forecast["yil"] = forecast["ds"].dt.year
    tahmin_2026_2027 = forecast[forecast["yil"].isin([2026, 2027])].copy()

    sonuc = tahmin_2026_2027[
        ["ds", "yhat", "yhat_lower", "yhat_upper"]
    ].rename(columns={"ds": "tarih"})

    return sonuc


if __name__ == "__main__":
    df_out = konut_2026_2027_tahmin("TP.KFE.TR10")
    ensure_output_dirs()
    dosya_adi = CSV_DIR / "konut_2026_2027_TP_KFE_TR10.csv"
    df_out.to_csv(dosya_adi, index=False, encoding="utf-8-sig")
    print(f"Tahmin dosyası yazıldı: {dosya_adi}")

