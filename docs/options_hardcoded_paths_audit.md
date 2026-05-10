# Phase 20F/20G hardcoded path audit

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

## Fixed in Phase 20G

- Added centralized `tradingagents/dataflows/local_paths.py` for Alan local data warehouse env vars and defaults.
- `tradingagents/options/data_loader.py` and `tradingagents/dataflows/alan_business_db.py` now share the same path resolver/constants instead of duplicating literal defaults.
- Existing env overrides remain unchanged: `TRADINGAGENTS_SHFE_OPTIONS_DB`, `TRADINGAGENTS_METALS_DB`, and `TRADINGAGENTS_TUSHARE_DB`.
- SQLite access remains read-only by default.

## Remaining intentional hardcoded defaults

- Alan local data warehouse absolute defaults now live only in `tradingagents/dataflows/local_paths.py`.
- These are currently acceptable because every path is env-overridable and the defaults are Alan-local convenience defaults, not portable external-user requirements.

## Follow-up candidates

- If this project is prepared for external users, replace Alan-specific data defaults with documentation-only examples and require explicit env vars.
- Keep scanning for non-options hardcoded service URLs/timeouts separately; those were outside this options maintainability slice.
