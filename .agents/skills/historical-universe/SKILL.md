---
name: historical-universe
description: Build and audit an expanding descending historical point-in-time market-cap universe with publication-time checks, delisted assets, exclusions and resumable cohort cursors.
---
# Historical universe

- Require both an observation effective/as-of timestamp and publication/availability timestamp; both must be no later than the ranking snapshot.
- Sort by market cap descending with deterministic asset-ID tie-break. Validate positive finite cap values, duplicates, stale records, units and historical symbol/contract mapping.
- Current ranks can discover instruments only. Never use them as historical ranks or restrict evaluation to a permanent top-N subset.
- Persist snapshot ID, rank frontier, last completed rank, completed/pending assets, explicit exclusions/reasons, source hashes, pagination cursors and resume state.
- After a cohort is exhausted, continue to the next lower-ranked cohort. Batch size is operational, not an eligibility cutoff.
- Include delisted assets where evidence allows; report gaps rather than silently survivorship-filtering.
- If free historical point-in-time cap evidence is unavailable, set BLOCKED_DATA_GATE and continue with source-independent work.
