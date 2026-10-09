import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  STATISTICS, getStatisticForMarket, getPlayerStatistic, sortPlayers,
  filterPlayersByStatistic, formatStatistic, getPlayerWorkload,
} from '../src/lib/player-research.js';

const player = (id, stats, overrides = {}) => ({ id, name: id, sample_games: 4, stats, ...overrides });
const ids = (players) => players.map((item) => item.id);

test('numeric sorting handles double-digit production and preserves its input', () => {
  const players = [player('Nine', { receiving_yards: 9 }), player('Hundred', { receiving_yards: 100 }), player('Twenty', { receiving_yards: 20 })];
  assert.deepEqual(ids(sortPlayers(players, 'receiving_yards')), ['Hundred', 'Twenty', 'Nine']);
  assert.deepEqual(ids(sortPlayers(players, 'receiving_yards', 'asc')), ['Nine', 'Twenty', 'Hundred']);
  assert.deepEqual(ids(players), ['Nine', 'Hundred', 'Twenty']);
});

test('known zeros and negative yards sort numerically while missing values remain last', () => {
  const players = [player('No stats', null), player('Missing', {}), player('Zero', { rushing_yards: 0 }), player('Loss', { rushing_yards: -7 }), player('Gain', { rushing_yards: 12 })];
  assert.deepEqual(ids(sortPlayers(players, 'rushing_yards')), ['Gain', 'Zero', 'Loss', 'Missing', 'No stats']);
  assert.deepEqual(ids(sortPlayers(players, 'rushing_yards', 'asc')), ['Loss', 'Zero', 'Gain', 'Missing', 'No stats']);
});

test('ties have deterministic name and id ordering independent of sort direction or input', () => {
  const players = [player('3', { receptions: 7 }, { name: 'Beta' }), player('2', { receptions: 7 }, { name: 'Alpha' }), player('1', { receptions: 7 }, { name: 'Alpha' })];
  assert.deepEqual(ids(sortPlayers(players, 'receptions')), ['1', '2', '3']);
  assert.deepEqual(ids(sortPlayers([...players].reverse(), 'receptions', 'asc')), ['1', '2', '3']);
});

test('a receiving sort remains independent of passing production and market data', () => {
  const passer = player('Passer', { passing_yards: 1400, receiving_yards: 0 });
  const receiver = player('Receiver', { passing_yards: 0, receiving_yards: 250 });
  assert.deepEqual(ids(sortPlayers([passer, receiver], 'receiving_yards')), ['Receiver', 'Passer']);
  assert.deepEqual(ids(sortPlayers([passer, receiver], 'passing_yards')), ['Passer', 'Receiver']);
});

test('combined rush and receiving totals require both actual numeric components', () => {
  const complete = player('Complete', { rushing_yards: -2, receiving_yards: 27, rushing_tds: 0, receiving_tds: 3, passing_tds: 99 });
  assert.equal(getPlayerStatistic(complete, 'rush_receiving_yards'), 25);
  assert.equal(getPlayerStatistic(complete, 'rush_receiving_tds'), 3);
  assert.equal(getPlayerStatistic(player('Zero', { rushing_yards: 0, receiving_yards: 0 }), 'rush_receiving_yards'), 0);
  for (const stats of [{ rushing_yards: 20 }, { receiving_yards: 30 }, { rushing_yards: null, receiving_yards: 30 }, { rushing_yards: 0, receiving_yards: '' }]) {
    assert.equal(getPlayerStatistic(player('Incomplete', stats), 'rush_receiving_yards'), null);
  }
});

test('empty, malformed, non-finite and boolean statistics remain unknown', () => {
  for (const value of [null, undefined, '', '0', false, true, NaN, Infinity, -Infinity]) {
    assert.equal(getPlayerStatistic(player('Invalid', { receiving_yards: value }), 'receiving_yards'), null);
  }
  assert.equal(getPlayerStatistic(player('Known', { receiving_yards: 0 }), 'receiving_yards'), 0);
  assert.equal(getPlayerStatistic(player('Unknown key', { arbitrary: 500 }), 'arbitrary'), null);
});

