import requests
import csv
import time
from datetime import datetime
import sys
import os
import json

# Configuration
API_KEY = "7b0117d6050971e8c7f3c786dc5ff038"  # Replace with your TMDb API key
OUTPUT_FILE = "tmdb_movies_2020-2025.csv"
PROGRESS_FILE = "tmdb_extraction_progress.json"
YEARS = [2020, 2021, 2022, 2023, 2024, 2025]
RATE_LIMIT_DELAY = 0.3  # Seconds between requests
MAX_RETRIES = 3  # Number of retries for failed requests
PAUSE_ON_ERROR = True  # Pause and ask user before continuing after errors

class TMDbExtractor:
    def __init__(self, api_key):
        self.api_key = api_key
        self.total_movies = 0
        self.failed_requests = 0
        self.session = requests.Session()
        self.extracted_ids = set()
        self.progress = self.load_progress()
        
    def load_progress(self):
        """Load progress from previous run."""
        if os.path.exists(PROGRESS_FILE):
            try:
                with open(PROGRESS_FILE, 'r') as f:
                    progress = json.load(f)
                    print(f"📂 Found previous progress file")
                    print(f"   Last year: {progress.get('last_year', 'N/A')}")
                    print(f"   Last page: {progress.get('last_page', 'N/A')}")
                    print(f"   Movies extracted: {progress.get('total_movies', 0)}")
                    return progress
            except Exception as e:
                print(f"⚠ Could not load progress file: {e}")
                return {"last_year": None, "last_page": 0, "total_movies": 0, "extracted_ids": []}
        return {"last_year": None, "last_page": 0, "total_movies": 0, "extracted_ids": []}
    
    def save_progress(self, year, page):
        """Save current progress."""
        progress = {
            "last_year": year,
            "last_page": page,
            "total_movies": self.total_movies,
            "extracted_ids": list(self.extracted_ids),
            "last_updated": datetime.now().isoformat()
        }
        try:
            with open(PROGRESS_FILE, 'w') as f:
                json.dump(progress, f, indent=2)
        except Exception as e:
            print(f"⚠ Could not save progress: {e}")
    
    def load_existing_movie_ids(self):
        """Load movie IDs from existing CSV to avoid duplicates."""
        if os.path.exists(OUTPUT_FILE):
            try:
                with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    ids = {int(row['id']) for row in reader if row.get('id')}
                    print(f"📂 Found existing CSV with {len(ids)} movies")
                    return ids
            except Exception as e:
                print(f"⚠ Could not load existing CSV: {e}")
        return set()
    
    def should_skip_year(self, year):
        """Check if we should skip this year based on progress."""
        last_year = self.progress.get('last_year')
        if last_year is None:
            return False
        return year < last_year
    
    def get_starting_page(self, year):
        """Get the starting page for a given year."""
        last_year = self.progress.get('last_year')
        if last_year == year:
            return self.progress.get('last_page', 1)
        return 1
        
    def fetch_with_retry(self, url, params, context=""):
        """Fetch URL with retry logic and proper error handling."""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self.session.get(url, params=params, timeout=15)
                
                # Check for rate limiting
                if response.status_code == 429:
                    print(f"  ⚠ Rate limited. Waiting 10 seconds...")
                    time.sleep(10)
                    continue
                
                # Check for successful response
                if response.status_code == 200:
                    data = response.json()
                    
                    # Validate response has expected structure
                    if 'results' in data or 'id' in data:
                        return data
                    else:
                        print(f"  ⚠ Unexpected response structure for {context}")
                        print(f"     Response keys: {list(data.keys())}")
                        if attempt < MAX_RETRIES:
                            print(f"     Retrying ({attempt}/{MAX_RETRIES})...")
                            time.sleep(2)
                        continue
                
                # Handle other error codes
                error_msg = f"HTTP {response.status_code}"
                try:
                    error_data = response.json()
                    error_msg = error_data.get('status_message', error_msg)
                except:
                    pass
                    
                print(f"  ⚠ Error fetching {context}: {error_msg}")
                
                if response.status_code in [401, 403]:
                    print(f"  ❌ Authentication error. Please check your API key.")
                    return None
                    
                if attempt < MAX_RETRIES:
                    print(f"     Retrying ({attempt}/{MAX_RETRIES})...")
                    time.sleep(2)
                    
            except requests.exceptions.Timeout:
                print(f"  ⚠ Timeout fetching {context}")
                if attempt < MAX_RETRIES:
                    print(f"     Retrying ({attempt}/{MAX_RETRIES})...")
                    time.sleep(2)
            except requests.exceptions.RequestException as e:
                print(f"  ⚠ Network error fetching {context}: {e}")
                if attempt < MAX_RETRIES:
                    print(f"     Retrying ({attempt}/{MAX_RETRIES})...")
                    time.sleep(2)
            except Exception as e:
                print(f"  ⚠ Unexpected error fetching {context}: {e}")
                if attempt < MAX_RETRIES:
                    print(f"     Retrying ({attempt}/{MAX_RETRIES})...")
                    time.sleep(2)
        
        self.failed_requests += 1
        return None

    def fetch_movie_details(self, movie_id, movie_title=""):
        """Fetch detailed information for a specific movie."""
        url = f"https://api.themoviedb.org/3/movie/{movie_id}"
        params = {
            "api_key": self.api_key,
            "append_to_response": "credits"
        }
        
        context = f"movie details for '{movie_title}' (ID: {movie_id})"
        return self.fetch_with_retry(url, params, context)

    def fetch_movies_from_year(self, year, page=1):
        """Fetch movies from a specific year."""
        url = "https://api.themoviedb.org/3/discover/movie"
        params = {
            "api_key": self.api_key,
            "primary_release_year": year,
            "page": page,
            "sort_by": "popularity.desc"
        }
        
        context = f"year {year}, page {page}"
        return self.fetch_with_retry(url, params, context)

    def extract_movie_data(self, details):
        """Extract relevant data from movie details."""
        if not details:
            return None
        
        # Find director
        director = ""
        if details.get("credits") and details["credits"].get("crew"):
            for person in details["credits"]["crew"]:
                if person.get("job") == "Director":
                    director = person.get("name", "")
                    break
        
        # Get top 10 cast members
        cast = ""
        if details.get("credits") and details["credits"].get("cast"):
            cast_names = [person.get("name", "") for person in details["credits"]["cast"][:10]]
            cast = ", ".join(cast_names)
        
        # Get genres
        genres = ""
        if details.get("genres"):
            genre_names = [g.get("name", "") for g in details["genres"]]
            genres = ", ".join(genre_names)
        
        # Get production companies
        production_companies = ""
        if details.get("production_companies"):
            company_names = [c.get("name", "") for c in details["production_companies"]]
            production_companies = ", ".join(company_names)
        
        return {
            "id": details.get("id", ""),
            "title": details.get("title", ""),
            "release_date": details.get("release_date", ""),
            "year": details.get("release_date", "")[:4] if details.get("release_date") else "",
            "runtime": details.get("runtime", ""),
            "overview": details.get("overview", "").replace("\n", " ").replace("\r", " "),
            "genres": genres,
            "director": director,
            "cast": cast,
            "vote_average": details.get("vote_average", ""),
            "vote_count": details.get("vote_count", ""),
            "popularity": details.get("popularity", ""),
            "budget": details.get("budget", ""),
            "revenue": details.get("revenue", ""),
            "original_language": details.get("original_language", ""),
            "production_companies": production_companies,
            "tagline": details.get("tagline", "").replace("\n", " ").replace("\r", " "),
        }

    def pause_on_error_prompt(self, year, page, error_description):
        """Pause and ask user how to proceed after an error."""
        print("\n" + "!" * 60)
        print(f"ERROR OCCURRED: {error_description}")
        print(f"Location: Year {year}, Page {page}")
        print(f"Movies extracted so far: {self.total_movies}")
        print(f"Failed requests: {self.failed_requests}")
        print("!" * 60)
        print("\nOptions:")
        print("  1. Continue to next year (skip remaining pages for this year)")
        print("  2. Retry this page")
        print("  3. Stop extraction and save what we have")
        print("  4. Continue anyway (ignore errors)")
        
        while True:
            choice = input("\nEnter choice (1-4): ").strip()
            if choice in ['1', '2', '3', '4']:
                return choice
            print("Invalid choice. Please enter 1, 2, 3, or 4.")

    def run(self):
        """Main extraction logic."""
        print("=" * 60)
        print("TMDb Movie Extractor (2020-2025) - Resumable")
        print("=" * 60)
        
        if self.api_key == "YOUR_API_KEY_HERE":
            print("❌ ERROR: Please edit the script and add your TMDb API key")
            print("   Get a free key at: https://www.themoviedb.org/settings/api")
            return
        
        # Load existing movie IDs to avoid duplicates
        self.extracted_ids = self.load_existing_movie_ids()
        self.total_movies = len(self.extracted_ids)
        
        # Test API key
        print("\n✓ Testing API key...")
        test_url = f"https://api.themoviedb.org/3/movie/550"
        test_params = {"api_key": self.api_key}
        test_result = self.fetch_with_retry(test_url, test_params, "API key test")
        
        if not test_result:
            print("❌ Failed to validate API key. Please check your key and try again.")
            return
        
        print("✓ API key validated successfully\n")
        
        # Determine if we're appending or creating new file
        file_mode = 'a' if os.path.exists(OUTPUT_FILE) else 'w'
        write_header = not os.path.exists(OUTPUT_FILE)
        
        if file_mode == 'a':
            print(f"📝 Appending to existing file: {OUTPUT_FILE}")
        else:
            print(f"📝 Creating new file: {OUTPUT_FILE}")
        
        # Open CSV file for writing
        with open(OUTPUT_FILE, file_mode, newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'id', 'title', 'release_date', 'year', 'runtime', 'overview', 
                'genres', 'director', 'cast', 'vote_average', 'vote_count', 
                'popularity', 'budget', 'revenue', 'original_language', 
                'production_companies', 'tagline'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            if write_header:
                writer.writeheader()
            
            for year in YEARS:
                # Skip years we've already completed
                if self.should_skip_year(year):
                    print(f"\n⏭️  Skipping year {year} (already completed)")
                    continue
                
                starting_page = self.get_starting_page(year)
                
                if starting_page > 1:
                    print(f"\n📅 Resuming year {year} from page {starting_page}...")
                else:
                    print(f"\n📅 Processing year {year}...")
                
                page = starting_page
                total_pages = 1
                consecutive_empty_pages = 0
                year_movies = 0
                
                while page <= total_pages:
                    # Fetch page of movies
                    data = self.fetch_movies_from_year(year, page)
                    
                    if not data:
                        if PAUSE_ON_ERROR:
                            choice = self.pause_on_error_prompt(year, page, f"Failed to fetch page {page}")
                            if choice == '1':  # Skip to next year
                                print(f"  → Skipping to next year...")
                                self.save_progress(year, page)
                                break
                            elif choice == '2':  # Retry
                                print(f"  → Retrying page {page}...")
                                continue
                            elif choice == '3':  # Stop
                                print(f"  → Stopping extraction...")
                                self.save_progress(year, page)
                                print(f"\n✓ Saved {self.total_movies} movies before stopping")
                                print(f"✓ Progress saved. Run again to resume from Year {year}, Page {page}")
                                return
                            elif choice == '4':  # Continue anyway
                                print(f"  → Continuing to next page...")
                                page += 1
                                self.save_progress(year, page)
                                continue
                        else:
                            print(f"  ⚠ Failed to fetch page {page}, skipping to next year...")
                            self.save_progress(year, page)
                            break
                    
                    total_pages = min(data.get("total_pages", 1), 500)
                    results = data.get("results", [])
                    
                    # Check for empty results
                    if not results:
                        consecutive_empty_pages += 1
                        print(f"  ⚠ Page {page}/{total_pages}: No results (empty page #{consecutive_empty_pages})")
                        
                        if consecutive_empty_pages >= 3:
                            print(f"  ⚠ Found 3 consecutive empty pages. Possible API issue.")
                            if PAUSE_ON_ERROR:
                                choice = self.pause_on_error_prompt(year, page, "Multiple consecutive empty pages")
                                if choice == '1':
                                    self.save_progress(year, page)
                                    break
                                elif choice == '2':
                                    consecutive_empty_pages = 0
                                    continue
                                elif choice == '3':
                                    self.save_progress(year, page)
                                    print(f"\n✓ Saved {self.total_movies} movies before stopping")
                                    return
                        
                        page += 1
                        self.save_progress(year, page)
                        time.sleep(1)
                        continue
                    
                    consecutive_empty_pages = 0
                    print(f"  Page {page}/{total_pages}: Found {len(results)} movies")
                    
                    page_new_movies = 0
                    for movie in results:
                        movie_id = movie.get("id")
                        movie_title = movie.get("title", "Unknown")
                        
                        if not movie_id:
                            continue
                        
                        # Skip if we already have this movie
                        if movie_id in self.extracted_ids:
                            continue
                        
                        # Fetch detailed movie information
                        details = self.fetch_movie_details(movie_id, movie_title)
                        if details:
                            movie_data = self.extract_movie_data(details)
                            if movie_data:
                                writer.writerow(movie_data)
                                csvfile.flush()  # Flush to disk immediately
                                self.extracted_ids.add(movie_id)
                                self.total_movies += 1
                                year_movies += 1
                                page_new_movies += 1
                                
                                # Progress indicator
                                if self.total_movies % 100 == 0:
                                    print(f"    ✓ Extracted {self.total_movies} movies total ({year_movies} new from {year})...")
                        
                        # Rate limiting
                        time.sleep(RATE_LIMIT_DELAY)
                    
                    if page_new_movies > 0:
                        print(f"    → Added {page_new_movies} new movies from this page")
                    else:
                        print(f"    → No new movies (all already in database)")
                    
                    page += 1
                    self.save_progress(year, page)
                    time.sleep(0.5)
                
                print(f"  ✓ Completed {year}. Extracted {year_movies} new movies from this year.")
                print(f"  ✓ Total so far: {self.total_movies} movies")
        
        # Clear progress file after successful completion
        if os.path.exists(PROGRESS_FILE):
            os.remove(PROGRESS_FILE)
            print("\n✓ Progress file cleared (extraction complete)")
        
        print("\n" + "=" * 60)
        print(f"🎉 Extraction complete!")
        print(f"   Total movies in database: {self.total_movies}")
        print(f"   Failed requests: {self.failed_requests}")
        print(f"   Output file: {OUTPUT_FILE}")
        print("=" * 60)

def main():
    extractor = TMDbExtractor(API_KEY)
    extractor.run()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠ Extraction interrupted by user")
        print("Progress has been saved. Run the script again to resume.")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
