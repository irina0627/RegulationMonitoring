# 금융규제 실시간 모니터링 시스템 구축 설계서

> 증권사 임직원용 규제 인텔리전스 모니터링 시스템.
> 금융위원회 보도자료를 실시간 트리거로 삼아 규제 이슈를 지식 그래프로 구조화하고,
> 부서·업권별 맞춤 다이제스트를 매일 아침 자동 이메일로 보내는 내부 도구. (웹사이트 없음)

---

## 0. 이 문서의 사용법

- 본 문서는 **구현 가능한 수준의 설계 스펙**이다. Claude Code 등으로 단계별 구현 시 이 문서를 프로젝트 기준 문서(spec)로 사용한다.
- `[추천]` 표시는 "추천에 맡김"으로 위임된 결정에 대한 기본값이다. 언제든 override 가능하며, 변경 시 영향 범위를 함께 기재해 두었다.
- `[결정됨]` 표시는 사전 확정된 사항이다.
- `[확인필요]` 표시는 구현 진행 중 사용자 확인이 필요한 지점이다.

---

## 1. 프로젝트 개요

### 1.1 목적
금융위원회의 규제 발표를 실시간으로 감지·구조화하여, 증권사 임직원이 "지금 어떤 규제가, 어느 단계까지 와 있고, 우리 상품·업무에 무엇을 의미하는지"를 파악하게 한다. 결과는 화면이 아니라 **매일 아침 부서·업권별 맞춤 이메일 다이제스트**로 전달한다.

### 1.2 대상 사용자
- 1차: 증권사 내부 임직원(컴플라이언스, 상품, 리스크, 전략 부서)
- 사용 맥락: 매일 아침 받은 이메일 다이제스트로 확인. 신뢰성·출처 명확성·대응 시점 판단이 핵심.

### 1.3 핵심 가치 (단순 뉴스피드와의 차별점)
- 이슈 단위 묶음: 보도자료 + 관련 기사 + 관련 법령을 하나의 "규제 이슈"로 통합
- 라이프사이클 가시화: 입법예고 → 의결 → 시행령 → 시행 → 후속 단계 표시
- 영향 매핑: 이슈가 어떤 업권·상품에 영향을 주는지 연결
- 출처 신뢰도 계층: 금융위 공식(1차) vs 언론(2차) 명확히 구분
- 지식 그래프 기반 태깅: 이슈를 업권·상품·법령에 연결해 부서별 맞춤 발송과 관련 이슈 묶음에 활용 (별도 탐색 화면은 두지 않음)

### 1.4 비기능 목표
- 정시성: 매일 정해진 시각(예: 08:00)에 다이제스트 발송. 신규 보도자료는 다음 발송 주기에 포함
- 신뢰성: 모든 이메일 항목에 1차/2차 출처 표기 강제
- 이식성: 외부 환경 → 사내 폐쇄망 이전이 어댑터 교체 수준으로 가능(LLM·이메일 발송 포함)

---

## 2. 핵심 결정사항 (확정)

| 항목 | 결정 | 비고 |
|---|---|---|
| 배포 전략 | `[결정됨]` 외부(개인PC·클라우드) 우선 구축 → 사내망 이전 | 외부 의존성을 어댑터 뒤로 격리하는 것이 전제 |
| 전달 방식 | `[결정됨]` 웹사이트 없음. 매일 아침 부서·업권별 이메일 다이제스트 | 표출 레이어 = 이메일 |
| 기술 스택 | `[추천]` Python 백엔드 + PostgreSQL + SMTP 이메일 (프론트엔드 없음) | 2.1 참조 |
| 발송 인프라 | `[추천]` SMTP를 EmailSender 어댑터로 격리 | 사내 이전 시 사내 메일 릴레이로 교체 |
| 요약·태깅 | `[결정됨]` 외부 LLM(OpenAI API, 기본 모델 gpt-4o-mini) 사용, 어댑터로 추상화 | 사내망 이전 시 온프렘/규칙기반으로 교체 가능 |
| MVP 범위 | `[추천]` 금융위 보도자료 + 법령 API 공식 소스만 | 외부 뉴스는 2단계 |
| 그래프 저장 | `[추천]` PostgreSQL 관계형(노드/엣지 테이블), 내부 태깅·매칭용 | 표출용 시각화 화면은 없음. Neo4j는 규모 확장 시 옵션 |

### 2.1 기술 스택 선정 이유
- **Python 백엔드(FastAPI)**: 수집·HWP/PDF 파싱·LLM 연동·NLP 라이브러리 생태계가 가장 강하다. 공공데이터·법령 API 예제도 Python이 풍부하다.
- **PostgreSQL**: 관계형 + JSON 컬럼 + (필요 시) 그래프 쿼리를 한 DB로 처리. 사내망에서도 가장 무난하게 승인·운영되는 표준 DBMS. 초기 로컬은 SQLite로 시작해도 무방하나, 스키마 호환을 위해 처음부터 PostgreSQL 권장.
- **이메일(SMTP + HTML 템플릿)**: 표출은 웹이 아니라 이메일. HTML 이메일 템플릿(Jinja2)으로 다이제스트를 렌더하고, SMTP를 `EmailSender` 어댑터 뒤에 두어 사내 메일 릴레이로 교체 가능하게 한다. 프론트엔드 프레임워크는 사용하지 않는다.
- **스케줄러**: 초기 APScheduler(단일 프로세스, 간단) → 확장 시 Celery + beat.
- **컨테이너**: Docker / docker-compose. 사내망 이전 시 환경 재현성 확보의 핵심.

