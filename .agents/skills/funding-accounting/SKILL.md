---
name: funding-accounting
description: Implement and audit causal cross-venue funding signals, actual funding cash flows, price/basis attribution, equal-notional pair exposure and transaction costs.
---
# Funding accounting

- Normalize funding to an eight-hour equivalent using the documented actual interval; preserve original rate, units, event time and normalized value.
- Use only information available at signal time; exclude incomplete hourly bars and enter no earlier than the next tradable hourly open.
- For side s (+1 long, -1 short), notional N, funding rate r, cash flow is -s*N*r. Positive rates mean longs pay shorts. Test both signs with known-answer fixtures.
- Record funding at actual settlement times only while positions are open under venue settlement conventions.
- Keep long price PnL, short price PnL, net price/basis PnL, funding, fees, slippage and total net PnL separate. Do not double count funding inside price returns.
- Equal-notional legs; total gross portfolio exposure <=1.0x equity; no hidden leverage.
- Model missing bars, missed settlements, venue outages, contract changes and entry/exit assumptions explicitly. Never invent fills.
- Costs are frozen sensitivity inputs unless a versioned preregistered change is made.
