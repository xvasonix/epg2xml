# epg2xml httpx 전환 가이드

## 📁 프로젝트 위치
`d:\projects\Antigravity\workspace\epg2xml`

## 🎯 목표
Wavve API 차단 문제 해결을 위해 requests → httpx로 전환

---

## 📋 수정해야 할 파일 목록

### 1. `pyproject.toml` - 의존성 변경
**위치**: `d:\projects\Antigravity\workspace\epg2xml\pyproject.toml`

**변경 내용**:
```diff
dependencies = [
-    "requests",
+    "httpx",
     "beautifulsoup4>=4.8",
]
```

### 2. `epg2xml/providers/__init__.py` - 메인 HTTP 클라이언트 로직
**위치**: `d:\projects\Antigravity\workspace\epg2xml\epg2xml\providers\__init__.py`

**변경할 줄**:
- 17줄: `import requests` → `import httpx`
- 257줄: `self.sess = requests.Session()` → `self.sess = httpx.Client()`
- 271줄: `r = self.sess.request(...)` → httpx 방식으로 변경
- 276줄: `requests.exceptions.HTTPError` → `httpx.HTTPStatusError`

**상세 변경 코드**:
```python
# 17줄
import httpx  # requests 대신

# 246-280줄 EPGProvider 클래스 __init__ 및 __request 메서드
class EPGProvider:
    """Base class for EPG Providers"""

    referer: str = None
    title_regex: Union[str, re.Pattern] = None
    tps: float = 1.0
    was_channel_updated: bool = False

    def __init__(self, cfg: dict):
        self.provider_name = self.__class__.__name__
        self.cfg = cfg
        # requests.Session() → httpx.Client()로 변경
        self.sess = httpx.Client(
            headers={"User-Agent": UA, "Referer": self.referer},
            proxies=cfg["HTTP_PROXY"] if cfg.get("HTTP_PROXY") else None,
            timeout=30.0,  # httpx는 timeout 필수
            follow_redirects=True  # 리다이렉트 자동 처리
        )
        if self.title_regex:
            self.title_regex = re.compile(self.title_regex)
        self.request = RateLimiter(tps=self.tps)(self.__request)
        # placeholders
        self.svc_channels: List[dict] = []
        self.req_channels: List[EPGChannel] = []

    def __request(self, url: str, method: str = "GET", **kwargs) -> str:
        ret = ""
        try:
            r = self.sess.request(method=method, url=url, **kwargs)
            r.raise_for_status()  # httpx는 명시적으로 호출해야 함
            try:
                ret = r.json()
            except (json.decoder.JSONDecodeError, ValueError):
                ret = r.text
        except httpx.HTTPStatusError as e:  # requests.exceptions.HTTPError 대신
            log.error("요청 중 에러: %s", e)
        except httpx.RequestError as e:  # 네트워크 오류
            log.error("네트워크 오류: %s", e)
        except Exception:
            log.exception("요청 중 예외:")
        return ret
```

### 3. `epg2xml/providers/tving.py` (참고)
**위치**: `d:\projects\Antigravity\workspace\epg2xml\epg2xml\providers\tving.py`

**변경 내용**: 
- 6줄: `import requests` 제거 (베이스 클래스에서 처리)
- 또는 동일하게 `import httpx`로 변경

---

## 🔧 로컬 개발 환경 설정

### 1단계: 개발 모드로 설치
```bash
cd d:\projects\Antigravity\workspace\epg2xml

# httpx 설치
pip install httpx

# 로컬 개발 모드로 epg2xml 설치 (editable mode)
pip install -e .
```

### 2단계: 수정 후 테스트
```bash
# 버전 확인
epg2xml -v

# Wavve 채널 업데이트 테스트
epg2xml update_channels

# Wavve EPG 데이터 수집 테스트
epg2xml run --config epg2xml.json
```

---

## ✅ 변경 체크리스트

