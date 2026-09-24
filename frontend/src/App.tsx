import { useEffect } from 'react';
import { Link, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { Grid2X2, Moon, Sun } from 'lucide-react';
import { QueLogo } from './components/QueLogo';
import { ListPage } from './routes/ListPage';
import { DetailPage } from './routes/DetailPage';
import { NotFoundPage } from './routes/NotFoundPage';

function useTapFlash() {
  useEffect(() => {
    const timers = new WeakMap<Element, number>();
    const onClick = (event: MouseEvent) => {
      const target = (event.target as Element | null)?.closest('button, .iconbtn, .meta-icon-btn, .btn, .ingest-target-option');
      if (!(target instanceof HTMLElement) || target.hasAttribute('disabled') || target.getAttribute('aria-disabled') === 'true') return;
      const previous = timers.get(target);
      if (previous) window.clearTimeout(previous);
      target.classList.remove('tap-flash');
      void target.offsetWidth;
      target.classList.add('tap-flash');
      timers.set(target, window.setTimeout(() => {
        target.classList.remove('tap-flash');
        timers.delete(target);
      }, 520));
    };
    document.addEventListener('click', onClick);
    return () => document.removeEventListener('click', onClick);
  }, []);
}

function Shell() {
  useTapFlash();
  const location = useLocation();
  const navigate = useNavigate();
  const isKnownRoute = location.pathname === '/' || /^\/items\/[^/]+\/?$/.test(location.pathname);
  const isNotFoundRoute = !isKnownRoute;

  const isDetail = location.pathname.startsWith('/items/');
  const showBackToList = isDetail || isNotFoundRoute;
  return (
    <>
      <nav className="topnav">
        <Link className="brand logo-cycle que-logo-button" to="/" aria-label="메인 페이지" title="메인 페이지">
          <QueLogo playOnList={location.pathname === '/'} />
        </Link>
        {showBackToList && (
          <button className="iconbtn nav-right" type="button" onClick={() => navigate('/')} title="목록" aria-label="목록">
            <Grid2X2 size={18} />
          </button>
        )}
        <button className="iconbtn theme-toggle" type="button" onClick={toggleTheme} aria-label="다크/라이트 전환" title="다크/라이트 전환">
          <Moon className="icon-moon" size={18} />
          <Sun className="icon-sun" size={18} />
        </button>
      </nav>
      <Routes>
        <Route path="/" element={<ListPage />} />
        <Route path="/items/:id" element={<DetailPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </>
  );
}

let themeTransitionTimer = 0;
function toggleTheme() {
  const root = document.documentElement;
  const next = root.dataset.theme === 'dark' ? 'light' : 'dark';
  root.classList.add('theme-transitioning');
  root.dataset.theme = next;
  localStorage.setItem('qi-theme', next);
  window.clearTimeout(themeTransitionTimer);
  themeTransitionTimer = window.setTimeout(() => {
    root.classList.remove('theme-transitioning');
  }, 320);
}

export function App() {
  return <Shell />;
}
