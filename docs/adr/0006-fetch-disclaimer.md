# fetch 코드는 남기고, 공개 서비스처럼 안내하지 않는다

추출기는 YouTube 자막 비공식 API, FxEmbed, Threads 렌더, trafilatura를 쓴다. 코드가 있는 것과 남 대신 돌리는 서버는 다르다(ADR 0001).

공개 README에 적는다: 로컬 개인용이다. 대상 사이트의 이용약관을 각자 따른다. 데모 호스팅을 제공하지 않는다. X/Threads/YouTube 추출은 깨지거나 막힐 수 있다.

`safe_fetch`의 SSRF 가드는 그대로 둔다. 오픈소스여도 기본 바인딩을 `0.0.0.0`으로 두기보다 README는 `127.0.0.1`을 권한다.

- **Status**: accepted
