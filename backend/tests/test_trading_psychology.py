"""
Tests for the Trading Psychology layer (deterministic guards + composure +
scanner integration). Runs under pytest OR standalone:

    backend/venv/bin/python tests/test_trading_psychology.py
    backend/venv/bin/python -m pytest tests/test_trading_psychology.py
"""
import os
import sys
import types

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import trading_psychology as tp  # noqa: E402
from trading_psychology import (  # noqa: E402
    PositionDisciplineTracker,
    check_scale_in_allowed,
    check_strict_loser_cut,
    check_horizon_breach,
    check_thesis_invalidated,
    clamp_stop_never_wider,
)


# ── check_scale_in_allowed (averaging down) ─────────────────────────────
def test_scale_in_blocks_average_down_long():
    # LONG, price below avg entry, basket underwater → adding to a loser
    assert check_scale_in_allowed("LONG", 99.0, 100.0, -2.0).action == tp.BLOCK


def test_scale_in_blocks_average_down_short():
    # SHORT, price above avg entry → adding to a loser
    assert check_scale_in_allowed("SHORT", 101.0, 100.0, -2.0).action == tp.BLOCK


def test_scale_in_allows_scale_up_winner_long():
    assert check_scale_in_allowed("LONG", 101.0, 100.0, 1.5).action == tp.ALLOW


def test_scale_in_allows_scale_up_winner_short():
    assert check_scale_in_allowed("SHORT", 99.0, 100.0, 1.5).action == tp.ALLOW


def test_scale_in_disabled_always_allows():
    assert check_scale_in_allowed("LONG", 99.0, 100.0, -5.0,
                                  block_average_down=False).action == tp.ALLOW


def test_scale_in_no_basis_allows():
    assert check_scale_in_allowed("LONG", 99.0, 0.0, -5.0).action == tp.ALLOW


# ── clamp_stop_never_wider (stop is sacred) ─────────────────────────────
def test_clamp_rejects_wider_stop():
    assert clamp_stop_never_wider(1.0, 2.0) == 1.0     # wider proposed → keep tighter


def test_clamp_accepts_tighter_stop():
    assert clamp_stop_never_wider(1.0, 0.5) == 0.5     # tighter proposed → accept


def test_clamp_adds_stop_when_none():
    assert clamp_stop_never_wider(0.0, 1.5) == 1.5     # no stop yet → accept


def test_clamp_refuses_to_remove_stop():
    assert clamp_stop_never_wider(1.0, 0.0) == 1.0     # remove attempt → keep


# ── check_strict_loser_cut (strict losers / pay to see the flop) ────────
def test_strict_loser_winner_holds():
    assert check_strict_loser_cut(5.0, 0.0).action == tp.HOLD


def test_strict_loser_thesis_intact_within_bounds_holds():
    # the "pay to see the flop" allowance
    v = check_strict_loser_cut(-1.0, -1.0, max_adverse_excursion_usd=5.0, thesis_intact=True)
    assert v.action == tp.HOLD


def test_strict_loser_thesis_broken_cuts():
    assert check_strict_loser_cut(-1.0, -1.0, thesis_intact=False).action == tp.CUT_NOW


def test_strict_loser_mae_breach_cuts():
    v = check_strict_loser_cut(-6.0, -6.0, max_adverse_excursion_usd=5.0, thesis_intact=True)
    assert v.action == tp.CUT_NOW


# ── check_horizon_breach (day-trade → swing guard) ──────────────────────
def test_horizon_cuts_loser_held_too_long():
    v = check_horizon_breach(2000, -1.0, max_loser_hold_secs=1800)
    assert v.action == tp.CUT_NOW


def test_horizon_holds_winner_past_horizon():
    v = check_horizon_breach(2000, 3.0, max_loser_hold_secs=1800, max_position_hold_secs=1800)
    assert v.action == tp.HOLD


def test_horizon_cuts_breakeven_past_position_cap():
    v = check_horizon_breach(8000, 0.0, max_position_hold_secs=7200)
    assert v.action == tp.CUT_NOW


