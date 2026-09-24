import { Link } from 'react-router-dom';

export function NotFoundPage() {
  return (
    <main className="not-found-page">
      <section className="not-found-panel" aria-labelledby="notFoundTitle">
        <p className="not-found-code">404</p>
        <h1 id="notFoundTitle">페이지를 찾을 수 없습니다.</h1>
        <p>요청한 주소가 없거나 더 이상 사용할 수 없습니다.</p>
        <Link className="btn btn-primary" to="/">목록으로</Link>
      </section>
    </main>
  );
}
