import re
import random
import time
import traceback
from urllib.parse import urlencode

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

GOOGLE_MAPS_URL = "https://www.google.com/maps"
SHEET_NAME = "Leads_Data"
VERCEL_BASE_URL = "https://dental-clinic-nine-tau.vercel.app"
WAIT_SECONDS = 30
SCROLL_PAUSE_SECONDS = 2
MAX_SCROLLS = 8
PAGE_LOAD_RETRIES = 3

# --- NAYE DENTAL IMAGE SETS (with Gallery) ---
GENERAL_IMAGE_SETS = [
    {
        "hero_image": "https://images.unsplash.com/photo-1588776814546-ec7e3f5d4f2c",
        "section_image_1": "https://images.unsplash.com/photo-1609840114035-3c981b782dfe",
        "section_image_2": "https://images.unsplash.com/photo-1629909613654-28e377c37b09",
        "gallery_1": "https://images.unsplash.com/photo-1606811841689-23dfddce3e95",
        "gallery_2": "https://images.unsplash.com/photo-1583947582886-f40ec95dd752",
    },
    {
        "hero_image": "https://images.unsplash.com/photo-1606811841689-23dfddce3e95",
        "section_image_1": "https://images.unsplash.com/photo-1583947582886-f40ec95dd752",
        "section_image_2": "https://images.unsplash.com/photo-1593022356769-11f762e25ed9",
        "gallery_1": "https://images.unsplash.com/photo-1588776814546-daab30f310ce",
        "gallery_2": "https://images.unsplash.com/photo-1625134673337-519d8cdfe4dc",
    },
    {
        "hero_image": "https://images.unsplash.com/photo-1588776814546-daab30f310ce",
        "section_image_1": "https://images.unsplash.com/photo-1625134673337-519d8cdfe4dc",
        "section_image_2": "https://images.unsplash.com/photo-1612277795421-9bc7706a4a41",
        "gallery_1": "https://images.unsplash.com/photo-1588776814546-ec7e3f5d4f2c",
        "gallery_2": "https://images.unsplash.com/photo-1609840114035-3c981b782dfe",
    },
]

# (Google Sheets aur Selenium Setup waise hi hain)
def connect_google_sheet():
    print("Connecting to Google Sheets Database...")
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    client = gspread.authorize(creds)
    sheet = client.open(SHEET_NAME).sheet1
    print("Successfully connected to Database!")
    return sheet

def create_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--lang=en")
    options.add_argument("--log-level=3")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--remote-allow-origins=*")
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option("useAutomationExtension", False)
    options.page_load_strategy = "normal"
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(90)
    return driver

def dismiss_google_dialogs(driver):
    possible_buttons = [
        (By.XPATH, '//button[@aria-label="Reject all"]'),
        (By.XPATH, '//button[@aria-label="Accept all"]'),
        (By.XPATH, '//button[.//span[text()="Reject all"]]'),
        (By.XPATH, '//button[.//span[text()="Accept all"]]'),
        (By.XPATH, '//button[.//span[text()="I agree"]]'),
        (By.CSS_SELECTOR, 'form[action*="consent"] button'),
    ]
    for by, locator in possible_buttons:
        try:
            button = WebDriverWait(driver, 4).until(EC.element_to_be_clickable((by, locator)))
            button.click()
            time.sleep(2)
            print("Consent dialog handled.")
            return True
        except (TimeoutException, WebDriverException):
            continue
    return False

def wait_for_maps_ready(driver, wait):
    dismiss_google_dialogs(driver)
    search_selectors = [
        (By.ID, "searchboxinput"),
        (By.CSS_SELECTOR, 'input#searchboxinput'),
        (By.XPATH, '//input[contains(@aria-label, "Search Google Maps")]'),
        (By.XPATH, '//input[contains(@aria-label, "Search")]'),
        (By.CSS_SELECTOR, 'input[name="q"]'),
    ]
    for by, locator in search_selectors:
        try:
            search_box = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((by, locator)))
            print(f"Search box found via: {locator}")
            return search_box
        except (TimeoutException, WebDriverException):
            continue
    print("Search box not found on first pass. Retrying after consent check...")
    if dismiss_google_dialogs(driver):
        time.sleep(2)
    return wait.until(EC.element_to_be_clickable((By.ID, "searchboxinput")))

def get_results_feed(driver, wait):
    return wait.until(EC.presence_of_element_located((By.XPATH, '//div[@role="feed"] | //div[contains(@aria-label, "Results for")]')))

def scroll_results_panel(driver, results_feed):
    print("Scrolling through business listings...")
    last_height = driver.execute_script("return arguments[0].scrollHeight", results_feed)
    for _ in range(MAX_SCROLLS):
        driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", results_feed)
        time.sleep(SCROLL_PAUSE_SECONDS)
        new_height = driver.execute_script("return arguments[0].scrollHeight", results_feed)
        if new_height == last_height:
            break
        last_height = new_height