test('per-game values use the actual positive sample and never fall back to a season week or stats.games', () => {
  const a = player('A', { receiving_yards: 300, games: 4 }, { sample_games: 2 });
  const b = player('B', { receiving_yards: 400, games: 9 }, { sample_games: 4 });
  assert.equal(getPlayerStatistic(a, 'receiving_yards', 'perGame'), 150);
  assert.equal(getPlayerStatistic(a, 'receiving_yards', 'per_game'), 150);
  assert.deepEqual(ids(sortPlayers([a, b], 'receiving_yards', 'desc', 'perGame')), ['A', 'B']);
  assert.deepEqual(ids(sortPlayers([a, b], 'receiving_yards')), ['B', 'A']);
  for (const sample of [0, -1, null, undefined, '', '4', true, NaN, Infinity]) {
    assert.equal(getPlayerStatistic(player('Bad sample', { receiving_yards: 300, games: 4 }, { sample_games: sample }), 'receiving_yards', 'perGame'), null);
  }
  assert.equal(getPlayerStatistic(a, 'receiving_yards', 'projection'), null);
});

test('per-game sorting keeps invalid sample rows after known zero rows in both directions', () => {
  const players = [player('Missing sample', { receiving_yards: 900 }, { sample_games: 0 }), player('Zero', { receiving_yards: 0 }), player('Known', { receiving_yards: 120 })];
  assert.deepEqual(ids(sortPlayers(players, 'receiving_yards', 'desc', 'perGame')), ['Known', 'Zero', 'Missing sample']);
  assert.deepEqual(ids(sortPlayers(players, 'receiving_yards', 'asc', 'perGame')), ['Zero', 'Known', 'Missing sample']);
});

test('empty thresholds do not filter while zero thresholds include known zeros and exclude missing values', () => {
  const players = [player('Unknown', null), player('Zero', { receiving_yards: 0 }), player('Loss', { receiving_yards: -3 }), player('Gain', { receiving_yards: 20 })];
  assert.deepEqual(ids(filterPlayersByStatistic(players, 'receiving_yards')), ids(players));
  assert.deepEqual(ids(filterPlayersByStatistic(players, 'receiving_yards', { minimum: ' ' })), ids(players));
  assert.deepEqual(ids(filterPlayersByStatistic(players, 'receiving_yards', { minimum: '0' })), ['Zero', 'Gain']);
  assert.deepEqual(ids(filterPlayersByStatistic(players, 'receiving_yards', { minimum: -3 })), ['Zero', 'Loss', 'Gain']);
  assert.deepEqual(ids(filterPlayersByStatistic(players, 'receiving_yards', { minimum: '20' })), ['Gain']);
});

test('thresholds apply to the selected per-game value with inclusive boundary', () => {
  const players = [player('Two games', { receiving_yards: 200 }, { sample_games: 2 }), player('Four games', { receiving_yards: 300 }), player('Missing sample', { receiving_yards: 500 }, { sample_games: 0 })];
  assert.deepEqual(ids(filterPlayersByStatistic(players, 'receiving_yards', { basis: 'perGame', minimum: '100' })), ['Two games']);
});

test('recorded-statistic filtering retains negative and zero production without inventing activity', () => {
  const players = [player('Unknown', {}), player('Zero', { rushing_yards: 0 }), player('Loss', { rushing_yards: -3 })];
  assert.deepEqual(ids(filterPlayersByStatistic(players, 'rushing_yards', { requireRecorded: true })), ['Zero', 'Loss']);
  assert.deepEqual(ids(filterPlayersByStatistic(players, 'rushing_yards', { requireActivity: true })), []);
});

test('activity uses relevant workload and retains zero and negative yards from actual opportunities', () => {
  const players = [
    player('No activity', { rushing_yards: 0, carries: 0, targets: 15 }),
    player('Zero on carries', { rushing_yards: 0, carries: 2 }),
    player('Lost yards', { rushing_yards: -3, carries: 1 }),
    player('Unknown yards', { carries: 7 }),
  ];
  assert.deepEqual(ids(filterPlayersByStatistic(players, 'rushing_yards', { requireActivity: true })), ['Zero on carries', 'Lost yards']);
  assert.deepEqual(ids(filterPlayersByStatistic(players, 'rushing_yards', { requireActivity: true, minimum: '0' })), ['Zero on carries']);
});

