import re

with open("frontend/src/components/fleet/BotWizard.tsx", "r") as f:
    content = f.read()

# First restore original
search_categories_memo = """    const filteredCategories = useMemo(() => {
      return CATEGORIES.filter(cat =>
        cat.label.toLowerCase().includes(categorySearch.toLowerCase()) ||
        (SYMBOLS_BY_CATEGORY[cat.id] || []).some(s => s.ticker.toLowerCase().includes(categorySearch.toLowerCase()))
      );
    }, [CATEGORIES, SYMBOLS_BY_CATEGORY, categorySearch]);"""

replace_categories_orig = """    const filteredCategories = CATEGORIES.filter(cat =>
      cat.label.toLowerCase().includes(categorySearch.toLowerCase()) ||
      SYMBOLS_BY_CATEGORY[cat.id].some(s => s.ticker.toLowerCase().includes(categorySearch.toLowerCase()))
    );"""

search_symbols_memo = """    const symbols = useMemo(() => {
      return (SYMBOLS_BY_CATEGORY[category] ?? []).filter(s =>
        s.ticker.toLowerCase().includes(symbolSearch.toLowerCase()) ||
        s.name.toLowerCase().includes(symbolSearch.toLowerCase())
      );
    }, [SYMBOLS_BY_CATEGORY, category, symbolSearch]);"""

replace_symbols_orig = """    const symbols = (SYMBOLS_BY_CATEGORY[category] ?? []).filter(s =>
      s.ticker.toLowerCase().includes(symbolSearch.toLowerCase()) ||
      s.name.toLowerCase().includes(symbolSearch.toLowerCase())
    );"""

content = content.replace(search_categories_memo, replace_categories_orig)
content = content.replace(search_symbols_memo, replace_symbols_orig)

# Now put useMemo hooks at the top level
search_insert = """  const { categories, symbolsByCategory } = useMemo(() => {"""
replace_insert = """  const filteredCategories = useMemo(() => {
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

content = content.replace(search_insert, replace_insert)

# Replace local variables in render functions
search_cat_render = """  const renderCategory = () => {
    const filteredCategories = CATEGORIES.filter(cat =>
      cat.label.toLowerCase().includes(categorySearch.toLowerCase()) ||
      SYMBOLS_BY_CATEGORY[cat.id].some(s => s.ticker.toLowerCase().includes(categorySearch.toLowerCase()))
    );"""
replace_cat_render = """  const renderCategory = () => {"""
content = content.replace(search_cat_render, replace_cat_render)

search_sym_render = """  const renderSymbol = () => {
    const symbols = (SYMBOLS_BY_CATEGORY[category] ?? []).filter(s =>
      s.ticker.toLowerCase().includes(symbolSearch.toLowerCase()) ||
      s.name.toLowerCase().includes(symbolSearch.toLowerCase())
    );"""
replace_sym_render = """  const renderSymbol = () => {
    const symbols = filteredSymbols;"""
content = content.replace(search_sym_render, replace_sym_render)


with open("frontend/src/components/fleet/BotWizard.tsx", "w") as f:
    f.write(content)
