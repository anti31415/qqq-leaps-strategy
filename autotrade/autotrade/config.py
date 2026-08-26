from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    alpaca_api_key_id: str
    alpaca_api_secret_key: str
    alpaca_api_base_url: str
    alpaca_data_base_url: str
    signal_symbol: str
    vix_symbol: str
    rsi_period: int
    rsi_buy_below: float
    target_delta: float
    contract_target_days: int
    contract_day_tolerance: int
    force_exit_days_to_expiry: int
    short_call_dte: int
    short_call_otm_pct: float
    option_feed: str
    dry_run: bool
    root_dir: Path
    state_path: Path
    log_dir: Path
    data_start: str
    strategy_version: str
    email_notify_enabled: bool
    smtp_host: str
    smtp_port: int
    smtp_security: str
    smtp_username: str
    smtp_password: str
    smtp_from: str
    smtp_to: str


def load_settings() -> Settings:
    root_dir = Path(__file__).resolve().parents[1]
    _load_env_file(root_dir / ".env")

    sibling_env = root_dir.parents[1] / "tianbro_qqq_tqqq_strategy" / "autotrade" / ".env"
    _load_env_file(sibling_env)

    return Settings(
        alpaca_api_key_id=os.getenv("ALPACA_API_KEY_ID", ""),
        alpaca_api_secret_key=os.getenv("ALPACA_API_SECRET_KEY", ""),
        alpaca_api_base_url=os.getenv("ALPACA_API_BASE_URL", "https://paper-api.alpaca.markets"),
        alpaca_data_base_url=os.getenv("ALPACA_DATA_BASE_URL", "https://data.alpaca.markets"),
        signal_symbol=os.getenv("STRATEGY_SIGNAL_SYMBOL", "QQQ"),
        vix_symbol=os.getenv("STRATEGY_VIX_SYMBOL", "^VIX"),
        rsi_period=int(os.getenv("STRATEGY_RSI_PERIOD", "14")),
        rsi_buy_below=float(os.getenv("STRATEGY_RSI_BUY_BELOW", "35")),
        target_delta=float(os.getenv("STRATEGY_TARGET_DELTA", "0.70")),
        contract_target_days=int(os.getenv("STRATEGY_CONTRACT_TARGET_DAYS", "730")),
        contract_day_tolerance=int(os.getenv("STRATEGY_CONTRACT_DAY_TOLERANCE", "120")),
        force_exit_days_to_expiry=int(os.getenv("STRATEGY_FORCE_EXIT_DAYS_TO_EXPIRY", "180")),
        short_call_dte=int(os.getenv("STRATEGY_SHORT_CALL_DTE", "30")),
        short_call_otm_pct=float(os.getenv("STRATEGY_SHORT_CALL_OTM_PCT", "0.10")),
        option_feed=os.getenv("STRATEGY_OPTION_FEED", "indicative"),
        dry_run=_bool_env("DRY_RUN", True),
        root_dir=root_dir,
        state_path=root_dir / "state.json",
        log_dir=root_dir / "logs",
        data_start=os.getenv("STRATEGY_DATA_START", "2011-01-01"),
        strategy_version="qqq_leaps_tiered_vix_calls_live_v1",
        email_notify_enabled=_bool_env("EMAIL_NOTIFY_ENABLED", False),
        smtp_host=os.getenv("SMTP_HOST", ""),
        smtp_port=int(os.getenv("SMTP_PORT", "587")),
        smtp_security=os.getenv("SMTP_SECURITY", "starttls").strip().lower(),
        smtp_username=os.getenv("SMTP_USERNAME", ""),
        smtp_password=os.getenv("SMTP_PASSWORD", ""),
        smtp_from=os.getenv("SMTP_FROM", ""),
        smtp_to=os.getenv("SMTP_TO", ""),
    )
