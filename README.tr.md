<p align="center"><img src="assets/icon/png/concept-trail-128.png" width="104" alt="Concept Trail"></p>

# Concept Trail

[English](README.md) · **Türkçe** · **[Tanıtım: neyi çözer, baştan sona bir örnekle](docs/TANITIM.md)**

*Yazılım fikirleri için bir düşünme alanı: sen yapmaya başlamadan önce açık soruları sorar, fikri daha önce kimin yaptığını araştırır ve senin onayın olmadan notuna tek kelime yazmaz.*

Bir fikir, bir yazılım fikri aklımıza geldiğinde, o fikir henüz detaylı değilken ucu açık sorularla birlikte kafamızda tam bir yapı kuramıyoruz — ve projeye böyle başlıyoruz. Sonra o açık uçlarla karşılaşınca tıkanıyoruz: başta bu soruları düşünmeden hareket ettiğimiz için kritik sorunlar yüzünden projeyi, bütün sistemi baştan yapılandırmak zorunda kalıyoruz.

**Concept Trail bu sorunu kaldırmak için hazırlanmış bir yardımcı araç.** Fikrini bir nota yazarsın; asistan fikri genişten dara netleştiren sorular sorar, cevaplarını tartışır, daha önce kimin ne yaptığını araştırır — ve not hep senin kalır.

---

## Nasıl çalışır

### Not canlı izlenir
Yazmaya **15 saniye ara verdiğinde** ya da bir şey **yapıştırdığında** asistan notuna sessizce bakar: eksikleri ve açık uçları bulur. Yazarken araya girmez; bulduğu sorular sağdaki panelde bekler, ekrana kart fırlatmaz. Durum çubuğundan açılıp kapatılır; `Ctrl+Enter` ile her an elle de sorulabilir.

**Kaç soru sorulacağına model karar verir.** Sorulara nasıl yetiştiğin ona bildirilir: kaç soru bekliyor, en eskisi ne kadardır bekliyor, son zamanlarda kaçını sonuçlandırdın. Tempoyu buna göre ayarlar: konuşulacak çok şey varsa ve sen cevap verdikçe sormaya devam eder; cevapsız sorular birikirse yalnız önemli olanı sorar. Sohbette de bir cevabın yeterince net olduğuna aynı şekilde kendisi karar verir. Sabit bir soru sınırı yok; kod yalnızca bozulmuş bir modele karşı bir sigorta tutar.

### Yazarken tamamlama
Kod editörlerindeki satır içi öneriler gibi: bir satırın sonunda bir an durduğunda devamı imlecin önünde soluk yazıyla, notunun kendi dili ve üslubuyla belirir. **Tab** hepsini alır, **Ctrl+→** bir kelimesini alır, **Esc** kapatır, **Ctrl+Space** hemen ister; gösterdiği harfleri yazmaya devam edersen gerisi durur. Nota yalnızca senin tuşunla, geri alınabilir tek bir adım olarak girer. Model ayarlarında kendi görevi vardır (*Yazarken tamamlama*; hızlı ve ucuz bir model yeter, boş bırakılırsa not izleme modeli), durum çubuğunda açma/kapama düğmesi vardır; cevap verecek model yoksa sessiz kalır. Gizli notlar burada da yalnız yerel modellere gider.

### Sorular genişten dara: karar merdiveni
Bir yazılım notu dört basamaktan geçer; asistan yalnızca bulunduğu basamağın açık kararlarını sorar:

| Basamak | Kararlar |
|---|---|
| **Kapsam** | amaç · kullanıcı · platform · çalışma ortamı |
| **Mimari** | ana parçalar · veri · iletişim · dış bağımlılıklar |
| **Bileşenler** | sorumluluklar · arayüzler · hata durumu |
| **Detay** | teknoloji · uç durumlar · doğrulama · dağıtım |

Notta zaten yazan bir kararı tekrar sormaz (notun kendi kelimeleriyle kaydeder); verdiğin cevap o kararın değeri olur ve sonraki sorular onun üstüne kurulur. On beş kararın hepsi verildiğinde not **"ürün evresine"** geldi diye duyurulur. Yol haritası kartındaki her karar bir çiptir: model yanılırsa işaretleyip geri alabilirsin.

### Her soru için bir sohbet
Bir soruya panelde tek satırla cevap verebilir ya da onun için ayrı bir sohbet açabilirsin. Anlaşılmayan noktalar orada tartışılır; asistan sonuca ulaşınca bunu nota eklemek için **onay ister**. Beğenmezsen eklemez, sohbet sürer. Bir cevaptan doğan yeni soru üst sorusuna bağlanır; sohbet o dalın önceki konuşmasını bilir.