test('combined activity recognizes rush or receiving opportunity without counting passing touchdowns', () => {
  const players = [
    player('Rusher', { rushing_tds: 0, receiving_tds: 0, carries: 3, targets: 0 }),
    player('Receiver', { rushing_tds: 0, receiving_tds: 1, carries: 0, targets: 4 }),
    player('Passer', { rushing_tds: 0, receiving_tds: 0, carries: 0, targets: 0, attempts: 25, passing_tds: 3 }),
    player('Incomplete', { rushing_tds: 1, carries: 5 }),
  ];
  assert.deepEqual(ids(filterPlayersByStatistic(players, 'rush_receiving_tds', { requireActivity: true })), ['Rusher', 'Receiver']);
});

test('all 33 supported player markets map to matching historical statistics or explicit missing detail', () => {
  const mapping = {
    player_pass_yds: 'passing_yards', player_pass_tds: 'passing_tds', player_pass_attempts: 'attempts',
    player_pass_completions: 'completions', player_pass_interceptions: 'passing_interceptions',
    player_rush_yds: 'rushing_yards', player_rush_attempts: 'carries', player_rush_tds: 'rushing_tds',
    player_reception_yds: 'receiving_yards', player_receptions: 'receptions', player_reception_tds: 'receiving_tds',
    player_rush_reception_yds: 'rush_receiving_yards', player_anytime_td: 'touchdowns_scored',
    player_tds_over: 'touchdowns_scored', player_1st_td: null,
    player_pass_rush_yds: 'pass_rush_yards', player_pass_rush_reception_yds: 'pass_rush_receiving_yards',
    player_pass_rush_reception_tds: 'pass_rush_receiving_tds', player_rush_reception_tds: 'rush_receiving_tds',
    player_pass_longest_completion: null, player_rush_longest: null, player_reception_longest: null,
    player_pass_yds_q1: null, player_tds: 'touchdowns_scored', player_last_td: null,
    player_field_goals: 'fg_made', player_kicking_points: 'kicking_points', player_pats: 'pat_made',
    player_sacks: 'def_sacks', player_solo_tackles: 'def_tackles_solo', player_assists: 'def_tackle_assists',
    player_tackles_assists: 'tackles_assists', player_defensive_interceptions: 'def_interceptions',
  };
  const catalog = JSON.parse(readFileSync(new URL('../config/nfl-markets.json', import.meta.url), 'utf8'));
  assert.equal(Object.keys(mapping).length, 33);
  assert.deepEqual(Object.keys(mapping).sort(), catalog.markets.map((item) => item.key).sort());
  for (const [market, statistic] of Object.entries(mapping)) {
    assert.equal(getStatisticForMarket(market), statistic);
    if (statistic !== null) assert.equal(STATISTICS.some((item) => item.key === statistic), true);
    else assert.equal(getStatisticForMarket(market, true), null);
  }
  assert.equal(getStatisticForMarket('player_1st_td'), null);
  assert.equal(getStatisticForMarket('unsupported'), null);
  assert.equal(getStatisticForMarket('__proto__'), null);
  assert.equal(getStatisticForMarket('player_pass_yds', true), 'touchdowns_scored');
});

test('catalog historical-stat availability stays aligned with UI helpers without claiming probability', () => {
  const catalog = JSON.parse(readFileSync(new URL('../config/nfl-markets.json', import.meta.url), 'utf8'));
  assert.equal(catalog.markets.length, 33);
  assert.equal(catalog.markets.filter((entry) => entry.default).length, 15);
  const unsupportedHistoricalMarkets = [
    'player_1st_td', 'player_last_td', 'player_pass_longest_completion',
    'player_rush_longest', 'player_reception_longest', 'player_pass_yds_q1',
  ];
  assert.deepEqual(catalog.markets.filter((entry) => entry.statistic === null).map((entry) => entry.key).sort(), unsupportedHistoricalMarkets.sort());
  for (const entry of catalog.markets) {
    assert.equal(getStatisticForMarket(entry.key), entry.statistic, `${entry.key} catalog/UI statistic disagreement`);
    if (entry.statistic !== null) {
      assert.equal(STATISTICS.some((statistic) => statistic.key === entry.statistic), true, `${entry.key} has no selectable historical statistic`);
      assert.doesNotMatch(entry.statistic, /probability|forecast|projection/);
    }
  }
});

