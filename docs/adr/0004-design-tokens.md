# 색과 모션 토큰은 다시 고른다

`static/app.css`의 `--primary: #d97757`과 페이퍼 배경 `#faf9f5`는 Anthropic/Claude 웹과 가깝다. 다크 팔레트 주석은 `bassimeledath.com`을 참고했다고 적혀 있다. `DESIGN_SYSTEM.md`는 “Anthropic/Refero 계열”이라고 적는다. Refero는 갤러리고, 톤을 보고 따라 그린 것과 파일을 넣은 것은 다르다.

폰트 파일(ADR 0003)과 달리 색 값은 아이디어라 재배포 금지가 아니다. 그래도 공개 레포가 Claude 스킨으로 보이면 불필요하다.

선택지:

- A. 토큰을 우리 값으로 조금 옮긴다. 따뜻한 페이퍼 editorial은 유지하되 primary를 Claude 오렌지가 아니게 한다. 3일 안에 가능하다.
- B. 시스템만 갈아끼우고 색은 그대로 둔다. 빠르지만 “훔친 토큰” 인상이 남는다.
- C. 팔레트를 처음부터 다시 짠다. 일주일 기한을 잠식한다.

추천은 A. Brunch `assets/icons/brunch.png`는 상표 파일이다. kind 아이콘을 글자나 간단한 마크다운 아이콘으로 바꾼다.

- **Status**: proposed
- **Considered Options**: A 소폭 이동, B 유지, C 전면 재설계