> override 영향: 스택 변경 시 13장(디렉토리 구조)·11장(스택 상세)이 함께 바뀐다. 데이터 소스·그래프 설계·파이프라인은 스택 독립적이다.

---

## 3. 시스템 아키텍처

### 3.1 레이어 구조
```
[외부 소스]                    [수집 레이어]          [처리 레이어]         [저장 레이어]        [전달 레이어]
금융위 RSS         ─┐
금융위 게시판/첨부  ─┤
금융공공데이터 API  ─┼──▶  Collectors  ──▶  Parsers ──▶ NLP/LLM ──▶  PostgreSQL  ──▶  Digest Builder ──▶ Email Sender
법제처 법령 API    ─┤        (어댑터)        (HWP/PDF)  (OpenAI       (관계형+그래프)   (그룹별 선별)      (SMTP, 매일 발송)
외부 뉴스(2단계)   ─┘                                   gpt-4o-mini)
```

### 3.2 외부 → 사내망 이전을 위한 설계 원칙 (가장 중요)
배포 전략이 "외부 우선 → 사내 이전"이므로, **모든 외부 호출을 추상화 경계 뒤로 숨기는 것**을 처음부터 강제한다.

- **수집 어댑터 격리**: 코어 로직(이슈 생성·그래프 구축)은 외부 URL/네트워크를 전혀 모른다. 외부 접근은 `collectors/` 모듈에서만 일어난다.
- **LLM 어댑터 격리**: NLP 코어는 `LLMClient` 인터페이스만 호출한다. 구현체(`OpenAIClient`, 기본 모델 gpt-4o-mini)만 외부 API를 안다. 사내망에서 외부 LLM이 막히면 `OnPremClient` 또는 `RuleBasedClient`로 교체.
- **DMZ 수집기 패턴 대비**: 사내 이전 시, 외부영역(DMZ)에 수집기만 두고 결과를 내부 DB로 단방향 전달하는 구조로 분리할 수 있게, 수집 결과를 "직렬화 가능한 표준 레코드(JSON)"로 만든다.
- **설정 외부화**: 모든 엔드포인트·키·주기는 `.env`로. 코드에 하드코딩 금지.
- **오프라인 패키지 대비**: 폐쇄망 설치를 위해 의존성을 `requirements.txt`/`package-lock.json`으로 고정. 사내 미러/오프라인 휠 설치 가능하도록.

---

## 4. 데이터 소스 상세

> 핵심 원칙: **공식·무료 루트 우선.** 기관이 배포 목적으로 공개한 채널(RSS·OpenAPI)일수록 사내 IT보안·컴플라이언스 승인이 쉽다.

### 4.1 금융위 보도자료 RSS — 실시간 트리거 (1순위)
- 보도자료: `http://www.fsc.go.kr/about/fsc_bbs_rss/?fid=0111`
- 보도설명자료: `http://www.fsc.go.kr/about/fsc_bbs_rss/?fid=0112`
- 공지사항: `http://www.fsc.go.kr/about/fsc_bbs_rss/?fid=0114`
- 카드뉴스: `http://www.fsc.go.kr/about/fsc_bbs_rss/?fid=0411`
- 제공 내용: 제목, 게시 링크, 게시일자(본문은 미포함)
- 용도: **신규 보도자료 발생 감지.** 폴링 주기 `[추천]` 10분.
- 주의: RSS는 "발생 알림"만. 본문은 4.2에서 별도 수집.

### 4.2 금융위 보도자료 게시판 + 첨부 — 본문 수집 (1순위)
- 게시판: `https://www.fsc.go.kr/no010101`
- 구조: 목록(제목·담당부서·게시일) → 상세 페이지 → 첨부파일(hwp/hwpx/pdf)
- **본문은 첨부파일에 들어 있음** → HWP/PDF 파싱 필요 (6.3·7장 참조)
- 용도: RSS로 감지한 항목의 상세·본문·담당부서 확보
- 주의: 스크래핑이므로 사이트 구조 변경에 취약 → 파서 모듈화 + 실패 모니터링

### 4.3 data.go.kr 보도자료 파일데이터 — 사용하지 않음
- 라이선스: 이용허락범위 제한 없음, 무료 (라이선스는 깨끗)
- **그러나 갱신주기가 "수시(1회성)"인 스냅샷**이라 실시간 모니터링에 부적합
- 결론: 실시간 파이프라인에 넣지 말 것. (참고/백필 용도로만 검토 가능)

### 4.4 금융공공데이터 OpenAPI — 영향 매핑 보조 (2순위)
- 포털: data.go.kr, Base 예: `http://apis.data.go.kr/1160100/service/...`
- 내용: 기업기본정보, 기업/금융회사 재무정보, 금융회사기본정보, 주식권리일정 등 **정형 데이터**(보도자료 본문 아님)
- 트래픽 한도: 개발계정 일 10,000건 / 운영계정 일 100,000건
- 신청: data.go.kr 회원가입 → 활용신청(개발계정 자동승인)
- 용도: 이슈를 특정 회사·상품으로 연결할 때 보조 근거. MVP에서는 선택적.