test('formatting separates known zero from missing and formats historical totals or averages', () => {
  assert.equal(formatStatistic(12345, { unit: 'yds', basis: 'total' }), '12,345');
  assert.equal(formatStatistic(123.456, { unit: 'yds', basis: 'perGame' }), '123.5');
  assert.equal(formatStatistic(123.456, { unit: 'yds', basis: 'per_game' }), '123.5');
  assert.equal(formatStatistic(0, { unit: 'TDs', basis: 'perGame' }), '0');
  assert.equal(formatStatistic(-3, { unit: 'yds' }), '-3');
  assert.equal(formatStatistic(-0), '0');
  assert.equal(formatStatistic(0.5, { unit: 'sacks', basis: 'total' }), '0.5');
  for (const value of [null, undefined, '', '0', false, NaN, Infinity]) assert.equal(formatStatistic(value), '—');
});

test('workload display follows the selected statistic instead of a different player role', () => {
  const versatile = player('Versatile', { completions: 23, attempts: 35, carries: 6, receptions: 2, targets: 4 });
  assert.equal(getPlayerWorkload(versatile, 'passing_yards'), '23 completions / 35 attempts');
  assert.equal(getPlayerWorkload(versatile, 'rushing_yards'), '6 carries');
  assert.equal(getPlayerWorkload(versatile, 'receiving_yards'), '2 receptions / 4 targets');
  assert.equal(getPlayerWorkload(versatile, 'rush_receiving_yards'), '6 carries + 4 targets');
});

test('workload display preserves known zeros and omits missing or unrelated components', () => {
  assert.equal(getPlayerWorkload(player('Zero', { receptions: 0, targets: 3 }), 'receiving_tds'), '0 receptions / 3 targets');
  assert.equal(getPlayerWorkload(player('Targets only', { targets: 3 }), 'receiving_yards'), '3 targets');
  assert.equal(getPlayerWorkload(player('Carries only', { carries: 0, targets: null }), 'rush_receiving_yards'), '0 carries');
  assert.equal(getPlayerWorkload(player('Passing only', { attempts: 35 }), 'receiving_yards'), null);
  assert.equal(getPlayerWorkload(player('Unknown', null), 'passing_yards'), null);
  assert.equal(getPlayerWorkload(player('Unknown key', { targets: 3 }), 'unsupported'), null);
});

test('kicking points count three points per field goal and one per PAT, requiring both components', () => {
  const kicker = player('Kicker', { fg_made: 10, fg_att: 12, pat_made: 8, pat_att: 9 });
  assert.equal(getPlayerStatistic(kicker, 'kicking_points'), 38);
  assert.equal(getPlayerStatistic(kicker, 'kicking_points', 'per_game'), 9.5);
  assert.equal(getPlayerStatistic(player('Zero', { fg_made: 0, pat_made: 0 }), 'kicking_points'), 0);
  for (const stats of [{ fg_made: 10 }, { pat_made: 8 }, { fg_made: null, pat_made: 8 }]) {
    assert.equal(getPlayerStatistic(player('Incomplete', stats), 'kicking_points'), null);
  }
  assert.equal(getPlayerWorkload(kicker, 'fg_made'), '10 FG made / 12 FG attempts');
  assert.equal(getPlayerWorkload(kicker, 'pat_made'), '8 PAT made / 9 PAT attempts');
  assert.equal(getPlayerWorkload(kicker, 'kicking_points'), '12 FG attempts + 9 PAT attempts');
});

test('kicking activity requires the relevant recorded attempt while retaining zero makes', () => {
  const players = [
    player('FG misses', { fg_made: 0, fg_att: 2, pat_made: 0, pat_att: 0 }),
    player('PAT misses', { fg_made: 0, fg_att: 0, pat_made: 0, pat_att: 2 }),
    player('No kicks', { fg_made: 0, fg_att: 0, pat_made: 0, pat_att: 0 }),
  ];
  assert.deepEqual(ids(filterPlayersByStatistic(players, 'fg_made', { requireActivity: true })), ['FG misses']);
  assert.deepEqual(ids(filterPlayersByStatistic(players, 'pat_made', { requireActivity: true })), ['PAT misses']);
  assert.deepEqual(ids(filterPlayersByStatistic(players, 'kicking_points', { requireActivity: true })), ['FG misses', 'PAT misses']);
});

