-- Farmedia database schema v2 for Supabase (PostgreSQL). Fresh install: run once in the SQL editor.
--
-- Principles
--   * Passwords live only in Supabase auth.users (hashed). Nothing here stores them.
--   * Row Level Security (RLS) is ON for every table. Users see and change only their own rows.
--   * Legal documents are versioned. Sign-up is refused unless the accepted versions are the
--     CURRENT published ones, so nobody can accept outdated text.
--   * The jurisdiction (KVKK / GDPR / CCPA / other) is derived from the country by the
--     database itself, not taken from the client, so required consents cannot be skipped.
--   * Every consent given, changed or withdrawn is appended to consent_log (audit trail).

-- ---------------------------------------------------------------------------
-- Legal documents: versioned Terms of Service and Privacy Policy per language.
-- Exactly one version per (doc_type, locale) should have is_current = true.
-- Text itself is hosted at `url`; this table only tracks versions.
-- ---------------------------------------------------------------------------
create table if not exists public.legal_documents (
  id           bigint generated always as identity primary key,
  doc_type     text not null check (doc_type in ('terms', 'privacy')),
  locale       text not null check (locale in ('tr', 'en')),
  version      text not null,
  url          text not null,
  is_current   boolean not null default false,
  published_at timestamptz not null default now(),
  unique (doc_type, locale, version)
);
create unique index if not exists legal_documents_one_current
  on public.legal_documents (doc_type, locale) where is_current;