### 4.5 법제처 국가법령정보 OPEN API — 라이프사이클 보강 (2순위)
- 포털: `https://open.law.go.kr` (국가법령정보 공동활용)
- 내용: 법령 본문, 시행일, 개정 이력, 입법예고 등 — **정식 API**
- 용도: 보도자료에서 추출한 법령명을 실제 법령 데이터에 매핑하고, 시행일·개정단계로 라이프사이클을 정확히 채움.
- 신청: open.law.go.kr 사용자 신청(인증키 발급)
- `[확인필요]` 활용 신청 시 기관/용도 기재 항목이 있을 수 있음 — 발급 절차는 구현 단계에서 함께 확인.

### 4.6 금융위 법령·의결 페이지 (보조 공식 소스)
스크래핑/모니터링 대상으로 라이프사이클 추적에 유용 (전부 금융위 공식):
- 입법예고/규정변경예고: `https://www.fsc.go.kr/po040301`
- 금융위 소관법규: `https://www.fsc.go.kr/po040101`
- 소관 규정/고시/공고/훈령: `https://www.fsc.go.kr/po040200`
- 금융위 의결정보: `https://www.fsc.go.kr/no020101`
- 증선위 의결정보: `https://www.fsc.go.kr/no020102`
- 금융규제 법령해석포털: `https://better.fsc.go.kr/`

### 4.7 외부 뉴스 (구글 뉴스 등) — 2단계, 저작권 주의
- 용도: 같은 이슈에 대한 언론 반응·해석 (2차 자료)
- **저작권**: 공공저작물 아님(언론사 저작권). 원문 저장·재배포 금지.
  - 저장 허용: 제목 + 원문 링크 + **자체 생성 요약**(원문 복제 아님)
  - robots.txt·이용약관 준수, 공식 RSS/피드 경로 우선
- MVP에서 제외, 컴플라이언스 가드(15장) 적용 후 도입

### 4.8 소스 요약표

| 소스 | 공식 | 실시간 | 본문 | MVP 포함 | 비고 |
|---|---|---|---|---|---|
| 보도자료 RSS | O | O | 제목·링크 | O | 트리거 |
| 보도자료 게시판/첨부 | O | O | HWP·PDF | O | 본문 |
| data.go.kr 파일데이터 | O | X | — | X | 1회성, 미사용 |
| 금융공공데이터 API | O | 일배치 | 정형 | 선택 | 영향 매핑 |
| 법제처 법령 API | O | 수시 | 법령 | 선택 | 라이프사이클 |
| 외부 뉴스 | X | O | 기사 | X(2단계) | 저작권 주의 |

---

## 5. 데이터 파이프라인

### 5.1 전체 흐름
```
1) Collect   : RSS 폴링 → 신규 항목 감지 → 게시판 상세·첨부 수집
2) Normalize : 제목/날짜/담당부서/링크를 표준 레코드로 정규화, 중복 제거(GUID 기준)
3) Parse     : 첨부 HWP/HWPX/PDF → 본문 텍스트 추출
4) Enrich    : LLM으로 요약·핵심요지·엔터티추출·분류·라이프사이클 판별·영향 추정
5) Graph     : 이슈 노드 생성/병합(클러스터링), 엔터티·소스 엣지 연결
6) Score     : 이슈 중요도 점수 계산(다이제스트 선별·정렬용)
7) Deliver   : 매일 정해진 시각에 부서·업권별 다이제스트 생성 → 이메일 발송(중복 제외)
```

### 5.2 단계별 상세
- **Collect**: `collectors/rss.py`가 RSS를 폴링하여 `guid`(또는 링크 해시)로 신규 여부 판별. 신규면 `collectors/board.py`가 상세 페이지에서 담당부서·첨부 URL 확보, `collectors/attachment.py`가 파일 다운로드.
- **Normalize**: 모든 소스를 공통 레코드 형태로 변환(직렬화 가능 JSON). 사내망 DMZ 분리 시 이 레코드가 경계를 넘는 단위가 된다.
- **Parse**: HWP/HWPX/PDF 파서(7장). 실패 시 제목·요약만으로 레코드 우선 생성(graceful degradation).
- **Enrich**: LLM 어댑터 호출. 출력은 구조화 JSON(요약/요지/엔터티/단계/영향). 비용·환각 통제를 위해 결과 캐싱 + 출처 강제.
- **Graph**: 신규 이슈 vs 기존 이슈 병합 판단(8.4 클러스터링). 엔터티 정규화 후 엣지 생성.
- **Score/Deliver**: 중요도 점수(최신성 + 단계 가중 + 영향도)로 선별·정렬 → 그룹 filters와 이슈 엔터티를 매칭해 그룹별 다이제스트 구성 → delivery_log로 중복 제외 후 발송.

### 5.3 멱등성·재처리
- 모든 단계는 멱등(idempotent)하게 설계: 같은 보도자료를 재수집해도 중복 이슈가 생기지 않음(외부 ID·해시 키 사용).
- 단계별 상태(`parse_status`, `enrich_status`)를 저장해 실패 항목만 재처리.

---

## 6. 지식 그래프 설계

### 6.1 노드(Node) 타입
| 노드 | 설명 | 주요 속성 |
|---|---|---|
| Issue(규제 이슈) | 허브 노드 | title, summary, why_it_matters, lifecycle_stage, importance_score |
| PressRelease(보도자료) | 1차 소스 | title, published_at, dept, source_url, body_text |
| NewsArticle(외부 기사) | 2차 소스 | title, url, publisher, published_at, summary |
| Regulation(법령·제도) | 연결 개념 | law_name, law_id, enforce_date, revision_history |
| Agency/Dept(기관·부서) | 연결 개념 | name, type |
| Product(금융상품) | 연결 개념 | name, category |
| Sector(업권) | 연결 개념 | name |
| LifecycleStage(규제 단계) | 상태 | stage_code, order |