test('passing composites include only their stated components and preserve missing pieces', () => {
  const versatile = player('Versatile', { passing_yards: 300, rushing_yards: -5, receiving_yards: 20, passing_tds: 2, rushing_tds: 1, receiving_tds: 0, attempts: 30, carries: 5, targets: 2 });
  assert.equal(getPlayerStatistic(versatile, 'pass_rush_yards'), 295);
  assert.equal(getPlayerStatistic(versatile, 'pass_rush_receiving_yards'), 315);
  assert.equal(getPlayerStatistic(versatile, 'pass_rush_receiving_tds'), 3);
  assert.equal(getPlayerStatistic(versatile, 'rush_receiving_tds'), 1);
  assert.equal(getPlayerStatistic(player('No receiving', { passing_yards: 300, rushing_yards: 10 }), 'pass_rush_receiving_yards'), null);
  assert.equal(getPlayerStatistic(player('No passing TDs', { rushing_tds: 1, receiving_tds: 0 }), 'pass_rush_receiving_tds'), null);
  assert.equal(getPlayerWorkload(versatile, 'pass_rush_yards'), '30 pass attempts + 5 carries');
  assert.equal(getPlayerWorkload(versatile, 'pass_rush_receiving_yards'), '30 pass attempts + 5 carries + 2 targets');
});

test('tackle totals include distinct solo, primary assisted tackles and assisting tackle credits', () => {
  const defender = player('Defender', { def_tackles_solo: 20, def_tackle_assists: 8, def_tackles_with_assist: 12, def_interceptions: 1 });
  assert.equal(getPlayerStatistic(defender, 'tackles_assists'), 40);
  assert.equal(getPlayerStatistic(defender, 'tackles_assists', 'per_game'), 10);
  assert.equal(getPlayerStatistic(player('Missing assists', { def_tackles_solo: 20, def_tackles_with_assist: 12 }), 'tackles_assists'), null);
  assert.equal(getPlayerStatistic(player('Missing primary assisted credit', { def_tackles_solo: 20, def_tackle_assists: 8 }), 'tackles_assists'), null);
  assert.equal(getPlayerWorkload(defender, 'tackles_assists'), null);
});

test('combined tackles preserve published 2025 examples with primary assisted credits', () => {
  // nflverse dictionary: the three tackle columns are distinct credit categories.
  // https://raw.githubusercontent.com/nflverse/nflreadr/main/data-raw/dictionary_player_stats.json
  const examples = [
    ['Jordyn Brooks', 96, 3, 84, 183],
    ['Jack Campbell', 87, 2, 87, 176],
    ['Devin White', 90, 5, 79, 174],
  ];
  for (const [name, solo, withAssist, assists, total] of examples) {
    assert.equal(getPlayerStatistic(player(name, { def_tackles_solo: solo, def_tackles_with_assist: withAssist, def_tackle_assists: assists }), 'tackles_assists'), total);
  }
});

test('fractional sack credit is retained in numeric sorts and formatted totals', () => {
  const players = [player('Half', { def_sacks: 0.5 }), player('Missing', {}), player('Whole', { def_sacks: 1 }), player('Zero', { def_sacks: 0 })];
  assert.deepEqual(ids(sortPlayers(players, 'def_sacks')), ['Whole', 'Half', 'Zero', 'Missing']);
  assert.equal(getPlayerStatistic(players[0], 'def_sacks'), 0.5);
  assert.equal(formatStatistic(getPlayerStatistic(players[0], 'def_sacks'), { unit: 'sacks' }), '0.5');
});

