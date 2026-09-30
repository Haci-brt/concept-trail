# Concept Trail'i test etmek

Üç parça var: elle denemek için ayrı bir **test ortamı**, her şeyi kendiliğinden deneyen **otomatik testler** ve adım adım bir **kontrol listesi**. Hiçbiri gerçek notlarına ya da ayarlarına dokunmaz.

---

## 1. Test ortamı

Depo klasöründe:

```bash
python -m testkit
```

Tarayıcıda örnek notlarla dolu ayrı bir Concept Trail açılır. Cevapları **sahte bir model** verir: API anahtarı, ücret ve internet gerekmez (araştırma hariç). Sahte model akıllı değildir ama her zaman aynı biçimde cevap verir; bu yüzden her ekran ve her düğme denenebilir.

| Komut | Ne yapar |
|---|---|
| `python -m testkit` | Tarayıcıda açar |
| `python -m testkit --pencere` | Masaüstü penceresinde açar (asistan kartıyla birlikte) |
| `python -m testkit --ilk-acilis` | Hiç model bağlı değilmiş gibi açar: kurulum sihirbazını dene |
| `python -m testkit --gercek-model` | Sahte model yerine kendi model ayarlarınla açar; notlar yine ayrı kalır |
| `python -m testkit --sifirla` | Örnek notları ve test ayarlarını baştan kurar |
| `python -m testkit --sunucu` | Hiç pencere açmaz; yazdığı adresi kendin açarsın |
| `python -m testkit --gecikme 1` | Sahte modelin cevabını 1 saniye geciktirir (bekleme animasyonlarını görmek için) |

Her şey kod klasörünün yanındaki `.sandbox/` içinde durur: notlar `.sandbox/kasa`, ayarlar `.sandbox/ayar`. Git bu klasörü görmez. Durdurmak için komut penceresinde **Ctrl+C**.

**Örnek notlar**

| Not | Ne için |
|---|---|
| Beni oku | Bu listenin kısası |
| Bitki hatırlatıcı | Karar merdiveni baştan: Kapsam soruları |
| Harcama takibi | Kapsamı yazılmış not: merdiven Mimari basamağında |
| Kitap takası | `tur: fikir` notu: merak soruları |
| Expense tracker | İngilizce not: dil ayarlarını denemek için |
| Maaş planı | `gizli: true` notu |
| Uzun not | 25 bin karakter: yazarken hız |
| Büyük ağaç | 120 düğümlü fikir ağacı |

---

## 2. Otomatik testler

```bash
python -m pytest                     # hepsi (1–2 dakika)
python -m pytest -m "not e2e"        # tarayıcısız olanlar (yaklaşık 20 saniye)
python -m pytest tests/e2e           # yalnız tarayıcı testleri (yaklaşık 1 dakika)
```

Tarayıcı testleri için bir kez `python -m playwright install chromium` gerekir; Chromium yoksa bu testler atlanır, başarısız sayılmaz. Tarayıcı testleri uygulamayı gerçekten başlatır (kendi geçici kasası ve sahte modeliyle), ekranı olmayan bir Chromium'da açar ve gerçek tuşlarla dener:

- açılış: örnek notlar, model düğmesi, sayfada hiç JavaScript hatası olmaması
- yazarken tamamlama: soluk öneri, harfleri yazınca devam etmesi, Ctrl+→, Tab, tek adımda Ctrl+Z, Esc, Ctrl+Space, kapatma
- asistanın sorusu → cevap → "Nota eklensin mi?" → onay ve ancak o zaman notta görünmesi
- kurulum sihirbazı: kendiliğinden açılma, geçme, hatalı adresin anlaşılır sözle söylenmesi, bağlanma
- fikir ağacı: 100+ yıldız, akan animasyon, kenardan uzaklaşınca yıldızların savrulmaması
- yedi tema ve her birinin gökyüzü
- İngilizce arayüzde Türkçe kalmış arayüz metni olmaması (not adları ve model metni hariç)
- master prompt: 19 bölüm ve modelin verdiği kararlar
- `tur: fikir` notunda karar merdiveni yerine merak soruları
- hız: uzun notta tuş başına süre, büyük ağaçta fizik adımı

Her push'ta aynı testler GitHub Actions'ta Ubuntu, macOS ve Windows'ta çalışır (`.github/workflows/kurulum.yml`); tarayıcı testleri Ubuntu ve Windows'ta.

---

## 3. Elle kontrol listesi

Test ortamında sırayla dene. Her maddede **ne yapacağın → ne görmen gerektiği** yazıyor.

**Kurulum ve açılış** (`python -m testkit --ilk-acilis`)
- [ ] Uygulama açılınca "Asistanı bir modele bağla" penceresi kendiliğinden gelir.
- [ ] "Şimdilik geç" → pencere kapanır; üstteki model düğmesi "Modeli bağla" olur; sayfayı yenileyince pencere kendiliğinden gelmez.
- [ ] "Modeli bağla"ya tıkla → "Bu bilgisayarda çalışan bir model" → bulunan modeli seç → "Bağlan ve dene" → "Hazır!"
- [ ] Yanlış bir adres yaz (ör. `http://127.0.0.1:9`) → "…adresine ulaşılamadı" gibi anlaşılır bir mesaj; hiçbir şey kaydedilmez.

