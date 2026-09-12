import re

with open("frontend/src/components/fleet/BotWizard.tsx", "r") as f:
    content = f.read()

search_quote = 'No markets found matching "{categorySearch}"'
replace_quote = 'No markets found matching &quot;{categorySearch}&quot;'

content = content.replace(search_quote, replace_quote)

with open("frontend/src/components/fleet/BotWizard.tsx", "w") as f:
    f.write(content)
