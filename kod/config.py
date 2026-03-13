import os
from pathlib import Path
from urllib.parse import quote_plus

from sqlalchemy import create_engine


# Bu dosya proje boyunca tek baglanti noktasi olarak kullanilir.
# GitHub'a cikarken gercek baglanti bilgileri burada tutulmaz; .env dosyasindan okunur.
BASE_DIR = Path(__file__).resolve().parent.parent
RESULT_DIR = BASE_DIR / "result"
CSV_DIR = RESULT_DIR / "csv"
GRAPH_DIR = RESULT_DIR / "grafik"


# Paylasilan repoda tablo ve kolon adlari generic tutulur.
# Gercek ortaminizda bunlari kendi veritabani yapiniza gore guncelleyin.
DB_SCHEMA = "ornek_sema"

TABLES = {
    "housing_index": "KonutEndeksTablosu",
    "stock_index": "FinansEndeksTablosu",
    "fx_gold": "KurVeEmtiaTablosu",
    "inflation": "EnflasyonTablosu",
    "construction_cost": "InsaatMaliyetTablosu",
}

COLUMNS = {
    "date": "Tarih",
    "region_code": "BolgeKodu",
    "housing_value": "Endeks",
    "stock_value": "Deger",
    "usd": "Dolar",
    "eur": "Euro",
    "gold": "Altin",
    "inflation": "Yillik",
    "year": "Yil",
    "month": "Ay",
    "total": "Toplam",
    "id": "Id",
}


def _load_env_file() -> None:
    # Lokal gelistirme icin .env dosyasi varsa ortama yuklenir.
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if value:
        return value
    raise RuntimeError(
        f"Eksik ortam degiskeni: {name}. .env.example dosyasini kopyalayip kendi bilgilerinizle .env olusturun."
    )


def get_engine():
    # SQLAlchemy baglantisi her ortamda .env degerleriyle kurulur.
    kullanici = _required_env("DB_USER")
    sifre = _required_env("DB_PASSWORD")
    host = _required_env("DB_HOST")
    port = os.getenv("DB_PORT", "5432")
    veritabani = _required_env("DB_NAME")

    safe_kullanici = quote_plus(kullanici)
    safe_sifre = quote_plus(sifre)
    return create_engine(
        f"postgresql+pg8000://{safe_kullanici}:{safe_sifre}@{host}:{port}/{veritabani}"
    )


def ensure_output_dirs() -> None:
    # CSV ve grafik ciktilari tek klasorde toplansin diye ihtiyac halinde klasorleri olusturur.
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    GRAPH_DIR.mkdir(parents=True, exist_ok=True)
