# RegulationMonitoring — 금융규제 실시간 모니터링 시스템

금융위원회 보도자료를 실시간 트리거로 삼아 규제 이슈를 지식 그래프로 구조화하고,
부서·업권별 맞춤 다이제스트를 매일 아침 자동 이메일로 보내는 증권사 임직원용 내부 도구.
(사용자용 웹사이트 없음 — 표출은 이메일 다이제스트)

## 문서
- 설계서(스펙): [docs/README.md](docs/README.md)
- 작업 규칙(Claude Code용): [docs/CLAUDE.md](docs/CLAUDE.md)

## 기술 스택
- Python 3.11+ / FastAPI(헤드리스 운영용) / SQLAlchemy + Alembic / APScheduler
- PostgreSQL 15+ (로컬 개발도 PostgreSQL, docker-compose 기동)
- LLM: OpenAI API (기본 모델 gpt-4o-mini) — `nlp/` 어댑터 뒤에서만 사용
- 이메일: Jinja2(HTML 템플릿) + aiosmtplib — `email/` 어댑터 뒤에서만 사용

## 디렉토리 구조
```
backend/
  app/
    collectors/   # RSS·게시판·첨부·법령 수집
    parsers/      # HWP/PDF/HTML 파싱
    nlp/          # LLMClient 어댑터(openai_client.py), 요약·엔터티·단계·영향
    graph/        # 노드/엣지 빌더·클러스터링·매칭
    email/        # EmailSender 어댑터, HTML 템플릿, 다이제스트 빌더
    models/       # SQLAlchemy 모델
    api/          # 운영·관리·헬스체크 (헤드리스)
    core/         # config, scheduler, logging, db
    db/           # alembic migrations
  config/         # recipients.yaml 시드(선택)
  tests/
docs/             # 설계서 등
```

## 개발 준비
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

환경 변수는 루트 `.env` 로 관리한다(커밋 금지). `cp .env.example .env` 로 만든 뒤 값을 채운다.
모든 코드는 환경변수를 `app/core/config.py` 의 `settings` 를 통해서만 읽는다.

## 실행

DB(PostgreSQL)를 먼저 띄우고 마이그레이션을 적용한 뒤 서버를 기동한다.

```bash
# 1) PostgreSQL 기동 (루트에서)
docker compose up -d

# 2) DB 스키마 적용 (backend 에서)
cd backend
PYTHONPATH=. alembic upgrade head

# 3) FastAPI(헤드리스) 기동 — 개발용 --reload
PYTHONPATH=. uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

헬스체크:

```bash
curl -s http://localhost:8000/api/health
# → {"status":"ok","db":"ok"}
```

> 사용자용 웹 화면은 없다. HTTP 엔드포인트는 운영·관리·헬스체크용(헤드리스)뿐이다.

## 개발 로드맵
M0 환경설정 → M1 수집 → M2 NLP → M3 그래프 → M4 이메일 다이제스트(MVP).
자세한 내용은 [docs/README.md](docs/README.md) 14장 참조.