# ── check_thesis_invalidated ────────────────────────────────────────────
def test_thesis_long_cut_below_level():
    assert check_thesis_invalidated("LONG", 99.0, 100.0).action == tp.CUT_NOW


def test_thesis_short_cut_above_level():
    assert check_thesis_invalidated("SHORT", 101.0, 100.0).action == tp.CUT_NOW


def test_thesis_unset_holds():
    assert check_thesis_invalidated("LONG", 50.0, 0.0).action == tp.HOLD


# ── PositionDisciplineTracker ───────────────────────────────────────────
def test_tracker_mae_monotonic_and_peak():
    t = PositionDisciplineTracker("b")
    t.update(1, 2.0, 100.0, "LONG", 100.0, now=0.0)
    t.update(1, -3.0, 99.0, "LONG", 100.0, now=1.0)
    t.update(1, -1.0, 99.5, "LONG", 100.0, now=2.0)   # recovers, but MAE keeps worst
    st = t.get(1)
    assert st.mae_usd == -3.0
    assert st.peak_net == 2.0
    assert st.ticks_held == 3


def test_tracker_prune_drops_closed():
    t = PositionDisciplineTracker("b")
    t.update(1, 1.0, 100.0, "LONG", 100.0, now=0.0)
    t.update(2, 1.0, 100.0, "LONG", 100.0, now=0.0)
    t.prune({2})
    assert t.get(1) is None and t.get(2) is not None


def test_tracker_worst_open_mae():
    t = PositionDisciplineTracker("b")
    t.update(1, -2.0, 100.0, "LONG", 100.0, now=0.0)
    t.update(2, -5.0, 100.0, "LONG", 100.0, now=0.0)
    assert t.worst_open_mae() == -5.0
    assert PositionDisciplineTracker("empty").worst_open_mae() == 0.0


# ── BotVitalSigns composure / tilt ──────────────────────────────────────
def test_composure_loss_streak_triggers_tilt_and_zero_size():
    from bot_vital_signs import BotVitalSigns
    from bot_config import BotConfig
    cfg = BotConfig(tilt_loss_streak=3, tilt_cooldown_secs=900)
    vs = BotVitalSigns("b")
    for _ in range(3):
        vs.record_trade_outcome(-1.0, now=1000.0, cfg=cfg)
    assert vs.in_tilt_lockout(1000.0)
    assert vs.update_composure(0.0, now=1000.0, cfg=cfg) == "TILTED"
    assert vs.composure_qty_multiplier() == 0.0


def test_composure_win_streak_overconfident_half_size():
    from bot_vital_signs import BotVitalSigns
    from bot_config import BotConfig
    cfg = BotConfig(overconfidence_win_streak=4)
    vs = BotVitalSigns("b")
    for _ in range(4):
        vs.record_trade_outcome(1.0, now=10.0, cfg=cfg)
    assert vs.update_composure(0.0, now=10.0, cfg=cfg) == "OVERCONFIDENT"
    assert vs.composure_qty_multiplier() == 0.5


def test_composure_starts_calm_full_size():
    from bot_vital_signs import BotVitalSigns
    vs = BotVitalSigns("b")
    assert vs.composure_state == "CALM"
    assert vs.composure_qty_multiplier() == 1.0


def test_rolling_trade_count_windowed():
    from bot_vital_signs import BotVitalSigns
    vs = BotVitalSigns("b")
    vs.record_entry(100.0)
    vs.record_entry(200.0)
    vs.record_entry(5000.0)
    assert vs.rolling_trade_count(5000.0, window_secs=3600) == 1  # only 5000 within 1h
    assert vs.rolling_trade_count(5000.0, window_secs=10000) == 3


def test_loss_streak_resets_on_win():
    from bot_vital_signs import BotVitalSigns
    from bot_config import BotConfig
    cfg = BotConfig()
    vs = BotVitalSigns("b")
    vs.record_trade_outcome(-1.0, 1.0, cfg)
    vs.record_trade_outcome(-1.0, 2.0, cfg)
    assert vs.loss_streak == 2
    vs.record_trade_outcome(1.0, 3.0, cfg)
    assert vs.loss_streak == 0 and vs.win_streak == 1


