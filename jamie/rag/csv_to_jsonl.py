import os
import csv
import json
import sys

def convert_csv_directory_to_jsonl(csv_directory_path):
    # 1. Increase the field size limit to handle large rows (Enron/CEAS_08)
    # We set it to the maximum allowed by the system
    max_limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(max_limit)
            break
        except OverflowError:
            # In case sys.maxsize is too large for some platforms
            max_limit = int(max_limit / 10)

    if not os.path.exists(csv_directory_path):
        print(f"Error: Directory '{csv_directory_path}' not found.")
        return

    files = [f for f in os.listdir(csv_directory_path) if f.endswith('.csv')]
    
    if not files:
        print("No CSV files found in the source directory.")
        return

    # Get current working directory for output
    output_dir = os.getcwd()
    print(f"Found {len(files)} files. Outputting JSONL files to: {output_dir}")

    for filename in files:
        csv_path = os.path.join(csv_directory_path, filename)
        jsonl_filename = os.path.splitext(filename)[0] + ".jsonl"
        jsonl_path = os.path.join(output_dir, jsonl_filename)

        try:
            with open(csv_path, mode='r', encoding='utf-8-sig', errors='replace') as csv_file:
                reader = csv.DictReader(csv_file)
                
                with open(jsonl_path, mode='w', encoding='utf-8') as jsonl_file:
                    count = 0
                    for row in reader:
                        json.dump(row, jsonl_file)
                        jsonl_file.write('\n')
                        count += 1
            
            print(f"Successfully converted: {filename} -> {jsonl_filename} ({count} rows)")
            
        except Exception as e:
            print(f"Failed to convert {filename}: {e}")

# --- CONFIGURATION ---
# Path to the folder where your CSVs are stored
source_csv_folder = './csv' 

if __name__ == "__main__":
    convert_csv_directory_to_jsonl(source_csv_folder)