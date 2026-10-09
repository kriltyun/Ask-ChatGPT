import test from 'node:test';
import assert from 'node:assert/strict';
import {
  americanToDecimal, decimalToAmerican, breakEvenProbability, normalizePrice,
  marketKey, findPrice, calculateParlay, STALE_PRICE_MS,
} from '../src/lib/markets.js';

const now = Date.parse('2026-10-09T01:00:00Z');
const updated = new Date(now).toISOString();
const leg = (overrides = {}) => ({
  id: 'selection-1', game_id: 'game-1', player: 'Test Player', market: 'player_pass_yds',
  outcome: 'Over', line: 249.5,
  prices: [{ bookmaker: 'fanduel', price: -110, last_update: updated }],
  ...overrides,
});
const calculate = (legs, stake = 10, bookmaker = 'fanduel') => calculateParlay(legs, stake, bookmaker, { now });
const hasWarning = (result, type) => result.warnings.some((warning) => warning.type === type);

test('provider stale flag is honored even when quote timestamp is recent', () => {
  const result = calculate([leg({ prices: [{ bookmaker: 'fanduel', price: -110, last_update: updated, stale: true }] })]);
  assert.equal(hasWarning(result, 'stale_price'), true);
  assert.equal(result.complete, true);
  assert.match(result.quoteLabel, /Synthetic/);
});

test('American conversion handles positive, negative and even-money prices', () => {
  assert.equal(americanToDecimal(150), 2.5);
  assert.equal(americanToDecimal(-200), 1.5);
  assert.equal(americanToDecimal('+100'), 2);
  assert.equal(americanToDecimal(-100), 2);
  assert.equal(decimalToAmerican(2.5), 150);
  assert.equal(decimalToAmerican(1.5), -200);
  assert.equal(decimalToAmerican(2), 100);
  assert.equal(breakEvenProbability(-200), 2 / 3);
  assert.equal(breakEvenProbability(150), 0.4);
});

test('invalid American and decimal prices remain unavailable', () => {
  for (const value of [0, '', ' ', null, undefined, true, false, Infinity, NaN, 'abc', 50, -50]) {
    assert.equal(normalizePrice(value), null);
    assert.equal(americanToDecimal(value), null);
    assert.equal(breakEvenProbability(value), null);
  }
  for (const value of [0, 1, -1, null, '', Infinity, 'invalid']) assert.equal(decimalToAmerican(value), null);
  assert.equal(normalizePrice(' -110 '), -110);
});

test('synthetic single-price product separates stake, return and profit', () => {
  const result = calculate([
    leg({ prices: [{ bookmaker: 'fanduel', price: 150, last_update: updated }] }),
    leg({ game_id: 'game-2', player: 'Another Player', prices: [{ bookmaker: 'fanduel', price: -200, last_update: updated }] }),
  ], 20);
  assert.equal(result.complete, true);
  assert.equal(result.decimal, 3.75);
  assert.equal(result.totalReturn, 75);
  assert.equal(result.profit, 55);
  assert.match(result.quoteLabel, /Synthetic/);
  assert.equal(result.jointProbability, null);
});

test('the requested sportsbook is never replaced by a different book', () => {
  const selection = leg({ prices: [{ bookmaker: 'draftkings', price: 150, last_update: updated }] });
  assert.equal(findPrice(selection, 'fanduel'), null);
  const unavailable = calculate([selection]);
  assert.equal(unavailable.complete, false);
  assert.equal(unavailable.totalReturn, null);
  assert.equal(hasWarning(unavailable, 'missing_price'), true);
  assert.equal(calculate([selection], 10, 'draftkings').decimal, 2.5);
});

test('market identity preserves thresholds and distinct touchdown definitions', () => {
  assert.notEqual(marketKey(leg()), marketKey(leg({ line: 259.5 })));
  assert.equal(marketKey(leg()), marketKey(leg({ line: '249.5', player: '  test PLAYER  ' })));
  assert.notEqual(marketKey(leg({ market: 'player_pass_tds' })), marketKey(leg({ market: 'player_anytime_td' })));
  assert.notEqual(marketKey(leg({ market: 'player_1st_td' })), marketKey(leg({ market: 'player_team_1st_td' })));
  assert.notEqual(marketKey(leg()), marketKey(leg({ outcome: 'Under' })));
  assert.notEqual(marketKey(leg()), marketKey(leg({ game_id: 'game-2' })));
});

test('quotes with a different threshold or market identity cannot match', () => {
  const selection = leg({ prices: [
    { bookmaker: 'fanduel', price: 120, line: 259.5, last_update: updated },
    { bookmaker: 'fanduel', price: 130, line: 249.5, outcome: 'Under', last_update: updated },
    { bookmaker: 'draftkings', price: 140, line: 249.5, last_update: updated },
  ] });
  assert.equal(findPrice(selection, 'fanduel'), null);
  assert.equal(hasWarning(calculate([selection]), 'missing_price'), true);
});

test('same-game marginal probabilities are never asserted as joint probability', () => {
  const result = calculate([leg({ probability: 0.6 }), leg({ player: 'Another Player', probability: 0.7 })]);
  assert.equal(result.complete, true);
  assert.equal(hasWarning(result, 'same_game'), true);
  assert.equal(result.jointProbability, null);
  assert.match(result.probabilityLabel, /unavailable/);
});