-- ---------------------------------------------------------------------------
-- Profiles: one row per user, created by the sign-up trigger.
-- ---------------------------------------------------------------------------
create table if not exists public.profiles (
  id                       uuid primary key references auth.users (id) on delete cascade,
  email                    text not null,
  first_name               text not null default '',
  last_name                text not null default '',
  role                     text not null default 'hobby' check (role in ('hobby', 'farm')),
  farm_size                numeric check (farm_size is null or farm_size >= 0),
  location                 jsonb not null default '{}'::jsonb,
  crops                    jsonb not null default '{}'::jsonb,
  -- UI preferences synced across devices: theme, density, forecastDays. Small, validated in the
  -- update function below.
  preferences              jsonb not null default '{}'::jsonb,

  -- Region (fixed at sign-up)
  country                  char(2) not null,
  jurisdiction             text not null check (jurisdiction in ('kvkk', 'gdpr', 'ccpa', 'global')),
  locale                   text not null default 'en' check (locale in ('tr', 'en')),

  -- Required legal acceptances (fixed at sign-up)
  terms_version            text not null,
  terms_accepted_at        timestamptz not null,
  privacy_version          text not null,
  privacy_accepted_at      timestamptz not null,
  kvkk_explicit_at         timestamptz,   -- KVKK explicit consent (Turkey only)
  kvkk_transfer_at         timestamptz,   -- KVKK cross-border transfer consent (Turkey only)

  -- Optional, changeable consents
  alert_email_consent      boolean not null default false,
  alert_sms_consent        boolean not null default false,
  marketing_email_consent  boolean not null default false,
  alert_consent_updated_at timestamptz,

  -- CCPA: true = the user opted out of the sale/sharing of their personal information
  do_not_sell              boolean not null default false,

  created_at               timestamptz not null default now(),
  updated_at               timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Consent log: append-only audit trail.
-- ---------------------------------------------------------------------------
create table if not exists public.consent_log (
  id           bigint generated always as identity primary key,
  -- Set to NULL when the account is deleted (never cascaded): the consent record is kept as an
  -- anonymous proof of consent (GDPR Art. 7(1), KVKK audit), but it is no longer linked to a person.
  user_id      uuid references auth.users (id) on delete set null,
  consent_type text not null check (consent_type in (
    'terms', 'privacy_policy', 'kvkk_explicit', 'kvkk_transfer',
    'alert_email', 'alert_sms', 'marketing_email', 'do_not_sell')),
  granted      boolean not null,
  version      text,
  recorded_at  timestamptz not null default now(),
  -- Set when the account is deleted. After this date the row may be purged (see retention note below).
  retention_until timestamptz
);
create index if not exists consent_log_user_idx on public.consent_log (user_id, recorded_at desc);

-- ---------------------------------------------------------------------------
-- Row Level Security
-- ---------------------------------------------------------------------------
alter table public.legal_documents enable row level security;
alter table public.profiles        enable row level security;
alter table public.consent_log     enable row level security;

-- Legal documents are public (shown before sign-up). Only the SQL editor (owner) can change them.
drop policy if exists legal_documents_read on public.legal_documents;
create policy legal_documents_read on public.legal_documents
  for select to anon, authenticated using (true);

-- Profiles: read and update own row only. No client insert (trigger) and no delete.
drop policy if exists profiles_select_own on public.profiles;
create policy profiles_select_own on public.profiles
  for select to authenticated using (auth.uid() = id);

drop policy if exists profiles_update_own on public.profiles;
create policy profiles_update_own on public.profiles
  for update to authenticated using (auth.uid() = id) with check (auth.uid() = id);

-- Consent log: read and add own entries. No UPDATE/DELETE policy, so entries are immutable.
drop policy if exists consent_log_select_own on public.consent_log;
create policy consent_log_select_own on public.consent_log
  for select to authenticated using (auth.uid() = user_id);

drop policy if exists consent_log_insert_own on public.consent_log;
create policy consent_log_insert_own on public.consent_log
  for insert to authenticated with check (auth.uid() = user_id);

-- ---------------------------------------------------------------------------
-- Jurisdiction from country. Mirrors services/compliance.py; keep both in sync.
-- ---------------------------------------------------------------------------
create or replace function public.jurisdiction_for(c text)
returns text
language sql
immutable
as $$
  select case
    when upper(c) = 'TR' then 'kvkk'
    when upper(c) in ('AT','BE','BG','HR','CY','CZ','DK','EE','FI','FR','DE','GR','HU','IE',
                      'IT','LV','LT','LU','MT','NL','PL','PT','RO','SK','SI','ES','SE',
                      'IS','LI','NO','GB') then 'gdpr'
    when upper(c) = 'US' then 'ccpa'
    else 'global'
  end
$$;

-- ---------------------------------------------------------------------------
-- Protect identity, region and sign-up consent fields; keep updated_at current.
-- ---------------------------------------------------------------------------
create or replace function public.protect_profile_fields()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  if new.id                  <> old.id
     or new.email            <> old.email
     or new.country          <> old.country
     or new.jurisdiction     <> old.jurisdiction
     or new.terms_version    <> old.terms_version
     or new.terms_accepted_at   <> old.terms_accepted_at
     or new.privacy_version  <> old.privacy_version
     or new.privacy_accepted_at <> old.privacy_accepted_at
     or new.kvkk_explicit_at    is distinct from old.kvkk_explicit_at
     or new.kvkk_transfer_at    is distinct from old.kvkk_transfer_at then
    raise exception 'Protected profile field cannot be changed';
  end if;
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists profiles_protect on public.profiles;
create trigger profiles_protect
  before update on public.profiles
  for each row execute function public.protect_profile_fields();

-- ---------------------------------------------------------------------------
-- Sign-up: validate consents against the DB's own rules, then create profile + log.
-- Runs as the owner (security definer) so it can write rows RLS would block.
-- ---------------------------------------------------------------------------
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  m            jsonb := coalesce(new.raw_user_meta_data, '{}'::jsonb);
  c            text  := upper(coalesce(m ->> 'country', ''));
  loc          text  := case when m ->> 'locale' = 'tr' then 'tr' else 'en' end;
  j            text  := public.jurisdiction_for(c);
  terms_v      text  := m ->> 'terms_version';
  privacy_v    text  := m ->> 'privacy_version';
  kvkk_ok      boolean := coalesce((m ->> 'kvkk_explicit')::boolean, false);
  transfer_ok  boolean := coalesce((m ->> 'kvkk_transfer')::boolean, false);
  alert_e      boolean := coalesce((m ->> 'alert_email')::boolean, false);
  alert_s      boolean := coalesce((m ->> 'alert_sms')::boolean, false);
  marketing    boolean := coalesce((m ->> 'marketing_email')::boolean, false);
  do_not_sell  boolean := coalesce((m ->> 'do_not_sell')::boolean, false);
  now_ts       timestamptz := now();
begin
  if length(c) <> 2 then
    raise exception 'A valid country code is required';
  end if;
  if coalesce((m ->> 'terms_accepted')::boolean, false) is not true
     or coalesce((m ->> 'privacy_accepted')::boolean, false) is not true then
    raise exception 'Terms of Service and Privacy Policy must be accepted';
  end if;
  if not exists (select 1 from public.legal_documents
                 where doc_type = 'terms' and locale = loc and version = terms_v and is_current)
     or not exists (select 1 from public.legal_documents
                 where doc_type = 'privacy' and locale = loc and version = privacy_v and is_current) then
    raise exception 'Accepted document versions are not the current published versions';
  end if;
  if j = 'kvkk' and (not kvkk_ok or not transfer_ok) then
    raise exception 'KVKK explicit consent and cross-border transfer consent are required in Turkey';
  end if;

  insert into public.profiles (
    id, email, first_name, last_name, country, jurisdiction, locale,
    terms_version, terms_accepted_at, privacy_version, privacy_accepted_at,
    kvkk_explicit_at, kvkk_transfer_at,
    alert_email_consent, alert_sms_consent, marketing_email_consent,
    alert_consent_updated_at, do_not_sell
  ) values (
    new.id, new.email,
    coalesce(m ->> 'first_name', ''), coalesce(m ->> 'last_name', ''),
    c, j, loc,
    terms_v, now_ts, privacy_v, now_ts,
    case when j = 'kvkk' then now_ts end,
    case when j = 'kvkk' then now_ts end,
    alert_e, alert_s, marketing, now_ts, do_not_sell
  );

  insert into public.consent_log (user_id, consent_type, granted, version) values
    (new.id, 'terms',           true,        terms_v),
    (new.id, 'privacy_policy',  true,        privacy_v),
    (new.id, 'alert_email',     alert_e,     null),
    (new.id, 'alert_sms',       alert_s,     null),
    (new.id, 'marketing_email', marketing,   null),
    (new.id, 'do_not_sell',     do_not_sell, null);
  if j = 'kvkk' then
    insert into public.consent_log (user_id, consent_type, granted, version) values
      (new.id, 'kvkk_explicit', true, privacy_v),
      (new.id, 'kvkk_transfer', true, privacy_v);
  end if;

  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ---------------------------------------------------------------------------
-- Profile update with consent logging, in ONE transaction.
-- Called through PostgREST: POST /rest/v1/rpc/update_profile_with_consents {"p_changes": {...}}.
-- SECURITY INVOKER: it runs as the signed-in user, so RLS on profiles and consent_log applies.
-- Every change to an optional consent is appended to consent_log in the same transaction as
-- the profile write. If either write fails, both are rolled back.
-- ---------------------------------------------------------------------------
create or replace function public.update_profile_with_consents(p_changes jsonb)
returns jsonb
language plpgsql
security invoker
set search_path = public
as $$
declare
  editable_cols  text[] := array['first_name', 'last_name', 'role', 'farm_size', 'location', 'crops', 'preferences'];
  consent_cols   text[] := array['alert_email_consent', 'alert_sms_consent',
                                 'marketing_email_consent', 'do_not_sell'];
  consent_types  text[] := array['alert_email', 'alert_sms', 'marketing_email', 'do_not_sell'];
  uid            uuid := auth.uid();
  cur            public.profiles%rowtype;
  unknown        text;
  new_val        boolean;
  any_consent    boolean := false;
  i              int;
  result         jsonb;
begin
  if p_changes is null or jsonb_typeof(p_changes) <> 'object' then
    raise exception 'Request body must be a JSON object';
  end if;
  if p_changes = '{}'::jsonb then
    raise exception 'No fields to update.';
  end if;

  if p_changes ? 'preferences' then
    if jsonb_typeof(p_changes -> 'preferences') <> 'object' or length((p_changes -> 'preferences')::text) > 1000 then
      raise exception 'preferences must be a small JSON object';
    end if;
  end if;

  select string_agg(k, ', ' order by k) into unknown
    from jsonb_object_keys(p_changes) as k
   where k <> all (editable_cols || consent_cols);
  if unknown is not null then
    raise exception 'Field(s) cannot be updated: %', unknown;
  end if;

  -- Lock the row so two concurrent updates cannot both see the same "before" state.
  select * into cur from public.profiles where id = uid for update;
  if not found then
    raise exception 'Profile not found';
  end if;

  -- Consent fields: strict boolean check, then log only real changes.
  for i in 1 .. array_length(consent_cols, 1) loop
    if p_changes ? consent_cols[i] then
      if jsonb_typeof(p_changes -> consent_cols[i]) <> 'boolean' then
        raise exception '% must be true or false.', consent_cols[i];
      end if;
      new_val := (p_changes ->> consent_cols[i])::boolean;
      if new_val is distinct from (to_jsonb(cur) ->> consent_cols[i])::boolean then
        insert into public.consent_log (user_id, consent_type, granted, version)
          values (uid, consent_types[i], new_val, null);
        any_consent := true;
      end if;
    end if;
  end loop;

  update public.profiles set
    first_name = coalesce(p_changes ->> 'first_name', first_name),
    last_name  = coalesce(p_changes ->> 'last_name', last_name),
    role       = coalesce(p_changes ->> 'role', role),
    farm_size  = coalesce((p_changes ->> 'farm_size')::numeric, farm_size),
    location   = coalesce(p_changes -> 'location', location),
    crops      = coalesce(p_changes -> 'crops', crops),
    preferences = coalesce(p_changes -> 'preferences', preferences),
    alert_email_consent      = coalesce((p_changes ->> 'alert_email_consent')::boolean, alert_email_consent),
    alert_sms_consent        = coalesce((p_changes ->> 'alert_sms_consent')::boolean, alert_sms_consent),
    marketing_email_consent  = coalesce((p_changes ->> 'marketing_email_consent')::boolean, marketing_email_consent),
    do_not_sell              = coalesce((p_changes ->> 'do_not_sell')::boolean, do_not_sell),
    alert_consent_updated_at = case when any_consent then now() else alert_consent_updated_at end
  where id = uid
  returning to_jsonb(profiles.*) into result;

  return result;
end;
$$;

-- Only signed-in users may call it (anon gets no access at all).
revoke all on function public.update_profile_with_consents(jsonb) from public;
revoke all on function public.update_profile_with_consents(jsonb) from anon;
grant execute on function public.update_profile_with_consents(jsonb) to authenticated;

-- ---------------------------------------------------------------------------
-- Migration for databases created before Phase 2 (idempotent; safe to re-run).
-- ---------------------------------------------------------------------------
alter table public.consent_log alter column user_id drop not null;
alter table public.consent_log drop constraint if exists consent_log_user_id_fkey;
alter table public.consent_log add constraint consent_log_user_id_fkey
  foreign key (user_id) references auth.users (id) on delete set null;
alter table public.consent_log add column if not exists retention_until timestamptz;
alter table public.profiles add column if not exists preferences jsonb not null default '{}'::jsonb;

-- ---------------------------------------------------------------------------
-- Table privileges. RLS decides which rows a role sees, but the role still needs the privilege.
-- In the project this schema was tested on, anon got "permission denied for table legal_documents",
-- so the grants are explicit here. Nothing is granted to anon except public legal documents.
-- ---------------------------------------------------------------------------
grant select on public.legal_documents to anon, authenticated;
grant select, update on public.profiles to authenticated;
grant select, insert on public.consent_log to authenticated;

-- ---------------------------------------------------------------------------
-- Account deletion (GDPR Art. 17, CCPA deletion right, KVKK Art. 11).
-- SECURITY DEFINER, so it can delete from auth.users. It only ever acts on auth.uid(),
-- i.e. the caller's own account. The service_role key is not needed.
--
-- Retention decision (Phase 1.3):
--   * profiles: deleted (cascade from auth.users). Personal data is erased.
--   * consent_log: kept for 3 years after deletion as anonymous proof of consent
--     (user_id set to NULL, retention_until set). After retention_until the rows should be
--     purged. THE 3-YEAR PERIOD IS A PLACEHOLDER: counsel must confirm it per regime.
--     The purge job is not implemented yet.
--   * Deletion of auth.users also revokes all of the user's sessions.
-- ---------------------------------------------------------------------------
create or replace function public.delete_own_account()
returns void
language plpgsql
security definer
set search_path = public, auth
as $$
declare
  uid uuid := auth.uid();
begin
  if uid is null then
    raise exception 'Sign in required';
  end if;

  update public.consent_log
     set user_id = null,
         retention_until = now() + interval '3 years'
   where user_id = uid;

  -- Cascades to public.profiles. Removes the login and revokes all sessions.
  delete from auth.users where id = uid;
end;
$$;

revoke all on function public.delete_own_account() from public;
revoke all on function public.delete_own_account() from anon;
grant execute on function public.delete_own_account() to authenticated;
