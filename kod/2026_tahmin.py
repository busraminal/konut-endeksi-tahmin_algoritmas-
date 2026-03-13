import pandas as pd
from prophet import Prophet
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any
import uvicorn

from config import COLUMNS, DB_SCHEMA, TABLES, get_engine


# API ve tahmin kodu ayni dosyada tutuluyor; baglanti bilgisi config.py'den gelir.
engine = get_engine()


bolgeler = {
    "TP.KFE.TR": "Turkiye geneli",
    "TP.KFE.TR10": "Istanbul",
    "TP.KFE.TR51": "Ankara",
    "TP.KFE.TR31": "Izmir",
    "TP.KFE.TR21": "Edirne, Kirklareli, Tekirdag",
    "TP.KFE.TR22": "Balikesir, Canakkale",
    "TP.KFE.TR32": "Aydin, Denizli, Mugla",
    "TP.KFE.TR33": "Afyonkarahisar, Kutahya, Manisa, Usak",
    "TP.KFE.TR41": "Bursa, Eskisehir, Bilecik",
    "TP.KFE.TR42": "Bolu, Kocaeli, Sakarya, Yalova, Duzce",
    "TP.KFE.TR52": "Konya, Karaman",
    "TP.KFE.TR61": "Antalya, Burdur, Isparta",
    "TP.KFE.TR62": "Adana, Mersin",
    "TP.KFE.TR63": "Hatay, Kahramanmaras, Osmaniye",
    "TP.KFE.TR7": "Nevsehir, Nigde, Kirikkale, Kirsehir, Aksaray, Kayseri, Sivas, Yozgat",
    "TP.KFE.TR8": "Karadeniz bolge grubu",
    "TP.KFE.TR9": "Dogu Karadeniz bolge grubu",
    "TP.KFE.TRA": "TRA bolge grubu",
    "TP.KFE.TRB": "TRB bolge grubu",
    "TP.KFE.TRC": "TRC bolge grubu",
}


def hazirla(df: pd.DataFrame) -> pd.DataFrame:
    # Prophet'in bekledigi tarih kolonunu standart datetime formatina ceviriyoruz.
    df["ds"] = pd.to_datetime(df["ds"], utc=True).dt.tz_localize(None)
    return df.sort_values("ds")