test('only supplied cross-game probabilities produce an independence approximation', () => {
  const selections = [leg({ probability: 0.6 }), leg({ game_id: 'game-2', player: 'Another Player', probability: 0.7 })];
  const result = calculate(selections);
  assert.equal(result.jointProbability, 0.42);
  assert.match(result.probabilityLabel, /Independence approximation/);
  assert.equal(calculate([selections[0], { ...selections[1], probability: undefined }]).jointProbability, null);
  assert.equal(calculate([selections[0], { ...selections[1], probability: 1.1 }]).jointProbability, null);
  assert.equal(calculate([selections[0], { ...selections[1], game_id: undefined }]).jointProbability, null);
});

test('opposite outcomes at the same exact line are incompatible', () => {
  const result = calculate([leg(), leg({ id: 'selection-2', outcome: 'Under' })]);
  assert.equal(result.complete, false);
  assert.equal(result.decimal, null);
  assert.equal(hasWarning(result, 'incompatible'), true);
  assert.equal(hasWarning(result, 'repeated_player'), true);
  // Different thresholds are preserved as separate wagers, not treated as equal.
  assert.equal(hasWarning(calculate([leg(), leg({ outcome: 'Under', line: 259.5 })]), 'incompatible'), false);
});

test('duplicate selections cannot multiply the same wager twice', () => {
  const result = calculate([leg(), leg({ id: 'different-local-id' })]);
  assert.equal(result.complete, false);
  assert.equal(result.totalReturn, null);
  assert.equal(hasWarning(result, 'duplicate'), true);
});

test('nested scored touchdowns are flagged without conflating passing touchdowns', () => {
  const anytime = leg({ market: 'player_anytime_td', outcome: 'Yes', line: null });
  const multiple = leg({ market: 'player_tds_over', outcome: 'Over', line: 1.5 });
  const result = calculate([anytime, multiple]);
  assert.equal(hasWarning(result, 'nested_outcome'), true);
  assert.equal(result.jointProbability, null);
  assert.equal(result.complete, true);
  assert.equal(hasWarning(calculate([anytime, leg({ market: 'player_pass_tds', line: 1.5 })]), 'nested_outcome'), false);
});

test('staleness uses the bookmaker update timestamp and a strict 15-minute threshold', () => {
  const quoteAt = (age) => leg({ prices: [{ bookmaker: 'fanduel', price: -110, last_update: new Date(now - age).toISOString() }], saved_at: updated });
  assert.equal(hasWarning(calculate([quoteAt(STALE_PRICE_MS)]), 'stale_price'), false);
  assert.equal(hasWarning(calculate([quoteAt(STALE_PRICE_MS + 1)]), 'stale_price'), true);
  assert.equal(hasWarning(calculate([leg({ prices: [{ bookmaker: 'fanduel', price: -110 }] })]), 'missing_timestamp'), true);
});

test('zero prices are flagged as invalid and do not produce synthetic totals', () => {
  const result = calculate([leg({ prices: [{ bookmaker: 'fanduel', price: 0, last_update: updated }] })]);
  assert.equal(result.complete, false);
  assert.equal(result.totalReturn, null);
  assert.equal(hasWarning(result, 'invalid_price'), true);
});

test('empty drafts, negative stakes and non-numeric stakes do not produce totals', () => {
  assert.equal(calculate([]).complete, false);
  assert.equal(calculate([]).decimal, null);
  assert.equal(hasWarning(calculate([leg()], -10), 'invalid_stake'), true);
  assert.equal(hasWarning(calculate([leg()], 'invalid'), 'invalid_stake'), true);
  assert.equal(calculate([leg()], 0).totalReturn, 0);
});

test('price matching uses the latest timestamp within one exact bookmaker', () => {
  const selection = leg({ prices: [
    { bookmaker: 'fanduel', price: -120, last_update: '2026-10-09T00:30:00Z' },
    { bookmaker: 'fanduel', price: 120, last_update: updated },
    { bookmaker: 'draftkings', price: 300, last_update: updated },
  ] });
  assert.equal(findPrice(selection, 'fanduel').price, 120);
  assert.equal(hasWarning(calculate([selection]), 'stale_price'), false);
});

test('opposing moneylines, opposing complementary spreads and game-first scorers conflict', () => {
  assert.equal(hasWarning(calculate([
    leg({ player: null, market: 'h2h', outcome: 'Away', line: null }),
    leg({ player: null, market: 'h2h', outcome: 'Home', line: null }),
  ]), 'incompatible'), true);
  assert.equal(hasWarning(calculate([
    leg({ player: null, market: 'spreads', outcome: 'Away', line: 3.5 }),
    leg({ player: null, market: 'spreads', outcome: 'Home', line: -3.5 }),
  ]), 'incompatible'), true);
  assert.equal(hasWarning(calculate([
    leg({ market: 'player_1st_td', outcome: 'Yes', line: null }),
    leg({ market: 'player_1st_td', player: 'Another Player', outcome: 'Yes', line: null }),
  ]), 'incompatible'), true);
});
