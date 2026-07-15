# ⚠️ 중요: 포트 5002를 Windows 방화벽에서 열어야 함

## 🔴 **현재 문제**
- Flask 서버는 http://0.0.0.0:5002 에서 실행 중
- 로컬(127.0.0.1)에서는 접속 가능
- **외부(Cloudflare)에서는 접속 불가능** ← 방화벽이 포트 차단!

## ✅ **해결책**

### **방법 1: 배치 파일 실행 (쉬움)**

1. `open_firewall.bat` 파일을 **마우스 우클릭**
2. **"관리자 권한으로 실행"** 선택
3. 명령 창이 열렸다 닫힘 → ✅ 포트 열림

### **방법 2: 수동 (PowerShell 관리자 권한)**

PowerShell을 **관리자 권한으로 실행**한 후:

```powershell
netsh advfirewall firewall add rule name="Flask Server 5002" dir=in action=allow protocol=tcp localport=5002
```

### **방법 3: Windows Defender 방화벽 GUI**

1. Windows 검색 → "방화벽" 검색
2. "Windows Defender 방화벽을 통한 앱 허용" 클릭
3. "다른 앱 허용" 클릭
4. Python 추가 (또는 포트 5002 직접 추가)

---

## 🧪 **포트 열렸는지 확인**

PowerShell에서:
```powershell
netsh advfirewall firewall show rule name="Flask Server 5002"
```

또는 외부에서 접속 테스트:
```bash
# 다른 기기에서
curl http://210.101.130.111:5002/api/test
```

---

## 📋 **다음 단계**

1. ✅ 포트 5002 열기 (위의 방법 중 하나)
2. ✅ Flask 서버 재시작 (필요 없음, 이미 실행 중)
3. ✅ Cloudflare Pages에서 파일 업로드 시도
4. ✅ 이제 405 에러 해결됨!

---

**포트를 열었으면 다시 시도해주세요!** 🚀
