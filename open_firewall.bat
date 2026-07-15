@echo off
REM 포트 5002를 Windows 방화벽에서 열기 (관리자 권한 필요)

REM 기존 규칙 제거 (있으면)
netsh advfirewall firewall delete rule name="Flask Server 5002" >nul 2>&1

REM 새 규칙 추가
netsh advfirewall firewall add rule name="Flask Server 5002" dir=in action=allow protocol=tcp localport=5002

echo.
echo ✅ 포트 5002가 Windows 방화벽에서 열렸습니다!
echo.
pause
