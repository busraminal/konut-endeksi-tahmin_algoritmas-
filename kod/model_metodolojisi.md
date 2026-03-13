### Model Metodolojisi

#### 1. Amac ve Kapsam

Bu modelin amaci, secilen bolge bazinda (or. `BOLGE_KODU_01`) onumuzdeki donemler icin konut endeksi tahmini uretmektir.
Model, gecmis konut fiyatlarini ve finansal/makroekonomik gostergeleri birlikte kullanir.

- **Hedef degisken**: ornek konut endeksi tablosundaki hedef endeks kolonu
- **Tahmin ufku**: API isteginde verilen `horizon_ay`

---

#### 2. Veri Kaynaklari ve Kullanilan Degiskenler

Model, ayni veritabanindaki ornek veri kaynaklarini kullanir:

- **Konut fiyat endeksi (hedef seri)**
  - **Tablo**: ornek konut endeks tablosu
  - **Filtre**: ornek bolge kodu kolonu uzerinden yapilir
  - **Kolonlar**:
    - tarih kolonu -> `ds`
    - endeks kolonu -> `y`

- **Finans endeksi (regresor)**
  - tarih kolonu -> `ds`
  - deger kolonu -> `borsa`

- **Kur ve emtia verileri (regresorler)**
  - tarih kolonu -> `ds`
  - kur kolonlari -> `usd`, `eur`
  - emtia kolonu -> `altin`

- **Enflasyon (regresor)**
  - tarih kolonu -> `ds`
  - yillik oran kolonu -> `enflasyon`

- **Insaat maliyet endeksi (regresor)**
  - yil / ay kolonlari -> `ds`
  - toplam kolonu -> `insaat_maliyet`

Bu yapi sayesinde model su degiskenleri birlikte kullanir:

- `borsa`
- `usd`
- `eur`
- `altin`
- `enflasyon`
- `insaat_maliyet`

---

#### 3. Veri Birlestirme ve Temizleme

1. Temel seri olarak konut endeks tablosu alinir.
2. Diger tablolar `ds` uzerinden `merge_asof` ile eklenir.
3. Hedef seri bos olan satirlar atilir.
4. Regresor kolonlari icin ileri doldurma, geri doldurma ve gerekirse `0` ile tamamlama uygulanir.

---

#### 4. Model Yapisi

- **Model turu**: Prophet
- **Hedef**: `y`
- **Regresorler**: `usd`, `eur`, `altin`, `enflasyon`, `insaat_maliyet`, `borsa`
- **Sezonsallik**:
  - yillik acik
  - haftalik kapali veya senaryoya gore acik
  - gunluk kapali

---

#### 5. Cok Asamali (Multi-stage) Mimari

Gelismis surumde her makro degisken icin ayri zaman serisi modeli kurulur:

- USD modeli
- EUR modeli
- Altin modeli
- Enflasyon modeli
- Insaat maliyet modeli
- Finans endeksi modeli

Bu alt modellerin ileri donuk tahminleri, ana konut modeline regressor olarak verilir.
Buna **multi-stage causal forecasting** yaklasimi denir.

---

#### 6. Tahmin Ciktilari

Her gelecek donem icin uc ana deger uretilir:

- `tahmin` (`yhat`): merkez tahmin
- `alt_sinir` (`yhat_lower`): alt beklenti bandi
- `ust_sinir` (`yhat_upper`): ust beklenti bandi

Bu yapi sayesinde model, tek bir sayi degil ayni zamanda belirsizlik araligini da sunar.

---

#### 7. Guvenlik ve Paylasim Notu

Bu dokumanda tablo, sema ve kolon isimleri bilerek **ornek / generic** hale getirilmistir.
Gercek kurum ici nesne adlari, baglanti bilgileri ve uretim verileri GitHub gibi ortamlarda paylasilmamalidir.