def collect_listing_urls(driver):
    listing_elements = driver.find_elements(By.XPATH, '//a[contains(@href, "/maps/place/")]')
    unique_urls, seen_urls = [], set()
    for listing in listing_elements:
        href = listing.get_attribute("href")
        if not href: continue
        normalized_href = href.split("&entry=")[0]
        if normalized_href in seen_urls: continue
        seen_urls.add(normalized_href)
        unique_urls.append(normalized_href)
    return unique_urls

def extract_phone_number(driver):
    phone_selectors = [
        '//button[contains(@data-item-id, "phone:tel:")]',
        '//a[contains(@data-item-id, "phone:tel:")]',
        '//button[contains(@aria-label, "Phone")]',
        '//button[contains(@aria-label, "Call")]',
    ]
    for selector in phone_selectors:
        try:
            phone_element = driver.find_element(By.XPATH, selector)
            data_item = phone_element.get_attribute("data-item-id") or ""
            if "phone:tel:" in data_item: return data_item.replace("phone:tel:", "").strip()
            aria_label = phone_element.get_attribute("aria-label") or ""
            if aria_label:
                label_parts = aria_label.split(":", 1)
                if len(label_parts) == 2 and label_parts[1].strip(): return label_parts[1].strip()
            visible_text = phone_element.text.strip()
            if visible_text: return visible_text
        except NoSuchElementException:
            continue
    return "N/A"

def extract_address(driver):
    address_selectors = [
        '//button[contains(@data-item-id, "address")]//div[contains(@class, "fontBodyMedium")]',
        '//button[contains(@data-item-id, "address")]',
        '//div[@data-item-id="address"]',
    ]
    for selector in address_selectors:
        try:
            address_element = driver.find_element(By.XPATH, selector)
            aria_label = address_element.get_attribute("aria-label") or ""
            if aria_label:
                parts = aria_label.split(":", 1)
                if len(parts) == 2 and parts[1].strip(): return parts[1].strip()
            text = address_element.text.strip()
            if text: return text.replace("Address:", "").strip()
        except NoSuchElementException:
            continue
    return "N/A"

def extract_lat_lng_from_url(url):
    if not url: return "N/A", "N/A"
    match = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", url)
    if match: return match.group(1), match.group(2)
    return "N/A", "N/A"

def extract_business_details(driver, wait):
    name_element = wait.until(EC.presence_of_element_located((By.XPATH, '//h1')))
    try:
        business_name = WebDriverWait(driver, 5).until(lambda d: name_element.text.strip() or False)
    except TimeoutException:
        business_name = "Name Loading Error"

    website_elements = driver.find_elements(By.XPATH, '//a[@data-item-id="authority"] | //a[contains(@aria-label, "Website")]')
    has_real_website = False
    if website_elements:
        website_url = (website_elements[0].get_attribute("href") or "").lower()
        social_domains = ["facebook.com", "instagram.com", "twitter.com", "x.com", "linkedin.com", "wa.me", "api.whatsapp.com", "business.site", "linktr.ee", "youtube.com"]
        if website_url and not any(domain in website_url for domain in social_domains):
            has_real_website = True

    phone_number = extract_phone_number(driver)
    address = extract_address(driver)
    lat, lng = extract_lat_lng_from_url(driver.current_url)
    return business_name, has_real_website, phone_number, address, lat, lng

def get_general_image_set():
    return random.choice(GENERAL_IMAGE_SETS)

# --- NAYA FUNCTION: URL Builder ---
def build_dynamic_vercel_url(business_name, phone_number, address, lat, lng, city_name, image_set):
    clean_name = business_name.replace("&", "and")
    email = f"info@{clean_name.lower().replace(' ', '')}.com"
    
    # 50-80 reviews ke darmiyan koi bhi random number generate karo for social proof
    random_reviews = random.randint(50, 200) 
    random_rating = round(random.uniform(4.7, 5.0), 1)

    params = {
        # Core Location & Identity
        'client': clean_name,
        'city': city_name,
        'phone': phone_number,
        'address': address,
        'lat': lat,
        'long': lng,
        'email': email,
        
        # Hero & Smart Defaults
        'hero_badge': f"Premium Dentistry in {city_name}",
        'trust_1_value': f"{random_reviews}+",
        'trust_1_label': "Happy Patients",
        'rating_value': str(random_rating),
        
        # Images
        'hero_image': image_set['hero_image'],
        'section_image_1': image_set['section_image_1'],
        'section_image_2': image_set['section_image_2'],
        'gallery_image_1': image_set['gallery_1'],
        'gallery_image_2': image_set['gallery_2'],
        
        # SEO & Text (Ye aap baad mein mazeed barha sakte hain)
        'services_title': "Elite Dental Solutions",
        'appointment_title': "Book Your Perfect Smile",
        'footer_tagline': f"Transforming smiles across {city_name}."
    }
    
    # URL Encoding (Safe conversion of spaces and special chars)
    query_string = urlencode(params)
    return f"{VERCEL_BASE_URL}/?{query_string}"


