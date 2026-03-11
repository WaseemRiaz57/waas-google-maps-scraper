import time
import traceback
from urllib.parse import quote_plus

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
WAIT_SECONDS = 30
SCROLL_PAUSE_SECONDS = 2
MAX_SCROLLS = 8
PAGE_LOAD_RETRIES = 3


def connect_google_sheet():
    """Google Sheets API ke zariye Leads_Data sheet se connection banata hai."""
    print("Connecting to Google Sheets Database...")
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    client = gspread.authorize(creds)
    sheet = client.open(SHEET_NAME).sheet1
    print("Successfully connected to Database!")
    return sheet


def create_driver():
    """Stable Chrome session start karta hai taake Google Maps automation crash na kare."""
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
    # IMPORTANT: "normal" ensures the full SPA (Google Maps) finishes loading
    # before Selenium tries to find elements.  "eager" caused the TimeoutException
    # because Maps' JS had not rendered the search box yet.
    options.page_load_strategy = "normal"

    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(90)
    return driver


def dismiss_google_dialogs(driver):
    """Cookie ya consent popups ko close karta hai agar woh nazar aayen."""
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
    """Search input load hone ka wait karta hai — multiple selector fallbacks ke sath."""
    # Pehle consent dialog handle karo (agar aaye toh)
    dismiss_google_dialogs(driver)

    # Multiple selectors try karo — Google Maps DOM change hota rehta hai
    search_selectors = [
        (By.ID, "searchboxinput"),
        (By.CSS_SELECTOR, 'input#searchboxinput'),
        (By.XPATH, '//input[contains(@aria-label, "Search Google Maps")]'),
        (By.XPATH, '//input[contains(@aria-label, "Search")]'),
        (By.CSS_SELECTOR, 'input[name="q"]'),
    ]

    for by, locator in search_selectors:
        try:
            search_box = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((by, locator))
            )
            print(f"Search box found via: {locator}")
            return search_box
        except (TimeoutException, WebDriverException):
            continue

    # Agar koi selector kaam nahi aaya — last resort: consent dobara try karo
    print("Search box not found on first pass. Retrying after consent check...")
    if dismiss_google_dialogs(driver):
        time.sleep(2)

    # Final attempt with long wait
    return wait.until(
        EC.element_to_be_clickable((By.ID, "searchboxinput"))
    )


def get_results_feed(driver, wait):
    """Results list ka scrollable panel find karta hai."""
    return wait.until(
        EC.presence_of_element_located(
            (
                By.XPATH,
                '//div[@role="feed"] | //div[contains(@aria-label, "Results for")]'
            )
        )
    )


def scroll_results_panel(driver, results_feed):
    """Google Maps lazy loading ko trigger karne ke liye results panel scroll karta hai."""
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
    """Visible search results se unique business URLs nikalta hai."""
    listing_elements = driver.find_elements(By.XPATH, '//a[contains(@href, "/maps/place/")]')
    unique_urls = []
    seen_urls = set()

    for listing in listing_elements:
        href = listing.get_attribute("href")
        if not href:
            continue

        normalized_href = href.split("&entry=")[0]
        if normalized_href in seen_urls:
            continue

        seen_urls.add(normalized_href)
        unique_urls.append(normalized_href)

    return unique_urls


def extract_phone_number(driver):
    """Business details page se phone number nikalta hai."""
    phone_selectors = [
        '//button[contains(@data-item-id, "phone:tel:")]',
        '//a[contains(@data-item-id, "phone:tel:")]',
        '//button[contains(@aria-label, "Phone")]',
        '//button[contains(@aria-label, "Call")]',
    ]

    for selector in phone_selectors:
        try:
            phone_element = driver.find_element(By.XPATH, selector)
        except NoSuchElementException:
            continue

        data_item = phone_element.get_attribute("data-item-id") or ""
        if "phone:tel:" in data_item:
            return data_item.replace("phone:tel:", "").strip()

        aria_label = phone_element.get_attribute("aria-label") or ""
        if aria_label:
            label_parts = aria_label.split(":", 1)
            if len(label_parts) == 2 and label_parts[1].strip():
                return label_parts[1].strip()

        visible_text = phone_element.text.strip()
        if visible_text:
            return visible_text

    return "N/A"


def extract_business_details(driver, wait):
    """Detail page se business name, website status, aur phone nikalta hai."""
    # Google Maps skeleton UI ki wajah se <h1> pehle aa jata hai lekin text late fill hota hai.
    # Is liye pehle element wait karo, phir max 5 sec tak non-empty text ka wait karo.
    name_element = wait.until(EC.presence_of_element_located((By.XPATH, '//h1')))

    def _name_text_loaded(_driver):
        text = name_element.text.strip()
        return text if text else False

    try:
        business_name = WebDriverWait(driver, 5).until(_name_text_loaded)
    except TimeoutException:
        business_name = "Name Loading Error"

    website_exists = len(
        driver.find_elements(
            By.XPATH,
            '//a[@data-item-id="authority"] | //a[contains(@aria-label, "Website")]'
        )
    ) > 0

    phone_number = extract_phone_number(driver)
    return business_name, website_exists, phone_number

