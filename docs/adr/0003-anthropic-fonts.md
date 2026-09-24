# Anthropic webfont 파일은 공개하지 않는다

`assets/fonts/anthropic/`에 Anthropic Sans/Serif `.woff2` 네 개가 커밋되어 있고, `static/app.css`가 `@font-face`로 불러온다. 파일명에 `.reference`가 붙어 있다. 이건 톤 참고가 아니라 바이너리 재배포다. public 전에 레포에서 지운다.

대체는 이미 스택에 있는 시스템 폰트로 한다. `--serif` / `--sans`에서 `"Anthropic Serif"` / `"Anthropic Sans"`를 빼고, `-apple-system`, `"Apple SD Gothic Neo"`, `"Noto Sans KR"`, Georgia 쪽으로 떨어지게 한다. 로고 기본 Cochin은 시스템 폰트 이름이므로 파일을 싣지 않으면 그대로 둔다.

- **Status**: accepted
- **Consequences**: 공개 빌드의 본문 결이 Claude 웹과 덜 닮는다. 그게 목적이다. git history에 파일이 남아 있으므로 public 전환 전에 이 경로를 히스토리에서 지울지 한 번 더 본다. 3일 일정에서는 현재 트리에서 삭제하는 것을 최소로 하고, history rewrite는 별도 결정이다.
