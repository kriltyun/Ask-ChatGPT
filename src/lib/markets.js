/** Research-only odds math. These helpers never quote a sportsbook parlay. */
export const STALE_PRICE_MS = 15 * 60 * 1000;

const text = (value) => String(value ?? '').normalize('NFKC').trim().replace(/\s+/g, ' ').toLowerCase();
const marketName = (value) => text(value).replace(/[\s-]+/g, '_');

function finiteNumber(value) {
  if (typeof value !== 'number' && typeof value !== 'string') return null;
  if (typeof value === 'string' && !value.trim()) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

/** American odds use +100 or greater, or -100 or lower; zero is never a price. */
export function normalizePrice(value) {
  const price = finiteNumber(value);
  return price !== null && Math.abs(price) >= 100 ? price : null;
}

export function americanToDecimal(odds) {
  const price = normalizePrice(odds);
  if (price === null) return null;
  return price > 0 ? 1 + price / 100 : 1 + 100 / Math.abs(price);
}

export function decimalToAmerican(decimal) {
  const value = finiteNumber(decimal);
  if (value === null || value <= 1) return null;
  return Math.round(value >= 2 ? (value - 1) * 100 : -100 / (value - 1));
}

/** This is a price's break-even probability, never a model probability. */
export function breakEvenProbability(odds) {
  const decimal = americanToDecimal(odds);
  return decimal === null ? null : 1 / decimal;
}

function threshold(line) {
  if (line === undefined || line === null || line === '') return null;
  const number = finiteNumber(line);
  return number === null ? String(line) : number;
}

/** Identity preserves exact betting lines and distinct provider market definitions. */
export function marketKey(leg) {
  return JSON.stringify([
    String(leg?.game_id ?? ''),
    text(leg?.player),
    marketName(leg?.market),
    text(leg?.outcome),
    threshold(leg?.line),
  ]);
}

function timeOf(value) {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (typeof value !== 'string' || !value.trim()) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * Match only the requested bookmaker and, when supplied on a quote, its exact
 * market identity. The newest matching quote wins; an invalid price stays null.
 */
export function findPrice(leg, bookmaker) {
  const book = text(bookmaker);
  if (!book || !Array.isArray(leg?.prices)) return null;
  const quotes = leg.prices.filter((quote) => {
    if (!quote || text(quote.bookmaker) !== book) return false;
    if ('line' in quote && threshold(quote.line) !== threshold(leg.line)) return false;
    if ('market' in quote && marketName(quote.market) !== marketName(leg.market)) return false;
    if ('outcome' in quote && text(quote.outcome) !== text(leg.outcome)) return false;
    if ('player' in quote && text(quote.player) !== text(leg.player)) return false;
    if ('game_id' in quote && String(quote.game_id) !== String(leg.game_id)) return false;
    return true;
  });
  if (!quotes.length) return null;
  const latest = quotes.reduce((current, quote) =>
    (timeOf(quote.last_update) ?? -Infinity) > (timeOf(current.last_update) ?? -Infinity) ? quote : current);
  return { ...latest, price: normalizePrice(latest.price) };
}

export const findPriceForBookmaker = findPrice;

function subject(leg) {
  return leg.player || leg.outcome || 'Selection';
}

function oppositeSides(left, right) {
  return (left === 'over' && right === 'under') || (left === 'under' && right === 'over')
    || (left === 'yes' && right === 'no') || (left === 'no' && right === 'yes');
}

function sameGame(left, right) {
  return Boolean(left.game_id) && String(left.game_id) === String(right.game_id);
}

function touchdownLevel(leg) {
  const market = marketName(leg.market);
  const outcome = text(leg.outcome);
  if (market.includes('pass') || outcome === 'no' || outcome === 'under') return null;
  if (/anytime.*(?:touchdown|td)/.test(market)) return 1;
  if (/(?:two|2)_?(?:plus|or_more).*?(?:touchdown|td)|(?:touchdown|td).*?(?:two|2)_?(?:plus|or_more)/.test(market)) return 2;
  if (/^(?:player_)?(?:tds|touchdowns)(?:_over)?$/.test(market) && outcome === 'over') {
    const line = threshold(leg.line);
    if (line === 0.5) return 1;
    if (line === 1.5) return 2;
  }
  return null;
}

function incompatible(left, right) {
  if (!sameGame(left, right)) return false;
  const leftMarket = marketName(left.market);
  const rightMarket = marketName(right.market);
  const leftOutcome = text(left.outcome);
  const rightOutcome = text(right.outcome);
  const samePlayer = text(left.player) === text(right.player);
  if (leftMarket === rightMarket && samePlayer && threshold(left.line) === threshold(right.line)
    && oppositeSides(leftOutcome, rightOutcome)) return true;
  if (leftMarket !== rightMarket) return false;
  if (/^(?:h2h|moneyline)$/.test(leftMarket) && leftOutcome && rightOutcome && leftOutcome !== rightOutcome) return true;
  if (/^(?:spreads|spread)$/.test(leftMarket) && leftOutcome !== rightOutcome) {
    const leftLine = finiteNumber(left.line);
    const rightLine = finiteNumber(right.line);
    if (leftLine !== null && rightLine !== null && leftLine + rightLine === 0) return true;
  }
  // First scorer for a game has one winner. Team-first markets remain distinct.
  if (/(?:1st|first).*(?:td|touchdown)/.test(leftMarket) && !leftMarket.includes('team')
    && text(left.player) && text(right.player) && !samePlayer) return true;
  return false;
}

const cents = (amount) => Math.round((amount + Number.EPSILON) * 100) / 100;

/**
 * A synthetic product of single prices, not an executable sportsbook quote.
 * Same-game probabilities are deliberately never multiplied. Cross-game model
 * probabilities are used only when provided for every leg and clearly labeled.
 * A fourth clock option is available for deterministic callers and tests.
 */
export function calculateParlay(legs, stake, bookmaker, { now = Date.now() } = {}) {
  const selections = Array.isArray(legs) ? legs : [];
  const warnings = [];
  const addWarning = (type, message) => warnings.push({ type, message });
  let complete = selections.length > 0;
  let product = 1;
  const amount = finiteNumber(stake);
  if (amount === null || amount < 0) {
    complete = false;
    addWarning('invalid_stake', 'Enter a hypothetical stake of zero or more.');
  }

  const gameCounts = new Map();
  const playerCounts = new Map();
  const identities = new Set();
  for (const leg of selections) {
    if (!leg || typeof leg !== 'object') {
      complete = false;
      addWarning('invalid_leg', 'A selection is missing its market information.');
      continue;
    }
    if (leg.game_id) gameCounts.set(String(leg.game_id), (gameCounts.get(String(leg.game_id)) ?? 0) + 1);
    const player = text(leg.player);
    if (player) playerCounts.set(player, { count: (playerCounts.get(player)?.count ?? 0) + 1, name: leg.player });
    const key = marketKey(leg);
    if (identities.has(key)) {
      complete = false;
      addWarning('duplicate', `${subject(leg)}: the exact same market is included more than once.`);
    }
    identities.add(key);

    const quote = findPrice(leg, bookmaker);
    if (!quote) {
      complete = false;
      addWarning('missing_price', `${subject(leg)}: no exact price is available at ${bookmaker || 'the selected sportsbook'}.`);
      continue;
    }
    const decimal = americanToDecimal(quote.price);
    if (decimal === null) {
      complete = false;
      addWarning('invalid_price', `${subject(leg)}: this sportsbook price is invalid; zero is not American odds.`);
      continue;
    }
    product *= decimal;
    const updated = timeOf(quote.last_update);
    if (updated === null) addWarning('missing_timestamp', `${subject(leg)}: the price update time is unavailable.`);
    else if (quote.stale === true) addWarning('stale_price', `${subject(leg)}: the provider marks this price stale. Refresh before comparing.`);
    else if (now - updated > STALE_PRICE_MS) addWarning('stale_price', `${subject(leg)}: the selected price is older than 15 minutes. Refresh before comparing.`);
  }

  for (const count of gameCounts.values()) {
    if (count > 1) addWarning('same_game', 'Selections from the same game may be correlated. Multiplied singles are not a same-game parlay quote; a joint probability is unavailable.');
  }
  for (const { count, name } of playerCounts.values()) {
    if (count > 1) addWarning('repeated_player', `${name} appears in multiple legs; workload and outcomes may be dependent.`);
  }
  for (let leftIndex = 0; leftIndex < selections.length; leftIndex += 1) {
    for (let rightIndex = leftIndex + 1; rightIndex < selections.length; rightIndex += 1) {
      const left = selections[leftIndex];
      const right = selections[rightIndex];
      if (!left || !right) continue;
      if (incompatible(left, right)) {
        complete = false;
        addWarning('incompatible', `${subject(left)} and ${subject(right)} select incompatible outcomes in the same game.`);
      }
      if (sameGame(left, right) && text(left.player) && text(left.player) === text(right.player)) {
        const levels = [touchdownLevel(left), touchdownLevel(right)];
        if (levels.includes(1) && levels.includes(2)) addWarning('nested_outcome', `${left.player}: scoring two or more touchdowns already includes an anytime touchdown. These outcomes are nested.`);
      }
    }
  }
  if (!Number.isFinite(product)) {
    complete = false;
    addWarning('invalid_price', 'The multiplied price exceeds the supported numeric range.');
  }

  const distinctGames = selections.every((leg) => Boolean(leg?.game_id)) && gameCounts.size === selections.length;
  const suppliedProbabilities = selections.length > 0 && selections.every((leg) =>
    typeof leg?.probability === 'number' && Number.isFinite(leg.probability) && leg.probability >= 0 && leg.probability <= 1);
  const jointProbability = complete && distinctGames && suppliedProbabilities
    ? selections.reduce((probability, leg) => probability * leg.probability, 1) : null;
  const decimal = complete ? product : null;
  const totalReturn = complete ? cents(amount * product) : null;
  return {
    decimal,
    totalReturn,
    profit: complete ? cents(totalReturn - amount) : null,
    complete,
    warnings,
    jointProbability,
    probabilityLabel: jointProbability === null ? 'Joint probability unavailable' : 'Independence approximation from supplied probabilities',
    quoteLabel: 'Synthetic calculation from multiplied single prices',
  };
}
