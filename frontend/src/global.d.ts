export {};

declare global {
  interface Window {
    __qiInitYouTube?: () => void;
    twttr?: { widgets?: { load: (root?: Element | null) => void } };
  }
}
