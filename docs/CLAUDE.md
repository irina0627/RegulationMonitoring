# CLAUDE.md — 금융규제 모니터링 시스템

## 프로젝트
금융위원회 보도자료를 실시간 트리거로 삼아 규제 이슈를 지식 그래프로 구조화하고,
부서·업권별 맞춤 다이제스트를 매일 아침 자동 이메일로 보내는 증권사 임직원용 도구.
상세 설계는 docs/금융규제_실시간_모니터링_시스템_설계서.md 를 따른다.
이 문서와 설계서가 충돌하면 설계서가 기준이다.

## 표출 방식
사용자용 웹사이트/프론트엔드는 만들지 않는다. 결과는 이메일 다이제스트로만 전달한다.
백엔드의 HTTP 엔드포인트는 운영·관리·디버그용(헤드리스)뿐이다.

## 배포 전제
외부(개인PC·클라우드)에서 먼저 만들고, 이후 사내 폐쇄망으로 이전한다.
따라서 외부 의존성을 어댑터 뒤로 격리하는 것을 항상 우선한다.

## 기술 스택
- 백엔드: Python 3.11+, FastAPI(헤드리스 운영용), SQLAlchemy + Alembic, APScheduler
- DB: PostgreSQL 15+ (로컬 개발도 PostgreSQL, docker-compose로 기동)
- 설정: pydantic-settings (.env 로딩)
- 수집/파싱: httpx, feedparser, beautifulsoup4(lxml), pdfplumber 또는 PyMuPDF, pyhwp
- LLM(M2~): OpenAI API (기본 모델 gpt-4o-mini) — 반드시 nlp/ 어댑터(LLMClient) 뒤에만
- 이메일(M4~): Jinja2(HTML 템플릿) + smtplib/aiosmtplib — 반드시 email/ 어댑터(EmailSender) 뒤에만
- 프론트엔드 프레임워크 없음

## 아키텍처 원칙 (반드시 준수)
1. 외부 의존성 격리: 외부 네트워크 호출은 collectors/ , nlp/openai_client.py ,
   email/sender.py 에서만 한다. 코어 로직(graph/, 이슈 생성, models/, digest 빌드)은
   외부 URL·키·SMTP를 알면 안 된다. (사내망 이전 대비)
2. 설정 외부화: 모든 URL·키·주기·SMTP는 .env → core/config.py 를 통해서만 접근. 하드코딩 금지.
3. 멱등성: 같은 보도자료를 다시 수집/처리해도 중복 레코드가 생기면 안 된다.
   외부 식별자/해시(rss_guid 등)를 유니크 키로 사용한다.
   이메일도 (그룹·이슈·일자) 기준으로 중복 발송하지 않는다(delivery_log).
4. Graceful degradation: 본문 파싱에 실패해도 제목·날짜·담당부서·링크로 레코드는 생성하고
   parse_status='failed' 로 표시한다. 전체 파이프라인을 멈추지 않는다.
5. 표준 레코드: 수집 결과는 직렬화 가능한 dict/JSON(표준 레코드)로 만든다.
   (사내망 이전 시 DMZ 경계를 넘는 단위가 된다.)

## 금지 사항
- 사용자용 웹사이트/프론트엔드를 만들지 말 것. 표출은 이메일.
- data.go.kr 의 "금융위원회_보도자료 파일데이터"를 실시간 소스로 쓰지 말 것. (1회성 스냅샷)
- 외부 뉴스 원문을 저장하지 말 것. (이후 단계, 언론사 저작권)
- 비밀키·SMTP 비밀번호를 코드나 커밋에 포함하지 말 것. .env 는 반드시 .gitignore.

## 코딩 컨벤션
- 타입 힌트 필수. 함수는 작게, 모듈은 단일 책임.
- 한국어 주석 허용. 공개 함수에는 docstring 권장.
- 각 수집기/파서/빌더에는 단위 테스트(tests/)를 함께 작성한다.
- 한 번에 하나의 기능만 구현하고, 동작 확인 후 다음으로 넘어간다.
- 외부 호출에는 타임아웃·재시도·에러 로깅을 둔다.

## 디렉토리 구조 (목표)
backend/
  app/
    collectors/   # rss.py, board.py, attachment.py, opendata.py, law.py, news.py
    parsers/      # hwp.py, pdf.py, html.py
    nlp/          # llm_client.py, openai_client.py, prompts/, entity.py, lifecycle.py, impact.py
    graph/        # schema.py, builder.py, queries.py, clustering.py, grouping.py
    email/        # sender.py(EmailSender), templates/(HTML), digest.py(빌더), delivery.py(중복방지·이력)
    models/       # SQLAlchemy 모델
    api/          # admin.py(운영/관리), health.py   ← 헤드리스, 사용자 웹 없음
    core/         # config.py, scheduler.py, logging.py, db.py
    db/           # alembic migrations
  config/         # recipients.yaml (수신자 그룹·주소 시드, 선택)
  tests/
docs/             # 설계서 등
docker-compose.yml
.env.example

## 작업 진행 방식
- 작업 지시서의 M0 → M1 → M2 → M3 → M4 순서대로 진행한다.
- 각 단계 종료 시 "확인 기준"을 점검하고, 통과해야 다음 단계로 간다.
- 파일 생성·수정은 사용자 동의 없이 바로 진행해도 된다.
- bash(터미널) 명령도 사용자 동의 없이 바로 실행해도 된다. (권한은 .claude/settings.local.json 에서 Bash 전체 허용)
- 파일 삭제는 반드시 사용자 동의를 받은 뒤에만 진행한다.