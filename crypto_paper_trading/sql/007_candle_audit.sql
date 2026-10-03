-- 007 : audit du suivi bougie par bougie (idempotent).
-- sim_through_at = fin de la dernière bougie fermée déjà simulée : la vérification suivante
-- repart exactement de là (aucune bougie relue, aucune bougie sautée).
alter table public.positions add column if not exists sim_through_at timestamptz;
comment on column public.positions.sim_through_at is
  'Fin de la dernière bougie fermée déjà simulée (chaque bougie est traitée une seule fois).';

-- Frais alignés sur Bybit (perp USDT, compte standard) : 0,055 % preneur par côté,
-- appliqué aussi aux sorties à l'objectif (hypothèse prudente : pas de remise faiseur).
update public.config set value = '0.00055'::jsonb, updated_at = now()
 where key = 'fee_rate_per_side' and value <> '0.00055'::jsonb;

insert into public.iteration_log(routine, change, rationale, evidence)
select 'maintenance',
       '{"action":"audit_bougies","fee_rate_per_side":{"avant":0.0005,"apres":0.00055},"sim_through_at":"ajouté"}'::jsonb,
       'Audit du suivi : bougies traitées une seule fois, ordre stop/objectif tranché en 1 min, funding réel, frais Bybit.',
       '{"source":"https://www.bybit.com/en/help-center/article/Trading-Fee-Structure","date":"2026-10-03"}'::jsonb
 where not exists (select 1 from public.iteration_log where change->>'action' = 'audit_bougies');
