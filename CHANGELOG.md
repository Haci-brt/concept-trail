# Değişiklik günlüğü

Concept Trail'deki önemli değişiklikler bu dosyada tutulur.

Biçim [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) düzenine dayanır; sürüm numaraları [Anlamsal Sürümleme](https://semver.org/lang/tr/) kurallarına uyar. Uygulamanın sürümü tek bir yerde yazılıdır: `server/settings.py` içindeki `VERSION`.

## [Yayımlanmamış]

## [0.3.0] - 2026-09-30

İlk herkese açık sürüm. Eylül 2026'da yapılan her şeyi kapsar; ondan önce yayımlanmış bir sürüm yok.

### Eklendi

**Not defteri**
- Web tabanlı Markdown not defteri: canlı önizleme ve notun kendi başlıklarından bir gezinme şeridi, sekmeler, komut paleti (Ctrl P), etiketler, sabitlenen notlar, odak kipi.
- Masaüstü penceresi (PyQt6) ve her zaman üstte duran asistan kartı; masaüstü penceresi açılamayan bir Linux'ta uygulama tarayıcıda açılır.
- Yazarken tamamlama: satırın devamı soluk yazıyla önerilir; Tab alır, Ctrl+→ bir kelime alır, Esc kapatır, Ctrl+Z tek adımda geri alır.
- Açık ve koyu görünüm, yedi tema; fikir ağacının gökyüzü temayla değişir.
- Arayüz, asistan ve master prompt beş dilde: Türkçe, English, Deutsch, Español, Français. Notlar ve modelin yazdıkları hiç çevrilmez.

**Asistan**
- Canlı izleme: yazmayı 15 saniye bıraktığında ya da bir şey yapıştırdığında not sessizce incelenir; sorular araya girmeden panelde bekler. Ctrl+Enter beklemeden sorar.
- Karar merdiveni: yazılım notlarında sorular genişten dara gider (Kapsam → Mimari → Bileşenler → Detay); notta yazan karar yeniden sorulmaz. `tur: fikir` notlarında merdiven yerine merak soruları gelir.
- Her soru için bir sohbet: karttan ya da sohbetten cevap verilir, takip soruları üst sorusuna bağlanır. "Bilmiyorum" ya da "fikrin var mı" artı ve eksileriyle seçenekler getirir.
- Modelin önerisi: notta en az iki dayanağı olan öneriler, farklı bakış açılarından; genel geçer tavsiyeler elenir.
- Rotayı düzelt: asistanın gidişatını her an değiştirebilirsin; model etkisini inceler, sen onaylarsın, yeni yönün açtığı sorular hemen gelir.
- Fikir ağacı: not ortada, sorular ondan ışın ışın dağılan bir takımyıldız. Sürüklenen yıldız bağlılarını çeker, tıklanan yıldızın yolu aydınlanır; 100'ü aşkın düğümde de akıcıdır.
- Master prompt (Ctrl Shift M): not, kararlar ve araştırma bir kodlama yapay zekâsı için eksiksiz bir yapım talimatına döner; modelin senin yerine verdiği kararlar ayrıca listelenir.

**Araştırma**
- "Bu fikir yapılmış mı?": fikir GitHub'da ve web'de aranır, bileşenleri ayrıca aranır, okunan kaynaklar gösterilir. En yakın projeler yakından incelenir (etkinlik, lisans, kullanıcı şikâyetleri, README, site) ve Türkçe bir tabloda fikirle karşılaştırılır; hangi ve kaç rakip olduğuna model karar verir, tabloyu kanıt doldurur.
- Araştırma araçları uygulamanın içindedir: GitHub araması (isteğe bağlı token, hız sınırlarına uyar, sonuçları bir saat saklar), görünmez web araması (Chromium ailesinden bir tarayıcıyla, yoksa tarayıcısız) ve sayfa okuma.
- Web araması araştırma panelinden kapatılabilir; araştırma yalnız sen başlattığında dış ağa çıkar.

**Modeller ve ayarlar**
- Modelden bağımsızlık: not izleme, sohbet, nota yazma, araştırma yargıları, master prompt ve tamamlama ayrı ayrı bir sağlayıcıya bağlanabilir; yerel sunucular (llama.cpp, Ollama, LM Studio) ve OpenAI uyumlu servisler aynı biçimde çalışır, her işin bir yedeği olabilir.
- İlk açılış sihirbazı: OpenRouter anahtarı, bu bilgisayarda çalışan bir model ya da başka bir servis. Kaydetmeden önce gerçek bir çağrı yapar; yanlış anahtar ya da model adı anlaşılır sözlerle söylenir.
- Uzak model bütçesi: OpenRouter'ın bildirdiği gerçek maliyet dolar olarak izlenir; günlük harcama, istek ve token sınırları.
- Düşünen modeller için token bütçesi: cevap düşünmenin ortasında kesilmez.
- Güncelleme denetimi: Ayarlar → Sürüm → "Güncellemeleri denetle". GitHub'daki en yeni sürümü sorar ve varsa nasıl güncelleneceğini söyler. Uygulama kendiliğinden hiçbir zaman internete çıkıp güncelleme aramaz.
- Sürüm numarası ayarlar ve klavye kısayolları pencerelerinde görünür.

**Kurulum**
- Tek komutla kurulum: Windows'ta `install.ps1`, macOS ve Linux'ta `install.sh`. Kendi Python ortamını kurar, masaüstüne ve Başlat menüsüne logolu bir kısayol koyar; Windows'ta Python yoksa winget ile kurmayı önerir. Aynı komut güncellemedir: kod yenilenir, notlar ve ortam korunur.
- Kaldırma betikleri: `uninstall.ps1` ve `uninstall.sh` uygulama klasörünü ve kısayolları kaldırır; ayarları (API anahtarları dahil) silmeden önce sorar, notlara dokunmaz.
- Her push'ta kurulum betikleri gerçek Ubuntu, macOS ve Windows makinelerinde çalışır.

**Test**
- `python -m testkit`: sahte bir model ve örnek notlarla ayrı bir Concept Trail; anahtar, ücret ve gerçek notlar gerekmez.
- Uygulamayı başsız bir Chromium'da gerçek tuşlarla deneyen uçtan uca testler ve adım adım elle kontrol listesi (`docs/TEST.md`).

### Değişti
- Uygulamanın adı "Fikir Not Defteri"yken Concept Trail oldu; eski ayar klasörü yeni adın altına kopyalanır.
- Canlı izleme, sohbet ve araştırma tek büyük modelle çalışabilir; model ayrı ayrı bağlanmadıkça her iş aynı modeli kullanır.
- Araştırma kuralları alana göre modelden gelir; elle yazılmış alan kuralları kaldırıldı. GitHub araması projelerin gerçek etiketleriyle ve GitHub'ın adlandırmasıyla yapılır, boşa giden sorgular atlanır.
- Ayarlar penceresi tıklar tıklamaz açılır; araç durumu geldiğinde kendini doldurur.
- Model başlatma düğmesi yalnız bu bilgisayarda gerçekten bulunan bir başlatma betiği varsa görünür. Yoksa model düğmesi ve "Model kapalı" bildirimi Ayarlar → Sihirbazla bağla'ya yönlendirir.
- Sayfa okuyan aracın kimlik dizesi uygulamanın sürümünü ve bu deponun adresini söyler.
- README İngilizce; Türkçesi `README.tr.md`.

### Düzeltildi
- Fikir ağacındayken onaylanan cümle sohbet kutusuna değil nota yazılıyor.
- Yarım yazılmış cevap her sorunun kendi sohbetinde kalıyor; bekleyen "Nota eklensin mi?" kartı sohbet yeniden açılınca duruyor.
- İngilizce ve Almanca notlarda sorular ve kararlar notun kendi dilinde geliyor.
- Uzun notta yazmak ve büyük ağaçta gezinmek hızlandı; soru temposu frenleniyor.
- Geçici bir ağ hatası bütün araştırmayı durdurmuyor.
- Ayarlar penceresi yazarken titremiyor, yapılan seçimi yutmuyor; token alanı araç sunucuları çalışmasa da düzenlenebiliyor.
- Konsolsuz (pythonw) başlatma sessizce çökmüyor; hatalar günlüğe yazılıyor.
- İngilizce Windows'ta kurulum kısayol adımında çökmüyor; Windows kurulumu yerel komutların uyarılarında durmuyor.

### Güvenlik
- Sunucu yalnız 127.0.0.1'e bağlanır; yabancı Host başlıklarını (DNS rebinding) ve uygulamanın kendi sayfasından gelmeyen yazma isteklerini reddeder.
- Asistan notuna yalnız senin onayınla yazar; `gizli: true` notlar hiçbir zaman uzak bir sağlayıcıya ya da web aramasına gitmez.
- Sayfa okuma yalnız herkese açık adresleri açar; yönlendirmeler de aynı denetimden geçer.
- Kurulum betiği, Concept Trail kurulumuna benzemeyen dolu bir klasörü artık silmez (ör. `CT_APP_DIR` yanlışlıkla ev klasörünü gösteriyorsa); uygulama açıkken dosyaları değiştirmeye kalkmaz.

[Yayımlanmamış]: https://github.com/Haci-brt/concept-trail/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/Haci-brt/concept-trail/releases/tag/v0.3.0
