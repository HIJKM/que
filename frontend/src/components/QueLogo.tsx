import { useEffect, useMemo, useRef, useState } from 'react';

export type FontSpec = { name: string; family: string; weight: string };
type Pair = { font: FontSpec; word: string };

export const logoFonts: FontSpec[] = [
  { name: 'System Sans', family: '-apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", sans-serif', weight: '620' },
  { name: 'System Serif', family: 'Georgia, "Apple SD Gothic Neo", serif', weight: '400' },
  { name: 'Apple System', family: '-apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", sans-serif', weight: '620' },
  { name: 'Cochin', family: 'Cochin, Georgia, serif', weight: '700' },
  { name: 'Palatino', family: 'Palatino, "Palatino Linotype", Georgia, serif', weight: '500' },
  { name: 'American Typewriter', family: '"American Typewriter", Georgia, serif', weight: '600' },
  { name: 'Optima', family: 'Optima, "Gill Sans", sans-serif', weight: '500' },
  { name: 'Didot', family: 'Didot, "Bodoni 72", serif', weight: '400' },
  { name: 'Bradley Hand', family: '"Bradley Hand", cursive', weight: '700' },
  { name: 'Menlo', family: 'Menlo, Monaco, monospace', weight: '700' },
];
const words = ['Quartz', 'Query', 'Quill', 'Quest', 'Queue', 'Quorum', 'Quantum', 'Quiet', 'Quasar', 'Quip', 'Quiddity'];
export const logoStorageKey = 'quartz.logoFont';
export const defaultLogoFont = logoFonts.find((f) => f.name === 'Cochin') || logoFonts[0];

export function getStoredLogoFont(): FontSpec {
  try {
    const saved = window.localStorage.getItem(logoStorageKey);
    return logoFonts.find((font) => font.name === saved) || defaultLogoFont;
  } catch {
    return defaultLogoFont;
  }
}

export function storeLogoFont(name: string) {
  try { window.localStorage.setItem(logoStorageKey, name); } catch {}
  window.dispatchEvent(new CustomEvent('que-logo-font-change', { detail: { name } }));
}

type Frame = { text: string; font: FontSpec; start: number; end: number; done?: boolean };

function pickPair(prev?: Pair): Pair {
  for (let i = 0; i < 8; i += 1) {
    const pair = { font: logoFonts[Math.floor(Math.random() * logoFonts.length)], word: words[Math.floor(Math.random() * words.length)] };
    if (!prev || prev.font.name !== pair.font.name || prev.word !== pair.word) return pair;
  }
  return { font: logoFonts[0], word: words[0] };
}

function makeSequence(): Pair[] {
  const result: Pair[] = [];
  let prev: Pair | undefined;
  for (let i = 0; i < 3; i += 1) {
    prev = pickPair(prev);
    result.push(prev);
  }
  return result;
}

function buildTimeline(sequence: Pair[], finalFont: FontSpec): { frames: Frame[]; duration: number } {
  const frames: Frame[] = [];
  let elapsed = 0;
  const push = (text: string, font: FontSpec, duration: number, done = false) => {
    frames.push({ text, font, start: elapsed, end: elapsed + duration, done });
    elapsed += duration;
  };
  push('Q', finalFont, 220);
  for (const pair of sequence) {
    for (let i = 2; i <= pair.word.length; i += 1) push(pair.word.slice(0, i), pair.font, 180);
    push(pair.word, pair.font, 600);
    for (let i = pair.word.length - 1; i >= 1; i -= 1) push(pair.word.slice(0, i), pair.font, 120);
    push('Q', pair.font, 360);
  }
  push('Qu', finalFont, 180);
  push('Que', finalFont, 180);
  push('Que', finalFont, 820);
  push('Que.', finalFont, 180);
  push('Que.', finalFont, 0, true);
  return { frames, duration: elapsed };
}

function frameAt(frames: Frame[], elapsed: number) {
  return frames.find((frame) => elapsed >= frame.start && elapsed < frame.end) || frames[frames.length - 1];
}

export function QueLogo({ playOnList }: { playOnList: boolean }) {
  const [sequence, setSequence] = useState<Pair[]>(() => makeSequence());
  const [startedAt, setStartedAt] = useState<number>(() => Date.now());
  const [elapsed, setElapsed] = useState(0);
  const hasPlayed = useRef(false);
  const [selectedFont, setSelectedFont] = useState<FontSpec>(() => getStoredLogoFont());
  const timeline = useMemo(() => buildTimeline(sequence, selectedFont), [sequence, selectedFont]);
  const clamped = Math.min(elapsed, timeline.duration);
  const frame = frameAt(timeline.frames, clamped);
  const done = clamped >= timeline.duration || frame.done;

  useEffect(() => {
    if (playOnList) {
      setSequence(makeSequence());
      setStartedAt(Date.now());
      setElapsed(0);
      hasPlayed.current = true;
      return;
    }
    if (!hasPlayed.current) setElapsed(timeline.duration);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playOnList]);

  useEffect(() => {
    const onFontChange = () => setSelectedFont(getStoredLogoFont());
    window.addEventListener('que-logo-font-change', onFontChange);
    window.addEventListener('storage', onFontChange);
    return () => {
      window.removeEventListener('que-logo-font-change', onFontChange);
      window.removeEventListener('storage', onFontChange);
    };
  }, []);

  useEffect(() => {
    if (done) return;
    const timer = window.setInterval(() => setElapsed(Date.now() - startedAt), 48);
    return () => window.clearInterval(timer);
  }, [done, startedAt]);

  return (
    <span className={done ? 'logo-typing-done' : ''} aria-label="Que">
      <span style={{ fontFamily: frame.font.family, fontWeight: frame.font.weight }}>{frame.text}</span>
      <span className="logo-typing-cursor" aria-hidden="true" />
    </span>
  );
}
