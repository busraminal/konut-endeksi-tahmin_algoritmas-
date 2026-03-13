import pandas as pd
import matplotlib.pyplot as plt
from config import CSV_DIR, GRAPH_DIR, ensure_output_dirs


def plot_2025(bolge_kodu: str = "TP.KFE.TR10", model_adi: str = "M7_maliyet_enflasyon") -> None:
    """
    2025 yılı için, seçilen modelin konut tahminlerini gerçek değerlerle birlikte çizer.

    Girdi dosyası: konut_test_tahminler_<bolge>.csv
    Kolonlar: model, tarih, gercek, tahmin
    """
    ensure_output_dirs()
    kod_kisa = bolge_kodu.replace(".", "_")
    # Grafik, backtest scriptinin urettiği CSV dosyasini kullanir.
    dosya_adi = CSV_DIR / f"konut_test_tahminler_{kod_kisa}.csv"
    grafik_dosyasi = GRAPH_DIR / f"konut_2025_gercek_vs_tahmin_{kod_kisa}_{model_adi}.png"

    df = pd.read_csv(dosya_adi)

    # tarih kolonunu datetime'a çevir
    df["tarih"] = pd.to_datetime(df["tarih"])
    df["yil"] = df["tarih"].dt.year

    # Sadece 2025 ve seçilen modeli filtrele
    df_2025 = df[(df["yil"] == 2025) & (df["model"] == model_adi)].copy()
    if df_2025.empty:
        raise ValueError(f"2025 yılı için '{model_adi}' modeline ait kayıt bulunamadı.")

    df_2025 = df_2025.sort_values("tarih")

    # Gercek ve tahmin serilerini ayni eksende gostererek gorsel karsilastirma sagliyoruz.
    plt.figure(figsize=(12, 6))
    plt.plot(df_2025["tarih"], df_2025["gercek"], marker="o", label="Gerçek KFE")
    plt.plot(df_2025["tarih"], df_2025["tahmin"], marker="s", label=f"Tahmin ({model_adi})")

    plt.title(f"{bolge_kodu} - 2025 Konut Fiyat Endeksi\nGerçek vs Tahmin ({model_adi})")
    plt.xlabel("Tarih")
    plt.ylabel("Endeks")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    # Grafik hem kaydedilir hem de ekranda gosterilir; boylece raporlama icin tekrar uretmeye gerek kalmaz.
    plt.savefig(grafik_dosyasi, dpi=150, bbox_inches="tight")
    plt.show()
    print(f"Grafik kaydedildi: {grafik_dosyasi}")


if __name__ == "__main__":
    # İstersen model_adi'nı 'M0_sadece_konut' veya 'Mfull_6_kisit_6_regresor' yapabilirsin.
    plot_2025("TP.KFE.TR10", model_adi="M7_maliyet_enflasyon")