- [ ] `pyproject.toml` - requests → httpx 의존성 변경
- [ ] `epg2xml/providers/__init__.py` - import httpx 추가
- [ ] `epg2xml/providers/__init__.py` - Session 생성 로직 변경 (257줄)
- [ ] `epg2xml/providers/__init__.py` - 예외 처리 변경 (276줄)
- [ ] `epg2xml/providers/__init__.py` - raise_for_status() 추가
- [ ] `epg2xml/providers/tving.py` - import 구문 확인 (선택)
- [ ] httpx 설치 (`pip install httpx`)
- [ ] 로컬 개발 모드 설치 (`pip install -e .`)
- [ ] Wavve API 테스트 실행
- [ ] Git commit 및 push

---

## 🚀 Git 작업 흐름

### 1. 브랜치 생성
```bash
cd d:\projects\Antigravity\workspace\epg2xml
git checkout -b feature/httpx-migration
```

### 2. 변경사항 커밋
```bash
git add pyproject.toml
git add epg2xml/providers/__init__.py
git commit -m "feat: migrate from requests to httpx for Wavve API compatibility"
```

### 3. GitHub에 푸시
```bash
git push origin feature/httpx-migration
```

### 4. Pull Request 생성 (선택)
원본 저장소(epg2xml/epg2xml)에 기여하고 싶다면 PR 생성

---

## 📊 httpx vs requests 주요 차이점

| 기능 | requests | httpx |
|------|----------|-------|
| **세션 생성** | `requests.Session()` | `httpx.Client()` |
| **timeout** | 기본값 None (무한대기) | **필수 설정 권장** |
| **프록시 설정** | `session.proxies = {...}` | 생성자에서 `proxies=...` |
| **예외** | `requests.exceptions.HTTPError` | `httpx.HTTPStatusError` |
| **상태 확인** | 자동 | `raise_for_status()` 명시 호출 |
| **리다이렉트** | 기본 활성화 | `follow_redirects=True` 설정 |
| **HTTP/2 지원** | ❌ | ✅ |
| **비동기 지원** | ❌ | ✅ (AsyncClient) |

---

## 🧪 테스트 방법

### 간단한 테스트 스크립트
`d:\projects\Antigravity\workspace\epg2xml\test_httpx_wavve.py` 생성:

```python
#!/usr/bin/env python
import httpx

# Wavve API 테스트
client = httpx.Client(
    headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json"
    },
    timeout=10.0,
    follow_redirects=True
)

try:
    # VOD API 테스트 (성공할 것으로 예상)
    response = client.get("https://apis.wavve.com/fz/streaming")
    print(f"VOD API: {response.status_code}")
    
    # Live EPG API 테스트
    params = {
        "apikey": "E5F3E0D30947AA5440556471321BB6D9",
        "client_version": "6.0.1",
        "device": "pc",
        "genre": "all",
        "limit": 10
    }
    response = client.get("https://apis.wavve.com/live/epgs", params=params)
    print(f"Live EPG API: {response.status_code}")
    
except Exception as e:
    print(f"오류: {e}")
finally:
    client.close()
```

실행:
```bash
python test_httpx_wavve.py
```

---

## 💡 팁

1. **점진적 전환**: 먼저 Wavve만 httpx로 전환 후 테스트
2. **버전 관리**: 변경 전 현재 상태를 별도 브랜치로 보존
3. **로그 확인**: 변경 후 상세 로그를 활성화하여 문제 확인
   ```bash
   epg2xml run --loglevel DEBUG
   ```
4. **롤백 준비**: 문제 발생 시 빠른 롤백을 위해 원본 파일 백업

---

## 🔗 참고 자료

- httpx 공식 문서: https://www.python-httpx.org/
- httpx GitHub: https://github.com/encode/httpx
- Migration Guide: https://www.python-httpx.org/compatibility/

---

작성일: 2026-01-19  
작성자: Antigravity AI Assistant