### 6.2 엣지(Edge) 타입
| 엣지 | from → to | 의미 |
|---|---|---|
| TRIGGERS | PressRelease → Issue | 보도자료가 이슈를 발생 |
| MENTIONS | NewsArticle → Issue | 기사가 이슈를 언급 |
| BASED_ON | Issue → Regulation | 이슈의 근거 법령 |
| AFFECTS | Issue → Product/Sector | 이슈의 영향 대상 |
| HANDLED_BY | Issue → Agency/Dept | 소관 부서 |
| AT_STAGE | Issue → LifecycleStage | 현재 단계 |

### 6.3 라이프사이클 단계 정의 (시드)
```
stage_code   order  설명
PRE_NOTICE     1    입법예고 / 규정변경예고
DECISION       2    금융위·증선위 의결 / 국무회의 (법률은 국회 단계 포함)
PROMULGATION   3    공포
SUB_LAW        4    시행령·시행규칙·고시 정비
ENFORCEMENT    5    시행
FOLLOW_UP      6    가이드라인·FAQ·검사 등 후속
```
> 법률/시행령/금융위 규정에 따라 경로가 다르므로, 단계는 "유연 매핑"으로 둔다. LLM 1차 판별 + 법제처 API 시행일로 보정.

### 6.4 이슈 클러스터링 (중복 묶기)
- 목적: 같은 사안의 보도자료+여러 기사를 하나의 Issue로 통합(다이제스트 중복 오염 방지)
- 방법 `[추천]`: 임베딩 유사도(제목+요약) + 규칙(법령명/날짜 근접/키워드) 하이브리드
- 보정: "수동 병합/분리" 관리 기능 제공(간단 CLI 또는 관리 엔드포인트). 자동 분류 오류 대비

### 6.5 시드 온톨로지 (예시 — 확장 가능)
- 업권: 증권, 은행, 보험, 카드·여전, 자산운용, 신탁, 가상자산, 핀테크
- 상품: ELS, ELB, DLS, 펀드, 신탁, CFD, 랩, IRP/연금, 채권
- 주요 법령: 자본시장법, 금융소비자보호법, 전자금융거래법, 신용정보법, 가상자산이용자보호법, 금융지주회사법
- 정규화 사전: 동의어/약칭 매핑(예: "자본시장법" = "자본시장과 금융투자업에 관한 법률")

### 6.6 저장 방식 / 그래프의 용도
- `[추천]` PostgreSQL 관계형으로 노드/엣지 표현(8장 스키마). 노드=issue/entity, 엣지=issue_entity/issue_source.
- **그래프는 화면 표출용이 아니라 내부 구조로 쓴다**: ① 이슈 태깅(영향 업권·상품·근거 법령), ② 부서·업권별 발송 매칭(그룹 filters ↔ 이슈 엔터티), ③ 관련 이슈 묶음. 인터랙티브 탐색 화면은 두지 않는다.
- 규모·복잡 질의 증가 시 Neo4j 이관(옵션). 이관을 쉽게 하려고 그래프 빌더를 `graph/` 모듈로 분리.

---

## 7. 파서 레이어 (HWP/PDF/HTML)

### 7.1 과제
보도자료 본문이 hwp/hwpx 첨부에 있어 한글 포맷 파싱이 필요 — 이 시스템의 대표적 난관.

### 7.2 파일 형식별 전략 `[추천]`
- **HWPX**(신형, XML 기반 zip): 우선 대상. zip 해제 후 XML에서 텍스트 추출이 비교적 안정적.
- **HWP**(구형 바이너리): `pyhwp` 등 파서 사용. 실패율이 있으므로 폴백 필수.
- **PDF**: `pdfplumber`/`PyMuPDF`로 텍스트 추출. 보도자료가 hwp·pdf 둘 다 첨부되는 경우가 많아 **PDF를 우선 시도**하고 실패 시 HWP로 폴백하는 전략이 실용적.
- **HTML**: 목록/상세 파싱은 `BeautifulSoup`/`lxml`.

### 7.3 폴백 원칙
- 본문 파싱 실패해도 제목·날짜·담당부서·링크로 레코드는 먼저 생성.
- 파싱 실패 항목은 `parse_status=failed`로 표시하고 재시도 큐로.
- `[확인필요]` 표/이미지 내 텍스트(스캔 PDF)는 OCR 필요 여부 — 초기엔 제외, 빈도 보고 결정.

---

## 8. 데이터 모델 (DB 스키마)

> PostgreSQL 기준. 타입은 단순화 표기. 실제 마이그레이션은 Alembic 등으로 관리.

