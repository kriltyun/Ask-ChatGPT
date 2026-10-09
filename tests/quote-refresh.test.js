import test from 'node:test';
import assert from 'node:assert/strict';
import { refreshSelection } from '../src/lib/quote-refresh.js';
import { findPrice, marketKey } from '../src/lib/markets.js';

const savedAt = '2026-10-08T18:00:00Z';
const retrievedAt = '2026-10-08T19:00:00Z';
const original = (overrides = {}) => ({
  id: 'saved-selection', game_id: 'test-game', player: 'Test Quarterback',
  market: 'player_pass_yds', outcome: 'Over', line: 249.5,
  prices: [{ bookmaker: 'fanduel', price: -110, last_update: savedAt }],
  source_url: 'https://example.test/original-source', saved_at: savedAt,
  ...overrides,
});
const response = (overrides = {}) => ({
  status: 'connected', markets: [],
  props: [{ bookmaker: 'fanduel', market: 'player_pass_yds', updated_at: retrievedAt,
    outcomes: [{ name: 'Over', description: 'Test Quarterback', point: 249.5, price: 120 }] }],
  source: { name: 'Provider', url: 'https://example.test/current-source', retrieved_at: retrievedAt },
  ...overrides,
});

test('refresh preserves saved wager identity, source and original prices', () => {
  const selection = original();
  const result = refreshSelection(selection, response());
  assert.equal(marketKey(result), marketKey(selection));
  assert.equal(result.id, selection.id);
  assert.equal(result.saved_at, savedAt);
  assert.equal(result.source_url, selection.source_url);
  assert.deepEqual(result.saved_prices, selection.prices);
  assert.equal(result.prices[0].price, 120);
  assert.equal(result.prices[0].last_update, retrievedAt);
  assert.equal(result.refreshed_at, retrievedAt);
  assert.equal(result.prices_source.url, 'https://example.test/current-source');
  assert.equal(result.prices_status, 'connected');
  assert.equal(selection.prices[0].price, -110);
  assert.equal('saved_prices' in selection, false);
});

test('a threshold change never refreshes a different exact wager', () => {
  const data = response();
  data.props[0].outcomes[0].point = 259.5;
  const result = refreshSelection(original(), data);
  assert.deepEqual(result.prices, []);
  assert.equal(result.prices_status, 'unavailable');
  assert.equal(result.line, 249.5);
  assert.equal(result.saved_prices[0].price, -110);
});

test('exact bookmaker groups remain separate and a mismatched book line is excluded', () => {
  const data = response();
  data.props.push(
    { bookmaker: 'draftkings', market: 'player_pass_yds', updated_at: retrievedAt,
      outcomes: [{ name: 'Over', description: 'Test Quarterback', point: 249.5, price: -105 }] },
    { bookmaker: 'draftkings', market: 'player_pass_yds', updated_at: retrievedAt,
      outcomes: [{ name: 'Over', description: 'Test Quarterback', point: 259.5, price: 200 }] },
  );
  const result = refreshSelection(original(), data);
  assert.equal(result.prices.length, 2);
  assert.equal(findPrice(result, 'fanduel').price, 120);
  assert.equal(findPrice(result, 'draftkings').price, -105);
  assert.equal(findPrice(result, 'other-book'), null);
});

test('a disconnected provider never reuses historical prices as current', () => {
  const result = refreshSelection(original(), response({ status: 'disconnected' }));
  assert.deepEqual(result.prices, []);
  assert.equal(result.prices_status, 'disconnected');
  assert.equal(result.saved_prices[0].price, -110);
  assert.equal(result.saved_prices[0].last_update, savedAt);
});

test('subsequent refreshes retain the first saved price snapshot', () => {
  const first = refreshSelection(original(), response());
  const nextData = response();
  nextData.props[0].outcomes[0].price = 140;
  const second = refreshSelection(first, nextData);
  assert.equal(second.prices[0].price, 140);
  assert.equal(second.saved_prices[0].price, -110);
  assert.equal(first.prices[0].price, 120);
});

test('different player, outcome and game identities do not match', () => {
  for (const changes of [{ description: 'Another Quarterback' }, { name: 'Under' }]) {
    const data = response();
    Object.assign(data.props[0].outcomes[0], changes);
    assert.deepEqual(refreshSelection(original(), data).prices, []);
  }
  assert.deepEqual(refreshSelection(original(), response({ game_id: 'other-game' })).prices, []);
  assert.deepEqual(refreshSelection(original({ game_id: null }), response()).prices, []);
});

test('passing, anytime, multi-TD and first-scorer market definitions remain distinct', () => {
  const selection = original({ market: 'player_anytime_td', outcome: 'Yes', line: null });
  const differentMarket = (market) => response({ props: [{ bookmaker: 'fanduel', market,
    updated_at: retrievedAt, outcomes: [{ name: 'Yes', description: 'Test Quarterback', point: null, price: 150 }] }] });
  for (const market of ['player_pass_tds', 'player_tds_over', 'player_1st_td', 'player_team_1st_td']) {
    assert.deepEqual(refreshSelection(selection, differentMarket(market)).prices, []);
  }
  assert.equal(refreshSelection(selection, differentMarket('player_anytime_td')).prices[0].price, 150);
});

test('moneyline prices match exact outcomes without inventing a player', () => {
  const selection = original({ player: null, market: 'h2h', outcome: 'Home Team', line: null });
  const result = refreshSelection(selection, response({ props: [], markets: [{
    bookmaker: 'draftkings', market: 'h2h', updated_at: retrievedAt,
    outcomes: [{ name: 'Home Team', price: -150 }, { name: 'Away Team', price: 130 }],
  }] }));
  assert.equal(result.prices.length, 1);
  assert.equal(result.prices[0].player, null);
  assert.equal(result.prices[0].price, -150);
});

test('stale exact prices keep their source timestamp and are labeled stale', () => {
  const result = refreshSelection(original(), response({ status: 'stale' }));
  assert.equal(result.prices_status, 'stale');
  assert.equal(result.prices[0].last_update, retrievedAt);
});

test('invalid prices, absent responses and empty markets leave current prices unavailable', () => {
  const data = response();
  data.props[0].outcomes[0].price = 0;
  assert.deepEqual(refreshSelection(original(), data).prices, []);
  assert.deepEqual(refreshSelection(original(), null).prices, []);
  assert.deepEqual(refreshSelection(original(), response({ props: [] })).prices, []);
  assert.equal(refreshSelection(original(), null).refreshed_at, null);
});
