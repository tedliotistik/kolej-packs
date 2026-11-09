@echo off
rem Proxy olmadan normal oynamak icin hosts ayarini geri alir. Yonetici olarak calistirin.
net session >nul 2>&1 || (echo Lutfen bu dosyaya sag tiklayip "Yonetici olarak calistir" deyin. & pause & exit /b 1)
set HOSTS=%SystemRoot%\System32\drivers\etc\hosts
findstr /v /i /c:"www.growtopia1.com" /c:"www.growtopia2.com" "%HOSTS%" > "%TEMP%\hosts.vendfinder"
copy /y "%TEMP%\hosts.vendfinder" "%HOSTS%" >nul
del "%TEMP%\hosts.vendfinder"
ipconfig /flushdns >nul
echo Hosts ayari kaldirildi. Growtopia artik proxy olmadan baglanir.
pause