```sql
-- 보도자료 (1차 소스)
CREATE TABLE press_release (
  id              BIGSERIAL PRIMARY KEY,
  fsc_post_id     TEXT,                 -- 게시판 게시물 식별자
  rss_guid        TEXT UNIQUE,          -- 중복 방지 키
  title           TEXT NOT NULL,
  published_at    TIMESTAMPTZ,
  dept            TEXT,                 -- 담당부서
  source_url      TEXT,
  body_text       TEXT,                 -- 파싱된 본문
  attachments     JSONB,                -- [{filename,type,url,parse_status}]
  parse_status    TEXT DEFAULT 'pending',
  enrich_status   TEXT DEFAULT 'pending',
  fetched_at      TIMESTAMPTZ DEFAULT now()
);

-- 규제 이슈 (허브 노드)
CREATE TABLE issue (
  id               BIGSERIAL PRIMARY KEY,
  title            TEXT NOT NULL,
  summary          TEXT,                -- LLM 한 줄 요약
  why_it_matters   TEXT,               -- LLM "왜 중요한가"
  lifecycle_stage  TEXT,               -- stage_code
  status           TEXT DEFAULT 'active',
  importance_score NUMERIC DEFAULT 0,
  first_seen_at    TIMESTAMPTZ DEFAULT now(),
  last_updated_at  TIMESTAMPTZ DEFAULT now()
);

-- 엔터티 (법령/상품/업권/기관/부서)
CREATE TABLE entity (
  id              BIGSERIAL PRIMARY KEY,
  type            TEXT NOT NULL,        -- regulation|product|sector|agency|dept
  name            TEXT NOT NULL,
  canonical_name  TEXT,                 -- 정규화 명칭
  metadata        JSONB,
  UNIQUE(type, canonical_name)
);

-- 이슈-소스 엣지 (TRIGGERS / MENTIONS)
CREATE TABLE issue_source (
  id           BIGSERIAL PRIMARY KEY,
  issue_id     BIGINT REFERENCES issue(id),
  source_type  TEXT NOT NULL,           -- press_release|news
  source_id    BIGINT NOT NULL,
  relation     TEXT NOT NULL            -- trigger|mention
);

-- 이슈-엔터티 엣지 (BASED_ON / AFFECTS / HANDLED_BY)
CREATE TABLE issue_entity (
  id         BIGSERIAL PRIMARY KEY,
  issue_id   BIGINT REFERENCES issue(id),
  entity_id  BIGINT REFERENCES entity(id),
  relation   TEXT NOT NULL,             -- based_on|affects|handled_by
  weight     NUMERIC DEFAULT 1.0
);

-- 외부 기사 (2차 소스, 2단계)
CREATE TABLE news_article (
  id            BIGSERIAL PRIMARY KEY,
  title         TEXT,
  url           TEXT UNIQUE,
  publisher     TEXT,
  published_at  TIMESTAMPTZ,
  summary       TEXT,                   -- 자체 생성 요약(원문 저장 금지)
  fetched_at    TIMESTAMPTZ DEFAULT now()
);

-- 법령 상세 (entity 보강)
CREATE TABLE regulation_detail (
  id               BIGSERIAL PRIMARY KEY,
  entity_id        BIGINT REFERENCES entity(id),
  law_id           TEXT,                -- 법제처 법령ID
  enforce_date     DATE,
  revision_history JSONB
);

-- 수신자 그룹 (부서·업권별 발송 단위)
CREATE TABLE recipient_group (
  id        BIGSERIAL PRIMARY KEY,
  name      TEXT NOT NULL,              -- 예: "리테일상품부", "파생업권"
  filters   JSONB NOT NULL,            -- {sectors:[],products:[],depts:[],keywords:[]} ↔ 이슈 엔터티 매칭
  active    BOOLEAN DEFAULT true
);

-- 그룹 수신자 (이메일 주소)
CREATE TABLE recipient (
  id        BIGSERIAL PRIMARY KEY,
  group_id  BIGINT REFERENCES recipient_group(id),
  email     TEXT NOT NULL,
  name      TEXT,
  active    BOOLEAN DEFAULT true,
  UNIQUE(group_id, email)
);

-- 발송 이력 (중복 발송 방지)
CREATE TABLE delivery_log (
  id          BIGSERIAL PRIMARY KEY,
  group_id    BIGINT REFERENCES recipient_group(id),
  issue_id    BIGINT REFERENCES issue(id),
  digest_date DATE NOT NULL,
  status      TEXT DEFAULT 'sent',      -- sent|failed
  sent_at     TIMESTAMPTZ DEFAULT now(),
  UNIQUE(group_id, issue_id, digest_date)  -- 같은 이슈를 같은 그룹에 같은 날 두 번 보내지 않음
);
```

> 그래프 관점: 노드 = `issue` + `entity`, 엣지 = `issue_source` + `issue_entity`. 이 4개 테이블이 지식 그래프의 본체다.

---

## 9. 운영 인터페이스 (헤드리스 — 웹사이트 없음)

