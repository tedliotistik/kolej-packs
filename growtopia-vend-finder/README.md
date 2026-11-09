# Growtopia Vend Finder (oyun içi /vend)

Discord'a girmeden, **oyunun içinden** eşya fiyatı aramak için bir proxy eklentisi.

Discord'daki Vend Finder botunun veritabanını kullanmaz. Onun yerine kendi verini toplar:
proxy açıkken **girdiğin her dünyadaki** vending machine / DigiVend'leri okuyup bilgisayarına
kaydeder. Sonra oyunda `/vend <eşya>` yazdığında sadece senin gezdiğin dünyalardaki fiyatları
en ucuzdan pahalıya gösterir.

```
[Vend Finder] magplant icin 3 ilan (en ucuz once):
1. 2 DL 50 WL Magplant 5000 - MAGSHOP (10, 20) - 2 sa once
2. 2 DL 70 WL Magplant 5000 - BUYMAG (4, 51) - 1 gun once
...
Dunyaya gitmek icin: /vgo <numara>
```

## Nasıl çalışır

[GTProxy](https://github.com/ZTzTopia/GTProxy) (açık kaynak Growtopia proxy'si) oyun ile
Growtopia sunucusu arasına girer. Bu klasördeki yama GTProxy'nin Lua script motoruna
vending machine verisini ve dünya adını açar; `scripts/vend_finder.lua` da:

1. Bir dünyaya girdiğinde (sunucu dünya haritasını gönderdiğinde) içindeki tüm vend'leri okur:
   eşya, fiyat, koordinat.
2. `data/vend_finder.tsv` dosyasına kaydeder (o dünyanın eski kaydının yerine yazar; vend'ler
   kaldırılmışsa dünyayı siler).
3. Sohbete yazdığın `/vend`, `/find` vb. komutları yakalar (sunucuya gitmez) ve cevabı oyun
   konsoluna yazar.

Fiyat notu: Growtopia vend fiyatı ya "her biri X WL" ya da "1 WL'ye X tane" şeklindedir.
Sıralama tek eşya başına WL fiyatına göredir. 100 WL = 1 DL, 100 DL = 1 BGL.
Stok miktarı dünya verisinde gelmediği için gösterilmez.

## Komutlar

| Komut | Açıklama |
|---|---|
| `/vend <eşya>` | Girdiğin dünyalardaki en ucuz 10 ilan. Tam isim eşleşmesi varsa sadece onu, yoksa ismin içinde geçenleri gösterir. |
| `/find <eşya>` | `/vend` ile aynı. |
| `/vgo <numara>` | Son aramadaki ilanın dünyasına ışınlanır (GTProxy'nin `/warp` komutunu kullanır). |
| `/vendworlds` | Kayıtlı dünyalar, vend sayısı ve ne zaman tarandığı. |
| `/venddel <dünya>` | Bir dünyayı kayıttan siler. |
| `/vendhelp` | Komut listesi. |

## Kurulum (Windows)

1. Bu repodaki GitHub Actions'ta **Vend Finder** iş akışının son başarılı çalışmasından
   `VendFinder-windows` dosyasını indirip bir klasöre çıkar.
   (Elle derlemek istersen aşağıdaki "Kendin derle" kısmına bak.)
2. `hosts-ekle.bat` dosyasına sağ tıkla → **Yönetici olarak çalıştır**. Bu, Growtopia'nın
   `www.growtopia1.com` / `www.growtopia2.com` adreslerini bilgisayarındaki proxy'ye yönlendirir.
3. `Proxy.exe`'yi çalıştır (ilk açılışta `config.json` oluşturur). Pencere açık kalsın.
4. Growtopia'yı aç ve normal giriş yap. Konsolda `[Vend Finder]` mesajları görmelisin.
5. Satış dünyalarını gez; her dünya otomatik kaydedilir. Sonra `/vend <eşya>` yaz.

Proxy olmadan normal oynamak için `hosts-kaldir.bat`'ı yönetici olarak çalıştır.

Veriler `Proxy.exe`'nin yanındaki `data/vend_finder.tsv` dosyasında durur (Excel ile de
açılabilir). Bulutta tutmak istersen bu klasörü OneDrive/Google Drive klasörüne koyman yeterli.

## Uyarılar

- **Ban riski:** Proxy kullanmak Growtopia kullanım şartlarına aykırıdır ve hesabın
  banlanabilir. Bu eklenti sadece gelen dünya verisini okur ve sunucuya hiçbir paket eklemez
  (sadece `/vgo` normal bir dünya giriş isteği gönderir), ama proxy'nin kendisi tespit
  edilebilir. Riski bilerek kullan; mümkünse önce yan hesapla dene.
- Veriler sadece **senin girdiğin** dünyalardan gelir ve girdiğin andaki fiyatları gösterir.
  Eski fiyatlar için yaş bilgisine bak ("2 sa once", "3 gun once").
- Oyun güncellemesiyle dünya veri formatı değişirse GTProxy'nin de güncellenmesi gerekebilir.
  O durumda `.github/workflows/vend-finder.yml` içindeki `GTPROXY_COMMIT` değerini yeni bir
  GTProxy sürümüne çekip yamanın hâlâ uygulandığını kontrol et.

## Kendin derle

```bash
git clone https://github.com/ZTzTopia/GTProxy.git
cd GTProxy
git checkout f51c5a3d66ed52af08e2dec8d0459876bc102e75
git submodule update --init --recursive
git apply ../growtopia-vend-finder/patches/0001-vend-finder-lua-bindings.patch
pip install "conan>2.0"
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release
```

Sonra `build/src/Release/Proxy.exe`, `build/conan/build/*.dll`, GTProxy'nin `resources/`
klasörü ve bu repodaki `scripts/vend_finder.lua` (GTProxy'nin `scripts/` klasörüne, örnek
test scriptlerini koymadan) aynı klasörde olmalı.

## Yamanın içeriği (`patches/`)

GTProxy'ye eklenenler:

- `world:get_name()` – şu anki dünyanın adı.
- `world:get_vendings()` – dünyadaki tüm vend'ler: `{ x, y, item_id, price, tile_id }`.
- `TileExtra:get_as_vending()` ve tile-extra Lua tiplerinin kaydı (önceden hiç çağrılmıyordu).
- `storage.read/write/now/path` – scriptlerin sadece `data/` klasörüne dosya yazabildiği
  küçük bir kayıt API'si (GTProxy Lua'da `io`/`os` kütüphanelerini açmıyor).
- `/warp` komutundaki bir hata düzeltmesi (dünya adı gecikmeli görevde referansla
  tutuluyordu, ışınlanma bozuk isimle gidebiliyordu).

## Testler

```bash
pip install lupa pytest
pytest growtopia-vend-finder/tests
```

Testler GTProxy API'sini taklit ederek scriptin tarama, kaydetme/yükleme, arama, sıralama ve
komutlarını doğrular.
