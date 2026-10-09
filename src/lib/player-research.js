/** Historical observations only. These helpers do not estimate future production. */
export const STATISTICS = [
  { key: 'receiving_yards', label: 'Receiving yards', shortLabel: 'Receiving yards', unit: 'yds', workloadKey: 'targets', market: 'player_reception_yds' },
  { key: 'rushing_yards', label: 'Rushing yards', shortLabel: 'Rushing yards', unit: 'yds', workloadKey: 'carries', market: 'player_rush_yds' },
  { key: 'passing_yards', label: 'Passing yards', shortLabel: 'Passing yards', unit: 'yds', workloadKey: 'attempts', market: 'player_pass_yds' },
  { key: 'receptions', label: 'Receptions', shortLabel: 'Receptions', unit: 'receptions', workloadKey: 'targets', market: 'player_receptions' },
  { key: 'targets', label: 'Receiving targets', shortLabel: 'Targets', unit: 'targets', workloadKey: 'targets', market: null },
  { key: 'carries', label: 'Rushing attempts', shortLabel: 'Carries', unit: 'carries', workloadKey: 'carries', market: 'player_rush_attempts' },
  { key: 'rush_receiving_yards', label: 'Rush + receiving yards', shortLabel: 'Rush + receiving yards', unit: 'yds', workloadKey: ['carries', 'targets'], market: 'player_rush_reception_yds' },
  { key: 'receiving_tds', label: 'Receiving touchdowns', shortLabel: 'Receiving TDs', unit: 'TDs', workloadKey: 'targets', market: 'player_reception_tds' },
  { key: 'rushing_tds', label: 'Rushing touchdowns', shortLabel: 'Rushing TDs', unit: 'TDs', workloadKey: 'carries', market: 'player_rush_tds' },
  { key: 'rush_receiving_tds', label: 'Rush + receiving touchdowns', shortLabel: 'Rush + receiving TDs', unit: 'TDs', workloadKey: ['carries', 'targets'], market: 'player_rush_reception_tds' },
  { key: 'touchdowns_scored', label: 'Touchdowns scored', shortLabel: 'Touchdowns scored', unit: 'TDs', workloadKey: 'player_games', market: 'player_anytime_td' },
  { key: 'passing_tds', label: 'Passing touchdowns', shortLabel: 'Passing TDs', unit: 'TDs', workloadKey: 'attempts', market: 'player_pass_tds' },
  { key: 'attempts', label: 'Passing attempts', shortLabel: 'Pass attempts', unit: 'attempts', workloadKey: 'attempts', market: 'player_pass_attempts' },
  { key: 'completions', label: 'Passing completions', shortLabel: 'Completions', unit: 'completions', workloadKey: 'attempts', market: 'player_pass_completions' },
  { key: 'passing_interceptions', label: 'Passing interceptions', shortLabel: 'Interceptions', unit: 'interceptions', workloadKey: 'attempts', market: 'player_pass_interceptions' },
  { key: 'pass_rush_yards', label: 'Pass + rushing yards', shortLabel: 'Pass + rushing yards', unit: 'yds', workloadKey: ['attempts', 'carries'], market: 'player_pass_rush_yds' },
  { key: 'pass_rush_receiving_yards', label: 'Pass + rush + receiving yards', shortLabel: 'Pass + rush + receiving yards', unit: 'yds', workloadKey: ['attempts', 'carries', 'targets'], market: 'player_pass_rush_reception_yds' },
  { key: 'pass_rush_receiving_tds', label: 'Pass + rush + receiving touchdowns', shortLabel: 'Pass + rush + receiving TDs', unit: 'TDs', workloadKey: ['attempts', 'carries', 'targets'], market: 'player_pass_rush_reception_tds' },
  { key: 'fg_made', label: 'Field goals made', shortLabel: 'Field goals made', unit: 'field goals', workloadKey: 'fg_att', market: 'player_field_goals' },
  { key: 'kicking_points', label: 'Kicking points', shortLabel: 'Kicking points', unit: 'points', workloadKey: ['fg_att', 'pat_att'], market: 'player_kicking_points' },
  { key: 'pat_made', label: 'Extra points made', shortLabel: 'Extra points made', unit: 'extra points', workloadKey: 'pat_att', market: 'player_pats' },
  { key: 'def_sacks', label: 'Defensive sacks', shortLabel: 'Sacks', unit: 'sacks', workloadKey: 'stat_games', market: 'player_sacks' },
  { key: 'def_tackles_solo', label: 'Solo tackles', shortLabel: 'Solo tackles', unit: 'tackles', workloadKey: 'stat_games', market: 'player_solo_tackles' },
  { key: 'def_tackle_assists', label: 'Assisted tackles', shortLabel: 'Assisted tackles', unit: 'assists', workloadKey: 'stat_games', market: 'player_assists' },
  { key: 'tackles_assists', label: 'Combined tackles', shortLabel: 'Combined tackles', unit: 'tackles', workloadKey: 'stat_games', market: 'player_tackles_assists' },
  { key: 'def_interceptions', label: 'Defensive interceptions', shortLabel: 'Defensive interceptions', unit: 'interceptions', workloadKey: 'stat_games', market: 'player_defensive_interceptions' },
];

