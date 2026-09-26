# Araştırma kalite ölçümü — 26 Eylül 2026

## Yöntem

Canlı testler, `127.0.0.1:8877` üzerinde ayrı bir `fikir-research-eval` kasasında ve yalnız sentetik iki fikirle çalıştırıldı. Kullanıcının notları araştırma sunucularına gönderilmedi. Yeniden üretmek için `python tests/manual_research_benchmark.py --url http://127.0.0.1:8877` kullanılabilir; betik kasa adını doğrulamadan not oluşturmaz.

Ölçümler: tamamlanan sorgular, gerçekten okunan web sayfası/README sayısı, okunan toplam karakter, kaynak alan adı çeşitliliği, süre ve önceden belirlenmiş araç/proje adlarının sonuç metinlerinde görünmesi. Son ölçüm kapsam göstergesidir; tek başına doğruluk veya tam geri çağırım ölçüsü değildir.

## İlk genişletilmiş sürüm: canlı baz çizgisi

Bu koşum, tam sayfa okuma eklendikten ve alaka düzeltmesinden önce yapıldı. Eski arayüz bağlantı/özet gösteriyor, araştırma hattı yalnız iki web sayfasını okuyordu.

| Sentetik fikir | Süre | Sorgu | Web/README okuması | Okunan karakter | Alan adı | Bilinen ad eşleşmesi |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Markdown bilgi ağı | 232,9 sn | 16/16 | 5/4 | 63.479 | 6 | 2/6 |
| Kanıtlı web araştırması | 257,1 sn | 16/16 | 4/4 | 52.341 | 5 | 2/5 |

İlk koşumda kaynak gövdesi gerçekten okunmasına rağmen “backlink” notlar arası bağlantı yerine SEO bağlantısı olarak yorumlandı. Okunan dokuz kaynağın üçü SEO odaklıydı. İkinci koşumda Trafilatura ve Playwright bulundu; buna karşın bazı genel metin çıkarma makaleleri ve düşük uyumlu depolar da önerildi. Her iki koşumda modelin benzerlik hükmü boş döndü. Bu bulgular, yalnız okunan sayfa sayısının yararlılığı göstermediğini ortaya koydu.

## Diğer doğrulamalar

- Kontrollü dört arama sonucunda ilk bağlantıları okuma yöntemi üç araştırma niyetinin birini kapsadı; sorgu niyetine göre kaynak seçimi üçünü de kapsadı. Bu, sabit sentetik veri üzerinde bir sıralama testi; gerçek web için genel bir başarı oranı değildir.
- Okunmuş kaynak, depo ve araç not önerisine dönüştürülebiliyor. Canlı arayüz testinde sentetik not 233 karakterken öneri sonrası aynı kaldı; onaydan sonra 530 karaktere çıktı. Kaynak önerisi reddedildiğinde başka sentetik not 269 karakterde kaldı.
- Çok bölümlü test notunda bölüm seçici doğru metin konumuna gitti; yazılan karakter `Ctrl+Z` ile geri alındı. Editörün yerel textarea davranışı korundu.

Bu ölçüm, ilgili kaynakları seçmenin ve sorgu sayısının süreye etkisini görmek için sonraki aynı koşumla karşılaştırılacak.

## Alaka düzeltmesi sonrası ilk tekrar

Aynı Markdown fikri, aynı yerel model ve aynı izole kasada yeniden çalıştırıldı. Öncelikli konu sorguları `markdown-notebook` ve `knowledge-graph` oldu; belirsiz “backlinking” araması `markdown notes` ile bağlandı.

| Koşum | Süre | Sorgu | Web/README okuması | Okunan karakter | SEO kaynağı | Bilinen ad eşleşmesi |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Önce | 232,9 sn | 16/16 | 5/4 | 63.479 | 3 | 2/6 |
| Sonra | 269,1 sn | 14/14 | 3/4 | 35.024 | 0 | 1/6 |

SEO sapması temizlendi ve okunan sayfalar not/bağlantı/graf konusuna döndü. Ancak süre **36,2 saniye arttı** ve bilinen araç/proje adı eşleşmesi azaldı. Önerilen 10 aracın çoğu yeniden kullanılabilir kütüphane yerine tam not uygulamasıydı. Bu tekrar, alaka düzeltmesinin tek başına hız ve yardımcı araç keşfi hedeflerini karşılamadığını gösterdi; bileşen araması ayrıca iyileştiriliyor.

## Bileşen araması sonrası ikinci tekrar

| Koşum | Süre | Sorgu | Web/README okuması | Okunan karakter | Bilinen ad eşleşmesi |
| --- | ---: | ---: | ---: | ---: | ---: |
| İlk genişletilmiş sürüm | 232,9 sn | 16/16 | 5/4 | 63.479 | 2/6 |
| Alaka düzeltmesi | 269,1 sn | 14/14 | 3/4 | 35.024 | 1/6 |
| Bileşen araması | 156,9 sn | 14/14 | 2/4 | 22.821 | 0/6 |

Son koşumun aşama süreleri (sn): terim çıkarma 8,09; önceki ürünleri GitHub'da arama 13,07; web çapraz kontrolü 12,00; yardımcı araç arama 7,13; yakın fikir arama 2,78; web sayfası okuma 3,35; README okuma 3,49; model değerlendirmesi **105,34**. Toplam 155,30 saniye sunucu ölçümü; istemci tarafında 156,9 saniye. Gecikmenin yaklaşık üçte ikisi model değerlendirmesinden geldi.

SEO kaynakları bu tekrarda da çıkmadı ve yerel tam metin arama adayları bulundu. Ancak modelin 10 araç kotasını zayıf, gerekçesiz depolarla doldurması ve “fikir daha önce yapılmıştır” gibi kanıtından güçlü bir ifade üretmesi yeni kalite hatalarıdır. Süre kazanımı elde edildi, fakat sonuç yararlılığı henüz yeterli görülmedi; gerekçesiz araçları ve aşırı kesin hükmü eleme düzeltmesi sıradadır.

## Kanıt kalibrasyonu sonrası üçüncü tekrar

Aynı sentetik Markdown fikrinde 15/15 sorgu yanıt aldı; 4 web sayfası ve 4 README'nin toplam **31.861 karakteri** okundu. İstemci süresi **164,9 sn**; bunun 21,72 saniyesi hızlı modelde benzerlik hükmü, 102,84 saniyesi sohbet modelinde araç ve fırsat önerisiydi. Beş aracın beşinde de kullanım gerekçesi var. Hüküm, yakın projeleri sayıyor ve kapsamın aynı olduğunun doğrulanmadığını belirtiyor; önceki koşumdaki kesinlik hatası giderildi. Sigma.js belgeleri ve GitHub README'si açılıp graf görselleştirme bileşeni olarak önerildi.

Bu tekrar iki yeni kusuru görünür kıldı. Yardımcı araç listesinde `margins` ve `notesdb` gibi tam not uygulamaları da var; bunlar bileşen değil, benzer proje adayı olmalı. Ayrıca ilk altı GitHub sorgusu `ok=True` görünse de `prior_git` 0,06 saniye sürdü ve bu sorgulardan hiçbir depo adaylara girmedi; adaylar bileşen ve web aramasından geldi. Başarı sayısı bu durumda araştırma verimini olduğundan iyi gösteriyor. Boş yanıtların ayrı sayılması ve önceki proje aramasının doğrulanması gerekiyor. Önceden belirlenen altı adın hiçbiri sonuç metninde yoktu (0/6); Sigma.js gibi yararlı yeni keşifler bu dar ölçüye dahil değil.
