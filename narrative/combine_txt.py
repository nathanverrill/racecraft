import os
import json

def combine_text_files_for_ai(directory, output_filename="combined_for_ai.jsonl"):
    """
    Reads all .txt files in a specified directory and formats their content
    into a JSON Lines file suitable for AI/ML models.

    Args:
        directory (str): The path to the directory containing the .txt files.
        output_filename (str): The name of the output JSON Lines file.
    """
    if not os.path.isdir(directory):
        print(f"Error: Directory '{directory}' not found.")
        return

    output_path = os.path.join(directory, output_filename)
    
    # Get a list of all .txt files that were pre-processed
    text_files = sorted([f for f in os.listdir(directory) if f.endswith(".txt")])
    
    if not text_files:
        print("No cleaned .txt files found to combine. Make sure the cleaning script was run first.")
        return

    print(f"Found {len(text_files)} text files. Combining them into '{output_filename}'...")

    try:
        with open(output_path, 'w', encoding='utf-8') as outfile:
            for filename in text_files:
                file_path = os.path.join(directory, filename)
                
                # Extract the title from the filename
                title = os.path.splitext(filename)[0].replace("Cleaned_Content_", "").strip()
                
                with open(file_path, 'r', encoding='utf-8') as infile:
                    text_content = infile.read().strip()
                
                # Create a dictionary for the article
                article_data = {
                    "title": title,
                    "text": text_content
                }
                
                # Write the JSON object as a single line
                outfile.write(json.dumps(article_data) + '\n')
            
        print(f"All text files have been successfully combined into {output_path}.")
    
    except Exception as e:
        print(f"An error occurred during file combination: {e}")

if __name__ == '__main__':
    # Example usage: Replace 'australia' with your target directory
    text_files_directory = 'australia'
    combine_text_files_for_ai(text_files_directory)