const metadata = new Map(STATISTICS.map((statistic) => [statistic.key, statistic]));
const combinedFields = {
  rush_receiving_yards: ['rushing_yards', 'receiving_yards'],
  rush_receiving_tds: ['rushing_tds', 'receiving_tds'],
  // Source categories exclude each other; passing TDs belong to the passer's separate market.
  touchdowns_scored: ['rushing_tds', 'receiving_tds', 'special_teams_tds', 'def_tds', 'fumble_recovery_tds'],
  pass_rush_yards: ['passing_yards', 'rushing_yards'],
  pass_rush_receiving_yards: ['passing_yards', 'rushing_yards', 'receiving_yards'],
  pass_rush_receiving_tds: ['passing_tds', 'rushing_tds', 'receiving_tds'],
  kicking_points: ['fg_made', 'pat_made'],
  // nflverse distinguishes solo, primary tackles with assistance, and assists.
  tackles_assists: ['def_tackles_solo', 'def_tackles_with_assist', 'def_tackle_assists'],
};
const marketStatistics = {
  player_pass_yds: 'passing_yards',
  player_pass_tds: 'passing_tds',
  player_pass_attempts: 'attempts',
  player_pass_completions: 'completions',
  player_pass_interceptions: 'passing_interceptions',
  player_rush_yds: 'rushing_yards',
  player_rush_attempts: 'carries',
  player_rush_tds: 'rushing_tds',
  player_reception_yds: 'receiving_yards',
  player_receptions: 'receptions',
  player_reception_tds: 'receiving_tds',
  player_rush_reception_yds: 'rush_receiving_yards',
  player_anytime_td: 'touchdowns_scored',
  player_tds_over: 'touchdowns_scored',
  player_1st_td: null,
  player_pass_rush_yds: 'pass_rush_yards',
  player_pass_rush_reception_yds: 'pass_rush_receiving_yards',
  player_pass_rush_reception_tds: 'pass_rush_receiving_tds',
  player_rush_reception_tds: 'rush_receiving_tds',
  player_pass_longest_completion: null,
  player_rush_longest: null,
  player_reception_longest: null,
  player_pass_yds_q1: null,
  player_tds: 'touchdowns_scored',
  player_last_td: null,
  player_field_goals: 'fg_made',
  player_kicking_points: 'kicking_points',
  player_pats: 'pat_made',
  player_sacks: 'def_sacks',
  player_solo_tackles: 'def_tackles_solo',
  player_assists: 'def_tackle_assists',
  player_tackles_assists: 'tackles_assists',
  player_defensive_interceptions: 'def_interceptions',
};

// API statistics are JSON numbers. Missing, empty and boolean values are not zero.
const recordedNumber = (value) => typeof value === 'number' && Number.isFinite(value) ? value : null;
const nameOrder = new Intl.Collator('en-US', { sensitivity: 'base', numeric: true });
const integerFormat = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
const statisticFormat = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 });
const isPerGame = (basis) => basis === 'per_game' || basis === 'perGame';
const defensivePositions = new Set(['DE', 'FS', 'OLB', 'S', 'MLB', 'LB', 'DT', 'CB', 'NT', 'SAF', 'DB', 'ILB', 'DL', 'EDGE', 'SS']);
const defensiveFields = ['def_sacks', 'def_tackles_solo', 'def_tackles_with_assist', 'def_tackle_assists', 'def_interceptions'];

/** Some markets require play-by-play detail unavailable in the weekly source. */
export function getStatisticForMarket(market, touchdowns = false) {
  if (!Object.hasOwn(marketStatistics, market) || marketStatistics[market] === null) return null;
  return touchdowns ? 'touchdowns_scored' : marketStatistics[market];
}

/** A combined total is unknown when either component is unknown. */
export function getPlayerStatistic(player, key, basis = 'total') {
  if (!metadata.has(key)) return null;
  let value;
  if (combinedFields[key]) {
    const components = combinedFields[key].map((field) => recordedNumber(player?.stats?.[field]));
    value = components.some((component) => component === null) ? null : components.reduce((sum, component, index) => sum + component * (key === 'kicking_points' && index === 0 ? 3 : 1), 0);
  } else {
    value = recordedNumber(player?.stats?.[key]);
  }
  if (value === null || !Number.isFinite(value)) return null;
  if (basis === 'total') return value;
  if (!isPerGame(basis)) return null;
  const sample = recordedNumber(player?.sample_games);
  if (sample === null || sample <= 0) return null;
  const average = value / sample;
  return Number.isFinite(average) ? average : null;
}

