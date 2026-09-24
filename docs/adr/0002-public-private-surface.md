# 공개 레포에 남기는 표면

제품 코드는 연다. 개인 운영 지식과 로컬 상태는 열지 않는다.

남긴다: `extract.py`, `safe_fetch.py`, 백엔드, 프론트, 테스트, sanitizer, 일반화된 README/SECURITY.

남기지 않는다: `data.db`, `auth.json`, 볼트, Anthropic 폰트 파일, 개인 홈 절대 경로, 개인 운영 경로, 개인 머신 배포를 전제로 한 문장.

애매한 것, 여기서 고른다:

1. `docs/agent-context/` — 에이전트용 운영 문서라 지금은 개인 핸드오프가 섞여 있다. 3일 안에 전부 다시 쓰지 않는다. 절대 경로와 머신 고유 문장을 지운 채 남기거나, 폴더를 비공개로 옮긴다.
2. `.github/workflows/deploy.yml` — self-hosted runner가 운영 checkout을 갱신한다. 비밀은 아니지만 개인 운영기다. 공개 레포에서는 빼서 로컬 스크립트로 두거나, “예시”로 일반화한다.
3. `AGENTS.md` — 개발/운영 checkout 경계를 에이전트에게 강제한다. 공개용은 self-host 규칙만 남기고, 개인 운영 규칙은 로컬 전용 파일로 분리하는 편이 맞다.

추천은 1과 3은 git 추적에서 빼고 디스크에는 남기며, 2는 워크플로를 레포에서 제거하는 것이다.

- **Status**: accepted
- **Consequences**: 이 경계가 안 닫히면 문서 소독이 끝없이 늘어나고 3일을 넘긴다.