### Modelin önerisi ve bakış açıları
Her turda sırayla **Mimar, Ürün, Güvenlik ve işletim, Geliştirici** gözü notu eleştirir ve nota eklenmeye değer somut bir argüman ya da gözden kaçan bir risk önerebilir ("Aile ortak kullanacağı için her fiş kimin harcaması olduğuyla etiketlenmeli"). Öneri de onaysız nota girmez; genel tavsiye cümleleri öneri sayılmaz.

### Rotayı düzelt
Sadece modelin sorularıyla ilerlemek fikri istediğin yerden uzaklaştırabilir. **"Rotayı düzelt"** ile projeye serbestçe yön verirsin: asistan düzeltmeni projenin amacı ve verilmiş kararlarla karşılaştırır, yeni gidişatı kısa bir özetle gösterir ve neyi değiştireceğini listeler — düzeltmenin değerini söylediği kararlar güncellenir, etkilediği kararlar yeniden sorulur, çelişen sorular kapanır. Hiçbiri sen onaylamadan olmaz; istemediğin kalemin işaretini kaldırırsın.

### Fikir ağacı: bir takımyıldız
Not ortada parlayan bir yıldız; soruları, önerileri ve sohbetleri ondan ışın ışın dağılır. **Cevap bekleyen sorular parlar** ve iplerinden ışık akar; çözülenler sakin bir ışıkla kalır. İpler gerçek iplerdir: bir yıldızı tutup sürükleyince bağlı olduklarını çeker, bırakınca yerine salınarak döner. Gökyüzünü kaydırınca asılı olan her şey geride kalıp salınır. Yazı yalnız fareyle üstüne gelince görünür. Bir yıldıza tıklayınca kartı ondan büyüyerek açılır; not ile o yıldız arasındaki yol aydınlanır, gökyüzünün geri kalanı kararır. Boşluğa tıklamak kartı yıldızına geri küçültür. **N** (ya da "Sıradaki soru") cevap bekleyen bir sonraki soruya uçar. Arkada hiç tam durmayan bir gökyüzü var: süzülen gaz bulutları, Samanyolu, farklı derinliklerde yıldız katmanları, arada bir parlayan bir yıldız, kayan yıldızlar. Gökyüzü temayla değişir: açık bir gece, ateş böcekli bir orman gecesi, sıcak ufkun üstünde kıvılcımlı bir gün batımı, sepya bir yıldız haritası, kutup ışıklı bir buzul gecesi, yüksek karşıtlık için sade bir siyah. Yakınlaşıp uzaklaşmak ağacı sarsmaz; kaydırmak onu yalnızca kalkışta ve duruşta salındırır. Not ilk açıldığında yıldızlar merkezden dışa doğru sırayla tutuşur, ipler çizilerek uzar.

### Master prompt
Tek tuş (**Ctrl Shift M**, üstteki "Master prompt"): not, yol haritasındaki kararlar, cevapladığın sorular, onayladığın ve reddettiğin öneriler ve araştırma, bir yapay zekâ kodlama ajanının (Claude Code, Codex gibi) uygulamayı **hiç soru sormadan** baştan sona yapabileceği bir talimata dönüşür: ürün özeti, kapsam, teknoloji yığını (sürümleriyle), mimari, veri modeli, API sözleşmeleri, ekranlar, hata ve uç durumlar, güvenlik, klasör yapısı, kilometre taşları, test ve kabul ölçütleri, kurulum. Notun açık bıraktığı her şeyi model kendisi karara bağlar ve bunları **Varsayımlar** bölümünde gerekçesiyle listeler; pencere o kararları en üstte gösterir. Hâlâ soru işaretiyle biten ya da kararı erteleyen bir satır kalırsa ikinci, kısa bir çağrı onları da kapatır. Not ürün evresine gelince düğme parlar, ama her an kullanılabilir. Beş dilden birinde (Türkçe, English, Deutsch, Español, Français); kopyala, yeni not olarak kaydet ya da .md indir. Son hazırlanan notla birlikte saklanır. Model ayarlarında kendi görevi vardır ("Master prompt"; boş bırakılırsa araştırma yargılarının modeli).