function compareIdentity(left, right) {
  const leftName = String(left?.name ?? '');
  const rightName = String(right?.name ?? '');
  const leftId = String(left?.id ?? '');
  const rightId = String(right?.id ?? '');
  return nameOrder.compare(leftName, rightName) || nameOrder.compare(leftId, rightId)
    || (leftName < rightName ? -1 : leftName > rightName ? 1 : 0)
    || (leftId < rightId ? -1 : leftId > rightId ? 1 : 0);
}

/** Missing observations remain last in either direction; ties use name then id. */
export function sortPlayers(players, key, direction = 'desc', basis = 'total') {
  return [...(Array.isArray(players) ? players : [])].sort((left, right) => {
    const leftValue = getPlayerStatistic(left, key, basis);
    const rightValue = getPlayerStatistic(right, key, basis);
    if (leftValue === null && rightValue !== null) return 1;
    if (rightValue === null && leftValue !== null) return -1;
    if (leftValue !== null && rightValue !== null && leftValue !== rightValue) {
      const ascending = leftValue < rightValue ? -1 : 1;
      return direction === 'asc' ? ascending : -ascending;
    }
    return compareIdentity(left, right);
  });
}

function minimumNumber(value) {
  if (typeof value !== 'number' && typeof value !== 'string') return null;
  if (typeof value === 'string' && !value.trim()) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

/**
 * Empty minimum keeps all rows. A minimum of zero keeps known zeros, not blanks.
 * Activity uses actual attempts/carries/targets, allowing negative-yard games.
 * Combined activity requires one relevant actual workload to be positive.
 * Defense requires a sampled defensive player or an actual defensive contribution.
 */
export function filterPlayersByStatistic(players, key, {
  basis = 'total', minimum = '', requireRecorded = false, requireActivity = false,
} = {}) {
  const threshold = minimumNumber(minimum);
  const workload = metadata.get(key)?.workloadKey;
  const workloadKeys = Array.isArray(workload) ? workload : workload ? [workload] : [];
  return (Array.isArray(players) ? players : []).filter((player) => {
    const value = getPlayerStatistic(player, key, basis);
    if ((requireRecorded || requireActivity || threshold !== null) && value === null) return false;
    if (threshold !== null && value < threshold) return false;
    if (requireActivity && !workloadKeys.some((field) => {
      if (field === 'player_games') {
        const sample = recordedNumber(player?.sample_games);
        return sample !== null && sample > 0;
      }
      if (field === 'stat_games') {
        const sample = recordedNumber(player?.sample_games);
        const defensiveRole = defensivePositions.has(String(player?.position ?? '').trim().toUpperCase());
        const contribution = defensiveFields.some((defensiveField) => (recordedNumber(player?.stats?.[defensiveField]) ?? 0) > 0);
        return sample !== null && sample > 0 && (defensiveRole || contribution);
      }
      const activity = recordedNumber(player?.stats?.[field]);
      return activity !== null && activity > 0;
    })) return false;
    return true;
  });
}

/** Format the number; the caller supplies the statistic unit and basis label. */
export function formatStatistic(value, { basis = 'total' } = {}) {
  const number = recordedNumber(value);
  if (number === null) return '—';
  // Fractional sack credits are source observations, including in season totals.
  return statisticFormat.format(number === 0 ? 0 : number);
}

/** Source workload totals; missing components are omitted rather than filled with zero. */
export function getPlayerWorkload(player, key) {
  const workload = metadata.get(key)?.workloadKey;
  const workloadLabels = { attempts: 'pass attempts', carries: 'carries', targets: 'targets', fg_att: 'FG attempts', pat_att: 'PAT attempts' };
  const fields = Array.isArray(workload) ? workload.map((field) => [field, workloadLabels[field] ?? field])
    : workload === 'attempts' ? [['completions', 'completions'], ['attempts', 'attempts']]
      : workload === 'targets' ? [['receptions', 'receptions'], ['targets', 'targets']]
        : workload === 'carries' ? [['carries', 'carries']]
          : workload === 'fg_att' ? [['fg_made', 'FG made'], ['fg_att', 'FG attempts']]
            : workload === 'pat_att' ? [['pat_made', 'PAT made'], ['pat_att', 'PAT attempts']] : [];
  const parts = fields.flatMap(([field, label]) => {
    const value = recordedNumber(player?.stats?.[field]);
    return value === null ? [] : [`${integerFormat.format(value)} ${label}`];
  });
  return parts.length ? parts.join(Array.isArray(workload) ? ' + ' : ' / ') : null;
}
