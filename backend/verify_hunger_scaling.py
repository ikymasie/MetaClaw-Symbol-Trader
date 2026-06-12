import sys
import os

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from vital_signs import get_hunger_multiplier, get_signal_relaxation
from position_sizer import PositionSizer

def test_hunger_scaling():
    scenarios = [
        {"balance": 1000.0, "desc": "Standard Account"},
        {"balance": 100.0,  "desc": "Threshold Account"},
        {"balance": 10.0,   "desc": "Hungry Account"},
        {"balance": 1.0,    "desc": "Starving Account ($1 Goal)"},
    ]

    sizer = PositionSizer(min_trades_for_kelly=20)
    
    print(f"{'Balance':<12} | {'Hunger':<8} | {'Relaxation':<12} | {'Kelly Frac':<12} | {'Min Trades':<10}")
    print("-" * 65)

    for s in scenarios:
        bal = s["balance"]
        hunger = get_hunger_multiplier(bal)
        relax = get_signal_relaxation(hunger)
        
        # Test Kelly scaling
        # Standard fraction is 0.25 (Quarter-Kelly)
        base_frac = 0.25
        # Simulate get_qty logic for fraction
        boost = 1.0 + (hunger - 1.0) * (3.0 / 49.0) if hunger > 1.0 else 1.0
        boosted_frac = min(2.0, base_frac * boost)
        
        # Effective min trades
        eff_min = 5 if hunger > 1.0 else 20
        
        print(f"${bal:<10,.2f} | {hunger:<8.1f} | {relax['bb_std']:<12.2f} | {boosted_frac:<12.3f} | {eff_min:<10}")

if __name__ == "__main__":
    test_hunger_scaling()
