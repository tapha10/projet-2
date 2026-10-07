-- 011 — Portefeuille « S » : stratégie INVERSE (short) en DÉMO uniquement (GUARDRAILS section 11).
-- Table séparée : `positions` reste long uniquement. Aucun ordre réel, aucune clé.
-- Alimenté par `python3 -m engine.inverse run`.

create table if not exists public.inverse_positions (
  id bigserial primary key,
  signal_id bigint not null unique,
  source_position_ids bigint[] not null default '{}',
  pair text not null,
  side text not null default 'short' check (side = 'short'),
  opened_at timestamptz not null,
  entry_price numeric not null check (entry_price > 0),
  size_usd numeric not null check (size_usd > 0),
  leverage numeric not null check (leverage >= 1 and leverage <= 2),
  stop_price numeric not null,
  initial_stop_price numeric not null,
  tp_price numeric not null,
  trailing_active boolean not null default false,
  max_hold_until timestamptz not null,
  status text not null default 'open' check (status in ('open','closed')),
  closed_at timestamptz,
  exit_price numeric,
  exit_reason text check (exit_reason in ('tp','sl','trailing','time')),
  pnl_usd numeric,
  pnl_pct numeric,
  r_multiple numeric,
  fees_usd numeric,
  funding_usd numeric,
  mfe_pct numeric,
  mae_pct numeric,
  lowest_price numeric,
  highest_price numeric,
  sim_through_at timestamptz,
  last_checked_at timestamptz,
  created_at timestamptz not null default now(),
  check (tp_price < entry_price and entry_price < initial_stop_price)  -- short : objectif < entrée < stop
);
create index if not exists inverse_positions_status_idx on public.inverse_positions(status);
alter table public.inverse_positions enable row level security;

-- Garde-fou : entrée figée, stop jamais élargi (il ne peut que baisser), pas de réouverture.
create or replace function public.inverse_guardrails_update() returns trigger
language plpgsql set search_path = '' as $fn$
begin
  if new.entry_price <> old.entry_price or new.size_usd <> old.size_usd
     or new.leverage <> old.leverage or new.pair <> old.pair or new.signal_id <> old.signal_id
     or new.initial_stop_price <> old.initial_stop_price then
    raise exception 'GUARDRAIL: parametres d entree figes (position inverse)';
  end if;
  if new.stop_price > old.stop_price then
    raise exception 'GUARDRAIL: le stop d un short ne peut pas etre elargi';
  end if;
  if old.status = 'closed' and new.status = 'open' then
    raise exception 'GUARDRAIL: une position fermee ne se rouvre pas';
  end if;
  return new;
end $fn$;
drop trigger if exists inverse_guardrails_update on public.inverse_positions;
create trigger inverse_guardrails_update before update on public.inverse_positions
  for each row execute function public.inverse_guardrails_update();

-- Paramètres modifiables plus tard (nouvelles entrées seulement) : un UPDATE sur cette ligne suffit.
-- tp_trail_pct : null = sortie fixe au TP ; sinon, au TP le short continue avec un stop suiveur
-- à cette distance au-dessus du plus bas (le TP est « augmenté »).
insert into public.config(key, value) values
  ('inverse_params', '{"stop_pct":0.30,"tp_pct":0.10,"hold_days":7,"leverage":2,"risk_pct":0.01,"tp_trail_pct":null,"max_open":8,"max_per_day":3,"drawdown_halt":0.15,"capital":1000}'::jsonb)
on conflict (key) do nothing;

-- État pour le moteur : un signal source par entrée longue (A, B, C, T) + les positions inverses.
create or replace function public.inverse_state() returns jsonb
language sql stable set search_path = '' as $$
  select jsonb_build_object(
    'now', now(),
    'params', (select value from public.config where key = 'inverse_params'),
    'prev', (select value from public.config where key = 'inverse_params_prev'),
    'sources', coalesce((
      select jsonb_agg(to_jsonb(s) order by s.opened_at)
      from (
        select p.signal_id, min(p.pair) as pair, min(p.opened_at) as opened_at,
               (array_agg(p.entry_price order by p.id))[1] as entry_price,
               array_agg(p.id order by p.id) as position_ids,
               array_agg(distinct p.arm) as arms
        from public.positions p
        where p.signal_id is not null and p.arm in ('A','B','C','T')
        group by p.signal_id
      ) s), '[]'::jsonb),
    'inverse', coalesce((select jsonb_agg(to_jsonb(i) order by i.opened_at, i.id)
                         from public.inverse_positions i), '[]'::jsonb));
$$;
