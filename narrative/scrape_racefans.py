import requests
from bs4 import BeautifulSoup
import os
from urllib.parse import urljoin

def save_articles_from_archive_page(archive_url):
    """
    Scrapes an archive page from racefans.net, finds all article links,
    and saves each article page to a local directory.
    """
    try:
        # Create a directory based on the archive date for saving articles
        directory_name = archive_url.split('/')[-2]
        if not os.path.exists(directory_name):
            os.makedirs(directory_name)
        print(f"Saving articles to directory: {directory_name}")

        # Download the archive page content
        response = requests.get(archive_url)
        response.raise_for_status()  # Raise an exception for bad status codes
        soup = BeautifulSoup(response.text, 'html.parser')

        # Find all article links. This selector might need adjustment if the site's structure changes.
        article_links = soup.select('article h2.entry-title a')

        if not article_links:
            print("No article links found on the page with the current selector.")
            return

        print(f"Found {len(article_links)} articles to save.")

        for link in article_links:
            article_title = link.get_text(strip=True)
            article_url = urljoin(archive_url, link['href'])

            # Sanitize filename by removing invalid characters
            sanitized_title = "".join(c for c in article_title if c.isalnum() or c in (' ', '-', '_')).rstrip()

            # Download the individual article page
            article_response = requests.get(article_url)
            article_response.raise_for_status()

            # Save the article content to an HTML file
            file_path = os.path.join(directory_name, f"{sanitized_title}.html")
            with open(file_path, 'w', encoding='utf-8') as file:
                file.write(article_response.text)
            print(f"Successfully saved: {file_path}")

    except requests.exceptions.RequestException as e:
        print(f"An error occurred while downloading a page: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == '__main__':
    # Example usage: Replace with the desired URL
    url_to_scrape = 'https://www.racefans.net/2025/03/16/'
    save_articles_from_archive_page(url_to_scrape)