test('defensive activity requires actual sampled defense rather than offensive rows with padded zeros', () => {
  const players = [
    player('Defender zero', { def_sacks: 0, def_tackles_solo: 0 }, { position: 'LB' }),
    player('QB zero', { def_sacks: 0, def_tackles_solo: 0 }, { position: 'QB' }),
    player('WR contribution', { def_sacks: 0, def_tackle_assists: 1 }, { position: 'WR' }),
    player('No role with sack', { def_sacks: 0.5 }, { position: null }),
    player('No sample', { def_sacks: 2 }, { position: 'DE', sample_games: 0 }),
    player('Unknown selected stat', { def_tackles_solo: 5 }, { position: 'CB' }),
  ];
  assert.deepEqual(ids(filterPlayersByStatistic(players, 'def_sacks', { requireActivity: true })), ['Defender zero', 'WR contribution', 'No role with sack']);
  assert.deepEqual(ids(filterPlayersByStatistic(players, 'def_sacks', { requireRecorded: true })), ['Defender zero', 'QB zero', 'WR contribution', 'No role with sack', 'No sample']);
  assert.deepEqual(ids(filterPlayersByStatistic(players, 'def_sacks', { requireActivity: true, minimum: '0.5' })), ['No role with sack']);
});

test('touchdowns scored include all five mutually exclusive source categories and exclude passes thrown', () => {
  const scorer = player('Scorer', { rushing_tds: 2, receiving_tds: 3, special_teams_tds: 1, def_tds: 2, fumble_recovery_tds: 1, passing_tds: 50 });
  assert.equal(getPlayerStatistic(scorer, 'touchdowns_scored'), 9);
  assert.equal(getPlayerStatistic(scorer, 'touchdowns_scored', 'per_game'), 2.25);
  assert.equal(getPlayerStatistic(scorer, 'rush_receiving_tds'), 5);
  assert.equal(getStatisticForMarket('player_rush_reception_tds'), 'rush_receiving_tds');
});

test('an actual defensive and fumble-recovery scoring game counts both touchdowns', () => {
  // Isaiah Rodgers, 2025 Week 3: one defensive TD plus one separately classified fumble-recovery TD.
  const rodgers = player('Isaiah Rodgers', { rushing_tds: 0, receiving_tds: 0, special_teams_tds: 0, def_tds: 1, fumble_recovery_tds: 1, passing_tds: 0 }, { position: 'CB', sample_games: 1 });
  assert.equal(getPlayerStatistic(rodgers, 'touchdowns_scored'), 2);
  assert.equal(getPlayerStatistic(rodgers, 'rush_receiving_tds'), 0);
  assert.equal(getPlayerStatistic(rodgers, 'touchdowns_scored', 'per_game'), 2);
});

test('missing any scored-touchdown category makes the combined total unknown, including known zero counterparts', () => {
  const stats = { rushing_tds: 0, receiving_tds: 0, special_teams_tds: 0, def_tds: 0, fumble_recovery_tds: 0 };
  assert.equal(getPlayerStatistic(player('Known zero', stats), 'touchdowns_scored'), 0);
  for (const field of Object.keys(stats)) {
    const partial = { ...stats };
    delete partial[field];
    assert.equal(getPlayerStatistic(player('Missing category', partial), 'touchdowns_scored'), null);
    assert.equal(getPlayerStatistic(player('Null category', { ...stats, [field]: null }), 'touchdowns_scored'), null);
  }
});

test('scored-touchdown activity keeps sampled players from any role including known zeros', () => {
  const zeroStats = { rushing_tds: 0, receiving_tds: 0, special_teams_tds: 0, def_tds: 0, fumble_recovery_tds: 0, passing_tds: 10 };
  const players = [
    player('QB no scores', zeroStats, { position: 'QB' }),
    player('Defender no scores', zeroStats, { position: 'CB' }),
    player('Unsampled scorer', { ...zeroStats, def_tds: 1 }, { position: 'LB', sample_games: 0 }),
    player('Missing category', { rushing_tds: 1, receiving_tds: 0 }, { position: 'RB' }),
  ];
  assert.deepEqual(ids(filterPlayersByStatistic(players, 'touchdowns_scored', { requireActivity: true })), ['QB no scores', 'Defender no scores']);
  assert.deepEqual(ids(filterPlayersByStatistic(players, 'touchdowns_scored', { requireActivity: true, minimum: '1' })), []);
});
