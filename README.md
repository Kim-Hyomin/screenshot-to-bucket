# Screenshot to Bucket — Gemini 3.5 Flash-Lite One-pass

모바일 스크린샷을 분석해 다음 정보를 만드는 Gradio PoC입니다.

1. 짧은 이미지 요약과 검색용 핵심 문구 (`key_text`, 최대 700자)
2. 고정된 출처 유형과 짧은 출처명
3. 콘텐츠 안에 실제로 보이는 날짜 원문 (`content_dates`)
4. 객체·색상·장소·활동·키워드
5. 행동 후보 **정확히 3개**
6. 사용자 선택 버킷
7. SQLite 기반 키워드·버킷 검색
8. 이미지별 토큰 사용량 기록

## 이번 버전의 핵심 방향

이 버전은 **Gemini 3.5 Flash-Lite가 이미지를 직접 보면서** 메타데이터와 행동 후보를 **한 번에** 생성합니다.

이전의 2단계 방식(이미지 → 메타데이터 → 텍스트 후보)과 달리,
화면 구석의 요소와 전체 화면의 맥락을 함께 반영할 수 있도록 설계했습니다.

또한 초기 버전의 문제였던 출력 폭주를 막기 위해 다음을 적용했습니다.

- 날짜는 `year/month/day`로 정규화하지 않고 원문만 저장
- 휴대전화 상태바 시각과 저장일 제외
- 출처 유형은 enum 후보 중 하나만 선택
- `evidence`, `confidence` 제거
- `key_text` 최대 700자
- 행동 후보는 정확히 3개
- 전체 출력 `MAX_OUTPUT_TOKENS` 제한
- 원본 응답 저장
- JSON 실패 시 더 짧은 프롬프트로 1회 재시도

## 행동 후보 설계 원칙

행동 후보는 항상 3개를 만들며, 다음을 동시에 고려합니다.

- 화면의 특정 요소를 반영한 후보
- 화면 전체를 포괄하는 공통 주제 기반 후보
- 서로 중복되지 않는 서로 다른 행동 관점

예:

- **토마토 요리 모음 화면**
  - 토마토 요리 모음 저장하기
  - 마음에 드는 토마토 요리 하나 골라 만들어보기
  - 건강식 레시피 아이디어로 참고 저장하기

- **책 리스트가 많은 화면**
  - 책 읽기 리스트로 저장하기
  - 이달의 읽을 책 후보로 추려보기
  - 관심 책 제목을 따로 메모해 구매·대여 검토하기

## 최소 프로젝트 구조

```text
screenshot-to-bucket-g35-onepass/
├── app.py
├── core.py
├── database.py
├── batch_analyze.py
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── data/
│   ├── raw/
│   └── images/
└── outputs/
    └── raw/
```

## 1. 설치

Windows 명령 프롬프트:

```cmd
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

macOS / Linux:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 2. 환경변수 설정

Windows 명령 프롬프트:

```cmd
copy .env.example .env
```

PowerShell:

```powershell
Copy-Item .env.example .env
```

`.env`에 실제 Gemini API 키를 입력합니다.

```env
GEMINI_API_KEY=실제_API_키
GEMINI_MODEL=gemini-3.5-flash-lite
MAX_OUTPUT_TOKENS=1800
DB_PATH=data/app_g35.db
IMAGE_DIR=data/images
OUTPUT_DIR=outputs
```

## 3. 먼저 5장 시험

원본 30장을 `data/raw/`에 넣은 뒤, 먼저 5장만 실행합니다.

```cmd
python batch_analyze.py --input-dir data/raw --limit 5
```

정상 출력 예시:

```text
[1/5] image.jpg
  저장 완료 | 후보 3개 | 토큰 1,234 | 상태 analyzed
```

확인할 파일:

```text
data/app_g35.db
outputs/usage.csv
outputs/raw/
```

5장 결과가 괜찮으면 전체를 실행합니다. 이미 저장된 5장은 자동으로 건너뜁니다.

```cmd
python batch_analyze.py --input-dir data/raw
```

같은 이미지를 다시 분석할 때만 `--force`를 사용합니다.

```cmd
python batch_analyze.py --input-dir data/raw --force
```

## 4. Gradio 실행

```cmd
python app.py
```

브라우저에서 보통 다음 주소를 엽니다.

```text
http://127.0.0.1:7860
```

### 새 이미지 분석

- 이미지 업로드
- 메타데이터 확인
- 기본 후보 3개 확인
- 제목·버킷·대상·이유 수정 가능
- 원하는 후보의 `선택` 체크
- 결과 저장

### 저장 결과 검토

- 30장을 하나씩 불러오기
- 잘못된 후보 수정
- 필요하면 후보 행을 추가하거나 삭제
- 수정 내용 저장

### 버킷·검색

검색은 두 영역을 분리합니다.

#### 사실 검색

- 요약
- 핵심 문구
- 출처
- 콘텐츠 날짜
- 객체·색상·장소·활동·키워드

#### 사용자 의도 검색

- 사용자가 선택한 후보만
- 후보 제목·대상·버킷·이유

선택하지 않은 AI 후보는 사용자 의도 검색 인덱스에 포함되지 않습니다.

## 5. 토큰 사용량 확인

모든 실행 기록은 `outputs/usage.csv`에 저장됩니다.

```csv
filename,model,prompt_tokens,output_tokens,thought_tokens,total_tokens,calls,status,error
```

원본 모델 응답은 `outputs/raw/`에 저장됩니다.

## 6. DB 백업

Gradio를 종료한 뒤 Windows cmd에서:

```cmd
copy data\app_g35.db data\app_g35_backup.db
```

실행 중 안전하게 백업하려면:

```cmd
python -c "import sqlite3; s=sqlite3.connect('data/app_g35.db'); d=sqlite3.connect('data/app_g35_backup.db'); s.backup(d); d.close(); s.close(); print('백업 완료')"
```