표출은 이메일이므로 사용자용 웹 화면은 없다. 아래는 운영·관리·디버그용 최소 엔드포인트다.
수신자 그룹 초기 구성은 엔드포인트 대신 설정 파일(`config/recipients.yaml` 시드)로도 가능하다.

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/admin/ingest/run` | 수동 수집 트리거 |
| POST | `/api/admin/digest/run` | 다이제스트 즉시 생성·발송(운영/디버그). `?dry_run=true`면 발송 안 함 |
| GET | `/api/admin/digest/preview` | 발송 전 HTML 미리보기(그룹 지정, 발송 안 함) |
| GET/POST/PUT/DELETE | `/api/admin/groups` | 수신자 그룹(부서·업권) 관리 |
| GET/POST/DELETE | `/api/admin/recipients` | 그룹별 수신자(이메일) 관리 |
| POST | `/api/admin/issues/{id}/merge` | 이슈 수동 병합 |
| GET | `/api/health` | 헬스체크 |

- 접근 통제 `[추천]`: 관리 엔드포인트는 내부망/관리자 토큰으로 제한. 일반 사용자 인증은 불필요(웹 UI가 없으므로).

---

## 10. 이메일 다이제스트 설계

### 10.1 발송 방식 `[결정됨]`
- 매일 아침 1회 정기 다이제스트. 발송 시각은 환경변수(`DIGEST_SEND_HOUR`, 예: 8시).
- 포함 대상: 직전 발송 이후 신규로 생성됐거나 라이프사이클 단계가 바뀐 이슈.
- 스케줄러(APScheduler)가 매일 정해진 시각에 다이제스트 빌드 → 그룹별 발송을 실행.

### 10.2 수신자 그룹 `[결정됨]`
- 부서·업권별 그룹으로 구분 발송(예: 리테일상품부, 파생업권, 컴플라이언스).
- 각 그룹은 `filters`(업권/상품/부서/키워드)를 가지며, 이슈의 엔터티(AFFECTS 업권·상품, HANDLED_BY 부서)와 매칭되는 이슈만 그 그룹 다이제스트에 담는다.
- 그룹·수신자는 `recipient_group`/`recipient` 테이블 또는 `config/recipients.yaml` 시드로 구성.

### 10.3 이메일 내용
- 형식: HTML 이메일(인라인 CSS·테이블 레이아웃 — 메일 클라이언트 호환).
- 상단: "오늘의 핵심 N건" 한 줄 요약.
- 각 이슈 항목: 제목 + 한 줄 요약 + 왜 중요한가 + 라이프사이클 단계 + 영향 업권/상품 태그 + 출처(1차/2차) + 원문 보도자료 링크.
- 톤 `[추천]`: 클린·미니멀. 색은 상태(단계·출처)에만, 색만으로 의존하지 않게 라벨 병기.
- 면책: "영향 추정은 내부 참고용, 투자권유 아님"을 푸터에 명시(16장).

### 10.4 발송 인프라 `[추천]`
- `EmailSender` 어댑터 인터페이스 뒤에 SMTP 구현을 둔다(LLM 어댑터와 동일 패턴).
- 외부 개발: 일반 SMTP(회사 메일 계정 또는 테스트 SMTP).
- 사내 이전: `EmailSender`만 사내 메일 릴레이 구현으로 교체.
```python
class EmailSender(Protocol):
    def send(self, to: list[str], subject: str, html: str) -> SendResult: ...
# 구현체: SmtpSender(외부), InternalRelaySender(사내, 추후)
```

### 10.5 중복 방지
- `delivery_log`에 (group_id, issue_id, digest_date)를 기록해 같은 이슈를 같은 그룹에 중복 발송하지 않음.
- 예외: 라이프사이클 단계가 바뀌는 등 중대한 업데이트 시 "업데이트" 표시로 1회 재포함.

### 10.6 빈 다이제스트 처리
- 그룹에 보낼 신규 이슈가 없으면 발송 생략(기본) 또는 "오늘 신규 없음" 짧은 메일(환경변수 `SEND_EMPTY_DIGEST`).

---

## 11. 기술 스택 상세

| 구분 | 선택 `[추천]` | 비고 |
|---|---|---|
| 언어(백엔드) | Python 3.11+ | 수집·파싱·NLP 생태계 |
| 웹 프레임워크 | FastAPI | 비동기·자동 문서(OpenAPI) |
| 스케줄러 | APScheduler → (확장)Celery+beat | 초기엔 단순 |
| DB | PostgreSQL 15+ (로컬 SQLite 가능) | 사내망 친화 |
| ORM/마이그레이션 | SQLAlchemy + Alembic | |
| HTTP/파싱 | httpx, BeautifulSoup, lxml | |
| HWP/PDF | pyhwp, pdfplumber/PyMuPDF | PDF 우선·HWP 폴백 |
| LLM | OpenAI API(어댑터), 기본 모델 gpt-4o-mini | 모델·요금은 platform.openai.com에서 확인. 어댑터로 다른 모델·제공자 교체 가능 |
| 임베딩(클러스터링) | 외부 임베딩 API 또는 경량 로컬 모델 | 사내망 시 로컬 우선 |
| 이메일 템플릿 | Jinja2 (HTML 이메일, 인라인 CSS) | 메일 클라이언트 호환 위해 테이블 레이아웃 |
| 이메일 발송 | smtplib/aiosmtplib + `EmailSender` 어댑터 | 사내 이전 시 사내 메일 릴레이로 교체 |
| 컨테이너 | Docker, docker-compose | 사내 이전 핵심 |

> `[확인필요]` 임베딩을 외부 API로 할지 로컬 모델로 할지는 비용·사내망 정책에 따라 결정. 어댑터로 분리해 교체 가능하게.

---

## 12. LLM/NLP 레이어 상세

### 12.1 어댑터 인터페이스
```python
class LLMClient(Protocol):
    def summarize(self, text: str) -> Summary: ...
    def extract_entities(self, text: str) -> list[Entity]: ...
    def classify_lifecycle(self, text: str) -> str: ...     # stage_code
    def assess_impact(self, text: str) -> Impact: ...        # 영향 업권·상품·근거
