-- Données de départ : configuration et les trois bras (statut challenger).
revoke all on function paper_hard_limits(), paper_cfg(text), paper_equity(text),
  paper_peak_equity(text), paper_drawdown(text) from public, anon, authenticated;

insert into config(key, value) values
  ('mode',                             '"paper"'),
  ('initial_capital_usdt',             '1000'),
  ('risk_pct',                         '0.01'),
  ('max_leverage',                     '10'),
  ('max_open_positions_per_arm',       '8'),
  ('max_new_entries_per_day_per_arm',  '3'),
  ('drawdown_halt_pct',                '0.15'),
  ('fee_rate_per_side',                '0.0005'),
  ('funding_rate_8h_estimate',         '0.0001'),
  ('maintenance_margin_rate',          '0.01'),
  ('liquidation_buffer_pct',           '0.02'),
  ('report_email',                     '"moustaphatall38@gmail.com"'),
  ('timezone',                         '"Europe/Paris"'),
  ('data_sources',                     '["gate","okx","mexc","kucoin"]'),
  ('entry_rules', '{
     "version": 1,
     "signal_candle_max_change": 0.15,
     "wait_min_days": 1,
     "wait_max_days": 2,
     "vol_ratio_min": 2.0,
     "max_drop_from_signal_close": 0.15,
     "unlock_max_supply_pct": 0.005,
     "unlock_window_days": 7,
     "min_score_enter": 3.0,
     "min_quote_volume_24h": 2000000,
     "max_candidates_per_scan": 15
   }'),
  ('signal_weights', '{
     "version": 1,
     "dated_announcement": 2.0,
     "listing_or_perp": 2.0,
     "volume_doubling": 1.5,
     "oi_rising": 1.0,
     "revenue_or_buyback": 1.0,
     "oversold_or_breakout": 1.0,
     "top_gainer_24h": 0.5,
     "alert_team_transfer": -3.0,
     "alert_unlock_7d": -3.0,
     "alert_peak_passed": -2.0
   }');

insert into strategy_versions(name, arm, status, params, rationale) values
 ('A-reference-v1', 'A', 'challenger', '{
    "stop": {"type": "fixed_pct", "pct": 0.25},
    "tp": {"type": "fixed_pct", "pct": 0.40},
    "max_leverage": 2,
    "max_hold_days": 10,
    "breakeven_trigger_pct": null,
    "trailing": null
  }', 'Bras de référence : stop large 25 %, objectif +40 %, levier 2x max. Rapport gain/perte 1,6 (équilibre à 39 % de réussite).'),
 ('B-stop-serre-v1', 'B', 'challenger', '{
    "stop": {"type": "fixed_pct", "pct": 0.12},
    "tp": {"type": "fixed_pct", "pct": 0.40},
    "max_leverage": 10,
    "max_hold_days": 10,
    "breakeven_trigger_pct": 0.15,
    "trailing": null
  }', 'Stop serré 12 %, objectif +40 %, stop à l''équilibre dès +15 %. Rapport 3,3 (équilibre à 23 %), mais plus exposé au bruit.'),
 ('C-adaptatif-v1', 'C', 'challenger', '{
    "stop": {"type": "atr", "mult": 1.5, "period": 14, "min_pct": 0.10, "max_pct": 0.25},
    "tp": {"type": "r_multiple", "r": 2.5},
    "max_leverage": 10,
    "max_hold_days": 10,
    "breakeven_trigger_pct": null,
    "trailing": {"activate_pct": 0.20, "distance": "stop_distance"}
  }', 'Stop 1,5 x ATR(14) journalier borné 10-25 %, objectif 2,5 x la distance du stop, stop suiveur après +20 %.');

insert into iteration_log(routine, change, rationale, evidence) values
 ('setup', '{"action": "init", "arms": ["A","B","C"], "capital": 1000}',
  'Initialisation du système de démo (hypothèses de départ issues de 4 cas manuels, non validées).',
  '{"source": "étude manuelle VELVET x2, PUMP, COTI"}');
