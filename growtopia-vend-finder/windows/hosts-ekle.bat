@echo off
rem Growtopia baglantisini proxy'ye yonlendirir. Yonetici olarak calistirin.
net session >nul 2>&1 || (echo Lutfen bu dosyaya sag tiklayip "Yonetici olarak calistir" deyin. & pause & exit /b 1)
set HOSTS=%SystemRoot%\System32\drivers\etc\hosts
set TMPH=%TEMP%\hosts.vendfinder
rem Eski/bozuk Growtopia satirlarini temizle (or. bir yorum satirina yapismis olanlar).
findstr /v /i /c:"www.growtopia1.com" /c:"www.growtopia2.com" "%HOSTS%" > "%TMPH%"
rem Dosya sonunda satir sonu olmayabilir; yeni satirlar ayri satirda baslasin.
echo.>> "%TMPH%"
echo 127.0.0.1 www.growtopia1.com>> "%TMPH%"
echo 127.0.0.1 www.growtopia2.com>> "%TMPH%"
copy /y "%TMPH%" "%HOSTS%" >nul || (echo Hosts dosyasi yazilamadi. Antivirus engelliyor olabilir. & pause & exit /b 1)
del "%TMPH%"
ipconfig /flushdns >nul
echo.
echo Kontrol:
ping -n 1 www.growtopia1.com | findstr /c:"127.0.0.1" >nul && (echo   www.growtopia1.com -^> 127.0.0.1  TAMAM) || (echo   www.growtopia1.com hala yonlendirilmiyor! Antivirus hosts dosyasini engelliyor olabilir.)
echo.
echo Simdi Proxy.exe'yi acip Growtopia'ya girebilirsiniz.
pause
