# Cloudflare Pages + Flask Backend 연동 가이드

## 🔍 **현재 상황**
- ✅ Cloudflare Pages: 프론트엔드 호스팅 (index.html)
- ✅ Flask 서버: 백엔드 API (/api/upload-pdf)
- ❌ 문제: 405 CORS 에러

---

## ✅ **해결책 2가지**

### **방법 1: `_redirects` 파일 (간단)**

`public/_redirects` 파일을 생성하고 다음 내용 입력:

```
/api/* https://YOUR_BACKEND_URL/api/:splat 200
/* /index.html 200
```

`YOUR_BACKEND_URL`을 실제 Flask 서버 주소로 변경:
- 예: `https://api.example.com`
- 또는: `http://192.168.0.4:5002`

**장점:**
- ✅ 간단함
- ✅ CORS 자동 해결 (같은 도메인으로 프록시)

**단점:**
- ❌ HTTP/HTTPS 혼용 불가
- ❌ 포트 5002는 Cloudflare Pages에서 지원 안 할 수 있음

---

### **방법 2: Cloudflare Workers (권장)**

1. **Worker 생성**
   - Cloudflare 대시보드 → Workers & Pages
   - "Create application" → "Create Worker"
   - 이름: `findjernal-api`

2. **코드 입력**
   - `src/index.js`에 아래 코드 붙여넣기:
   ```javascript
   const BACKEND_URL = 'http://YOUR_BACKEND_URL';
   
   export default {
     async fetch(request) {
       if (request.url.includes('/api/')) {
         const backendUrl = request.url.replace('https://findjernal.pages.dev', BACKEND_URL);
         const response = await fetch(backendUrl, {
           method: request.method,
           headers: request.headers,
           body: request.body,
         });
         
         const newResponse = new Response(response.body, response);
         newResponse.headers.set('Access-Control-Allow-Origin', '*');
         return newResponse;
       }
       return fetch(request);
     }
   };
   ```

3. **라우팅 설정**
   - Cloudflare Pages 설정 → Functions
   - Route: `*/api/*` → 위 Worker 연결

**장점:**
- ✅ 모든 포트 지원
- ✅ HTTP/HTTPS 모두 지원
- ✅ 더 안정적

---

## 🎯 **당신이 해야 할 일**

1. **Flask 서버의 실제 URL 확인**
   - IP: 192.168.0.4
   - 포트: 5002
   - 완전한 URL: `http://192.168.0.4:5002`

2. **선택하기**
   - 로컬 테스트만: `_redirects` 파일 (간단)
   - 프로덕션: Cloudflare Workers (권장)

3. **Cloudflare Pages에 배포**
   - git push → Cloudflare Pages 자동 배포

---

## 📝 **수정할 파일**

### `public/_redirects` 에서:
```diff
- /api/* https://YOUR_BACKEND_URL/api/:splat 200
+ /api/* http://192.168.0.4:5002/api/:splat 200
```

### 또는 Cloudflare Workers 사용 (권장)

---

## 🚀 **테스트**

1. Cloudflare Pages URL에서 파일 업로드
2. 네트워크 탭 확인:
   - ✅ 이제 OPTIONS 200 OK
   - ✅ POST 성공

---

**Flask 서버의 완전한 URL(프로토콜 포함)을 알려주면 정확한 설정을 제공하겠습니다!**
