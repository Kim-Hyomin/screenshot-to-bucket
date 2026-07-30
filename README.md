# Screenshot to Bucket

모바일 스크린샷을 분석해 **검색 가능한 메타데이터**와 **실행 가능한 버킷 행동 후보**로 변환하는 Gradio 기반 프로젝트입니다.

스크린샷에는 사고 싶은 물건, 가보고 싶은 장소, 읽고 싶은 책, 만들어보고 싶은 음식처럼 나중에 다시 활용하고 싶은 정보가 많이 담겨 있습니다. 그러나 일반 갤러리에서는 캡처 당시의 의도를 기록하거나, 화면 속 내용을 기준으로 검색하기 어렵습니다.

Screenshot to Bucket은 이미지 한 장을 입력받아 다음 작업을 수행합니다.

- 스크린샷의 핵심 내용과 검색용 메타데이터 추출
- 서로 다른 관점의 행동 후보 3개 생성
- 사용자가 후보를 선택하거나 직접 수정
- SQLite에 분석 결과와 선택한 행동 저장
- 키워드와 버킷을 이용한 검색
- 이미지별 토큰 사용량과 원본 모델 응답 기록

> Gemini API를 사용하므로 실행 전에 개인 API 키 설정이 필요합니다. 실제 API 키가 포함된 `.env` 파일은 저장소에 포함되어 있지 않습니다.

---

## 목차