# ── Engine-level: never-widen-stop, loser cut, session, verdict ─────────
def _make_engine(**cfg_kw):
    from bot_config import BotConfig
    from bot_vital_signs import BotVitalSigns
    from bot_engine import BotEngine
    cfg = BotConfig(symbol="Volatility 75 Index", **cfg_kw)
    return BotEngine("bot-eng", cfg, BotVitalSigns("bot-eng"))


def test_update_params_refuses_wider_stop_while_holding():
    e = _make_engine()
    e._params["stop_loss_pct"] = 1.0
    e.position_qty = 1.0
    e.position_side = "LONG"
    e.update_params({"stop_loss_pct": 5.0})       # try to widen
    assert e._params["stop_loss_pct"] == 1.0
    e.update_params({"stop_loss_pct": 0.5})       # tighten allowed
    assert e._params["stop_loss_pct"] == 0.5


def test_update_params_allows_change_when_flat():
    e = _make_engine()
    e._params["stop_loss_pct"] = 1.0
    e.position_qty = 0.0
    e.update_params({"stop_loss_pct": 3.0})
    assert e._params["stop_loss_pct"] == 3.0


def test_psych_loser_cut_mae_breach():
    e = _make_engine(max_adverse_excursion_usd=3.0)
    st = tp.PositionPsychState(ticket=1, side="LONG", entry_price=100.0, entry_ts=0.0,
                               mae_usd=-4.0)
    assert e._psych_loser_cut(st, net_profit=-4.0, current_price=99.0, side="LONG", now=10.0)


def test_psych_loser_cut_holds_winner():
    e = _make_engine(max_adverse_excursion_usd=3.0)
    st = tp.PositionPsychState(ticket=1, side="LONG", entry_price=100.0, entry_ts=0.0)
    assert e._psych_loser_cut(st, net_profit=2.0, current_price=101.0, side="LONG", now=10.0) is None


def test_session_giveback_halts_entries():
    e = _make_engine(rolling_giveback_pct=0.30)
    e.starting_equity = 100.0
    e._vital_signs._peak_equity = 120.0
    e.total_realized_pnl = -5.0   # equity 95 ≤ 120*0.7=84? no → not halted yet
    e._check_session_discipline(now=10.0)
    assert e._psych_halt_entries is False
    e.total_realized_pnl = -40.0  # equity 60 ≤ 84 → halt
    e._check_session_discipline(now=10.0)
    assert e._psych_halt_entries is True


def test_apply_review_verdicts():
    e = _make_engine()
    e.apply_position_review(7, "CUT_NOW", 1.0, "thesis broken", 0.0)
    assert 7 in e._force_close_tickets
    e.apply_position_review(8, "TIGHTEN", 0.5, "weakening", 0.0)
    assert e._tighten_tickets.get(8) == 0.5
    e.apply_position_review(9, "GIVE_ROOM", 1.0, "runner intact", 0.0)
    assert 9 in e._giveroom_tickets
    assert e._review_rationale[7] == "thesis broken"


# ── Scanner integration (fake MT5) ──────────────────────────────────────
class _FakePos:
    def __init__(self, ticket, profit, ptype, price_open=100.0, volume=0.1,
                 magic=0, symbol="", comment="", sl=0.0):
        self.ticket = ticket
        self.profit = profit
        self.commission = 0.0
        self.swap = 0.0
        self.type = ptype
        self.price_open = price_open
        self.price_current = price_open + (profit / 100.0)
        self.volume = volume
        self.magic = magic
        self.symbol = symbol
        self.comment = comment
        self.sl = sl


class _FakeInfo:
    filling_mode = 1
    volume_min = 0.01
    volume_step = 0.01
    point = 0.01
    trade_stops_level = 0
    digits = 2


class _FakeTick:
    bid = 100.0
    ask = 100.02


class _FakeResult:
    retcode = 10009  # TRADE_RETCODE_DONE
    price = 100.0
    comment = "done"


