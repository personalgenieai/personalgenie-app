"""
Amazon Prime Video Viewing History Extractor

This script uses Selenium to automate downloading your viewing history from Amazon Prime.
You'll need to log in manually, then the script will navigate and extract your watch history.

Requirements:
    pip install selenium
    
You'll also need Chrome/Chromium browser installed.
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import csv
import time
from datetime import datetime

# Configuration
OUTPUT_FILE = f"amazon_prime_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
WATCH_HISTORY_URL = "https://www.amazon.com/gp/video/settings/watch-history/ref=atv_set_watch-history"
SCROLL_PAUSE_TIME = 2  # Seconds to wait between scrolls
MAX_SCROLLS = 100  # Maximum number of scrolls (adjust based on your history size)

def setup_driver():
    """Set up and return a Chrome WebDriver."""
    options = webdriver.ChromeOptions()
    # Keep browser open so you can log in
    options.add_experimental_option("detach", True)
    # Optional: run in headless mode (uncomment if you want)
    # options.add_argument('--headless')
    
    try:
        driver = webdriver.Chrome(options=options)
        return driver
    except Exception as e:
        print(f"❌ Error setting up Chrome driver: {e}")
        print("\nMake sure you have Chrome installed.")
        print("You may need to install chromedriver:")
        print("  brew install chromedriver  # On Mac")
        return None

def wait_for_login(driver):
    """Wait for user to log in manually."""
    print("\n" + "="*60)
    print("PLEASE LOG IN TO AMAZON")
    print("="*60)
    print("A browser window has opened.")
    print("Please log in to your Amazon account.")
    print("Once you're logged in and see your watch history,")
    print("press Enter here to continue...")
    print("="*60)
    input()

def scroll_to_load_all_items(driver):
    """Scroll down the page to load all viewing history items."""
    print("\n📜 Scrolling to load all viewing history...")
    
    last_height = driver.execute_script("return document.body.scrollHeight")
    scroll_count = 0
    
    while scroll_count < MAX_SCROLLS:
        # Scroll down to bottom
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        
        # Wait for page to load
        time.sleep(SCROLL_PAUSE_TIME)
        
        # Calculate new scroll height and compare with last scroll height
        new_height = driver.execute_script("return document.body.scrollHeight")
        
        scroll_count += 1
        if scroll_count % 10 == 0:
            print(f"  Scrolled {scroll_count} times...")
        
        if new_height == last_height:
            print(f"  ✓ Reached end of history after {scroll_count} scrolls")
            break
            
        last_height = new_height
    
    return scroll_count

def extract_viewing_history(driver):
    """Extract viewing history from the page."""
    print("\n🎬 Extracting viewing history...")
    
    viewing_data = []
    
    try:
        # Wait for history items to load
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='watch-history-item']"))
        )
        
        # Find all viewing history items
        items = driver.find_elements(By.CSS_SELECTOR, "[data-testid='watch-history-item']")
        print(f"  Found {len(items)} items in viewing history")
        
        for idx, item in enumerate(items, 1):
            try:
                # Extract title
                title_elem = item.find_element(By.CSS_SELECTOR, "[data-testid='title']")
                title = title_elem.text if title_elem else "Unknown"
                
                # Extract metadata (season/episode info if available)
                metadata = ""
                try:
                    metadata_elem = item.find_element(By.CSS_SELECTOR, "[data-testid='metadata']")
                    metadata = metadata_elem.text if metadata_elem else ""
                except NoSuchElementException:
                    pass
                
                # Extract watch date
                watch_date = ""
                try:
                    date_elem = item.find_element(By.CSS_SELECTOR, "[data-testid='watch-date']")
                    watch_date = date_elem.text if date_elem else ""
                except NoSuchElementException:
                    pass
                
                # Extract image URL (thumbnail)
                image_url = ""
                try:
                    img_elem = item.find_element(By.CSS_SELECTOR, "img")
                    image_url = img_elem.get_attribute("src") if img_elem else ""
                except NoSuchElementException:
                    pass
                
                # Determine if it's a movie or TV show
                content_type = "TV Show" if "Season" in metadata or "Episode" in metadata else "Movie"
                
                # Parse season and episode if available
                season = ""
                episode = ""
                if "Season" in metadata:
                    parts = metadata.split(",")
                    for part in parts:
                        part = part.strip()
                        if part.startswith("Season"):
                            season = part.replace("Season", "").strip()
                        elif part.startswith("Episode") or part.startswith("Ep"):
                            episode = part.replace("Episode", "").replace("Ep", "").strip()
                
                viewing_data.append({
                    "title": title,
                    "content_type": content_type,
                    "metadata": metadata,
                    "season": season,
                    "episode": episode,
                    "watch_date": watch_date,
                    "image_url": image_url
                })
                
                if idx % 50 == 0:
                    print(f"    Processed {idx}/{len(items)} items...")
                    
            except Exception as e:
                print(f"  ⚠ Error extracting item {idx}: {e}")
                continue
        
        print(f"  ✓ Successfully extracted {len(viewing_data)} items")
        
    except TimeoutException:
        print("  ⚠ Timeout waiting for viewing history items")
    except Exception as e:
        print(f"  ❌ Error extracting viewing history: {e}")
    
    return viewing_data

def save_to_csv(data, filename):
    """Save viewing history data to CSV file."""
    if not data:
        print("❌ No data to save")
        return
    
    print(f"\n💾 Saving to {filename}...")
    
    fieldnames = ["title", "content_type", "metadata", "season", "episode", "watch_date", "image_url"]
    
    with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)
    
    print(f"✓ Saved {len(data)} items to {filename}")

def main():
    print("="*60)
    print("Amazon Prime Video Viewing History Extractor")
    print("="*60)
    
    # Set up browser
    driver = setup_driver()
    if not driver:
        return
    
    try:
        # Navigate to watch history page
        print(f"\n🌐 Navigating to Amazon Prime watch history...")
        driver.get(WATCH_HISTORY_URL)
        
        # Wait for user to log in
        wait_for_login(driver)
        
        # Scroll to load all items
        scroll_to_load_all_items(driver)
        
        # Extract viewing history
        viewing_data = extract_viewing_history(driver)
        
        # Save to CSV
        if viewing_data:
            save_to_csv(viewing_data, OUTPUT_FILE)
            print("\n" + "="*60)
            print("🎉 Extraction complete!")
            print(f"   Total items extracted: {len(viewing_data)}")
            print(f"   Output file: {OUTPUT_FILE}")
            print("="*60)
        else:
            print("\n⚠ No viewing history data found")
        
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
    
    finally:
        print("\nPress Enter to close the browser...")
        input()
        driver.quit()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠ Extraction interrupted by user")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