**Not ve canlı izleme** (Bitki hatırlatıcı)
- [ ] Notun sonuna bir cümle ekle ve 15 saniye bekle → sağ panelde sorular belirir; yazarken araya pencere girmez.
- [ ] Ctrl+Enter → beklemeden sorar.
- [ ] Durum çubuğundaki "Canlı izleme"ye tıkla → kapanır; 15 saniye beklemek artık soru getirmez.

**Karar merdiveni**
- [ ] Bitki hatırlatıcı: sorular Kapsam basamağından (kullanıcı, platform, çalışma ortamı).
- [ ] Bir soruya panelde tek satırla cevap ver → "Nota eklensin mi?" → Onayla → cümle notta; Vazgeç → notta hiçbir şey değişmez.
- [ ] Aynısını Fikir ağacı görünümünde, sohbet kutusuna tıklıyken yap → cümle nota girer, sohbet kutusu boş kalır.
- [ ] Sohbette "bilmiyorum" ya da "fikrin var mı" yaz → asistan artıları/eksileriyle seçenekler sunar, notuna hiçbir şey önermez; birini seçince ("ilkini yapalım") onu karar olarak önerir.
- [ ] Bir soruda yazıp göndermeden başka bir sorunun sohbetine geç → kutu boş; geri dön → yazdığın duruyor.
- [ ] Bir öneriyi onaylamadan sohbeti kapat, yeniden aç → "Nota eklensin mi?" kartı hâlâ orada.
- [ ] Yol haritası kartında karar çipleri dolar.
- [ ] Harcama takibi: notta yazan kararlar sorulmaz; sorular Mimari basamağından.

**Yazarken tamamlama**
- [ ] Bir satırın sonunda yaz ve bir an dur → devamı soluk yazıyla ve "Tab" işaretiyle belirir.
- [ ] Gösterilen harfleri yazmaya devam et → öneri kaybolmaz, kısalır.
- [ ] Ctrl+→ bir kelime alır; Tab kalanını alır; Ctrl+Z geri alır.
- [ ] Esc kapatır; başka bir harf yazmak kapatır; Ctrl+Space hemen ister.
- [ ] Durum çubuğundaki "Tamamlama"ya tıkla → kapanır, öneri gelmez.

**Fikir notu** (Kitap takası)
- [ ] Ctrl+Enter → "Derinleştirme", "Alternatif fikir" gibi merak soruları; "Kapsam · …" soruları gelmez.

**Rotayı düzelt**
- [ ] Bir notta "Rotayı düzelt" → bir düzeltme yaz → değişecekleri gösteren özet → onaylamadan hiçbir şey değişmez.
- [ ] Özette "Hemen sorulacak yeni sorular" var; onaylayınca bu sorular panelde "Yeni yön" etiketiyle hemen belirir.

**Fikir ağacı** (Büyük ağaç → Fikir ağacı)
- [ ] Yıldızlar merkezden dışa doğru tutuşur, ipler çizilerek uzar.
- [ ] Tekerlekle kenardan uzaklaş/yakınlaş → yumuşak zoom; yıldızlar savrulmaz.
- [ ] Boşluğu tutup kaydır → kalkışta geride kalır, durunca ileri salınır, sonra oturur.
- [ ] Bir yıldızı sürükle → bağlı olanları çeker; bırakınca yerine döner.
- [ ] Yıldıza tıkla → kartı açılır, yol aydınlanır; boşluğa tıkla → kapanır. N → sıradaki soru.
- [ ] Temayı değiştir → gökyüzü de değişir (orman gecesinde ateş böcekleri, gün batımında kıvılcımlar, buzulda kutup ışıkları).

**Master prompt** (Harcama takibi)
- [ ] Ctrl+Shift+M → Oluştur → 0'dan 18'e bölümler; üstte "Modelin senin yerine verdiği kararlar".
- [ ] Kopyala, Not olarak kaydet ve İndir çalışır.

**Diller**
- [ ] Üstteki dünya düğmesi → English → arayüz İngilizce; not adları ve notların içeriği değişmez.
- [ ] Asistan dilini ayrı seç (ör. Deutsch) → yeni sorular o dilde (sahte modelde soru metinleri şablondur; gerçek dil kalitesi için `--gercek-model`).

**Gizlilik** (`--gercek-model` ve uzak bir sağlayıcıyla)
- [ ] Maaş planı notunda Ctrl+Enter → uzak modele gitmez; yalnız yerel model varsa o kullanılır, yoksa sessiz kalır.

**Hız** (Uzun not)
- [ ] Notun ortasında hızlı yaz → takılma yok.

**Araştırma** (internet gerekir; anlamlı sonuç için `--gercek-model`)
- [ ] Harcama takibi → Araştır → GitHub ve web sonuçları, en yakın projelerin karşılaştırması; bulgular yalnız onayla nota girer.

**Masaüstü** (`python -m testkit --pencere`)
- [ ] Uygulama kendi penceresinde açılır; asistan kartı sorularla belirir.

---

## 4. Bir sorun bulursan

Şunları gönder:

1. Hangi adımda oldu, ne bekliyordun, ne gördün.
2. Ekran görüntüsü.
3. Günlük: test ortamında `python -m testkit`'i çalıştırdığın pencerenin son satırları; kurulu uygulamada `%APPDATA%\ConceptTrail\concept-trail.log`.
4. Tarayıcıda açtıysan F12 → Console'daki kırmızı satırlar.