1. [주요 기능](#주요-기능)
2. [전체 파이프라인](#전체-파이프라인)
3. [행동 후보 생성 원칙](#행동-후보-생성-원칙)
4. [분석 결과 구조](#분석-결과-구조)
5. [기술 스택](#기술-스택)
6. [프로젝트 구조](#프로젝트-구조)
7. [설치 및 실행](#설치-및-실행)
8. [Gradio 사용 방법](#gradio-사용-방법)
9. [검색 방식](#검색-방식)
10. [결과 파일 확인](#결과-파일-확인)
11. [토큰 사용량 확인](#토큰-사용량-확인)
12. [DB 백업과 복원](#db-백업과-복원)
13. [설정값 변경](#설정값-변경)
14. [문제 해결](#문제-해결)
15. [데이터 및 개인정보 안내](#데이터-및-개인정보-안내)
16. [현재 한계](#현재-한계)
17. [라이선스](#라이선스)

---

## 주요 기능

### 1. 스크린샷 분석

Gemini가 이미지의 시각 요소와 화면 속 텍스트를 함께 분석합니다. 전체 화면을 단순 OCR하는 대신, 이후 검색과 행동 제안에 필요한 핵심 정보만 구조화합니다.

### 2. 행동 후보 3개 생성

한 장의 이미지에서 정확히 3개의 행동 후보를 생성합니다.

예를 들어 토마토 요리 여러 개가 보이는 화면이라면 다음과 같은 후보를 만들 수 있습니다.

- 토마토 요리 모음을 저장하기
- 마음에 드는 요리 하나를 골라 직접 만들어보기
- 건강식 레시피 아이디어로 참고하기

### 3. 사용자 검토 및 수정

AI가 생성한 후보는 최종 결과가 아니라 제안입니다. Gradio 화면에서 다음 항목을 직접 수정할 수 있습니다.

- 선택 여부
- 행동 제목
- 버킷 ID
- 행동 대상
- 제안 이유

### 4. SQLite 저장

분석 결과, 이미지 정보, 행동 후보, 사용자의 선택 결과를 SQLite DB에 저장합니다. 앱을 종료했다가 다시 실행해도 저장된 결과를 불러올 수 있습니다.

### 5. 키워드 및 버킷 검색

메타데이터와 사용자가 선택한 행동 후보를 검색할 수 있습니다. 검색 결과는 이미지 갤러리와 표 형태로 확인할 수 있습니다.

### 6. 실행 기록 보존

각 이미지의 입력·출력·추론 토큰 수를 CSV로 저장하고, Gemini가 반환한 원본 JSON 응답도 별도로 보관합니다.

---

## 전체 파이프라인

```text
스크린샷 입력
    ↓
SHA-256 해시 생성 및 data/images에 복사
    ↓
Gemini 이미지 분석
    ↓
메타데이터 + 행동 후보 3개 생성
    ↓
Pydantic 스키마 검증 및 필드 정제
    ↓
형식 오류 발생 시 간결한 프롬프트로 1회 재시도
    ↓
SQLite에 이미지·메타데이터·후보 저장
    ↓
Gradio에서 후보 선택·수정
    ↓
SQLite FTS5 기반 키워드·버킷 검색
```

핵심 로직은 다음 네 파일로 나뉩니다.

- `core.py`: 프롬프트, 분석 스키마, Gemini 호출, 이미지 보관, 토큰 로그
- `database.py`: SQLite 저장, 수정, 중복 확인, FTS5 검색
- `batch_analyze.py`: 폴더 안의 여러 이미지를 일괄 분석
- `app.py`: Gradio 사용자 인터페이스

---

## 행동 후보 생성 원칙

행동 후보는 단순히 화면 속 물체를 분류하는 것이 아니라, **사용자가 이 이미지를 저장한 뒤 무엇을 할 수 있는지**를 제안하도록 설계했습니다.

### 후보 생성 시 고려한 사항

1. **정확히 3개 생성**  
   Pydantic 스키마에서 후보 수를 3개로 제한합니다.

2. **후보 간 의미 중복 방지**  
   같은 대상에 비슷한 표현만 반복하지 않고 구매, 비교, 방문, 체험, 읽기, 요리, 공부, 신청, 참고 등 서로 다른 행동 관점을 활용합니다.

3. **개별 요소와 전체 주제의 균형**  
   화면 속 특정 상품이나 장소뿐 아니라, 여러 요소를 묶는 공통 주제도 후보로 고려합니다.

4. **화면에 보이는 근거만 사용**  
   이미지에서 확인할 수 없는 장소, 날짜, 제품 정보나 사용자의 개인 취향을 임의로 추정하지 않습니다.

5. **부가 요소도 독립적인 관심사로 고려**  
   메인 게시물 이외의 요소라도 화면에서 명확히 보이고 실제 관심 대상으로 판단되면 후보에 포함할 수 있습니다.

6. **광고 요소는 제한적으로 반영**  
   단순 노출 광고가 아니라 사용자가 실제로 관심을 가질 가능성이 높다고 판단되는 경우에만 후보로 고려합니다.

7. **실행 가능한 문장으로 작성**  
   후보 제목은 `저장하기`, `비교해보기`, `방문하기`, `신청하기`처럼 사용자가 바로 이해할 수 있는 행동 형태로 생성합니다.

### 지원 버킷 예시

- 요리해보고 싶은 것
- 먹어보고 싶은 것
- 맛집·카페 가보기
- 방문하고 싶은 곳
- 여행 계획 세우기
- 사고 싶은 것
- 비교해보고 싶은 제품
- 스타일·코디 참고
- 한번 해보고 싶은 활동
- 취미로 시작하고 싶은 것
- 공부·탐구해보고 싶은 것
- 읽고 싶은 책
- 보고 싶은 콘텐츠
- 참여하고 싶은 행사
- 신청할 것
- 예약할 것
- 사용법·문제 해결 정보
- 나중에 참고할 정보
- 선물 아이디어
- 기억하고 싶은 생각·문장
- 건강·루틴으로 실천할 것

전체 버킷 ID는 Gradio의 **버킷 ID 안내** 또는 `core.py`의 `BUCKETS`에서 확인할 수 있습니다.

---

## 분석 결과 구조

Gemini는 다음 11개 최상위 필드를 가진 JSON을 생성합니다.

| 필드 | 설명 | 정보가 없을 때 |
|---|---|---|
| `summary` | 스크린샷의 중심 내용을 한 문장으로 요약 | 필수 문자열 |
| `key_text` | 검색에 필요한 핵심 문구. 최대 700자 | 필수 문자열 |
| `source_type` | 인스타그램, 유튜브, 네이버 검색, 쇼핑 사이트 등의 출처 유형 | `unknown` |
| `source_name` | 계정명, 채널명, 사이트명 | `null` |
| `content_dates` | 콘텐츠에 직접 표시된 날짜·기간·마감일 원문 | `[]` |
| `objects` | 화면의 주요 사물·상품·콘텐츠 | `[]` |
| `colors` | 주요 색상 | `[]` |
| `places` | 장소와 지역 | `[]` |
| `activities` | 요리, 독서, 여행, 쇼핑 등의 활동 | `[]` |
| `keywords` | 검색용 핵심 주제어 | `[]` |
| `action_candidates` | 제목, 대상, 버킷 ID, 이유로 구성된 행동 후보 | 정확히 3개 |

후보 하나의 구조는 다음과 같습니다.

```json
{
  "title": "토마토 파스타 만들어보기",
  "subject": "토마토 파스타",
  "bucket_id": "food.cook",
  "reason": "화면에 토마토 파스타 조리 예시가 표시되어 있다."
}
```

날짜 필드는 화면에 보이는 원문만 저장합니다. 휴대전화 상태바 시각, 파일 저장일, `3일 전`과 같은 상대 시각은 제외하며, 화면에 없는 연도를 추정하지 않습니다.

---

## 기술 스택

| 영역 | 기술 | 용도 |
|---|---|---|
| Language | Python | 전체 애플리케이션 구현 |
| Vision-Language Model | Gemini API | 이미지 이해, 메타데이터 및 행동 후보 생성 |
| UI | Gradio | 이미지 분석·검토·검색 웹 화면 |
| Validation | Pydantic | JSON 스키마 정의, 길이 제한, 후보 수 검증 |
| Database | SQLite | 이미지·메타데이터·후보 영구 저장 |
| Search | SQLite FTS5 | 메타데이터와 선택 후보의 키워드 검색 |
| Data handling | pandas | Gradio 표 데이터 처리 |
| Image handling | Pillow | 이미지 라이브러리 의존성 및 호환 지원 |
| Configuration | python-dotenv | `.env` 환경변수 로드 |

기본 모델은 `.env`의 `GEMINI_MODEL`에서 설정하며, 저장소의 기본값은 `gemini-3.5-flash-lite`입니다.

---

## 프로젝트 구조

```text
screenshot-to-bucket/
├── app.py                 # Gradio UI와 사용자 동작 처리
├── core.py                # Gemini 호출, 프롬프트, 스키마, 이미지·토큰 처리
├── database.py            # SQLite 저장·수정·검색
├── batch_analyze.py       # 폴더 단위 일괄 분석
├── requirements.txt       # Python 패키지 목록
├── .env.example           # 환경변수 예시
├── .gitignore             # API 키·DB·실행 결과 제외 설정
├── README.md
├── data/
│   ├── raw/               # 분석할 원본 이미지와 예제 이미지
│   │   ├── example_01.jpg
│   │   └── ...
│   └── images/            # 해시 기반 이름으로 복사된 분석 이미지
└── outputs/
    ├── usage.csv          # 이미지별 토큰 사용량과 실행 상태
    └── raw/               # Gemini 원본 JSON 응답
```

현재 `data/raw/`에는 바로 테스트할 수 있는 예제 스크린샷 10장이 포함되어 있습니다. 새로운 이미지를 분석하려면 같은 폴더에 JPG, JPEG, PNG 또는 WEBP 파일을 추가하면 됩니다.

`data/images/`, `outputs/`, SQLite DB는 실행 과정에서 자동으로 생성되거나 갱신됩니다.

---

# 설치 및 실행

## 0. 준비 사항

- Python 3.10 이상
- 인터넷 연결
- Gemini API 키
- Windows, macOS 또는 Linux

Python 설치 여부는 터미널에서 확인할 수 있습니다.

```bash
python --version
```

환경에 따라 `python` 대신 `python3` 명령을 사용해야 할 수 있습니다.

---

## 1. 저장소 받기

### 방법 A: GitHub에서 ZIP으로 받기

1. 저장소 상단의 **Code** 버튼 클릭
2. **Download ZIP** 선택
3. 압축 해제
4. 터미널에서 압축을 해제한 폴더로 이동

```bash
cd screenshot-to-bucket
```

### 방법 B: Git 사용

```bash
git clone <이 저장소의 URL>
cd screenshot-to-bucket
```

---

## 2. 가상환경 만들기

프로젝트마다 독립적인 패키지 환경을 사용하기 위해 가상환경 생성을 권장합니다.

### Windows 명령 프롬프트

```cmd
python -m venv .venv
.venv\Scripts\activate
```

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

PowerShell에서 실행 정책 오류가 발생하면 현재 세션에 한해 다음 명령을 먼저 실행할 수 있습니다.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
```

가상환경이 활성화되면 터미널 앞에 보통 `(.venv)`가 표시됩니다.

---

## 3. 패키지 설치

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

설치되는 주요 패키지는 Gradio, Google Gen AI SDK, pandas, Pillow, Pydantic, python-dotenv입니다.

---

## 4. 환경변수 설정

`.env.example`을 복사해 `.env` 파일을 만듭니다.

### Windows 명령 프롬프트

```cmd
copy .env.example .env
```

### Windows PowerShell

```powershell
Copy-Item .env.example .env
```

### macOS / Linux

```bash
cp .env.example .env
```

생성된 `.env`를 열고 `GEMINI_API_KEY`에 본인의 API 키를 입력합니다.

```env
GEMINI_API_KEY=your_actual_api_key
GEMINI_MODEL=gemini-3.5-flash-lite
MAX_OUTPUT_TOKENS=1800

DB_PATH=data/app.db
IMAGE_DIR=data/images
OUTPUT_DIR=outputs
```

`.env`는 실제 API 키를 포함하므로 GitHub나 다른 공개 공간에 업로드하지 마세요. 저장소의 `.gitignore`에는 `.env`가 제외 대상으로 설정되어 있습니다.

---

## 5. 분석할 이미지 준비

저장소의 `data/raw/`에는 예제 이미지 10장이 들어 있습니다.

새 이미지를 추가하려면 다음처럼 파일을 `data/raw/`에 복사합니다.

```text
data/raw/
├── example_01.jpg
├── example_02.jpg
├── my_screenshot_01.png
└── my_screenshot_02.webp
```

지원 형식:

```text
.jpg  .jpeg  .png  .webp
```

Gemini 버전에서는 이미지 해상도를 별도로 줄이지 않고 원본 바이트를 전달합니다. 매우 큰 이미지는 API 처리 시간과 사용량에 영향을 줄 수 있습니다.

---

## 6. 소량으로 먼저 테스트하기

처음 실행할 때는 `--limit` 옵션으로 일부 이미지만 분석하는 것을 권장합니다.

```bash
python batch_analyze.py --input-dir data/raw --limit 3
```

정상 실행 예시:

```text
[1/3] example_01.jpg
  저장 완료 | 후보 3개 | 토큰 1,234 | 상태 analyzed

완료 — 성공 3개 / 실패 0개 / 건너뜀 0개
토큰 사용량: outputs/usage.csv
```

분석이 끝나면 다음 파일과 폴더가 생성됩니다.

```text
data/app.db
outputs/usage.csv
outputs/raw/
data/images/
```

---

## 7. 전체 이미지 분석하기

```bash
python batch_analyze.py --input-dir data/raw
```

이미 DB에 저장된 동일한 이미지는 SHA-256 해시를 기준으로 자동으로 건너뜁니다. 파일 이름이 달라도 이미지 내용이 같으면 중복으로 판단할 수 있습니다.

배치 분석으로 생성된 행동 후보는 처음에는 모두 `선택하지 않음` 상태입니다. 버킷 필터와 사용자 의도 검색에 후보를 반영하려면 Gradio의 **저장 결과 검토** 탭에서 필요한 후보를 선택한 뒤 **수정 내용 저장**을 눌러주세요.

### 이미 분석한 이미지도 다시 분석하기

```bash
python batch_analyze.py --input-dir data/raw --force
```

`--force`를 사용하면 API가 다시 호출되므로 토큰과 비용이 추가로 발생합니다.

---

## 8. Gradio 앱 실행하기

```bash
python app.py
```

터미널에 표시되는 로컬 주소를 브라우저에서 엽니다. 일반적으로 다음 주소가 사용됩니다.

```text
http://127.0.0.1:7860
```

종료할 때는 앱을 실행한 터미널에서 `Ctrl + C`를 누릅니다.

---

# Gradio 사용 방법

Gradio 화면은 세 개의 탭으로 구성되어 있습니다.

## 1. 새 이미지 분석

1. **스크린샷** 영역에 이미지를 업로드하거나 클립보드에서 붙여넣습니다.
2. **분석하기** 버튼을 누릅니다.
3. 이미지 요약과 추출 메타데이터를 확인합니다.
4. 생성된 행동 후보 3개를 검토합니다.
5. 저장하고 싶은 후보의 `선택` 칸을 체크합니다.
6. 필요하면 제목, 버킷 ID, 대상, 이유를 직접 수정합니다.
7. **선택 결과 저장** 버튼을 누릅니다.

주의: **분석하기**만 누르면 결과가 화면과 토큰 로그에는 표시되지만, SQLite DB에 최종 저장하려면 **선택 결과 저장**을 눌러야 합니다.

## 2. 저장 결과 검토

1. **목록 새로고침**을 누릅니다.
2. `검토할 이미지` 목록에서 이미지를 선택합니다.
3. **불러오기**를 누릅니다.
4. 저장된 이미지, 메타데이터, 행동 후보를 확인합니다.
5. 후보 선택 여부와 내용을 수정합니다.
6. **수정 내용 저장**을 누릅니다.

후보를 수정하면 사용자 의도 검색용 텍스트도 함께 갱신됩니다.

## 3. 버킷·검색

1. 검색어를 입력합니다.
2. 필요한 경우 버킷 필터를 선택합니다.
3. **검색** 버튼을 누릅니다.
4. 이미지 갤러리와 메타데이터 표에서 결과를 확인합니다.

검색어 없이 버킷만 선택해 필터링할 수도 있습니다.

---

## 검색 방식

이 프로젝트의 검색은 임베딩이나 벡터 DB를 사용한 의미 검색이 아니라 **SQLite FTS5 기반 키워드 검색**입니다.

### 사실 정보 검색 대상

- 요약
- 핵심 문구
- 출처 유형과 출처명
- 콘텐츠 날짜
- 객체
- 색상
- 장소
- 활동
- 키워드

### 사용자 의도 검색 대상

사용자가 `선택`한 후보에 포함된 다음 정보만 검색 인덱스에 반영됩니다.

- 후보 제목
- 행동 대상
- 버킷 이름
- 후보 이유

선택하지 않은 AI 후보는 사용자 의도 검색에 포함되지 않습니다.

여러 단어를 입력하면 각 단어를 `AND` 조건으로 검색합니다. FTS5를 사용할 수 없거나 검색 결과가 없으면 `LIKE` 검색으로 한 번 더 조회합니다.

검색 결과는 BM25 관련도순이 아니라 **최신 업로드순**으로 정렬됩니다. `옷`, `의류`, `티셔츠`처럼 의미가 비슷해도 문자열이 다르면 자동으로 같은 개념으로 처리되지 않습니다.

---

## 결과 파일 확인

### `data/app.db`

SQLite 데이터베이스입니다. 다음 정보가 저장됩니다.

- 이미지 ID, 원본 파일명, SHA-256 해시, 저장 경로
- 사용 모델과 분석 상태
- 메타데이터 11개 필드
- 행동 후보 및 사용자 선택 여부
- 검색용 사실 텍스트와 의도 텍스트
- FTS5 검색 인덱스

DB 파일은 첫 실행 시 자동으로 생성됩니다.

### `data/images/`

분석에 사용된 이미지를 SHA-256 기반 파일명으로 복사해 보관합니다.

```text
data/images/a83f91c20d31ab12.jpg
```

원본 파일명이 달라도 동일한 이미지인지 판별하고 DB 레코드와 연결하는 데 사용합니다.

### `outputs/raw/`

Gemini가 반환한 원본 JSON 텍스트가 저장됩니다.

```text
outputs/raw/<image_id>_full_1.json.txt
outputs/raw/<image_id>_full_2.json.txt
```

`full_2` 파일은 첫 응답의 형식 검증에 실패해 재시도가 수행된 경우에 생성됩니다.

### `outputs/usage.csv`

이미지별 토큰 사용량, API 호출 횟수, 성공·실패 상태가 기록됩니다.

---

## 토큰 사용량 확인

`outputs/usage.csv`의 열은 다음과 같습니다.

```csv
filename,model,prompt_tokens,output_tokens,thought_tokens,total_tokens,calls,status,error
```

| 열 | 의미 |
|---|---|
| `filename` | 입력 이미지 파일명 |
| `model` | 사용한 Gemini 모델 |
| `prompt_tokens` | 프롬프트 및 이미지 입력 토큰 |
| `output_tokens` | 모델 출력 토큰 |
| `thought_tokens` | 모델 내부 추론 토큰 |
| `total_tokens` | 전체 토큰 |
| `calls` | 해당 이미지 분석에 사용된 API 호출 횟수 |
| `status` | 성공 또는 실패 상태 |
| `error` | 실패 시 오류 메시지 |

CSV는 Excel, Google Sheets 또는 pandas로 열 수 있습니다.

### 전체 토큰 합계 확인

```bash
python -c "import pandas as pd; d=pd.read_csv('outputs/usage.csv'); print(d[['prompt_tokens','output_tokens','thought_tokens','total_tokens','calls']].sum())"
```

### 실패한 행만 확인

```bash
python -c "import pandas as pd; d=pd.read_csv('outputs/usage.csv'); print(d[d['status']=='failed'][['filename','error']].to_string(index=False))"
```

`usage.csv`는 실행할 때마다 행이 추가됩니다. 같은 이미지를 `--force`로 다시 분석하면 새 실행 기록이 추가되므로, 실험별 사용량을 비교할 때 이 점을 고려하세요.

---

## DB 백업과 복원

백업 전에는 가능하면 Gradio 앱과 배치 분석을 종료하세요.

### Windows 명령 프롬프트에서 단순 복사

```cmd
copy data\app.db data\app_backup.db
```

### macOS / Linux에서 단순 복사

```bash
cp data/app.db data/app_backup.db
```

SQLite가 실행 중일 때 더 안전하게 백업하려면 Python의 SQLite backup API를 사용합니다.

```bash
python -c "import sqlite3; s=sqlite3.connect('data/app.db'); d=sqlite3.connect('data/app_backup.db'); s.backup(d); d.close(); s.close(); print('백업 완료')"
```

### 백업 DB로 실행하기

`.env`의 경로를 백업 파일로 변경합니다.

```env
DB_PATH=data/app_backup.db
```

또는 앱을 종료한 뒤 백업 파일을 `data/app.db`로 복사해 복원할 수 있습니다.

### 분석 결과를 처음부터 다시 만들기

기존 결과가 필요하지 않은지 확인한 뒤 앱과 배치 분석을 종료하고 다음 파일을 삭제합니다.

```text
data/app.db
data/app.db-wal
data/app.db-shm
data/images/ 안의 분석 이미지
outputs/usage.csv
outputs/raw/ 안의 원본 응답
```

`data/raw/`의 원본 및 예제 이미지는 유지해야 다시 분석할 수 있습니다.

---

## 설정값 변경

`.env`에서 다음 값을 변경할 수 있습니다.

| 변수 | 기본값 | 설명 |
|---|---|---|
| `GEMINI_API_KEY` | 없음 | 필수 Gemini API 키 |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | 이미지 분석에 사용할 모델 |
| `MAX_OUTPUT_TOKENS` | `1800` | 한 번의 응답에 허용할 최대 출력 토큰 |
| `DB_PATH` | `data/app.db` | SQLite DB 파일 경로 |
| `IMAGE_DIR` | `data/images` | 분석 이미지 복사본 저장 폴더 |
| `OUTPUT_DIR` | `outputs` | 토큰 로그와 원본 응답 저장 폴더 |

모델을 변경할 경우 해당 모델이 이미지 입력과 구조화 JSON 출력을 지원하는지 확인해야 합니다. 모델에 따라 품질, 속도, 토큰 사용량과 API 비용이 달라질 수 있습니다.

---

## 문제 해결

### `GEMINI_API_KEY가 없습니다`

`.env.example`을 `.env`로 복사했는지, `.env`의 `GEMINI_API_KEY`에 실제 키를 입력했는지 확인하세요.

### 모델 404 또는 접근 권한 오류

`.env`의 `GEMINI_MODEL`이 현재 계정에서 사용할 수 있는 모델인지 확인하세요. 다른 모델을 사용할 경우 환경변수만 변경할 수 있지만, 이미지 입력과 구조화 출력 호환성이 필요합니다.

### `분석할 이미지가 없습니다`

`data/raw/`에 지원되는 확장자의 이미지가 있는지 확인하세요.

```text
.jpg  .jpeg  .png  .webp
```

### 이미지가 계속 건너뛰어집니다

이미 같은 이미지가 DB에 저장되어 있기 때문입니다. 다시 분석하려면 `--force`를 사용하세요.

```bash
python batch_analyze.py --input-dir data/raw --force
```

### 후보가 저장되지 않습니다

Gradio에서 분석 후 **선택 결과 저장** 버튼을 눌렀는지 확인하세요. `분석하기`는 결과 생성 단계이며 DB 저장은 별도 단계입니다.

### 검색 결과가 기대와 다릅니다

현재 검색은 키워드 기반입니다. 동의어, 유사어, 문맥적 유사성을 자동으로 이해하는 의미 검색은 지원하지 않습니다. 검색어를 화면에 실제로 나타날 법한 단어로 바꿔보세요.

### FTS5를 사용할 수 없는 환경

일부 SQLite 빌드에는 FTS5가 포함되지 않을 수 있습니다. 이 경우 프로젝트는 FTS5 오류를 무시하고 `LIKE` 기반 검색으로 보완합니다.

### Gradio 주소가 열리지 않습니다

- `python app.py`를 실행한 터미널이 계속 열려 있는지 확인합니다.
- 터미널에 오류가 출력되었는지 확인합니다.
- 이미 실행 중인 다른 Gradio 프로세스가 있다면 종료한 뒤 다시 실행합니다.

---

## 데이터 및 개인정보 안내

- `data/raw/`의 예제 스크린샷은 기능 테스트를 위한 자료이며, 화면에 포함된 제3자 콘텐츠의 권리는 각 권리자에게 있습니다.
---

## 한계

- AI가 생성한 행동 후보가 실제 사용자의 캡처 의도와 다를 수 있습니다.
- 검색은 문자열 기반이므로 동의어와 문맥적 유사성을 충분히 처리하지 못합니다.
- 검색 결과는 관련도 점수가 아니라 최신 업로드순으로 정렬됩니다.
- 이미지 속 작은 글자, 가려진 텍스트, 복잡한 화면에서는 정보가 누락될 수 있습니다.
- 결과 품질과 비용은 Gemini 모델 및 API 정책에 따라 달라질 수 있습니다.
- 현재는 로컬 단일 사용자용 PoC이며, 계정 인증이나 다중 사용자 데이터 분리는 제공하지 않습니다.

향후 개선 방향으로는 임베딩 기반 의미 검색, 사용자 선택 이력을 반영한 개인화, 모바일 공유 기능, URL 입력, 자동 삭제 정책, 모델별 품질 평가 등을 고려할 수 있습니다.

---
