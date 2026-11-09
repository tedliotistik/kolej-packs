@echo off
rem Growtopia baglantisini proxy'ye yonlendirir. Yonetici olarak calistirin.
net session >nul 2>&1 || (echo Lutfen bu dosyaya sag tiklayip "Yonetici olarak calistir" deyin. & pause & exit /b 1)
set HOSTS=%SystemRoot%\System32\drivers\etc\hosts
findstr /i /c:"www.growtopia1.com" "%HOSTS%" >nul || echo 127.0.0.1 www.growtopia1.com>>"%HOSTS%"
findstr /i /c:"www.growtopia2.com" "%HOSTS%" >nul || echo 127.0.0.1 www.growtopia2.com>>"%HOSTS%"
ipconfig /flushdns >nul
echo Hosts ayari eklendi. Simdi Proxy.exe'yi acip Growtopia'ya girebilirsiniz.
pause