def scrape_google_maps(search_query, city_name, category_name, sheet):
    print(f"\nTargeting Niche: {category_name} in {city_name}")
    print(f"Searching Google Maps for: '{search_query}'...")
    driver = None

    try:
        driver = create_driver()
        wait = WebDriverWait(driver, WAIT_SECONDS)

        search_box = None
        for attempt in range(1, PAGE_LOAD_RETRIES + 1):
            try:
                print(f"Loading Google Maps (attempt {attempt}/{PAGE_LOAD_RETRIES})...")
                driver.get(GOOGLE_MAPS_URL)
                time.sleep(5)
                search_box = wait_for_maps_ready(driver, wait)
                break 
            except (TimeoutException, WebDriverException) as load_err:
                print(f"Attempt {attempt} failed: {load_err}")
                if attempt == PAGE_LOAD_RETRIES: raise
                time.sleep(3)

        search_box.clear()
        time.sleep(0.3)
        search_box.send_keys(search_query)
        time.sleep(0.5)
        search_box.send_keys(Keys.ENTER)
        print("Waiting for search results to load...")
        time.sleep(7)

        try:
            results_feed = get_results_feed(driver, wait)
            scroll_results_panel(driver, results_feed)
        except TimeoutException:
            print("Results feed not found. Trying visible page results only.")

        listing_urls = collect_listing_urls(driver)
        print(f"Total potential businesses found: {len(listing_urls)}")

        processed_count, skipped_count = 0, 0

        for index, listing_url in enumerate(listing_urls, start=1):
            try:
                print(f"Checking business {index}/{len(listing_urls)}...")
                driver.get(listing_url)
                time.sleep(3)

                business_name, has_real_website, phone_number, address, lat, lng = extract_business_details(driver, wait)

                if not has_real_website and phone_number != "N/A":
                    print(f"[HOT LEAD] Name: {business_name} | Phone: {phone_number}")

                    # NAYA URL BUILDER CALL KIYA HAI
                    image_set = get_general_image_set()
                    dynamic_url = build_dynamic_vercel_url(
                        business_name, phone_number, address, lat, lng, city_name, image_set
                    )

                    row_data = [business_name, phone_number, category_name, city_name, dynamic_url, "Pending", address, lat, lng]
                    
                    try:
                        sheet.append_row(row_data, value_input_option="USER_ENTERED")
                        print(f"  -> Saved to Google Sheet successfully.")
                        processed_count += 1
                    except Exception as sheet_err:
                        print(f"  -> [SHEET ERROR] Could not save '{business_name}': {sheet_err}")
                else:
                    print(f"[SKIPPED] {business_name} (Reason: Has Website or No Phone)")
                    skipped_count += 1

            except Exception as error:
                print(f"[SKIPPED] Error processing listing: {error}")
                skipped_count += 1
                continue

        print(f"\nScraping Completed! Successfully saved {processed_count} new leads to Google Sheets. Skipped: {skipped_count}.")

    except Exception as error:
        print(f"An error occurred during search: {error}")
        print(traceback.format_exc())
    finally:
        if driver: driver.quit()

# --- PREDEFINED TARGETS UPDATE KIYE HAIN ---
PREDEFINED_TARGETS = [
    {"category": "Dental Clinic", "city": "Lahore"},
    {"category": "Dentist",       "city": "Faisalabad"},
    {"category": "Orthodontist",  "city": "Islamabad"},
]

def get_targets():
    print("\n========== Lead Generation Bot ==========")
    print("1) Enter a custom Category & City")
    print("2) Run all predefined targets (Dental Clinics)")
    choice = input("Select mode (1 or 2): ").strip()

    if choice == "2":
        targets = [(f"{t['category']} in {t['city']}", t["city"], t["category"]) for t in PREDEFINED_TARGETS]
        print(f"Running {len(targets)} predefined target(s)...")
        return targets

    category = input("Enter Category (e.g. Dental Clinic): ").strip()
    city = input("Enter City (e.g. Peshawar): ").strip()
    if not category or not city:
        print("Category and City cannot be empty. Exiting.")
        return []
    return [(f"{category} in {city}", city, category)]

if __name__ == "__main__":
    google_sheet = connect_google_sheet()
    targets = get_targets()
    for query, city, category in targets:
        scrape_google_maps(query, city, category, google_sheet)
    print("\nAll targets processed. Bot finished.")