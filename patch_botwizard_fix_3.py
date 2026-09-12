import re

with open("frontend/src/components/fleet/BotWizard.tsx", "r") as f:
    content = f.read()

search_memo = """  const filteredCategories = useMemo(() => {
    return CATEGORIES.filter(cat =>
      cat.label.toLowerCase().includes(categorySearch.toLowerCase()) ||
      (SYMBOLS_BY_CATEGORY[cat.id] || []).some(s => s.ticker.toLowerCase().includes(categorySearch.toLowerCase()))
    );
  }, [categorySearch, SYMBOLS_BY_CATEGORY]);"""

replace_memo = """  const filteredCategories = useMemo(() => {
    return CATEGORIES.filter(cat =>
      cat.label.toLowerCase().includes(categorySearch.toLowerCase()) ||
      (SYMBOLS_BY_CATEGORY[cat.id] || []).some(s => s.ticker.toLowerCase().includes(categorySearch.toLowerCase()))
    );
  }, [CATEGORIES, categorySearch, SYMBOLS_BY_CATEGORY]);"""

content = content.replace(search_memo, replace_memo)

with open("frontend/src/components/fleet/BotWizard.tsx", "w") as f:
    f.write(content)
