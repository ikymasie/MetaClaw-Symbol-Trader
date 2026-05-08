
import os

path = "/Users/ikymasie/Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/Program Files/MetaTrader 5/config/common.ini"

if not os.path.exists(path):
    print(f"File not found: {path}")
    exit(1)

with open(path, 'rb') as f:
    content = f.read()

# Try decoding as UTF-16
try:
    text = content.decode('utf-16')
    print("Detected UTF-16 encoding")
except UnicodeDecodeError:
    text = content.decode('utf-8', errors='ignore')
    print("Detected non-UTF-16 encoding")

lines = text.splitlines()
new_lines = []
in_experts = False

for line in lines:
    clean_line = line.strip()
    if clean_line == "[Experts]":
        in_experts = True
    elif clean_line.startswith("[") and clean_line.endswith("]"):
        in_experts = False
    
    if in_experts:
        if clean_line.startswith("Enabled="):
            new_lines.append("Enabled=1")
            continue
        if clean_line.startswith("AllowDllImport="):
            new_lines.append("AllowDllImport=1")
            continue
        if clean_line.startswith("Api="):
            new_lines.append("Api=1")
            continue
    
    new_lines.append(line)

# Join back
new_text = "\r\n".join(new_lines)
with open(path, 'wb') as f:
    f.write(new_text.encode('utf-16'))

print("Updated common.ini with Experts settings enabled.")
