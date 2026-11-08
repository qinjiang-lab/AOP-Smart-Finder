import os
import glob
import pandas as pd


def merge_wos_files():
    merge_dir = './merge'
    search_pattern = os.path.join(merge_dir, '*.xls*')

    # Find all matching files
    files = sorted(glob.glob(search_pattern))

    if not files:
        print(f"Error: No .xls or .xlsx files found in '{merge_dir}' directory.")
        return

    # Print file list
    print(f"Found {len(files)} files in '{merge_dir}':")
    for i, f in enumerate(files, 1):
        print(f"  {i}. {os.path.basename(f)}")

    # Ask for confirmation
    choice = input("\nDo you want to merge these files? (y/n): ").strip().lower()
    if choice != 'y':
        print("Merge operation cancelled.")
        return

    # Get output filename
    output_name = input("Enter the output filename (without extension): ").strip()
    if not output_name:
        print("Error: Output filename cannot be empty.")
        return

    # 保存到当前 merge 文件夹下
    output_path = os.path.join(merge_dir, f"{output_name}.xlsx")

    # 防止把之前生成的合并文件再读进去合并一次
    valid_files = [f for f in files if os.path.abspath(f) != os.path.abspath(output_path)]

    print(f"\nReading and merging {len(valid_files)} files...")
    df_list = []

    for file in valid_files:
        try:
            if file.endswith('.xls'):
                df = pd.read_excel(file, engine='xlrd')
            else:
                df = pd.read_excel(file, engine='openpyxl')
            df_list.append(df)
            print(f"  Successfully read: {os.path.basename(file)}")
        except Exception as e:
            print(f"  Failed to read {os.path.basename(file)}: {e}")

    if not df_list:
        print("Error: No files were successfully read. Merge aborted.")
        return

    # 核心改动：以第一张表的列结构为基准，强制对齐所有的表，防止列错位
    base_columns = df_list[0].columns
    standardized_df_list = []

    for df in df_list:
        # 只保留 base_columns 里的列，多余的丢弃，缺失的用空值填充
        standardized_df = df.reindex(columns=base_columns)
        standardized_df_list.append(standardized_df)

    # Concatenate all dataframes (依次向下追加)
    merged_df = pd.concat(standardized_df_list, ignore_index=True)

    # Deduplicate based on UT (Unique ID) if it exists
    if 'UT (Unique ID)' in merged_df.columns:
        original_len = len(merged_df)
        merged_df = merged_df.drop_duplicates(subset=['UT (Unique ID)'])
        print(f"Removed {original_len - len(merged_df)} duplicate records based on UT.")
    elif 'UT' in merged_df.columns:
        original_len = len(merged_df)
        merged_df = merged_df.drop_duplicates(subset=['UT'])
        print(f"Removed {original_len - len(merged_df)} duplicate records based on UT.")

    # Save to Excel
    try:
        merged_df.to_excel(output_path, index=False)
        print(f"\nMerge complete. Total records: {len(merged_df)}")
        print(f"File saved to: {os.path.abspath(output_path)}")
    except Exception as e:
        print(f"Error saving file: {e}")


if __name__ == "__main__":
    merge_wos_files()