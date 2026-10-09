import { marketKey, normalizePrice } from './markets.js';

/**
 * Refresh one saved wager against a response from its own game's odds endpoint.
 * Saved identity, source context and initial price snapshot remain unchanged.
 * A different threshold or missing quote never becomes the saved wager's price.
 */
export function refreshSelection(selection, response) {
  const savedPrices = Array.isArray(selection?.saved_prices)
    ? selection.saved_prices : Array.isArray(selection?.prices) ? selection.prices : [];
  const refreshed = {
    ...selection,
    saved_prices: savedPrices.map((quote) => ({ ...quote })),
    prices: [],
    prices_status: response?.status === 'disconnected' ? 'disconnected' : 'unavailable',
    refreshed_at: response?.source?.retrieved_at ?? null,
    prices_source: response?.source ? { ...response.source } : null,
  };
  if (!selection?.game_id || !response || response.status === 'disconnected'
    || (response.game_id != null && String(response.game_id) !== String(selection.game_id))) return refreshed;

  const identity = marketKey(selection);
  const markets = [
    ...(Array.isArray(response.markets) ? response.markets : []),
    ...(Array.isArray(response.props) ? response.props : []),
  ];
  for (const market of markets) {
    if (!market || !Array.isArray(market.outcomes) || !market.bookmaker) continue;
    for (const outcome of market.outcomes) {
      if (!outcome) continue;
      const candidate = {
        game_id: selection.game_id,
        player: outcome.description || null,
        market: market.market,
        outcome: outcome.name,
        line: outcome.point ?? null,
      };
      if (marketKey(candidate) !== identity) continue;
      const price = normalizePrice(outcome.price);
      if (price === null) continue;
      refreshed.prices.push({
        ...candidate,
        bookmaker: market.bookmaker,
        price,
        last_update: market.updated_at ?? null,
        retrieved_at: market.retrieved_at ?? response.source?.retrieved_at ?? null,
        stale: market.stale ?? null,
      });
    }
  }
  if (refreshed.prices.length) refreshed.prices_status = response.status === 'stale' ? 'stale' : 'connected';
  return refreshed;
}
