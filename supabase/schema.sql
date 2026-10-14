-- Run in Supabase SQL editor. The backend uses the service-role key (bypasses RLS);
-- RLS is enabled with NO policies so the public anon key can read/write nothing.
create extension if not exists vector;

create table if not exists advisor_sessions (
  id            text primary key,
  state         jsonb not null,
  review_status text not null default 'none',   -- none | pending | reviewed
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index if not exists advisor_sessions_review_idx on advisor_sessions (review_status, updated_at);

create table if not exists report_cache (
  key        text primary key,
  report     jsonb not null,
  created_at timestamptz not null default now()
);

create table if not exists rag_chunks (
  id        bigserial primary key,
  source    text not null,         -- e.g. "BARC Fertilizer Recommendation Guide 2018"
  page      int,
  crop_id   text,                  -- null = general knowledge
  content   text not null,
  embedding vector(384)            -- multilingual-e5-small
);
create index if not exists rag_chunks_embedding_idx on rag_chunks using hnsw (embedding vector_cosine_ops);

create or replace function match_rag_chunks(
  query_embedding vector(384), match_count int default 3, filter_crop text default null
) returns table (id bigint, source text, page int, content text, similarity float)
language sql stable as $$
  select id, source, page, content, 1 - (embedding <=> query_embedding) as similarity
  from rag_chunks
  where filter_crop is null or crop_id is null or crop_id = filter_crop
  order by embedding <=> query_embedding
  limit match_count;
$$;

alter table advisor_sessions enable row level security;
alter table report_cache     enable row level security;
alter table rag_chunks       enable row level security;

-- ============ Section 2: plot digital twin ============
create table if not exists twin_plots (
  id         text primary key,
  user_id    text not null,
  name       text not null,
  crop_id    text not null,
  status     text not null default 'growing',   -- growing | ready | harvested | dead
  day        int  not null default 0,
  state      jsonb not null,                     -- full simulator state (soil, nutrients, config, answers...)
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists twin_plots_user_idx on twin_plots (user_id, updated_at desc);

create table if not exists twin_logs (            -- one row per simulated day (sensor readings + decisions)
  plot_id text not null references twin_plots(id) on delete cascade,
  day     int  not null,
  record  jsonb not null,
  primary key (plot_id, day)
);

create table if not exists twin_events (          -- alerts, auto/manual actions, questions, farmer answers
  id         bigserial primary key,
  plot_id    text not null references twin_plots(id) on delete cascade,
  day        int  not null,
  kind       text not null,                       -- alert | action | auto_action | question | answer | status | photo | review | sms | whatsapp
  payload    jsonb not null,
  created_at timestamptz not null default now()
);
create index if not exists twin_events_plot_idx on twin_events (plot_id, id desc);

alter table twin_plots  enable row level security;
alter table twin_logs   enable row level security;
alter table twin_events enable row level security;

-- ============ Section 2 upgrade: photo reviews + harvest records (safe to re-run) ============
alter table twin_plots add column if not exists needs_review boolean not null default false;
create index if not exists twin_plots_review_idx on twin_plots (needs_review) where needs_review;

create table if not exists harvest_records (       -- real outcomes; Section 1 can use these as the farmer's own yields
  id                    bigserial primary key,
  user_id               text not null,
  plot_id               text not null unique,
  crop_id               text not null,
  soil                  text,
  area                  numeric not null,
  yield_kg              numeric not null,
  yield_kg_per_decimal  numeric not null,
  revenue               numeric,
  cost                  numeric,
  profit                numeric,
  days                  int,
  health                int,
  start_date            date,
  created_at            timestamptz not null default now()
);
create index if not exists harvest_user_idx on harvest_records (user_id, created_at desc);
alter table harvest_records enable row level security;

-- ============ Section 4 (farmers' trust): failures + data source on every record (safe to re-run) ============
alter table harvest_records add column if not exists outcome text not null default 'harvested';   -- harvested | dead
alter table harvest_records add column if not exists source  text not null default 'simulation';  -- simulation | real
create index if not exists harvest_crop_idx on harvest_records (crop_id, created_at desc);


-- ============ GrowthTwin Sentinel: durable sensor telemetry (safe to re-run) ============
create table if not exists sensor_readings (
  id                       bigserial primary key,
  plot_id                  text not null references twin_plots(id) on delete cascade,
  device_id                text not null,
  sequence                 bigint not null check (sequence >= 0),
  timestamp                timestamptz not null,
  raw_moisture_adc         integer not null check (raw_moisture_adc between 0 and 65535),
  temperature_c            double precision,
  humidity_pct             double precision check (humidity_pct is null or humidity_pct between 0 and 100),
  calibrated_moisture_pct  double precision not null check (calibrated_moisture_pct between 0 and 100),
  quality                  text not null check (quality in ('valid', 'suspect')),
  reality_gap              jsonb not null,
  created_at               timestamptz not null default now(),
  unique (plot_id, device_id, sequence)
);
create index if not exists sensor_readings_plot_time_idx on sensor_readings (plot_id, timestamp desc);
create index if not exists sensor_readings_device_time_idx on sensor_readings (device_id, timestamp desc);
alter table sensor_readings enable row level security;


-- ============ WhatsApp / SMS channels ============
create table if not exists channel_links (        -- one row per phone (local format 01XXXXXXXXX): account link + chat state
  phone      text primary key,
  user_id    text,                                 -- null = not linked to an account (advisor still works)
  state      jsonb not null,
  updated_at timestamptz not null default now()
);
create index if not exists channel_links_user_idx on channel_links (user_id);

create table if not exists channel_link_codes (   -- one-time 6-digit codes, valid 10 minutes
  code       text primary key,
  user_id    text not null,
  expires_at timestamptz not null
);

alter table channel_links      enable row level security;
alter table channel_link_codes enable row level security;