```
- 구현체: `OpenAIClient`(외부, MVP, 기본 모델 gpt-4o-mini), 향후 `OnPremClient`/`RuleBasedClient`(사내망 대체).
- 코어 NLP는 이 인터페이스만 의존 → 외부 LLM 차단 시 구현체 교체로 대응.

### 12.2 작업별 LLM 호출 (프롬프트 설계 방향)
- **요약**: 보도자료 본문 → 한 줄 요약 + "왜 중요한가"(임직원 관점). 사실 기반, 추정·과장 금지.
- **엔터티 추출**: 법령명/상품/업권/소관부서/시행일 추출 → 시드 온톨로지에 정규화 매핑.
- **라이프사이클 판별**: 본문 단서로 stage_code 1차 추정 → 법제처 시행일로 보정.
- **영향 추정**: 어떤 업권·상품에 영향인지 + 근거 문장. **"투자권유 아님·내부 참고용" 면책 전제**(15장).
- 출력은 **구조화 JSON**으로 강제(파싱·검증 용이). 근거(원문 인용 위치) 함께 반환.

### 12.3 비용·환각 통제
- 결과 캐싱(같은 보도자료 재처리 방지).
- 출처 강제: LLM 출력은 항상 원문 보도자료와 함께 표시. 사실 주장은 근거 위치 표기.
- 검증 규칙: 추출 법령명이 사전/법제처에 없으면 플래그 → 사람이 확인.

---

## 13. 디렉토리 구조

```
fsc-monitor/
├─ backend/
│  ├─ app/
│  │  ├─ collectors/      # rss.py, board.py, attachment.py, opendata.py, law.py, news.py
│  │  ├─ parsers/         # hwp.py, pdf.py, html.py
│  │  ├─ nlp/             # llm_client.py, openai_client.py, prompts/, entity.py, lifecycle.py, impact.py
│  │  ├─ graph/           # schema.py, builder.py, queries.py, clustering.py
│  │  ├─ email/           # sender.py(EmailSender), templates/(HTML), digest.py(빌더), grouping.py(그룹 매칭), delivery.py(중복방지·이력)
│  │  ├─ models/          # SQLAlchemy 모델
│  │  ├─ api/             # admin.py(운영/관리), health.py  ← 헤드리스, 사용자 웹 없음
│  │  ├─ core/            # config.py, scheduler.py, logging.py
│  │  └─ db/              # alembic migrations
│  ├─ config/             # recipients.yaml (수신자 그룹·주소 시드, 선택)
│  ├─ tests/
│  ├─ pyproject.toml / requirements.txt
│  └─ Dockerfile
├─ docs/                 # 본 설계서 등
├─ docker-compose.yml
├─ .env.example
└─ README.md
```
(프론트엔드 디렉토리는 없음 — 표출은 이메일.)

---

## 14. 개발 로드맵 (마일스톤)

| 단계 | 산출물 | 핵심 작업 |
|---|---|---|
| M0 환경설정 | repo, .env, DB, API 키 | data.go.kr·법제처·OpenAI 키 발급, docker-compose 기동 |
| M1 수집 | press_release 적재 | RSS 폴링 + 게시판/첨부 수집 + HWP/PDF 파싱 |
| M2 NLP | issue 생성 | LLM 어댑터 + 요약·엔터티·단계·영향 |
| M3 그래프 | 노드/엣지 + 태깅 | 빌더·클러스터링·엔터티 매칭(내부용) |
| M4 이메일 다이제스트 MVP | 그룹별 일일 발송 | 그룹 매칭 + HTML 템플릿 + SMTP 발송 + 스케줄 + delivery_log |
| M5 법령 연계 | 라이프사이클 보강 | 법제처 API 매핑·시행일 보정 |
| M6 외부 뉴스 | 2차 소스 + 클러스터링 | 저작권 가드 적용, 기사 묶기 |
| M7 사내 이전 준비 | 컨테이너·어댑터 교체 가이드 | DMZ 수집기 분리, LLM 대체 경로, 오프라인 패키지 |

> MVP 정의 = **M1~M4** (보도자료 수집 → 부서·업권별 일일 이메일 다이제스트). M5는 품질 강화, M6는 확장, M7은 이전.

---

## 15. 사내망 이전 전략 (체크리스트)

- [ ] 외부 호출이 `collectors/`·`nlp/openai_client.py`에만 존재하는지 코드 점검(코어 격리 검증)
- [ ] 수집 결과가 직렬화 가능한 표준 레코드(JSON)인지 확인 → DMZ 경계 통과 단위
- [ ] DMZ 수집기 분리: 외부영역 수집 → 내부 DB 단방향 전달 구조로 재배치
- [ ] LLM 대체 경로 확정: 외부 LLM 불가 시 온프렘 sLLM 또는 규칙기반 폴백(`LLMClient` 교체)
- [ ] 이메일 발송 교체: 외부 SMTP → 사내 메일 릴레이(`EmailSender` 어댑터 교체), 발신 도메인/인증(SPF·DKIM) 사내 정책 적용
- [ ] 임베딩 로컬화(클러스터링용) 여부 결정
- [ ] 시크릿 관리: `.env` → 사내 vault/시크릿 매니저
- [ ] 오프라인 설치: pip 의존성 고정 + 사내 미러 또는 오프라인 휠
- [ ] 컨테이너 이미지 사내 레지스트리 등록
- [ ] 방화벽 승인: 공식 채널(RSS·OpenAPI) 목록으로 IT보안 승인 요청
- [ ] 운영/관리 엔드포인트 접근 통제(내부망 한정·관리자 토큰)

---

## 16. 컴플라이언스 · 저작권 · 면책

- **공공저작물(금융위 보도자료)**: data.go.kr 기준 이용허락범위 제한 없음·무료. 일반적으로 공공누리(KOGL) 적용 — 자유 이용 가능하되 **출처표시 권장**.
- **외부 뉴스(언론사)**: 저작권 별개. **원문 저장·재배포 금지.** 제목 + 링크 + 자체 생성 요약만. robots.txt·이용약관 준수.
- **면책 표기**: "영향 추정"은 **내부 참고용이며 투자권유가 아님**을 이메일 푸터에 명시. 컴플라이언스 검토 권장.
- **개인정보**: 보도자료엔 거의 없음(담당자명 정도). 최소 수집·표시.
- `[확인필요]` 사내 도입 시 자료 이용·재가공에 대한 내부 법무/컴플라이언스 사전 검토 필요.

---

## 17. 리스크 & 완화책

| 리스크 | 영향 | 완화책 |
|---|---|---|
| HWP 파싱 실패 | 본문 누락 | PDF 우선·HWP 폴백, 제목/요약 우선 카드, 재시도 큐 |
| LLM 비용·환각 | 신뢰성·비용 | 캐싱, 출처 강제, 구조화 출력 검증, 사전/법제처 대조 |
| 사이트 구조 변경 | 스크래핑 중단 | RSS 우선, 파서 모듈화, 실패 알림 모니터링 |
| 망분리 외부 차단 | 사내 이전 시 동작 불가 | 어댑터 추상화로 LLM/수집 교체 가능하게 설계(3.2) |
| 이슈 클러스터링 오류 | 중복/오병합 | 임베딩+규칙 하이브리드, 수동 병합/분리 관리 기능 |
| 외부 뉴스 저작권 | 법적 리스크 | 원문 미저장, 요약+링크, 2단계로 분리 |
| 이메일 발송 실패 | 미수신 | SMTP 재시도, delivery_log 실패 기록, 관리자 알림 |
| 중복·과잉 발송 | 수신 피로 | delivery_log로 (그룹·이슈·일자) 1회 보장, 빈 다이제스트 생략 옵션 |
| 스팸 분류 | 도달률 저하 | 발신 도메인·SPF/DKIM 사내 메일 정책 준수, 내부 발신 |

---

## 18. 환경 변수 (.env.example)

```
# 수집
FSC_RSS_PRESS=http://www.fsc.go.kr/about/fsc_bbs_rss/?fid=0111
FSC_BOARD_URL=https://www.fsc.go.kr/no010101
POLL_INTERVAL_MIN=10

