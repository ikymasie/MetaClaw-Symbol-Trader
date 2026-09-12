import re

with open("frontend/src/components/fleet/BotWizard.tsx", "r") as f:
    content = f.read()

# Fix the circular reference / out of order error because symbolsByCategory is defined AFTER filteredCategories
# I'll move it below the SYMBOLS_BY_CATEGORY block

search_insert = """  const filteredCategories = useMemo(() => {
    return CATEGORIES.filter(cat =>
      cat.label.toLowerCase().includes(categorySearch.toLowerCase()) ||
      (symbolsByCategory[cat.id] || []).some(s => s.ticker.toLowerCase().includes(categorySearch.toLowerCase()))
    );
  }, [categorySearch, symbolsByCategory]);

  const filteredSymbols = useMemo(() => {
    return (symbolsByCategory[category] ?? []).filter(s =>
      s.ticker.toLowerCase().includes(symbolSearch.toLowerCase()) ||
      s.name.toLowerCase().includes(symbolSearch.toLowerCase())
    );
  }, [symbolsByCategory, category, symbolSearch]);

  const { categories, symbolsByCategory: SYMBOLS_BY_CATEGORY } = useMemo(() => {"""

replace_insert = """  const { categories, symbolsByCategory: SYMBOLS_BY_CATEGORY } = useMemo(() => {"""

content = content.replace(search_insert, replace_insert)

search_after = """  const SYMBOLS_BY_CATEGORY = symbolsByCategory;"""
replace_after = """  const SYMBOLS_BY_CATEGORY = symbolsByCategory;

  const filteredCategories = useMemo(() => {
    return CATEGORIES.filter(cat =>
      cat.label.toLowerCase().includes(categorySearch.toLowerCase()) ||
      (SYMBOLS_BY_CATEGORY[cat.id] || []).some(s => s.ticker.toLowerCase().includes(categorySearch.toLowerCase()))
    );
  }, [categorySearch, SYMBOLS_BY_CATEGORY]);

  const filteredSymbols = useMemo(() => {
    return (SYMBOLS_BY_CATEGORY[category] ?? []).filter(s =>
      s.ticker.toLowerCase().includes(symbolSearch.toLowerCase()) ||
      s.name.toLowerCase().includes(symbolSearch.toLowerCase())
    );
  }, [SYMBOLS_BY_CATEGORY, category, symbolSearch]);"""

content = content.replace(search_after, replace_after)

with open("frontend/src/components/fleet/BotWizard.tsx", "w") as f:
    f.write(content)
