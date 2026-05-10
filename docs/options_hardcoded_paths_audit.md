# Phase 20F hardcoded path audit

Project: TradingAgents options layer
Date: 2026-05-10

## Scope

Scanned Python sources for absolute WSL/Windows paths, output-directory defaults, and subprocess calls in the options/report/CLI workflow.

## Fixed in Phase 20F

- Options artifact output directories no longer default to an Alan workspace absolute path.
- Added `scripts/options_cli_common.py` with:
  - `TRADINGAGENTS_OPTIONS_OUTPUT_ROOT` as the common configurable artifact root;
  - per-kind overrides: `TRADINGAGENTS_OPTIONS_ANALYTICS_OUTPUT_DIR`, `TRADINGAGENTS_OPTIONS_REPORTS_OUTPUT_DIR`, and `TRADINGAGENTS_OPTIONS_RESEARCH_PACKS_OUTPUT_DIR`;
  - `sanitized_subprocess_env(...)` to avoid passing API keys/tokens/secrets into test or wrapper subprocesses;
  - `run_subprocess_checked(...)` with text pipes, `check=True`, and timeout defaults.
- Existing options CLI subprocess tests now use `run_subprocess_checked(...)` for consistent timeout and sanitized environment handling.

## Remaining intentional hardcoded defaults

- Alan local data warehouse defaults remain in:
  - `tradingagents/options/data_loader.py`
  - `tradingagents/dataflows/alan_business_db.py`
- These are currently acceptable because every path is env-overridable through existing variables such as `TRADINGAGENTS_SHFE_OPTIONS_DB`, `TRADINGAGENTS_METALS_DB`, and `TRADINGAGENTS_TUSHARE_DB`.
- SQLite access remains read-only by default.

## Follow-up candidates

- Add a centralized `tradingagents/dataflows/local_paths.py` helper so Alan warehouse defaults are declared once instead of duplicated across data loaders.
- If this project is prepared for external users, replace Alan-specific data defaults with documentation-only examples and require explicit env vars.
- Keep scanning for non-options hardcoded service URLs/timeouts separately; those were outside this options maintainability slice.
