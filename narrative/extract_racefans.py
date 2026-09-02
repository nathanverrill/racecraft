import os
from bs4 import BeautifulSoup

def process_html_files(directory):
    """
    Finds all HTML files in a given directory, extracts the content of the
    <div class="entry-content"> section, and saves it to a new text file,
    stripping lines that start with "Advert |".
    """
    if not os.path.isdir(directory):
        print(f"Error: Directory '{directory}' not found.")
        return

    # Process each file in the specified directory
    for filename in os.listdir(directory):
        if filename.endswith(".html"):
            file_path = os.path.join(directory, filename)
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    soup = BeautifulSoup(f, 'html.parser')

                entry_content_div = soup.find('div', class_='entry-content')

                if entry_content_div:
                    # Extract the text content, preserving paragraph breaks
                    content_text = "\n\n".join([p.get_text(separator=' ', strip=True) for p in entry_content_div.find_all('p')])
                    
                    # Split the content into lines and filter out lines starting with "Advert |"
                    cleaned_lines = [line for line in content_text.splitlines() if not line.strip().startswith("Advert |")]
                    cleaned_content = "\n".join(cleaned_lines)

                    # Define the new filename
                    new_filename = f"{os.path.splitext(filename)[0]}.txt"
                    new_file_path = os.path.join(directory, new_filename)

                    # Save the cleaned content to the new text file
                    with open(new_file_path, 'w', encoding='utf-8') as new_f:
                        new_f.write(cleaned_content)
                    print(f"Successfully processed and saved: {new_file_path}")
                else:
                    print(f"Warning: 'entry-content' div not found in {filename}")

            except Exception as e:
                print(f"An error occurred while processing {filename}: {e}")

if __name__ == '__main__':
    # Example usage: Replace '2025-03-16' with the directory name created by the scraping script
    html_directory = 'australia'
    process_html_files(html_directory)