### Araştırma: bu fikir yapılmış mı?
Fikrin kısa bir özetinden sonra GitHub'da ve web'de bu fikri daha önce kimin geliştirdiği aranır — birden çok yoldan (topic, anahtar kelime, popülerlik, README, "alternatives", "Show HN"); bulunanlar kaç bağımsız yolun onu bulduğuna göre sıralanır. Fikrin parçaları için kullanılabilecek kütüphaneler ayrıca aranır. Uygun sayfalar ve README'ler açılıp okunur (JavaScript'le çizilen sayfalar tarayıcı katmanıyla).

**Rakip analizi:** en yakın beş proje yakından incelenir — etkinliği, lisansı, son issue'ları (kullanıcılarının neden şikâyet ettiği), README'si ve sitesi. Model bunları fikrinle karşılaştırır: fikrinin parçalarının her projede var / kısmen / yok olduğu bir tablo, her projenin fikrinle ortak yanı, eksiği, zayıf noktası ve ondan alınacak ders; **fikrini bunlardan ayıracak noktalar** ve **geliştirme argümanları**. Asistan, notunda başkalarının çözmüş olabileceği bir başlık görürse araştırmayı kendisi de önerebilir.

Seçtiğin bulgular nota yine yalnız onayınla eklenir. Hiçbir sonuç fikrin "özgün" olduğunu iddia etmez: aramada görünmemek yokluk kanıtı değildir.

---

## Temalar
Üstteki tema düğmesi yedi tema sunar — Kâğıt, Orman gecesi, **Takımyıldız** (fikir ağacıyla aynı gece gökyüzü), Gün batımı, Parşömen (basılı sayfa gibi okunan önizleme), Buzul ve Yüksek karşıtlık. Bir temanın üstüne gelmek bütün uygulamayı o temada gösterir; tıklayınca seçilir, geçiş yumuşakça olur.

## Diller
Arayüz beş dilde: Türkçe, English, Deutsch, Español, Français — üst çubuktaki dünya düğmesinden seçilir. **Asistanın dili** ayrıca seçilebilir: sorular, öneriler, sohbet cevapları ve nota eklenecek metin o dilde yazılır (seçmezsen arayüzle aynı dilde). Master prompt da beş dilden birinde hazırlanabilir. Notların ve sohbetlerin hiç çevrilmez.

---

## Modelden bağımsız
Asistan belirli bir modele bağlı değildir. OpenAI uyumlu her uç kullanılabilir: **OpenRouter** (varsayılan olarak ucuz ve hızlı bir model, ör. `openai/gpt-4o-mini`), başka bir bulut API'si ya da **yerel llama.cpp / ik_llama** sunucusu. İşler rollere ayrılır — *analiz* (not izleme, araştırma), *sohbet*, *özet* — ve her rol ayarlardan bir sağlayıcı zincirine bağlanır; ilki kapalıysa sıradaki devreye girer.

Ölçerek seçildi: aynı beş senaryoda GPT-4o-mini notta yazan 14/14 kararı buldu, hiçbirini uydurmadı, tur başına ~2 sn ve ~$0,0002. Uzun düşünen yerel modeller için düşünme bütçesi var; düşünmeden cevap vermeyen modelde de ayrıştırıcılar dayanıklı.

**Harcama koruması:** OpenRouter her isteğin gerçek maliyetini bildirir; günlük dolar, istek ve token sınırları ayarlardan değiştirilir (varsayılan günlük $0,50).

## Gizlilik
- Uygulama yalnız `127.0.0.1` üzerinde çalışır; başka siteler tarayıcın üzerinden istek atamaz.
- Frontmatter'ında `gizli: true` olan bir not uzak modellere gönderilmez ve araştırılmaz.
- Asistan notuna **hiçbir zaman kendi başına yazmaz**; her ekleme ve düzenleme bir öneridir.
- API anahtarları notların yanında değil, işletim sisteminin ayar klasöründe (`%APPDATA%\ConceptTrail`) durur.

---

## Kurulum

