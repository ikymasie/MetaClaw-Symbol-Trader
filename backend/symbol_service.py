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
                for _, row in df.iterrows():
                    name = str(row.get("Symbol", "")).strip()
                    if not name or name == "nan":
                        continue
                    
                    category = str(row.get("Category", sheet_name)).strip()
                    description = str(row.get("Description", "")).strip()
                    
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
        """Read broker suffix lazily so dotenv is loaded before we check it."""
        return os.getenv("MT5_SYMBOL_SUFFIX", "")

    def get_broker_symbol(self, clean_name: str) -> str:
        """
        Maps a 'clean' symbol name (e.g. EURUSD) to the broker-specific symbol (e.g. EURUSD_i).
        Uses the MT5_SYMBOL_SUFFIX environment variable (read at call time).
        """
        suffix = self._get_suffix()
        if not suffix:
            return clean_name

        # Don't double-append if suffix is already present
        if clean_name.endswith(suffix):
            return clean_name

        return f"{clean_name}{suffix}"

    def get_clean_symbol(self, broker_name: str) -> str:
        """
        Maps a broker-specific symbol (e.g. EURUSD_i) back to a clean name (e.g. EURUSD).
        """
        suffix = self._get_suffix()
        if not suffix:
            return broker_name

        if broker_name.endswith(suffix):
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