def konut_tahmin(bolge_kodu: str, horizon_ay: int) -> pd.DataFrame:
    if bolge_kodu not in bolgeler:
        raise ValueError("Gecersiz bolge kodu.")
    if horizon_ay <= 0:
        raise ValueError("Horizon (ay) pozitif olmali.")

    db_bolge_kodu = bolge_kodu.replace(".", "_")

    # Hedef seri: secilen bolgenin konut endeksi.
    query_konut = f'''
    SELECT "{COLUMNS["date"]}" AS ds, "{COLUMNS["housing_value"]}" AS y
    FROM {DB_SCHEMA}."{TABLES["housing_index"]}"
    WHERE "{COLUMNS["region_code"]}" = '{db_bolge_kodu}'
    ORDER BY "{COLUMNS["date"]}" ASC
    '''

    # Yardimci seri: finans/endeks verisi.
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

    # Yardimci seri: kur ve emtia verileri.
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

    # Yardimci seri: enflasyon verisi.
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

    # Yardimci seri: insaat maliyetleri.
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

    # Tum serileri ortak tarih ekseninde tek tabloya indiriyoruz.
    df = df_konut.copy()
    for df_extra in [df_borsa, df_doviz, df_enf, df_insaat]:
        df = pd.merge_asof(df, df_extra, on="ds", direction="backward")

    df = df.sort_values("ds").dropna(subset=["y"])
    for col in ["usd", "eur", "altin", "enflasyon", "insaat_maliyet", "borsa"]:
        if col in df.columns:
            df[col] = df[col].ffill().bfill().fillna(0)

    if df.empty:
        raise ValueError("Birlestirilmis veri seti bos.")

    son_tarih = df["ds"].max()

    # Ana model, hedef seriyi tum regresorlerle birlikte ogreniyor.
    model = Prophet(
        changepoint_prior_scale=0.2,
        yearly_seasonality=True,
        weekly_seasonality=False,
        daily_seasonality=False,
    )
    for reg in ["usd", "eur", "altin", "enflasyon", "insaat_maliyet", "borsa"]:
        model.add_regressor(reg)
    model.fit(df)

    # Her makro degisken icin ayri model kurarak ileriye donuk regresor senaryosu uretiyoruz.
    def tek_seri_model(df_seri: pd.DataFrame, kolon: str) -> Prophet:
        local_df = df_seri[["ds", kolon]].rename(columns={kolon: "y"}).dropna(subset=["y"])
        if local_df.empty:
            raise ValueError(f"{kolon} serisi bos.")
        m = Prophet(
            changepoint_prior_scale=0.2,
            yearly_seasonality=True,
            weekly_seasonality=False,
            daily_seasonality=False,
        )
        m.fit(local_df)
        return m

    usd_model = tek_seri_model(df_doviz, "usd")
    eur_model = tek_seri_model(df_doviz, "eur")
    altin_model = tek_seri_model(df_doviz, "altin")
    enf_model = tek_seri_model(df_enf, "enflasyon")
    insaat_model = tek_seri_model(df_insaat, "insaat_maliyet")
    borsa_model = tek_seri_model(df_borsa, "borsa")

    # Gelecek aylar icin once tarih, sonra da regressorlere ait tahmin serileri uretilir.
    future = model.make_future_dataframe(periods=horizon_ay, freq="M")
    future["usd"] = usd_model.predict(future[["ds"]])["yhat"].values
    future["eur"] = eur_model.predict(future[["ds"]])["yhat"].values
    future["altin"] = altin_model.predict(future[["ds"]])["yhat"].values
    future["enflasyon"] = enf_model.predict(future[["ds"]])["yhat"].values
    future["insaat_maliyet"] = insaat_model.predict(future[["ds"]])["yhat"].values
    future["borsa"] = borsa_model.predict(future[["ds"]])["yhat"].values

    forecast = model.predict(future)
    forecast_future = forecast[forecast["ds"] > son_tarih].copy()
    return forecast_future[["ds", "yhat", "yhat_lower", "yhat_upper"]]


app = FastAPI(title="Konut Endeksi Tahmin Servisi")


class TahminIstek(BaseModel):
    bolge_kodu: str
    horizon_ay: int


@app.get("/")
def root() -> Dict[str, str]:
    return {"status": "ok", "message": "Konut Endeksi Tahmin Servisi calisiyor. /docs veya /bolgeler kullanin."}


@app.get("/bolgeler")
def bolge_listesi() -> Dict[str, str]:
    return bolgeler


@app.post("/tahmin")
def tahmin_al(istek: TahminIstek) -> Dict[str, Any]:
    try:
        df = konut_tahmin(istek.bolge_kodu, istek.horizon_ay)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sunucu hatasi: {e}")

    # API cevabini JSON'a uygun hale getirmek icin DataFrame'i listeye ceviriyoruz.
    kayitlar: List[Dict[str, Any]] = []
    for _, row in df.iterrows():
        kayitlar.append(
            {
                "tarih": row["ds"].strftime("%Y-%m-%d"),
                "tahmin": float(row["yhat"]),
                "alt_sinir": float(row["yhat_lower"]),
                "ust_sinir": float(row["yhat_upper"]),
            }
        )

    return {
        "bolge_kodu": istek.bolge_kodu,
        "bolge_adi": bolgeler.get(istek.bolge_kodu, ""),
        "horizon_ay": istek.horizon_ay,
        "tahminler": kayitlar,
    }


if __name__ == "__main__":
    uvicorn.run("2026_tahmin:app", host="127.0.0.1", port=8000, reload=True)
