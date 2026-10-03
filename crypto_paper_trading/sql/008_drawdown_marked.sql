-- 008 : drawdown sur capital réalisé + latent (relecture de GUARDRAILS.md du 03/10/2026).
-- Idempotent. La taille des positions reste calculée sur le capital réalisé (paper_equity).
--
-- Le latent de chaque position ouverte est « marqué » par le moteur à chaque vérification
-- (routine 2) et juste avant chaque décision d'entrée (routines 1 et 1b). Seules les marques
-- des positions encore ouvertes comptent : une position fermée sort du latent et entre dans
-- le réalisé, sans double compte.

create table if not exists public.arm_marks (
  arm text primary key,
  marked_at timestamptz not null default now(),
  positions jsonb not null default '{}'::jsonb,   -- {id_position: pnl latent en USDT}
  peak_equity numeric                              -- plus haut du capital marqué (réalisé + latent)
);
alter table public.arm_marks enable row level security;

-- Latent d'un bras = somme des marques des positions encore ouvertes.
create or replace function public.paper_unrealized(p_arm text) returns numeric
language sql stable set search_path = '' as $$
  select coalesce(sum(m.value::numeric), 0)
    from public.arm_marks am
    cross join lateral jsonb_each_text(am.positions) m
    join public.positions p on p.id = m.key::bigint and p.status = 'open'
   where am.arm = p_arm;
$$;

-- Plus haut : le plus élevé du capital réalisé et du capital marqué.
create or replace function public.paper_peak_equity(p_arm text) returns numeric
language sql stable set search_path = '' as $$
  with c as (select (public.paper_cfg('initial_capital_usdt')#>>'{}')::numeric as cap),
  eq as (
    select c.cap + sum(p.pnl_usd) over (order by p.closed_at, p.id) as e
    from public.positions p, c
    where p.arm = p_arm and p.status = 'closed'
  )
  select greatest((select cap from c), coalesce((select max(e) from eq), 0),
                  coalesce((select peak_equity from public.arm_marks where arm = p_arm), 0));
$$;

-- Drawdown = recul du capital réalisé + latent depuis le plus haut (GUARDRAILS section 4).
create or replace function public.paper_drawdown(p_arm text) returns numeric
language sql stable set search_path = '' as $$
  select 1 - (public.paper_equity(p_arm) + public.paper_unrealized(p_arm))
             / nullif(public.paper_peak_equity(p_arm), 0);
$$;

-- Enregistre les marques : p = {"A": {"12": -3.5, ...}, "B": {...}, ...}.
-- Fusion : une position absente de p (prix indisponible) garde sa dernière marque ;
-- les identifiants qui ne sont pas des positions ouvertes du bras sont ignorés.
create or replace function public.paper_set_marks(p jsonb) returns jsonb
language plpgsql set search_path = '' as $$
declare
  a text;
  pos jsonb;
  eq numeric;
begin
  foreach a in array array['A','B','C','T'] loop
    select coalesce(jsonb_object_agg(m.key, round(m.value::numeric, 4)), '{}'::jsonb) into pos
      from jsonb_each_text(coalesce((select positions from public.arm_marks where arm = a), '{}'::jsonb)
                           || coalesce(p->a, '{}'::jsonb)) m
      join public.positions x on x.id = m.key::bigint and x.arm = a and x.status = 'open';
    insert into public.arm_marks(arm, marked_at, positions) values (a, now(), pos)
      on conflict (arm) do update set marked_at = now(), positions = excluded.positions;
    eq := public.paper_equity(a) + public.paper_unrealized(a);
    update public.arm_marks set peak_equity = greatest(coalesce(peak_equity, 0), eq) where arm = a;
  end loop;
  return (select jsonb_object_agg(arm, jsonb_build_object(
            'unrealized', round(public.paper_unrealized(arm), 2),
            'drawdown', round(public.paper_drawdown(arm), 4)))
            from public.arm_marks);
end;
$$;

revoke all on function public.paper_unrealized(text), public.paper_set_marks(jsonb),
  public.paper_peak_equity(text), public.paper_drawdown(text)
  from public, anon, authenticated;

insert into public.iteration_log(routine, change, rationale, evidence)
select 'maintenance',
       '{"action":"drawdown_realise_plus_latent","guardrails":"section 4"}'::jsonb,
       'Relecture de GUARDRAILS.md avec le propriétaire (03/10/2026) : l''arrêt des entrées à -15 % compte aussi le PnL latent des positions ouvertes.',
       '{"decision":"propriétaire, 03/10/2026"}'::jsonb
 where not exists (select 1 from public.iteration_log where change->>'action' = 'drawdown_realise_plus_latent');

-- Début de la démo : sert au seuil de passage (GUARDRAILS section 1 bis, 12 semaines minimum).
insert into public.config(key, value) values ('demo_started_at', '"2026-10-03T00:00:00+00:00"'::jsonb)
  on conflict (key) do nothing;
