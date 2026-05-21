import pandas as pd
import logging
import os
from typing import List, Dict, Optional

logger = logging.getLogger("tradeclaw.symbol_service")

EXCEL_PATH = "Weltrade_Full_MT5_Symbols.xlsx"
# NOTE: Do NOT cache MT5_SYMBOL_SUFFIX at module level — symbol_service is
# imported before load_dotenv() runs in main.py. Read lazily at call time.

class SymbolService:
    _instance = None
    _symbols: List[Dict[str, str]] = []
    _categories: List[str] = []

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SymbolService, cls).__new__(cls)
            cls._instance._load_symbols()
        return cls._instance

    def _load_symbols(self):
        # Resolve path - check current dir then parent dir
        path = EXCEL_PATH
        if not os.path.exists(path):
            path = os.path.join("..", EXCEL_PATH)
            
        if not os.path.exists(path):
            logger.error(f"Excel file not found at {EXCEL_PATH} or ../{EXCEL_PATH}")
            return

        try:
            excel_file = pd.ExcelFile(path)
            seen_symbols = {} # name -> symbol_data
            categories = set()

            for sheet_name in excel_file.sheet_names:
                df = excel_file.parse(sheet_name)
                # ⚡ Bolt: Using zip() instead of df.iterrows() to avoid Pandas Series boxing overhead
                for name, category, description in zip(df.get("Symbol", [""]*len(df)), df.get("Category", [sheet_name]*len(df)), df.get("Description", [""]*len(df))):
                    name = str(name).strip()
                    if not name or name == "nan":
                        continue
                    
                    category = str(category if pd.notna(category) else sheet_name).strip()
                    description = str(description).strip()
                    
                    # If we haven't seen this symbol yet, or if the current entry has better data
                    if name not in seen_symbols:
                        symbol_data = {
                            "name": name,
                            "category": category,
                            "description": description if description != "nan" else "",
                            "sheet": sheet_name
                        }
                        seen_symbols[name] = symbol_data
                        categories.add(category)

            self._symbols = list(seen_symbols.values())
            self._categories = sorted(list(categories))
            logger.info(f"Loaded {len(self._symbols)} unique symbols from {EXCEL_PATH}")
        except Exception as e:
            logger.error(f"Error loading symbols from Excel: {e}")

    def get_all_symbols(self) -> List[Dict[str, str]]:
        return self._symbols

    def get_categories(self) -> List[str]:
        return self._categories

    @staticmethod
    def _get_suffix() -> str:
        """Read broker suffix lazily from config_manager."""
        from config_manager import config_manager
        return config_manager.get_mt5_symbol_suffix()

    def _get_suffix_for(self, clean_name: str) -> str:
        """
        Return the correct suffix for this symbol.
        Crypto symbols on Weltrade use no suffix; all others use MT5_SYMBOL_SUFFIX.
        Override via MT5_CRYPTO_SYMBOL_SUFFIX env var (default: empty string).
        """
        default_suffix = self._get_suffix()
        if not default_suffix:
            return ""

        # Look up the symbol's category
        upper = clean_name.upper()
        for sym in self._symbols:
            if sym["name"].upper() == upper:
                if sym.get("category", "").lower() == "crypto":
                    return os.getenv("MT5_CRYPTO_SYMBOL_SUFFIX", "")
                break

        return default_suffix

    def get_broker_symbol(self, clean_name: str) -> str:
        """
        Maps a 'clean' symbol name (e.g. EURUSD) to the broker-specific symbol (e.g. EURUSD_i).
        Category-aware: Crypto symbols skip the default suffix.
        """
        base_name = self.get_clean_symbol(clean_name)
        suffix = self._get_suffix_for(base_name)
        if not suffix:
            return base_name

        # Don't double-append if suffix is already present (case-insensitive)
        if clean_name.lower().endswith(suffix.lower()):
            return clean_name[:-len(suffix)] + suffix

        return f"{base_name}{suffix}"

    def get_clean_symbol(self, broker_name: str) -> str:
        """
        Maps a broker-specific symbol (e.g. EURUSD_i) back to a clean name (e.g. EURUSD).
        """
        suffix = self._get_suffix()
        if not suffix:
            return broker_name

        if broker_name.lower().endswith(suffix.lower()):
            return broker_name[:-len(suffix)]

        return broker_name


    def search_symbols(self, query: str) -> List[Dict[str, str]]:
        query = query.lower()
        return [
            s for s in self._symbols
            if query in s["name"].lower() or query in s["description"].lower() or query in s["category"].lower()
        ]

symbol_service = SymbolService()


def to_mt5_symbol(symbol: str) -> str:
    """
    Convert any symbol name to the broker-specific MT5 terminal format.

    Handles:
      - Legacy Yahoo-style suffixes (EURUSD=X → EURUSD)
      - Slash separators (EUR/USD → EURUSD)
      - Broker suffix (EURUSD → EURUSD_i) via MT5_SYMBOL_SUFFIX env var

    Usage:
        from symbol_service import to_mt5_symbol
        mt5_name = to_mt5_symbol("EURUSD")  # → "EURUSD_i"
    """
    clean = symbol.strip().upper().replace("=X", "").replace("/", "")
    return symbol_service.get_broker_symbol(clean)

to_execution = to_mt5_symbol

def to_research(symbol: str) -> str:
    """
    Convert any symbol name (including MT5 broker symbols) to the YFinance research format.
    
    EURUSD_i -> EURUSD=X
    BTCUSD -> BTC-USD
    AAPL_i -> AAPL
    """
    clean = symbol_service.get_clean_symbol(symbol).strip().upper()
    
    # Try to find the category to apply correct Yahoo Finance suffix
    category = ""
    for sym in symbol_service._symbols:
        if sym["name"].upper() == clean:
            category = sym.get("category", "").lower()
            break
            
    if category == "crypto":
        # Usually Crypto on Yahoo is BASE-QUOTE (e.g. BTC-USD)
        if clean.endswith("USD"):
            return clean[:-3] + "-USD"
        elif clean.endswith("EUR"):
            return clean[:-3] + "-EUR"
        # Fallback
        return clean
    elif category in ["forex majors", "forex minors", "forex exotics"]:
        # Forex on Yahoo Finance uses =X suffix
        return f"{clean}=X"
    elif category == "metals":
        # XAUUSD -> XAUUSD=X works on Yahoo for Spot Gold
        return f"{clean}=X"
    else:
        # Stocks, Indices, Commodities are returned as clean
        return clean
