import os
import argparse
from pytube import YouTube, Channel, Search, Playlist
import time
import re
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound

def extract_video_id(url):
    """Extract video ID from a YouTube URL"""
    pattern = r'(?:v=|\/)([0-9A-Za-z_-]{11}).*'
    match = re.search(pattern, url)
    return match.group(1) if match else None

def get_video_urls(query, max_results=50, source_type='search'):
    """
    Get video URLs from a YouTube channel, search query, or playlist
    
    Parameters:
    query (str): Channel URL, search query, or playlist URL
    max_results (int): Maximum number of results to return
    source_type (str): Type of source ('search', 'channel', or 'playlist')
    
    Returns:
    list: List of video URLs
    """
    video_urls = []
    
    try:
        if source_type == 'channel':
            print(f"Fetching videos from channel: {query}")
            channel = Channel(query)
            video_urls = list(channel.video_urls)[:max_results]
            
        elif source_type == 'playlist':
            print(f"Fetching videos from playlist: {query}")
            playlist = Playlist(query)
            video_urls = list(playlist.video_urls)[:max_results]
            
        else:  # search
            print(f"Searching for videos: {query}")
            search_results = Search(query)
            count = 0
            while len(video_urls) < max_results:
                if count >= len(search_results.results):
                    break
                video = search_results.results[count]
                video_urls.append(f"https://www.youtube.com/watch?v={video.video_id}")
                count += 1
                
        print(f"Found {len(video_urls)} videos.")
        
    except Exception as e:
        print(f"Error getting videos: {str(e)}")
        
    return video_urls[:max_results]

def download_transcript(video_url, output_dir='transcripts', lang_code='en'):
    """
    Download transcript for a YouTube video using youtube_transcript_api
    
    Parameters:
    video_url (str): YouTube video URL
    output_dir (str): Directory to save transcripts
    lang_code (str): Language code for transcript (e.g., 'en', 'es')
    
    Returns:
    bool: Whether transcript was successfully downloaded
    """
    try:
        video_id = extract_video_id(video_url)
        if not video_id:
            print(f"Could not extract video ID from {video_url}")
            return False
        
        # Get video title
        try:
            yt = YouTube(video_url)
            video_title = yt.title
            # Clean video title for filename
            video_title = re.sub(r'[\\/*?:"<>|]', "", video_title)
        except Exception as e:
            print(f"Could not get video title: {str(e)}")
            video_title = video_id
        
        # Get transcript using youtube_transcript_api
        transcript_list = None
        transcript_language = None
        
        try:
            # First try: Get transcript in specified language
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=[lang_code])
            transcript_language = lang_code
        except:
            try:
                # Second try: List available transcripts
                available_transcripts = YouTubeTranscriptApi.list_transcripts(video_id)
                
                # Try to find a manually created transcript first
                manual_transcript = None
                for transcript in available_transcripts:
                    if not transcript.is_generated:
                        manual_transcript = transcript
                        break
                
                if manual_transcript:
                    transcript_list = manual_transcript.fetch()
                    transcript_language = manual_transcript.language_code
                else:
                    # Get any available transcript
                    for transcript in available_transcripts:
                        transcript_list = transcript.fetch()
                        transcript_language = transcript.language_code
                        break
            except Exception as e:
                print(f"No transcripts available for {video_url}: {str(e)}")
                return False
        
        if transcript_list:
            # Create output directory if it doesn't exist
            os.makedirs(output_dir, exist_ok=True)
            
            # Create filename
            filename = f"{video_title}_{video_id}.txt"
            filepath = os.path.join(output_dir, filename)
            
            # Save to file
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(f"Title: {video_title}\n")
                f.write(f"URL: {video_url}\n")
                f.write(f"Transcript Language: {transcript_language}\n\n")
                
                # Full text version
                f.write("--- Full Text ---\n\n")
                full_text = ' '.join([item['text'] for item in transcript_list])
                f.write(full_text)
                
                # Timestamped version
                f.write("\n\n--- Timestamped Text ---\n\n")
                for item in transcript_list:
                    start_seconds = int(item['start'])
                    minutes = start_seconds // 60
                    seconds = start_seconds % 60
                    f.write(f"[{minutes:02d}:{seconds:02d}] {item['text']}\n")
            
            print(f"Downloaded transcript for: {video_title}")
            return True
        else:
            print(f"No transcript found for: {video_url}")
            return False
            
    except TranscriptsDisabled:
        print(f"Transcripts are disabled for video: {video_url}")
        return False
    except NoTranscriptFound:
        print(f"No transcript found for video: {video_url}")
        return False
    except Exception as e:
        print(f"Error downloading transcript for {video_url}: {str(e)}")
        return False

def main():
    parser = argparse.ArgumentParser(description='Download YouTube transcripts')
    parser.add_argument('query', help='YouTube URL, channel URL, playlist URL, or search query')
    parser.add_argument('--type', choices=['video', 'channel', 'playlist', 'search'], default='search',
                      help='Type of query (default: search)')
    parser.add_argument('--max-results', type=int, default=50, help='Maximum number of videos to process')
    parser.add_argument('--lang', default='en', help='Transcript language code (default: en)')
    parser.add_argument('--output-dir', default='transcripts', help='Directory to save transcripts')
    parser.add_argument('--delay', type=float, default=0.5, help='Delay between videos (default: 0.5s)')
    
    args = parser.parse_args()
    
    # Handle different input types
    if args.type == 'video':
        video_urls = [args.query]
    elif args.type == 'channel':
        video_urls = get_video_urls(args.query, args.max_results, 'channel')
    elif args.type == 'playlist':
        video_urls = get_video_urls(args.query, args.max_results, 'playlist')
    else:  # search
        video_urls = get_video_urls(args.query, args.max_results, 'search')
    
    if not video_urls:
        print("No videos found.")
        return
    
    # Download transcripts for each video
    successful = 0
    for i, url in enumerate(video_urls):
        print(f"Processing video {i+1}/{len(video_urls)}")
        if download_transcript(url, args.output_dir, args.lang):
            successful += 1
        
        # Add delay between requests
        if i < len(video_urls) - 1:
            time.sleep(args.delay)
    
    print(f"\nDownloaded {successful} transcripts out of {len(video_urls)} videos.")

if __name__ == "__main__":
    main()