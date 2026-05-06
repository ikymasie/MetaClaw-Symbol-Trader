import sys
import os
import math

# Add backend to path
sys.path.append(os.path.join(os.getcwd(), "backend"))

from vital_signs import get_hunger_multiplier
from position_sizer import PositionSizer

def test_hunger_multiplier():
    print("=== Testing Hunger Multiplier Scaling ===")
    test_cases = [
        (1.0, 50.0),    # $1 -> 50x
        (10.0, 20.0),   # $10 -> ~20x
        (50.0, 5.0),    # $50 -> ~5x
        (99.0, 1.1),    # $99 -> ~1.1x
        (100.0, 1.0),   # $100 -> 1x
        (500.0, 1.0),   # $500 -> 1x
    ]
    
    for balance, expected_approx in test_cases:
        mult = get_hunger_multiplier(balance)
        print(f"Balance: ${balance:6.2f} | Multiplier: {mult:6.2f}x")
        # Check if it's within a reasonable range or exactly 1.0
        if balance >= 100:
            assert mult == 1.0
        else:
            assert mult >= 1.0
            if balance == 1.0:
                assert mult == 50.0

def test_position_sizer_hunger():
    print("\n=== Testing PositionSizer Hunger Integration ===")
    sizer = PositionSizer(min_trades_for_kelly=20)
    
    # Case 1: Low trades, NO hunger (standard)
    qty, diag = sizer.get_qty(
        win_rate=0.6,
        avg_win=100,
        avg_loss=-50,
        total_trades=10,
        base_qty=1,
        hunger_multiplier=1.0
    )
    print(f"Standard (10 trades): qty={qty} | reason={diag['reason']}")
    assert qty == 1
    assert "Insufficient data (<20 trades)" in diag['reason']

    # Case 2: Low trades, WITH hunger ($1 account)
    qty, diag = sizer.get_qty(
        win_rate=0.6,
        avg_win=100,
        avg_loss=-50,
        total_trades=10,
        base_qty=50, # Strategy passes base_qty * multiplier
        hunger_multiplier=50.0,
        max_qty=100
    )
    print(f"Hunger (10 trades): qty={qty} | reason={diag['reason']}")
    # With hunger_multiplier=50, effective_min_trades becomes 5. 
    # Since total_trades=10 > 5, Kelly should fire!
    assert qty > 1
    assert "Kelly:" in diag['reason']
    assert diag.get("min_trades_adjusted") is True

    # Case 3: Very low trades (e.g. 2), even with hunger
    qty, diag = sizer.get_qty(
        win_rate=0.6,
        avg_win=100,
        avg_loss=-50,
        total_trades=2,
        base_qty=50,
        hunger_multiplier=50.0,
        max_qty=100
    )
    print(f"Hunger (2 trades): qty={qty} | reason={diag['reason']}")
    # 2 < 5, so still base_qty (which is already multiplied by hunger in strategy)
    assert qty == 50
    assert "Insufficient data (<5 trades)" in diag['reason']

def test_vital_signs_hunger():
    print("\n=== Testing VitalSignsMonitor Hunger Integration ===")
    from vital_signs import VitalSignsMonitor, VitalState
    
    # Create a fresh monitor instance for testing
    monitor = VitalSignsMonitor()
    
    # Set initial balance to $1
    monitor.set_initial_balance(1.0)
    
    # Check status at $1
    status = monitor.check(current_equity=1.0, daily_pnl=0.0)
    print(f"Status at $1: Hunger Multiplier = {status['hunger_multiplier']}x")
    assert status['hunger_multiplier'] == 50.0
    assert status['survival_state'] == "HEALTHY" # Still healthy, just hungry
    
    # Check prompt generation
    prompt = monitor.build_organism_system_prompt()
    print("\nGenerated Prompt Snippet:")
    # Find the hunger level line
    hunger_line = [line for line in prompt.split("\n") if "Hunger Level:" in line][0]
    print(hunger_line)
    assert "50.0x" in hunger_line
    assert "EXTREME" in hunger_line

    # Scale balance up to $100 (neutral)
    status = monitor.check(current_equity=100.0, daily_pnl=0.0)
    print(f"\nStatus at $100: Hunger Multiplier = {status['hunger_multiplier']}x")
    assert status['hunger_multiplier'] == 1.0
    
    prompt = monitor.build_organism_system_prompt()
    hunger_line = [line for line in prompt.split("\n") if "Hunger Level:" in line][0]
    print(hunger_line)
    assert "1.0x" in hunger_line
    assert "SATISFIED" in hunger_line

if __name__ == "__main__":
    try:
        test_hunger_multiplier()
        test_position_sizer_hunger()
        test_vital_signs_hunger()
        print("\nALL TESTS PASSED!")
    except AssertionError as e:
        print(f"\nTEST FAILED!")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
