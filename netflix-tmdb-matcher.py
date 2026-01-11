"""
Netflix Viewing History Matcher

This script matches your Netflix viewing history against the TMDb movie database
to find which 2020+ movies you've already watched.

Note: This only matches MOVIES. TV series episodes are filtered out.
"""

import csv
from collections import defaultdict
from difflib import SequenceMatcher
import re

# Configuration
NETFLIX_FILE = "NetflixViewingHistory.csv"
TMDB_FILE = "tmdb_movies_2020-2025.csv"
OUTPUT_FILE = "matched_movies.csv"
SIMILARITY_THRESHOLD = 1.00  # 100% similarity for fuzzy matching

def is_tv_show(title):
    """Detect if a title is likely a TV show episode."""
    tv_indicators = [
        r':\s*Season\s+\d+',
        r':\s*Limited Series',
        r':\s*Part\s+\d+',
        r':\s*Episode\s+\d+',
        r':\s*Chapter\s+\d+',
        r'Season\s+\d+:',
        r'S\d+E\d+',
    ]
    
    for pattern in tv_indicators:
        if re.search(pattern, title, flags=re.IGNORECASE):
            return True
    return False

def normalize_title(title):
    """Normalize title for better matching."""
    # Remove special characters and convert to lowercase
    title = re.sub(r'[^\w\s]', '', title.lower())
    
    # Remove common words
    title = re.sub(r'\b(the|a|an)\b', '', title)
    
    # Remove extra whitespace
    title = ' '.join(title.split())
    
    return title.strip()

def title_similarity(title1, title2):
    """Calculate similarity between two titles."""
    norm1 = normalize_title(title1)
    norm2 = normalize_title(title2)
    return SequenceMatcher(None, norm1, norm2).ratio()

