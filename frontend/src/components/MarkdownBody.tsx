import { useEffect, useRef } from 'react';

export function MarkdownBody({ html, onRendered }: { html: string; onRendered?: () => void }) {
  const ref = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const root = ref.current;
    if (!root) return;

    const template = document.createElement('template');
    template.innerHTML = html || '';
    const currentYoutube = root.querySelector('.yt-sticky');
    const nextYoutube = template.content.querySelector('.yt-sticky');

    if (currentYoutube && nextYoutube) {
      nextYoutube.remove();
      Array.from(root.childNodes).forEach((node) => {
        if (node !== currentYoutube) node.remove();
      });
      root.append(...Array.from(template.content.childNodes));
    } else {
      root.replaceChildren(...Array.from(template.content.childNodes));
    }

    root.querySelectorAll<HTMLAnchorElement>('a[href]').forEach((anchor) => {
      if (anchor.hostname && anchor.hostname !== window.location.hostname) {
        anchor.target = '_blank';
        anchor.rel = 'noopener';
      }
    });

    const loadTwitterWidgets = () => {
      if (!root.querySelector('.twitter-tweet')) return;
      const load = () => window.twttr?.widgets?.load(root);
      if (window.twttr?.widgets) {
        load();
        return;
      }
      const existing = document.getElementById('twitter-widgets-script') as HTMLScriptElement | null;
      if (existing) {
        existing.addEventListener('load', load, { once: true });
        return;
      }
      const script = document.createElement('script');
      script.id = 'twitter-widgets-script';
      script.src = 'https://platform.twitter.com/widgets.js';
      script.async = true;
      script.onload = load;
      document.body.appendChild(script);
    };

    const initEmbeds = () => {
      window.__qiInitYouTube?.();
      loadTwitterWidgets();
    };

    onRendered?.();
    requestAnimationFrame(() => onRendered?.());

    const youtubeScriptId = 'que-youtube-script-v3';
    if (document.getElementById(youtubeScriptId)) {
      initEmbeds();
      return;
    }

    const script = document.createElement('script');
    script.id = youtubeScriptId;
    script.src = '/static/youtube.js?v=20260722-5';
    script.async = true;
    script.onload = initEmbeds;
    document.body.appendChild(script);
  }, [html, onRendered]);

  return <article ref={ref} className="reader" />;
}
