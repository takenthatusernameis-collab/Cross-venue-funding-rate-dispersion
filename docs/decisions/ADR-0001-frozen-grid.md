# ADR-0001: Freeze the parameter grid

- **Status:** Accepted for FVD-DISPERSION-V1.
- **Decision:** Exactly 108 configurations, stable IDs FVD001–FVD108; primary anchor FVD053.
- **Reason:** Preregistration limits researcher degrees of freedom and keeps selection/holdout policy auditable.
- **Consequence:** Do not change grid axes, order, values, threshold rule, costs, split fractions or holdout policy after seeing results. A changed premise requires a new experiment ID and preserved prior evidence.
- **Validation:** `PYTHONPATH=src python3 -m unittest discover -s tests -v` and `python3 scripts/validate_research.py`.