def load_netflix_history():
    """Load Netflix viewing history and filter for movies only."""
    print("📺 Loading Netflix viewing history...")
    all_items = []
    movies_only = []
    
    try:
        with open(NETFLIX_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                title = row.get('Title', '').strip()
                date = row.get('Date', '').strip()
                if title:
                    all_items.append({'title': title, 'date': date})
                    
                    # Filter out TV shows
                    if not is_tv_show(title):
                        movies_only.append({
                            'title': title,
                            'date': date,
                            'normalized': normalize_title(title)
                        })
        
        print(f"   Total items: {len(all_items)}")
        print(f"   TV shows filtered out: {len(all_items) - len(movies_only)}")
        print(f"   Movies to match: {len(movies_only)}")
        return movies_only
    except FileNotFoundError:
        print(f"   ❌ File not found: {NETFLIX_FILE}")
        return []
    except Exception as e:
        print(f"   ❌ Error loading Netflix history: {e}")
        return []

def load_tmdb_movies():
    """Load TMDb movie database."""
    print("\n🎬 Loading TMDb movie database...")
    movies = []
    
    try:
        with open(TMDB_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                title = row.get('title', '').strip()
                year = row.get('year', '').strip()
                if title and year:
                    movies.append({
                        'title': title,
                        'year': year,
                        'normalized': normalize_title(title),
                        'release_date': row.get('release_date', ''),
                        'director': row.get('director', ''),
                        'genres': row.get('genres', ''),
                        'vote_average': row.get('vote_average', ''),
                        'runtime': row.get('runtime', ''),
                        'overview': row.get('overview', '')[:200]  # First 200 chars
                    })
        
        print(f"   Found {len(movies)} movies in TMDb database")
        
        # Show year breakdown
        year_counts = defaultdict(int)
        for m in movies:
            year_counts[m['year']] += 1
        
        print(f"   Breakdown by year:")
        for year in sorted(year_counts.keys()):
            print(f"      {year}: {year_counts[year]} movies")
        
        return movies
    except FileNotFoundError:
        print(f"   ❌ File not found: {TMDB_FILE}")
        print(f"   Make sure you've run the TMDb extractor first!")
        return []
    except Exception as e:
        print(f"   ❌ Error loading TMDb database: {e}")
        return []

def match_titles(netflix_movies, tmdb_movies):
    """Match Netflix titles against TMDb movies."""
    print("\n🔍 Matching Netflix movies with TMDb database...")
    
    matches = []
    unmatched = []
    
    for idx, netflix_item in enumerate(netflix_movies, 1):
        best_match = None
        best_similarity = 0
        
        # Try to find best match
        for movie in tmdb_movies:
            similarity = title_similarity(netflix_item['title'], movie['title'])
            
            if similarity > best_similarity and similarity >= SIMILARITY_THRESHOLD:
                best_similarity = similarity
                best_match = movie
        
        if best_match:
            matches.append({
                'netflix_title': netflix_item['title'],
                'netflix_date': netflix_item['date'],
                'tmdb_title': best_match['title'],
                'year': best_match['year'],
                'release_date': best_match['release_date'],
                'director': best_match['director'],
                'genres': best_match['genres'],
                'rating': best_match['vote_average'],
                'runtime': best_match['runtime'],
                'similarity': f"{best_similarity:.1%}",
                'overview': best_match['overview']
            })
        else:
            unmatched.append(netflix_item['title'])
        
        if idx % 100 == 0:
            print(f"   Processed {idx}/{len(netflix_movies)} titles...")
    
    print(f"\n   ✓ Matched {len(matches)} movies")
    print(f"   ⚠ Could not match {len(unmatched)} movies")
    
    return matches, unmatched

def save_results(matches, unmatched):
    """Save matched results to CSV."""
    if not matches:
        print("\n⚠ No matches found to save")
        return
    
    print(f"\n💾 Saving results to {OUTPUT_FILE}...")
    
    try:
        with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8') as f:
            fieldnames = [
                'netflix_title', 'netflix_date', 'tmdb_title', 'year', 
                'release_date', 'director', 'genres', 'rating', 'runtime',
                'similarity', 'overview'
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(matches)
        
        print(f"   ✓ Saved {len(matches)} matched movies")
        
        # Also save unmatched titles for reference
        if unmatched:
            unmatched_file = "unmatched_netflix_titles.txt"
            with open(unmatched_file, 'w', encoding='utf-8') as f:
                f.write("Netflix titles that couldn't be matched:\n")
                f.write("=" * 60 + "\n\n")
                for title in sorted(unmatched):
                    f.write(f"{title}\n")
            print(f"   ✓ Saved {len(unmatched)} unmatched titles to {unmatched_file}")
    
    except Exception as e:
        print(f"   ❌ Error saving results: {e}")

def analyze_matches(matches):
    """Analyze and print statistics about matched movies."""
    if not matches:
        return
    
    print("\n" + "=" * 60)
    print("📊 ANALYSIS - Movies from 2020-2025 You've Watched")
    print("=" * 60)
    
    # Count by year
    year_counts = defaultdict(int)
    for match in matches:
        year = match['year']
        if year and year.isdigit() and int(year) >= 2020:
            year_counts[year] += 1
    
    print("\n🎬 Movies watched by year:")
    print("-" * 40)
    total = 0
    for year in sorted(year_counts.keys()):
        count = year_counts[year]
        print(f"   {year}: {count} movies")
        total += count
    print("-" * 40)
    print(f"   TOTAL: {total} movies\n")
    
    # Count by genre (top 10)
    genre_counts = defaultdict(int)
    for match in matches:
        genres = match.get('genres', '')
        if genres:
            for genre in genres.split(', '):
                genre = genre.strip()
                if genre:
                    genre_counts[genre] += 1
    
    if genre_counts:
        print("🎭 Top genres watched:")
        print("-" * 40)
        sorted_genres = sorted(genre_counts.items(), key=lambda x: x[1], reverse=True)
        for genre, count in sorted_genres[:10]:
            print(f"   {genre}: {count} movies")
        print()
    
    # Top rated movies watched
    rated_movies = [m for m in matches if m.get('rating') and m['rating'] != '']
    if rated_movies:
        sorted_by_rating = sorted(rated_movies, 
                                 key=lambda x: float(x['rating']) if x['rating'] else 0, 
                                 reverse=True)
        
        print("⭐ Top rated movies you watched (TMDb rating):")
        print("-" * 40)
        for movie in sorted_by_rating[:10]:
            rating = movie.get('rating', 'N/A')
            title = movie.get('tmdb_title', 'Unknown')
            year = movie.get('year', '')
            print(f"   {rating}/10 - {title} ({year})")

def main():
    print("=" * 60)
    print("Netflix Viewing History → TMDb Movie Matcher")
    print("=" * 60)
    
    # Load data
    netflix_movies = load_netflix_history()
    if not netflix_movies:
        print("\n❌ No Netflix data to process")
        return
    
    tmdb_movies = load_tmdb_movies()
    if not tmdb_movies:
        print("\n❌ No TMDb data to process")
        return
    
    # Match titles
    matches, unmatched = match_titles(netflix_movies, tmdb_movies)
    
    # Save results
    save_results(matches, unmatched)
    
    # Analyze
    analyze_matches(matches)
    
    print("\n" + "=" * 60)
    print("✅ COMPLETE!")
    print("=" * 60)
    print(f"Results saved to: {OUTPUT_FILE}")
    print("=" * 60)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠ Interrupted by user")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
