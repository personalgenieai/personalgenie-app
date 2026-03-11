"""
Matched Movies Table Viewer

This script displays matched movies in a clean table format for validation.
Shows Netflix title vs TMDb title with match percentage.
"""

import csv
from tabulate import tabulate

# Configuration
MATCHED_FILE = "matched_movies.csv"
ROWS_PER_PAGE = 50  # Number of rows to show at a time

def load_matches():
    """Load matched movies from CSV."""
    print("📂 Loading matched movies...\n")
    matches = []
    
    try:
        with open(MATCHED_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                matches.append(row)
        
        print(f"✓ Loaded {len(matches)} matched movies\n")
        return matches
    except FileNotFoundError:
        print(f"❌ File not found: {MATCHED_FILE}")
        print("   Run the matcher script first!")
        return []
    except Exception as e:
        print(f"❌ Error loading file: {e}")
        return []

def display_matches_table(matches, sort_by='similarity', ascending=False):
    """Display matches in a clean table format."""
    if not matches:
        print("No matches to display")
        return
    
    # Sort matches
    if sort_by == 'similarity':
        matches_sorted = sorted(matches, 
                               key=lambda x: float(x.get('similarity', '0%').rstrip('%')),
                               reverse=not ascending)
    elif sort_by == 'year':
        matches_sorted = sorted(matches, 
                               key=lambda x: x.get('year', ''),
                               reverse=not ascending)
    elif sort_by == 'date':
        matches_sorted = sorted(matches, 
                               key=lambda x: x.get('netflix_date', ''),
                               reverse=not ascending)
    elif sort_by == 'rating':
        matches_sorted = sorted(matches, 
                               key=lambda x: float(x.get('rating', '0') or '0'),
                               reverse=not ascending)
    else:
        matches_sorted = matches
    
    # Prepare table data
    table_data = []
    for idx, match in enumerate(matches_sorted, 1):
        netflix_title = match.get('netflix_title', '')
        tmdb_title = match.get('tmdb_title', '')
        year = match.get('year', '')
        similarity = match.get('similarity', '')
        rating = match.get('rating', 'N/A')
        netflix_date = match.get('netflix_date', '')
        
        # Truncate long titles
        netflix_short = netflix_title[:40] + '...' if len(netflix_title) > 40 else netflix_title
        tmdb_short = tmdb_title[:40] + '...' if len(tmdb_title) > 40 else tmdb_title
        
        # Format rating
        if rating and rating != 'N/A':
            try:
                rating = f"{float(rating):.1f}/10"
            except:
                rating = 'N/A'
        
        table_data.append([
            idx,
            netflix_short,
            tmdb_short,
            year,
            similarity,
            rating,
            netflix_date
        ])
    
    # Display table
    headers = ['#', 'Netflix Title', 'TMDb Title', 'Year', 'Match %', 'Rating', 'Watched']
    print(tabulate(table_data, headers=headers, tablefmt='grid'))

def display_paginated(matches, sort_by='similarity', ascending=False):
    """Display matches with pagination."""
    if not matches:
        print("No matches to display")
        return
    
    # Sort matches
    if sort_by == 'similarity':
        matches_sorted = sorted(matches, 
                               key=lambda x: float(x.get('similarity', '0%').rstrip('%')),
                               reverse=not ascending)
    elif sort_by == 'year':
        matches_sorted = sorted(matches, 
                               key=lambda x: x.get('year', ''),
                               reverse=not ascending)
    elif sort_by == 'date':
        matches_sorted = sorted(matches, 
                               key=lambda x: x.get('netflix_date', ''),
                               reverse=not ascending)
    elif sort_by == 'rating':
        matches_sorted = sorted(matches, 
                               key=lambda x: float(x.get('rating', '0') or '0'),
                               reverse=not ascending)
    else:
        matches_sorted = matches
    
    total = len(matches_sorted)
    page = 0
    
    while True:
        start_idx = page * ROWS_PER_PAGE
        end_idx = min(start_idx + ROWS_PER_PAGE, total)
        
        if start_idx >= total:
            page = 0
            start_idx = 0
            end_idx = min(ROWS_PER_PAGE, total)
        
        page_matches = matches_sorted[start_idx:end_idx]
        
        # Clear screen (optional)
        print("\n" * 2)
        print("=" * 120)
        print(f"Matched Movies - Page {page + 1} of {(total + ROWS_PER_PAGE - 1) // ROWS_PER_PAGE}")
        print(f"Showing {start_idx + 1}-{end_idx} of {total} movies")
        print(f"Sorted by: {sort_by} ({'ascending' if ascending else 'descending'})")
        print("=" * 120)
        print()
        
        # Prepare table data
        table_data = []
        for match in page_matches:
            netflix_title = match.get('netflix_title', '')
            tmdb_title = match.get('tmdb_title', '')
            year = match.get('year', '')
            similarity = match.get('similarity', '')
            rating = match.get('rating', 'N/A')
            netflix_date = match.get('netflix_date', '')
            
            # Truncate long titles
            netflix_short = netflix_title[:45] + '...' if len(netflix_title) > 45 else netflix_title
            tmdb_short = tmdb_title[:45] + '...' if len(tmdb_title) > 45 else tmdb_title
            
            # Format rating
            if rating and rating != 'N/A':
                try:
                    rating = f"{float(rating):.1f}"
                except:
                    rating = 'N/A'
            
            table_data.append([
                netflix_short,
                tmdb_short,
                year,
                similarity,
                rating,
                netflix_date
            ])
        
        # Display table
        headers = ['Netflix Title', 'TMDb Title', 'Year', 'Match', 'Rating', 'Watched']
        print(tabulate(table_data, headers=headers, tablefmt='grid'))
        
        # Navigation
        print("\n" + "=" * 120)
        print("Commands: [n]ext page | [p]revious | [s]ort | [f]ilter | [q]uit")
        choice = input("Enter command: ").strip().lower()
        
        if choice == 'n':
            page += 1
        elif choice == 'p':
            page = max(0, page - 1)
        elif choice == 's':
            print("\nSort by:")
            print("  1. Match percentage (default)")
            print("  2. Year")
            print("  3. Watch date")
            print("  4. Rating")
            sort_choice = input("Enter choice (1-4): ").strip()
            
            if sort_choice == '2':
                sort_by = 'year'
            elif sort_choice == '3':
                sort_by = 'date'
            elif sort_choice == '4':
                sort_by = 'rating'
            else:
                sort_by = 'similarity'
            
            asc = input("Ascending? (y/n): ").strip().lower() == 'y'
            return display_paginated(matches, sort_by, asc)
        elif choice == 'f':
            print("\nFilter options:")
            print("  1. By year")
            print("  2. By match % threshold")
            print("  3. By rating threshold")
            filter_choice = input("Enter choice (1-3): ").strip()
            
            if filter_choice == '1':
                year = input("Enter year (e.g., 2020): ").strip()
                filtered = [m for m in matches if m.get('year') == year]
                print(f"\nFiltered to {len(filtered)} movies from {year}")
                return display_paginated(filtered, sort_by, ascending)
            elif filter_choice == '2':
                threshold = input("Enter minimum match % (e.g., 90): ").strip()
                try:
                    threshold_val = float(threshold)
                    filtered = [m for m in matches 
                              if float(m.get('similarity', '0%').rstrip('%')) >= threshold_val]
                    print(f"\nFiltered to {len(filtered)} movies with ≥{threshold}% match")
                    return display_paginated(filtered, sort_by, ascending)
                except:
                    print("Invalid threshold")
            elif filter_choice == '3':
                threshold = input("Enter minimum rating (e.g., 7.0): ").strip()
                try:
                    threshold_val = float(threshold)
                    filtered = [m for m in matches 
                              if m.get('rating') and float(m.get('rating', 0)) >= threshold_val]
                    print(f"\nFiltered to {len(filtered)} movies with rating ≥{threshold}")
                    return display_paginated(filtered, sort_by, ascending)
                except:
                    print("Invalid threshold")
        elif choice == 'q':
            print("\nGoodbye!")
            break
        else:
            print("Invalid command")

def show_low_matches(matches, threshold=90):
    """Show movies with low match percentage for validation."""
    low_matches = [m for m in matches 
                   if float(m.get('similarity', '0%').rstrip('%')) < threshold]
    
    if not low_matches:
        print(f"\n✓ All matches are above {threshold}% similarity!")
        return
    
    print(f"\n⚠ Found {len(low_matches)} matches below {threshold}% - Review these:")
    print("=" * 120)
    
    table_data = []
    for match in low_matches:
        netflix_title = match.get('netflix_title', '')
        tmdb_title = match.get('tmdb_title', '')
        year = match.get('year', '')
        similarity = match.get('similarity', '')
        
        table_data.append([
            netflix_title[:50],
            tmdb_title[:50],
            year,
            similarity
        ])
    
    headers = ['Netflix Title', 'TMDb Title', 'Year', 'Match %']
    print(tabulate(table_data, headers=headers, tablefmt='grid'))

def main():
    print("=" * 120)
    print("Matched Movies Table Viewer")
    print("=" * 120)
    
    matches = load_matches()
    if not matches:
        return
    
    # Show statistics
    print("📊 Statistics:")
    print(f"   Total matches: {len(matches)}")
    
    # Year breakdown
    year_counts = {}
    for m in matches:
        year = m.get('year', 'Unknown')
        year_counts[year] = year_counts.get(year, 0) + 1
    
    print(f"   Years: {', '.join(sorted(year_counts.keys()))}")
    for year in sorted(year_counts.keys()):
        print(f"      {year}: {year_counts[year]} movies")
    
    # Match quality
    similarities = [float(m.get('similarity', '0%').rstrip('%')) for m in matches]
    avg_similarity = sum(similarities) / len(similarities) if similarities else 0
    print(f"   Average match: {avg_similarity:.1f}%")
    print()
    
    # Show low matches first
    show_low_matches(matches, threshold=90)
    
    print("\n")
    input("Press Enter to view all matches...")
    
    # Show paginated table
    display_paginated(matches)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nGoodbye!")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
