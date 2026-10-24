# Research state

Store small state records only. Raw responses and normalized historical panels belong in external cache/artifact storage and must be referenced by URL, retrieval timestamp, request parameters, schema version and checksums.

- `run_manifest.json`: initial NOT_RUN state, no metrics.
- `universe_frontier.json`: resumable descending rank frontier, currently NOT_STARTED.
- Future run records should be immutable and uniquely identified. Append corrections as new records linked to superseded artifacts.
