# Source-code rules

Keep calculations deterministic and side-effect free where possible. Parse timestamps as timezone-aware UTC; reject future/naive timestamps when point-in-time availability matters. Validate finite numeric values and units at boundaries. Do not add network calls to core calculation modules. Keep funding and price/basis accounting separate. Add known-answer and adversarial tests for every behavioral change.
