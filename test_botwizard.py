import re

with open("frontend/src/components/fleet/BotWizard.tsx", "r") as f:
    text = f.read()

# Let's check for any useMemo warnings in our file by running eslint manually on this file alone
