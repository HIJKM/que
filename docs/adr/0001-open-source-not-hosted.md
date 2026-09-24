# 호스팅하지 않고 오픈소스한다

Que를 남에게 보여 주는 방법으로 공개 파서 인스턴스(Vercel/Railway 등)와 오픈소스를 비교했다. 공개 서버는 운영자가 YouTube/X/Threads를 대신 fetch하게 되므로 약관 위치가 나빠진다. 비공개 네트워크 초대는 하지 않기로 했다.

그래서 레포를 public로 열고, 실행은 각자 머신에서 한다.

- **Status**: accepted
- **Considered Options**: 공개 데모 호스팅, 비공개 네트워크 초대, 오픈소스 self-host
- **Consequences**: 볼트 ingest·`que-render`는 클론한 사람에게 그대로 재현되지 않을 수 있다. 공개 브랜치의 중심은 추출·읽기 UX다. 번역은 공개 브랜치에서 임시 비활성화한다.