# 공공 API
DATA_GO_KR_API_KEY=____        # data.go.kr 발급
LAW_API_KEY=____               # 법제처 open.law.go.kr 발급

# LLM
OPENAI_API_KEY=____            # platform.openai.com 발급
LLM_PROVIDER=openai            # 사내 이전 시 onprem|rule 로 교체
LLM_MODEL=gpt-4o-mini          # 기본 모델. 필요 시 다른 OpenAI 모델로 교체

# 이메일 발송
SMTP_HOST=____
SMTP_PORT=587
SMTP_USER=____
SMTP_PASSWORD=____
EMAIL_FROM=regwatch@example.com
EMAIL_PROVIDER=smtp            # 사내 이전 시 internal_relay 로 교체
DIGEST_SEND_HOUR=8             # 매일 발송 시각(24h)
SEND_EMPTY_DIGEST=false        # 신규 없을 때 발송 여부

# DB
DATABASE_URL=postgresql://user:pass@localhost:5432/fsc_monitor

# 기타
LOG_LEVEL=INFO
```

---

## 19. 진행 중 확인이 필요한 항목 모음 (`[확인필요]`)

1. 법제처 API 활용 신청 시 기관/용도 기재 절차 (4.5)
2. 스캔 PDF에 대한 OCR 도입 여부 (7.3)
3. 임베딩을 외부 API vs 로컬 모델 중 무엇으로 (11)
4. 외부 뉴스 도입 전 내부 법무/컴플라이언스 검토 (16)
5. SMTP 발송 정보: 외부 개발용 계정/발신 도메인, 사내 메일 릴레이 정보 (10, 18)
6. 수신자 그룹·주소 초기 구성 방식: 설정 파일 시드 vs 관리 엔드포인트 (8, 9, 10)

---

## 20. 용어집

- **보도자료(Press Release)**: 금융위가 정책·제도·감독 방안을 공식 배포하는 1차 자료.
- **라이프사이클 단계**: 규제가 입법예고→의결→공포→시행령→시행→후속으로 진행되는 단계.
- **이슈(Issue)**: 하나의 규제 사안을 중심으로 보도자료·기사·법령을 묶은 허브 노드.
- **어댑터(Adapter)**: 외부 의존성(수집·LLM·이메일 발송)을 코어 로직과 분리하는 추상화 경계.
- **다이제스트(Digest)**: 일정 기간 신규/업데이트 이슈를 모아 한 통으로 구성한 이메일.
- **수신자 그룹**: 부서·업권 등으로 묶인 발송 단위. 그룹별 filters로 이슈를 매칭해 맞춤 발송.
- **DMZ 수집기**: 폐쇄망에서 외부영역에 두는 수집 전용 컴포넌트(데이터를 내부로 단방향 전달).

---

*본 설계서는 외부 우선 구축 → 사내망 이전을 전제로 하며, 모든 외부 의존성은 교체 가능하도록 격리되어 있다. 구현은 M1부터 순차 진행하되, 각 `[확인필요]` 지점에서 결정을 받아 반영한다.*