def scrape_google_maps(search_query, city_name, category_name, sheet):
    print(f"\nTargeting Niche: {category_name} in {city_name}")
    print(f"Searching Google Maps for: '{search_query}'...")

    driver = None

    try:
        driver = create_driver()
        wait = WebDriverWait(driver, WAIT_SECONDS)

        # ---------- Page Load with Retry ----------
        search_box = None
        for attempt in range(1, PAGE_LOAD_RETRIES + 1):
            try:
                print(f"Loading Google Maps (attempt {attempt}/{PAGE_LOAD_RETRIES})...")
                driver.get(GOOGLE_MAPS_URL)
                # Give the SPA time to fully hydrate before looking for elements
                time.sleep(5)
                search_box = wait_for_maps_ready(driver, wait)
                break  # success
            except (TimeoutException, WebDriverException) as load_err:
                print(f"Attempt {attempt} failed: {load_err}")
                if attempt == PAGE_LOAD_RETRIES:
                    raise
                time.sleep(3)

        print("Looking for the search box...")
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

        processed_count = 0
        skipped_count = 0

        # Har business URL ko detail page par visit kar ke filter lagayenge
        for index, listing_url in enumerate(listing_urls, start=1):
            try:
                print(f"Checking business {index}/{len(listing_urls)}...")
                driver.get(listing_url)
                time.sleep(3)

                business_name, website_exists, phone_number = extract_business_details(driver, wait)

                # Agar website nahi hai aur number mojood hai toh Save karein!
                if not website_exists and phone_number != "N/A":
                    print(f"[HOT LEAD] Name: {business_name} | Phone: {phone_number}")

                    # SEO Optimized Dynamic URL
                    clean_name = quote_plus(business_name.replace("&", "and"))
                    dynamic_url = f"https://youragency.vercel.app/?client={clean_name}&phone={phone_number}"

                    # Google Sheet me Data Insert Karna
                    row_data = [business_name, phone_number, category_name, city_name, dynamic_url]
                    try:
                        sheet.append_row(row_data, value_input_option="USER_ENTERED")
                        print(f"  -> Saved to Google Sheet successfully.")
                        processed_count += 1
                    except gspread.exceptions.APIError as api_err:
                        print(f"  -> [SHEET API ERROR] Could not save '{business_name}': {api_err}")
                        print(f"     Response: {api_err.response.text}")
                    except Exception as sheet_err:
                        print(f"  -> [SHEET ERROR] Could not save '{business_name}': {sheet_err}")
                else:
                    print(f"[SKIPPED] {business_name} (Reason: Has Website or No Phone)")
                    skipped_count += 1

            except TimeoutException:
                print(f"[SKIPPED] Detail page timed out for: {listing_url}")
                skipped_count += 1
                continue
            except WebDriverException as error:
                print(f"[SKIPPED] Browser issue while processing listing: {error}")
                skipped_count += 1
                continue
            except Exception as error:
                print(f"[SKIPPED] Unexpected error: {error}")
                skipped_count += 1
                continue

        print(
            f"\nScraping Completed! Successfully saved {processed_count} new leads to Google Sheets. "
            f"Skipped: {skipped_count}."
        )

    except TimeoutException as error:
        print(f"An error occurred during search: Timeout while waiting for Google Maps. {error}")
    except WebDriverException as error:
        print(f"An error occurred during search: Browser automation failed. {error}")
        print(traceback.format_exc())
    except Exception as error:
        print(f"An error occurred during search: {error}")
        print(traceback.format_exc())
    finally:
        if driver:
            driver.quit()

# ==========================================
# Predefined niches — add more entries here to batch-scrape multiple targets
# ==========================================
PREDEFINED_TARGETS = [
    {"category": "Marble & Granite",      "city": "Peshawar"},
    {"category": "Auto Spare Parts",      "city": "Peshawar"},
    {"category": "Furniture Shops",       "city": "Islamabad"},
]


def get_targets():
    """User se dynamic input leta hai ya predefined list use karta hai."""
    print("\n========== Lead Generation Bot ==========")
    print("1) Enter a custom Category & City")
    print("2) Run all predefined targets")
    choice = input("Select mode (1 or 2): ").strip()

    if choice == "2":
        targets = [
            (f"{t['category']} in {t['city']}", t["city"], t["category"])
            for t in PREDEFINED_TARGETS
        ]
        print(f"Running {len(targets)} predefined target(s)...")
        return targets

    # Default: custom single query
    category = input("Enter Category (e.g. Marble & Granite): ").strip()
    city = input("Enter City (e.g. Peshawar): ").strip()
    if not category or not city:
        print("Category and City cannot be empty. Exiting.")
        return []
    search_query = f"{category} in {city}"
    return [(search_query, city, category)]


# ==========================================
# Run the Bot
# ==========================================
if __name__ == "__main__":
    google_sheet = connect_google_sheet()
    targets = get_targets()

    for query, city, category in targets:
        scrape_google_maps(query, city, category, google_sheet)

    print("\nAll targets processed. Bot finished.")