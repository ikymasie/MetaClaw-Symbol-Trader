import re

with open("frontend/src/components/fleet/BotWizard.tsx", "r") as f:
    content = f.read()

search_redeclare = """  const { categories, symbolsByCategory: SYMBOLS_BY_CATEGORY } = useMemo(() => {"""
replace_redeclare = """  const { categories, symbolsByCategory } = useMemo(() => {"""

content = content.replace(search_redeclare, replace_redeclare)

with open("frontend/src/components/fleet/BotWizard.tsx", "w") as f:
    f.write(content)
