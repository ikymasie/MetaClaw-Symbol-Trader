from symbol_service import symbol_service, to_mt5_symbol, to_research

class SymbolMapper:
    """
    Bidirectional mapper for symbol normalisation between MT5 execution and TradingAgents research.
    """
    def to_research(self, mt5_symbol: str) -> str:
        """
        Convert any symbol name (including MT5 broker symbols) to the YFinance research format.
        """
        return to_research(mt5_symbol)

    def to_execution(self, research_symbol: str) -> str:
        """
        Convert any symbol name to the broker-specific MT5 terminal format.
        """
        return to_mt5_symbol(research_symbol)

symbol_mapper = SymbolMapper()
