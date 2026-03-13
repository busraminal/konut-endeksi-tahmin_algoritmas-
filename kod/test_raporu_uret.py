import pandas as pd
from prophet import Prophet
from typing import List, Dict, Tuple

from config import COLUMNS, CSV_DIR, DB_SCHEMA, TABLES, ensure_output_dirs, get_engine


# Bu script, 2025 gibi secilen bir yil icin model performansini olcmek icin kullanilir.
engine = get_engine()


def hazirla(ds_df: pd.DataFrame) -> pd.DataFrame:
    # Tum kaynaklarda tarih kolonunu ortak formata getiriyoruz.
    ds_df["ds"] = pd.to_datetime(ds_df["ds"], utc=True).dt.tz_localize(None)
    return ds_df.sort_values("ds")


def veri_yukle(bolge_kodu: str) -> pd.DataFrame:
    db_bolge_kodu = bolge_kodu.replace(".", "_")

    # Hedef seri: konut endeksi.
    query_konut = f'''
    SELECT "{COLUMNS["date"]}" AS ds, "{COLUMNS["housing_value"]}" AS y
    FROM {DB_SCHEMA}."{TABLES["housing_index"]}"
    WHERE "{COLUMNS["region_code"]}" = '{db_bolge_kodu}'
    ORDER BY "{COLUMNS["date"]}" ASC
    '''

    # Regresor 1: finans/endeks serisi.
    query_borsa = '''
    SELECT "{date_col}" AS ds, "{stock_value_col}" AS borsa
    FROM {schema_name}."{stock_table}"
    ORDER BY "{date_col}" ASC
    '''.format(
        date_col=COLUMNS["date"],
        stock_value_col=COLUMNS["stock_value"],
        schema_name=DB_SCHEMA,
        stock_table=TABLES["stock_index"],
    )

    # Regresor 2-4: USD, EUR ve altin serileri.
    query_doviz = '''
    SELECT "{date_col}" AS ds,
           "{usd_col}" AS usd,
           "{eur_col}" AS eur,
           "{gold_col}" AS altin
    FROM {schema_name}."{fx_table}"
    ORDER BY "{date_col}" ASC
    '''.format(
        date_col=COLUMNS["date"],
        usd_col=COLUMNS["usd"],
        eur_col=COLUMNS["eur"],
        gold_col=COLUMNS["gold"],
        schema_name=DB_SCHEMA,
        fx_table=TABLES["fx_gold"],
    )

    # Regresor 5: enflasyon.
    query_enf = '''
    SELECT "{date_col}" AS ds, "{inflation_col}" AS enflasyon
    FROM {schema_name}."{inflation_table}"
    ORDER BY "{date_col}" ASC
    '''.format(
        date_col=COLUMNS["date"],
        inflation_col=COLUMNS["inflation"],
        schema_name=DB_SCHEMA,
        inflation_table=TABLES["inflation"],
    )

    # Regresor 6: insaat maliyetleri.
    query_insaat = '''
    SELECT *
    FROM {schema_name}."{construction_table}"
    ORDER BY "{id_col}" ASC
    '''.format(
        schema_name=DB_SCHEMA,
        construction_table=TABLES["construction_cost"],
        id_col=COLUMNS["id"],
    )

    df_konut = hazirla(pd.read_sql(query_konut, engine))
    df_borsa = hazirla(pd.read_sql(query_borsa, engine))
    df_doviz = hazirla(pd.read_sql(query_doviz, engine))
    df_enf = hazirla(pd.read_sql(query_enf, engine))
    df_insaat_raw = pd.read_sql(query_insaat, engine)

    if df_konut.empty:
        raise ValueError("Secilen bolge icin konut verisi bulunamadi.")

    cols_insaat = {c.lower(): c for c in df_insaat_raw.columns}
    yil_ins = next((cols_insaat[k] for k in cols_insaat if k in ("yil", "yıl", "year")), None)
    ay_ins = next((cols_insaat[k] for k in cols_insaat if k in ("ay", "month")), None)
    toplam_ins = next((cols_insaat[k] for k in cols_insaat if k in ("toplam", "endeks", "deger")), None)
    if not (yil_ins and ay_ins and toplam_ins):
        raise ValueError("Insaat maliyet tablosu icin Yil/Ay/Toplam benzeri kolonlar bulunamadi.")

    df_insaat = df_insaat_raw.copy()
    df_insaat["ds"] = pd.to_datetime(
        {
            "year": df_insaat[yil_ins].astype(int),
            "month": df_insaat[ay_ins].astype(int),
            "day": 1,
        }
    )
    df_insaat = df_insaat.rename(columns={toplam_ins: "insaat_maliyet"})[["ds", "insaat_maliyet"]]
    df_insaat = hazirla(df_insaat)

    # Tum serileri tek bir egitim tablosuna topluyoruz.
    df = df_konut.copy()
    for df_extra in [df_borsa, df_doviz, df_enf, df_insaat]:
        df = pd.merge_asof(df, df_extra, on="ds", direction="backward")

    df = df.sort_values("ds").dropna(subset=["y"])
    for col in ["borsa", "usd", "eur", "altin", "enflasyon", "insaat_maliyet"]:
        if col in df.columns:
            df[col] = df[col].ffill().bfill().fillna(0)

    return df