### Tek komutla
**Windows** (PowerShell'e yapıştır; yönetici izni gerekmez):

```powershell
irm https://raw.githubusercontent.com/Haci-brt/concept-trail/main/install.ps1 | iex
```

**macOS / Linux:**

```bash
curl -fsSL https://raw.githubusercontent.com/Haci-brt/concept-trail/main/install.sh | bash
```

Komut uygulamayı indirir (Windows'ta `%LOCALAPPDATA%\Programs\ConceptTrail`, diğerlerinde `~/.local/share/concept-trail`), kendine ait bir Python ortamı kurar, **masaüstüne ve Başlat menüsüne logolu bir Concept Trail kısayolu** koyar ve uygulamayı açar. Python 3.10+ gerekir; Windows'ta yoksa winget ile kurmayı önerir. Notların **Belgeler\Concept Trail** klasöründe durur. Güncellemek için aynı komutu yeniden çalıştır — kod yenilenir, notlar ve ortam korunur. Kaldırmak için uygulama klasörünü ve kısayolları silmek yeter; notlar yerinde kalır.

> Windows'ta ve Linux'ta uçtan uca denendi (temiz bir Debian: kurulum, kısayollar, sunucu, sanal ekranda masaüstü penceresi). Her push'ta kurulum betikleri gerçek Ubuntu, macOS ve Windows makinelerinde çalışır (`.github/workflows/kurulum.yml`). Qt'nin web görünümünün istediği sistem kütüphaneleri olmayan bir Linux'ta uygulama kendi penceresi yerine tarayıcıda açılır. Web araması her yerde çalışır: varsa Chromium ailesinden bir tarayıcıyla, yoksa tarayıcısız.

### Elle (geliştirme için)

```bash
pip install -r requirements.txt
python main.py              # masaüstü penceresi + her zaman üstte duran asistan kartı
python main.py --browser    # varsayılan tarayıcıda
python main.py --server     # yalnız sunucu
python scripts/make_shortcut.py   # masaüstüne ve Başlat menüsüne logolu kısayol
```

İlk açılışta kısa bir sihirbaz asistanı bir modele bağlar: anahtarla **OpenRouter** (önerilen; bir bağlantı seni anahtar sayfasına götürür), **bu bilgisayarda zaten çalışan** bir model (Ollama, LM Studio ve llama.cpp her zamanki portlarında bulunur) ya da **OpenAI uyumlu başka bir servis**. Kaydetmeden önce gerçek bir çağrı yapar; yanlış bir anahtar ya da model adı orada, anlaşılır sözlerle söylenir. Geçersen üst çubuktaki model düğmesinin arkasında bekler; Ayarlar → Modeller'de de, ayrıntılı sağlayıcı düzenleyicisinin yanında durur. Notlar varsayılan olarak `./notes` klasöründe durur (`--vault` ile değiştirilir).

Araştırmanın araçları uygulamanın içindedir, başka bir kurulum istemez:
- **GitHub** (`server/github.py`): yalnız herkese açık depolar, GitHub'ın hız sınırına uyar, sonuçları bir saat önbellekte tutar. Anahtar isteğe bağlıdır (ayarlar penceresinden girilir); anahtarla aramalar 2 sn, anahtarsız 6 sn aralıklarla yapılır.
- **Web araması** (`server/websearch.py`): bilgisayarda zaten kurulu Chromium ailesinden bir tarayıcıyı kullanır — Opera, Edge (her Windows'ta var), Chrome, Brave ya da Chromium; ilk bulunanı — boş, yeni bir profille, asla seninkiyle; Windows'ta penceresi gizlenir, diğer sistemlerde görünmez (headless) çalışır. Hiç tarayıcı yoksa tarayıcısız arar: DuckDuckGo'nun JavaScript'siz tarayıcılar için sayfasıyla. Belirli bir tarayıcı için `CT_BROWSER` ile yolunu göster. Araştır panelinden kapatılabilir.
- **Sayfa okuma** (`server/fetch.py`): JavaScript'le çizilen sayfalar için `playwright install chromium` gerekir.

## Yapı
```
server/       FastAPI sunucusu: asistan, karar merdiveni, araştırma, sağlayıcılar, bütçe
core/         model istemcisi: istemler, ayrıştırıcılar, düşünme bütçesi
web/          arayüz (derleme adımı olmayan ES modülleri); web/locales çeviri sözlükleri
desktop/      PyQt6 masaüstü kabuğu ve asistan kartı (HUD)
assets/icon/  uygulama logosu: ana görsel concept-trail.png; build_icons.py bütün boyutları ve .ico'yu üretir
scripts/      make_shortcut.py: masaüstü / Başlat menüsü kısayolu
docs/         tanıtım, baştan sona bir örnekle (TANITIM.md, INTRODUCTION.md)
install.ps1   Windows'ta tek komutla kurulum; install.sh macOS / Linux için
tests/        pytest; tests/manual_research_benchmark.py canlı araştırma ölçümü
```

```bash
python -m pytest tests
```
