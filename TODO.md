# Albion Helper — TODO

Goal: keep the base clean and extensible while we build the first production‑ready slice.

## Base (current focus)
- Define a minimal, stable domain model for market data (item, city, quality, prices, timestamps).
- Add a simple service layer that wraps external data sources (AODP now, others later).
- Establish consistent error types and HTTP error mapping for data endpoints.
- Centralize caching behavior (TTL per endpoint, cache keys, invalidation hooks).
- Add small but reliable integration tests for data endpoints (mocked HTTP).
- Keep API responses versionable (add `version` or `schema` fields where appropriate).
- Replace temporary chat tool-routing with a proper MCP tool-calling protocol (incl. streaming).

## Next small features (planned, not yet building)
- Item name resolution via catalog file (`ITEM_CATALOG_PATH`) with locale support.
- Multi‑city price comparison in a single request.
- Basic crafting margin calculation (inputs + outputs + city fees).
- Historical price snapshots (rolling window) for simple trend charts.
- Data freshness indicators in UI (timestamp, cached vs. live).
- Configurable cache TTL per endpoint.

## Architecture guardrails
- Avoid hard‑coding provider logic in routes; use service modules.
- Keep all external APIs behind interfaces (AODP client, future DB client).
- Make response schemas explicit and testable.
- Keep frontend consuming only stable API shapes (avoid implicit coupling).






current problems
the tool-badge doesent appear on other providers because of the format of something idk currently we have to test it multiple times to see the results
the mcp part should be retouched and optimised currently itworks but cvalude or other providers can create wierd results like 


the output should have the md format for the markdown rendering

future enchancments
we can add few definitions how the responses should look or even we can add custom visualizations for the responses for example graph or table





 here are few resources that we want to inlcude
 spells, armory (contains game modes and few game mode rules), buffshrines(Shrines are a type of reward found inside Randomized Dungeons which provide a party or player with a buff for a limited time.),buildings(Buildings are vital structures used by players to refine gathered materials, craft equipment and items, and improve item storage capacity.), corrupteddungeons(Corrupted Dungeons are a special form of solo dungeons found throughout the open world. After choosing a difficulty level, players enter and begin cleansing corrupted creatures, which grant Infamy points. ), 