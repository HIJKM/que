export type ItemListResponse = {
  items: ItemSummary[];
  next_cursor: string | null;
  has_more: boolean;
  total_count: number;
};

export type ItemSummary = {
  id: number;
  share_code?: string | null;
  url: string;
  kind: string;
  kind_label: string;
  kind_icon_html?: string;
  status: string;
  title?: string | null;
  author?: string | null;
  author_display: string;
  author_initial: string;
  source_host: string;
  article_date: string;
  read_minutes: number;
  is_unread: boolean;
  error?: string | null;
  ingest_count: number;
  ingested_targets: string[];
};

export type IngestTarget = {
  key: string;
  label: string;
  path: string;
  relative_path: string;
  default: boolean;
  ingested: boolean;
};

export type ItemDetailResponse = {
  item: ItemSummary & { markdown?: string; meta_json?: string };
  body: { html: string; view: 'orig' | string };
  ingest_targets: IngestTarget[];
};
