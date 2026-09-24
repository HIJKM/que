# 오픈소스 공개 준비

기한은 일주일, 목표는 3일 안에 public로 내보내는 것이다. 라이브 파서 호스팅은 하지 않는다. 남이 만져보는 방법은 클론 후 self-host다.

이 폴더는 공개 전에 닫아야 할 결정의 목록이다. 각 항목의 본문은 `docs/adr/`에 있다.

## 일정

- **1일**: 폰트 바이너리 제거, vault 경로 환경변수화, LICENSE, README 면책. 이것들이 막히면 public 불가.
- **2일**: 공개/비공개 문서 경계 적용, 배포 워크플로 처리, 브랜드 아이콘·토큰 잔여분.
- **3일**: 레포 훑기, 개인 경로/이름 잔여 검색, visibility public.

## 내부 경계

Que는 한 레포 안에 제품과 개인 운영이 섞여 있다.

| 층 | 무엇인가 | public에 남나 |
|---|---|---|
| 제품 | 추출, sanitizer, SPA, Import API, SQLite 스키마 | 남긴다 |
| 로컬 상태 | `data.db`, `auth.json`, 볼트 파일 | 이미 gitignore. 확인만 |
| 개인 운영 | 개발/운영 checkout 경로, 리버스 프록시, 로컬 서비스 매니저, 개인 네트워크 | 빼거나 일반화한다 |
| 제3자 자산 | Anthropic webfont 파일, Brunch PNG | 제거·중립 표식으로 대체 완료 |
| 참고만 한 것 | editorial 톤, 페이퍼 팔레트, Cochin(시스템) | 톤은 유지 가능. 파일은 안 실음 |

ingest 경로는 `QUE_INGEST_*` 환경변수다. 문서 쪽 개인 운영 노트는 로컬 에이전트 컨텍스트에 남아 있다.

## 결정 목록

| ADR | 상태 | 공개 전에 |
|---|---|---|
| [0001 호스팅하지 않고 오픈소스](../adr/0001-open-source-not-hosted.md) | accepted | 이미 정함 |
| [0002 공개 표면](../adr/0002-public-private-surface.md) | accepted | 완료 |
| [0003 Anthropic 폰트](../adr/0003-anthropic-fonts.md) | accepted | 1일에 제거 |
| [0004 색·모션 토큰](../adr/0004-design-tokens.md) | proposed | 확인 필요 |
| [0005 라이선스](../adr/0005-license.md) | accepted | 완료 |
| [0006 fetch 면책](../adr/0006-fetch-disclaimer.md) | accepted | README에 적음 |

0004의 색상 조정은 공개 blocker가 아닌 후속 디자인 작업으로 남긴다. 공개 blocker였던
개인 운영 표면, 제3자 바이너리 자산, 라이선스는 현재 브랜치에서 닫혔다.
