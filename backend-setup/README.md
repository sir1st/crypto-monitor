# Multi-account trading bot

Python system that runs a signal strategy across several Bybit accounts at once,
manages take-profit ladders and trailing stops, and reports over Telegram.

> ## ⚠️ This places real orders
>
> Unlike the dashboard in the repository root — which is strictly read-only — the
> scripts in this directory **open and close leveraged positions with real
> money**. They need API keys with trade permission.
>
> A misconfigured `position_usdt` or `leverage` will size trades wrong on every
> enabled account simultaneously. Run on testnet until the behaviour is exactly
> what you expect, and enable live accounts one at a time.
>
> Nothing here has automated tests.

## Relationship to the dashboard

Two separate systems that happen to share a repository and an exchange:

| | Root project (`../`) | This directory |
| --- | --- | --- |
| Language | TypeScript / Node | Python |
| Exchange access | Read-only | **Places and closes orders** |
| API key scope | Read-only keys | Trade-permission keys |
| State | `../data/vale.db` (SQLite) | JSON files in this directory |
| Config | `../.env` | `.env` + `accounts_config.json` + `trading_config.json` |

They do not import from each other and do not share configuration. The dashboard
can watch the accounts this bot trades, since both read the same exchange.

---

## Setup

Requires Python 3.10+ (developed on 3.12).

```bash
cd backend-setup
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

Then create your three local files from the committed examples:

```bash
cp .env.example .env
cp accounts_config.example.json accounts_config.json
cp trading_config.example.json trading_config.json
```

All three are gitignored. Fill in `.env` with testnet keys first and leave
`USE_TESTNET=true`.

Sanity-check credentials before running anything that trades:

```bash
python account_balance_report.py
```

---

## Configuration

Three files, with a deliberate split: **credentials only in `.env`**, account
identity and sizing in `accounts_config.json`, strategy behaviour in
`trading_config.json`.

### `.env` — credentials

The only place secrets live. `accounts_config.json` refers to these variables *by
name*, so a key never appears in a config file.

### `accounts_config.json` — who trades, and how big

```json
{
  "accounts": [
    {
      "name": "main",
      "api_key_env": "BYBIT_API_KEY",
      "api_secret_env": "BYBIT_API_SECRET",
      "enabled": true,
      "position_usdt": 10,
      "leverage": 10
    }
  ],
  "trading_symbol": "BTCUSDT",
  "parallel_execution": true
}
```

| Field | Meaning |
| --- | --- |
| `api_key_env` / `api_secret_env` | **Names** of `.env` variables, not the keys |
| `enabled` | `false` takes the account out of every trade |
| `position_usdt` | Margin committed per trade, in USDT |
| `leverage` | Leverage applied to that margin |
| `parallel_execution` | Submit to all accounts concurrently rather than in sequence |

**How size is computed** (`multi_account_trader.py`):

```python
qty = (position_usdt * leverage) / current_price
```

So `position_usdt` is the **margin**, and the resulting notional is
`position_usdt × leverage`. `position_usdt: 10` at `leverage: 40` is a 400 USDT
position, not a 10 USDT one. Each enabled account is sized by its own numbers, so
raising `leverage` multiplies exposure everywhere at once.

### `trading_config.json` — how positions are managed

| Key | Meaning |
| --- | --- |
| `auto_mode` | `false` keeps a human in the loop. Turning this on lets the bot act unattended |
| `take_profit_enabled` / `take_profit_mode` | `simple` or `strategic`, selecting which ladder below applies |
| `simple_tp_levels` | Ladder of `{profit_pct, size_pct}` — close `size_pct` of the position at `profit_pct` ROI |
| `strategic_tp_levels` | The wider-target ladder |
| `trailing_stop.target_roi_pct` | ROI at which the trailing stop activates |
| `trailing_stop.callback_rate` | How far price may retrace before the stop fires |
| `trailing_stop.check_interval_minutes` | Poll interval for the trailing logic |
| `signal_strength_threshold` | Minimum signal score to act on |
| `trading_filters.min_signal_strength` | `Weak` / `Moderate` / `Strong` gate |
| `trading_filters.allow_counter_trend` | Permit entries against the higher-timeframe trend |
| `enforce_highest_timeframe_trend` | Require agreement from the top timeframe |
| `skip_signals_for_open_positions` | Ignore new signals while a position is open (no stacking) |
| `trading_pairs` | Symbols the strategy watches |
| `symbol_config.<SYMBOL>` | Per-symbol `leverage` and `position_usdt` override |

`size_pct` values within a ladder are portions of the position; they do not have
to total 100 — whatever is left rides to the stop.

---

## The AI model used by this backend

`s1.py` can ask an LLM to comment on a signal before the bot acts on it
(`analyze_signal_with_ai`). It is optional — with no key set, that step is skipped
and the strategy still runs on its own indicators.

**The model is not hardcoded.** It is resolved at call time:

| Setting | Effect |
| --- | --- |
| `AI_MODEL` | The model id to use. `MODEL` is accepted as an alias |
| *(neither set)* | Falls back to `gpt-5-mini` |
| `OPENROUTER_API_KEY` set | Requests routed via `https://openrouter.ai/api/v1` |
| `OPENROUTER_API_KEY` unset | Requests go to OpenAI using `OPENAI_API_KEY` |

