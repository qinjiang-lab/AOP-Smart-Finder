# wos_to_json_safe.py

import pandas as pd
import json
import os

# ------------------------------
# Get user input
# ------------------------------
input_word = os.environ.get("INPUT_WORD", "").strip()
input_file = os.environ.get("INPUT_FILE", "").strip()

if not input_word:
    raise SystemExit("❌ No INPUT_WORD has been received. Please run it via bat or set it in the environment variables.")

# print(f"[WOS_manage.py] Received input: {input_word}")
user_input = input_word

if not user_input.lower().endswith((".xls", ".xlsx")):
    if os.path.exists(user_input + ".xls"):
        input_file = user_input + ".xls"
    elif os.path.exists(user_input + ".xlsx"):
        input_file = user_input + ".xlsx"
    else:
        input_file = user_input + ".xls"
else:
    input_file = user_input

base_name = os.path.splitext(os.path.basename(input_file))[0]
# DOI
columns_to_extract = ["Article Title", "Abstract", "UT (Unique ID)", "DOI"]

# ------------------------------
# Read Excel
# ------------------------------
try:
    df = pd.read_excel(input_file)
except FileNotFoundError:
    print(f"Error: File '{input_file}' not found. Please check the path.")
    exit()
except Exception as e:
    print(f"Error reading Excel file: {e}")
    exit()

# ------------------------------
# 兼容性处理：WOS有时候导出的列名叫 'DI'
# ------------------------------
if "DOI" not in df.columns and "DI" in df.columns:
    df = df.rename(columns={"DI": "DOI"})
    print("Note: Renamed column 'DI' to 'DOI' for compatibility.")

if "UT (Unique ID)" not in df.columns:
    # 如果不在，再检查是否是 'UT (Unique WOS ID)'，如果是则改名
    if "UT (Unique WOS ID)" in df.columns:
        df = df.rename(columns={"UT (Unique WOS ID)": "UT (Unique ID)"})
        print("Note: Renamed column 'UT (Unique WOS ID)' to 'UT (Unique ID)' for compatibility.")
# ------------------------------
# Check if required columns exist
# ------------------------------
for col in columns_to_extract:
    if col not in df.columns:
        print(f"Error: Column '{col}' not found in the Excel file. Please make sure you exported 'DOI' and 'Abstract' fields from WOS.")
        exit()

df_extract = df[columns_to_extract]
df_extract = df_extract.fillna("")
df_extract = df_extract.rename(columns={"UT (Unique ID)": "UT"})
data = df_extract.to_dict(orient="records")

output_dir = base_name
os.makedirs(output_dir, exist_ok=True)
WOS = "wos_articles"
output_file = os.path.join(output_dir, f"{WOS}.json")

# ------------------------------
# Save as JSON
# ------------------------------
with open(output_file, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"Successfully loaded {len(data)} articles.")
print()