class _FakeMT5:
    POSITION_TYPE_BUY = 0
    POSITION_TYPE_SELL = 1
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_FILLING_RETURN = 2
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    TRADE_ACTION_DEAL = 1
    TRADE_ACTION_SLTP = 2
    ORDER_TIME_GTC = 0
    TRADE_RETCODE_DONE = 10009

    def __init__(self, positions):
        self._positions = positions
        self.sends = []

    def positions_get(self):
        return list(self._positions)

    def symbol_info(self, s):
        return _FakeInfo()

    def symbol_info_tick(self, s):
        return _FakeTick()

    def order_send(self, req):
        self.sends.append(req)
        # simulate close: drop the ticket from open positions
        if req.get("action") == self.TRADE_ACTION_DEAL and "position" in req:
            self._positions = [p for p in self._positions if p.ticket != req["position"]]
        return _FakeResult()

    def last_error(self):
        return "none"


def _install_fake_mt5(positions):
    fake = _FakeMT5(positions)
    mod = types.ModuleType("mt5_bridge")
    mod.mt5 = fake
    sys.modules["mt5_bridge"] = mod
    return fake


def test_scanner_cuts_loser_on_mae_exactly_one_order():
    from bot_engine import _stable_magic
    magic = _stable_magic("bot-eng")
    pos = _FakePos(ticket=111, profit=-5.0, ptype=0, magic=magic,
                   symbol="Volatility 75 Index")
    fake = _install_fake_mt5([pos])
    # max_adverse_excursion triggers a discipline CUT; no broker SL writes (sl_usd=0)
    e = _make_engine(max_adverse_excursion_usd=3.0, stop_loss_usd=0.0,
                     leverage_mode_enabled=False, take_profit_usd=0.0,
                     profit_retrace_enabled=True)
    n = e._close_profitable_positions("Volatility 75 Index", magic)
    deal_sends = [s for s in fake.sends if s.get("action") == fake.TRADE_ACTION_DEAL]
    assert n == 1
    assert len(deal_sends) == 1 and deal_sends[0]["position"] == 111


def test_scanner_does_not_cut_boost_on_discipline():
    from bot_engine import _stable_magic
    magic = _stable_magic("bot-eng")
    pos = _FakePos(ticket=222, profit=-5.0, ptype=0, magic=magic,
                   symbol="Volatility 75 Index", comment="TC_BOOST_bot-eng")
    fake = _install_fake_mt5([pos])
    e = _make_engine(max_adverse_excursion_usd=3.0, stop_loss_usd=0.0,
                     leverage_mode_enabled=False, take_profit_usd=0.0,
                     boost_max_loss_usd=30.0)
    e._boost_tickets.add(222)
    n = e._close_profitable_positions("Volatility 75 Index", magic)
    deal_sends = [s for s in fake.sends if s.get("action") == fake.TRADE_ACTION_DEAL]
    assert n == 0 and len(deal_sends) == 0   # boost exempt from discipline cut


def test_scanner_giveroom_never_holds_loser_past_hard_stop():
    from bot_engine import _stable_magic
    magic = _stable_magic("bot-eng")
    pos = _FakePos(ticket=333, profit=-5.0, ptype=0, magic=magic,
                   symbol="Volatility 75 Index", sl=0.0)
    fake = _install_fake_mt5([pos])
    e = _make_engine(stop_loss_usd=2.0, leverage_mode_enabled=False,
                     take_profit_usd=0.0, max_adverse_excursion_usd=0.0)
    e._giveroom_tickets.add(333)               # try to "give room" to a loser
    n = e._close_profitable_positions("Volatility 75 Index", magic)
    assert n == 1                               # hard SL still fires; giveroom ignored on losers


# ── standalone runner ───────────────────────────────────────────────────
if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for fn in fns:
        try:
            fn()
            passed += 1
            print(f"  PASS {fn.__name__}")
        except Exception as e:
            failed += 1
            print(f"  FAIL {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed} passed, {failed} failed ({len(fns)} total)")
    sys.exit(1 if failed else 0)