def metrik_hesapla(y_true: np.ndarray, y_pred: np.ndarray) -> Tuple[float, float, float]:
    mae = float(np.mean(np.abs(y_true - y_pred)))
    rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
    eps = 1e-8
    mape = float(np.mean(np.abs((y_true - y_pred) / (y_true + eps))) * 100)
    return mae, mape, rmse


def model_egit_ve_test_et_yila_gore(
    df: pd.DataFrame, regressor_list: List[str], test_yil: int, model_adi: str
) -> Tuple[Dict[str, float], pd.DataFrame]:
    # Gecmis yillar train, secilen yil ise test seti olarak ayrilir.
    df = df.sort_values("ds").reset_index(drop=True)
    df["yil"] = df["ds"].dt.year

    train = df[df["yil"] < test_yil].copy()
    test = df[df["yil"] == test_yil].copy()

    if train.empty or test.empty:
        raise ValueError(f"{test_yil} yili icin yeterli egitim/test verisi yok.")

    # Her model ayni Prophet ayarlariyla kurulur; fark sadece kullanilan regressorlardir.
    model = Prophet(
        changepoint_prior_scale=0.2,
        yearly_seasonality=True,
        weekly_seasonality=False,
        daily_seasonality=False,
    )

    for reg in regressor_list:
        model.add_regressor(reg)

    model.fit(train)
    forecast = model.predict(test[["ds"] + regressor_list])

    y_true = test["y"].values
    y_pred = forecast["yhat"].values
    mae, mape, rmse = metrik_hesapla(y_true, y_pred)

    metrikler = {
        "model": model_adi,
        "regresorler": ", ".join(regressor_list) if regressor_list else "yok",
        "MAE": mae,
        "MAPE": mape,
        "RMSE": rmse,
    }

    tahmin_df = pd.DataFrame(
        {
            "model": model_adi,
            "tarih": test["ds"].dt.strftime("%Y-%m-%d"),
            "gercek": y_true,
            "tahmin": y_pred,
        }
    )
    return metrikler, tahmin_df


def ana(bolge_kodu: str = "TP.KFE.TR10", test_yil: int = 2025) -> None:
    df = veri_yukle(bolge_kodu)

    modeller = [
        ("M0_sadece_konut", []),
        ("M6_insaat_maliyet", ["insaat_maliyet"]),
        ("M7_maliyet_enflasyon", ["insaat_maliyet", "enflasyon"]),
        ("Mfull_6_kisit_6_regresor", ["borsa", "usd", "eur", "altin", "enflasyon", "insaat_maliyet"]),
    ]

    metrik_list: List[Dict[str, float]] = []
    tahmin_list: List[pd.DataFrame] = []

    for model_adi, regs in modeller:
        print(f"Model calisiyor: {model_adi} (regresorler: {regs})")
        metrikler, tahmin_df = model_egit_ve_test_et_yila_gore(df, regs, test_yil=test_yil, model_adi=model_adi)
        metrik_list.append(metrikler)
        tahmin_list.append(tahmin_df)

    ensure_output_dirs()
    kod_kisa = bolge_kodu.replace(".", "_")
    metrik_path = CSV_DIR / f"konut_test_metrik_{kod_kisa}.csv"
    tahmin_path = CSV_DIR / f"konut_test_tahminler_{kod_kisa}.csv"

    # Sonuclari hem metrik tablosu hem de tarih bazli tahmin dosyasi olarak kaydediyoruz.
    pd.DataFrame(metrik_list).to_csv(metrik_path, index=False, encoding="utf-8-sig")
    pd.concat(tahmin_list, ignore_index=True).to_csv(tahmin_path, index=False, encoding="utf-8-sig")

    print(f"Metrik dosyasi yazildi: {metrik_path}")
    print(f"Tahmin detay dosyasi yazildi: {tahmin_path}")


if __name__ == "__main__":
    ana("TP.KFE.TR10", test_yil=2025)