```env
# OpenAI directly — bare model ids
AI_MODEL=gpt-5-mini
OPENAI_API_KEY=sk-...

# or via OpenRouter — "vendor/model" ids, which unlocks Claude too
AI_MODEL=anthropic/claude-sonnet-5
OPENROUTER_API_KEY=sk-or-...
```

Two things to know:

- An unknown model id fails **at call time**, not at startup. Verify the id
  against your provider's model list.
- This is separate from the dashboard's AI layer in `../server/ai/`. That one has
  its own registry, its own `AI_MODEL`/`AI_PROVIDER` in `../.env`, and supports
  Anthropic natively. The two do not share configuration, so you can run
  different models in each.

The response is recorded on the decision as `ai_analysis.model`, so
`trading_decision_history.json` shows which model produced each comment.

---

## Components

| Script | Role |
| --- | --- |
| `s1.py` | Multi-timeframe EMA-cross strategy. Consumes Bybit WebSocket mark prices and emits signals |
| `smi_indicator.py` | Stochastic Momentum Index, used to detect trend exhaustion |
| `trade_manager.py` | Opens and manages positions; the main trading loop. Imports `multi_account_trader` |
| `multi_account_trader.py` | Fans a single decision out to every enabled account and computes per-account size |
| `tpsl.py` | Take-profit / stop-loss monitor; maintains trailing stops and writes `tpsl.json` |
| `martingale_manager.py` | Martingale ladder state, logged to `martingale_log.json` |
| `telegram_martingale_commands.py` | Telegram commands for the martingale ladder |
| `tele.py` | Telegram bot — pushes signals, accepts commands |
| `trading_watchdog.py` | Supervises the other processes and restarts them |
| `account_balance_report.py` | Balance, PnL and position-sizing report, optionally to Telegram |
| `report.py` | Simpler multi-account balance summary |
| `time_sync.py` | Keeps local time aligned with the exchange — Bybit rejects requests whose timestamp drifts |

**Run them from this directory.** Every script opens its config by relative path
(`open("trading_config.json")`), so launching from the repository root fails to
find the files — `cd backend-setup` first.

If `accounts_config.json` is missing, `trade_manager.py` logs *"Single account
mode"* and falls back to the `BYBIT_API_KEY` pair from `.env` instead of failing.
That is a useful way to try things with one account before setting up the
multi-account file.

Most scripts have a `__main__` block and can be run directly:

```bash
python s1.py                      # strategy / signals
python tpsl.py                    # TP/SL monitor
python tele.py                    # Telegram bot
python trading_watchdog.py        # supervisor
python account_balance_report.py  # one-off report
```

Read the top of a script before running it — several assume others are already
running and expect the JSON state files to exist.

---

## Files this directory writes

All gitignored: they are either private or meaningless on another machine.

| File | Contents |
| --- | --- |
| `all_trade_signals.json` | Latest signal per symbol |
| `pending_signals.json` | Signals awaiting execution |
| `session_state.json` | Trading session (Asia / London / NY) and per-session trade counts |
| `tpsl.json` | Live stop-loss levels, achieved ROI, real fill prices |
| `martingale_log.json` | Martingale ladder history |
| `trading_decision_history.json` | Decision audit trail |
| `stream_data.json` | Last WebSocket payload |
| `pnl_history.json` | Realised PnL history (name set by `pnl_history_file`) |
| `telegram_bot.log`, `tpsl_monitor.log`, `trade_manager_log.txt` | Runtime logs |
| `backups/` | Timestamped copies of the signal files |

Deleting them resets state; the bot recreates what it needs. Don't delete them
while it is running.

---

## Before enabling a live account

- `USE_TESTNET=true` and testnet keys, until the behaviour is understood.
- `auto_mode: false` so nothing acts unattended.
- One account `enabled: true`, the rest `false`.
- The smallest `position_usdt` and lowest `leverage` the exchange accepts.
- Confirm `position_usdt × leverage` is the notional you actually intend.
- `python account_balance_report.py` returns real balances.
- Watch a full open → TP → close cycle before adding a second account.

## Security

- Credentials belong in `.env` only. Never in a `.json`, never in a `.py`.
  A hardcoded Telegram token was removed from `account_balance_report.py`; it now
  reads `REPORTS_BOT_TOKEN` / `REPORTS_CHAT_ID`, falling back to
  `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`.
- Trade-permission keys can move your positions. Scope them to trading only —
  never enable withdrawal.
- Restrict keys by IP where Bybit allows it.
- The logs here are verbose and may contain account balances and order ids. They
  are gitignored; treat them as private if you copy them anywhere.
