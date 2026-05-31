export function normalizeMarketCode(market) {
  return String(market || '').trim().toUpperCase();
}

export function marketCodesWithCapability(marketCatalog, capability, fallbackCodes) {
  const entries = Array.isArray(marketCatalog?.markets) ? marketCatalog.markets : [];
  const entriesWithCapability = entries.filter((entry) => (
    Object.prototype.hasOwnProperty.call(entry?.capabilities || {}, capability)
  ));
  if (entriesWithCapability.length === 0) {
    return fallbackCodes;
  }
  const codes = entriesWithCapability
    .filter((entry) => entry.capabilities?.[capability] === true)
    .map((entry) => normalizeMarketCode(entry.code))
    .filter(Boolean);
  return codes.length > 0 ? Array.from(new Set(codes)) : fallbackCodes;
}

export function marketOptionsForCapability({
  marketCatalog,
  capability,
  fallbackCodes,
  enabledMarkets,
  supportedMarkets,
}) {
  const eligibleMarkets = marketCodesWithCapability(
    marketCatalog,
    capability,
    fallbackCodes
  );
  const allowed = new Set(eligibleMarkets);
  const normalizeAllowed = (markets) => (
    Array.from(new Set(
      (markets || [])
        .map(normalizeMarketCode)
        .filter((market) => allowed.has(market))
    ))
  );

  const enabled = normalizeAllowed(enabledMarkets);
  if (enabled.length > 0) {
    return enabled;
  }

  const supported = normalizeAllowed(supportedMarkets || ['US']);
  return supported.length > 0 ? supported : eligibleMarkets;
}
