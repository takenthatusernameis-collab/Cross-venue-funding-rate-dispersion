# Data policy

Do not commit raw historical market data. Use free public endpoints only, bounded requests and no credentials. Record source URL, retrieval timestamp, request parameters, pagination cursor, content hash, schema version, units, effective time, publication/availability time and normalization.

Current endpoint responses or current market-cap ranks are not proof of historical coverage. The historical-universe gate requires point-in-time cap/rank data, contract mappings, listing/delisting status, funding settlements and hourly tradable-price evidence. Synthetic fixtures are for software tests only.
