import os
import random
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import quote

import gspread
from google.oauth2 import service_account  # v2: oauth2client is deprecated
from selenium import webdriver
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    WebDriverException,
)
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

SHEET_NAME = "Leads_Data"
# v2: NEVER use the committed chrome_profile/ from the public repo (it may hold a live session).
# Use a local, uncommitted profile dir, or set WHATSAPP_PROFILE_DIR.
CHROME_PROFILE_DIR = os.environ.get(
    "WHATSAPP_PROFILE_DIR",
    str(Path(__file__).resolve().parent / "chrome_profile_local"),
)


def connect_sheet(sheet_name: str):
    print("Connecting to Google Sheet...")
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
    ]
    creds = service_account.Credentials.from_service_account_file("credentials.json", scopes=scope)
    client = gspread.authorize(creds)
    spreadsheet = client.open(sheet_name)
    sheet = spreadsheet.sheet1
    records = sheet.get_all_records()
    return sheet, records


def _clean_chrome_locks(profile_dir: str) -> None:
    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie", "lockfile"):
        lock = os.path.join(profile_dir, name)
        try:
            if os.path.isfile(lock) or os.path.islink(lock):
                os.remove(lock)
            elif os.path.isdir(lock):
                shutil.rmtree(lock)
        except OSError:
            pass


def create_driver() -> webdriver.Chrome:
    _clean_chrome_locks(CHROME_PROFILE_DIR)
    _clean_chrome_locks(os.path.join(CHROME_PROFILE_DIR, "Default"))

    options = webdriver.ChromeOptions()
    options.add_argument(f"user-data-dir={CHROME_PROFILE_DIR}")
    options.add_argument("--start-maximized")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--remote-allow-origins=*")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-background-networking")
    options.add_argument("--profile-directory=Default")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.page_load_strategy = "normal"

    try:
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=options,
        )
        return driver
    except Exception as e:
        print(f"\nChrome start nahi hua: {e}")
        print("\nFix: Saare Chrome windows band karo aur dobara chalao.")
        print("Task Manager > Chrome > End Task\n")
        raise


def format_pakistani_phone(raw_phone) -> str:
    phone = str(raw_phone).strip()
    if phone.upper() == "N/A" or not phone:
        return ""
    phone = re.sub(r"\D", "", phone)
    if phone.startswith("92"):
        return "+" + phone
    if phone.startswith("03"):
        return "+92" + phone[1:]
    if phone.startswith("3") and len(phone) == 10:
        return "+92" + phone
    return "+" + phone if phone else ""


def build_message(business_name: str, dynamic_url: str) -> str:
    """v2: short Roman Urdu pitch with price and opt-out.
    The demo link is included ONLY when a real demo URL is passed in; pass "" to omit it
    (the demo page is still a placeholder and must not be sent as if it were the clinic's own site)."""
    demo_part = f"\nAap ki demo is link par dekh sakte hain:\n{dynamic_url}\n" if dynamic_url else ""
    return (
        f"Assalam o Alaikum! Mera naam Waseem hai, SiteSphere se. "
        f"Maine dekha {business_name} Google par hai lekin apni website nahi hai, "
        f"is liye patients ko booking ke liye call karna parti hai.\n\n"
        f"Website + WhatsApp booking + Google profile setup, aik dafa ki fixed price PKR 15,000 me, "
        f"kaam shuru karne ke liye 7,500 advance par. 3 din me pehla draft de dunga."
        f"{demo_part}"
        f"\nInterest ho to reply kar dein. SiteSphere WhatsApp: 03155741347.\n"
        f"Agar aap ye messages nahi chahte to STOP reply kar dein, dobara message nahi aayega."
    )


def wait_for_whatsapp_ready(driver: webdriver.Chrome) -> bool:
    try:
        WebDriverWait(driver, 25).until(
            EC.presence_of_element_located((By.XPATH, '//div[@data-testid="chat-list"]'))
        )
        return True
    except TimeoutException:
        return False


def _is_invalid_number_popup(driver: webdriver.Chrome) -> bool:
    invalid_xpaths = [
        '//*[contains(text(), "phone number shared via url is invalid")]',
        '//*[contains(text(), "Phone number shared via url is invalid")]',
        '//div[@data-testid="confirm-popup"]',
        '//div[contains(@class, "overlay")]//div[contains(text(), "invalid")]',
    ]
    for xpath in invalid_xpaths:
        try:
            elements = driver.find_elements(By.XPATH, xpath)
            if elements:
                return True
        except Exception:
            continue
    return False


def _dismiss_invalid_popup(driver: webdriver.Chrome) -> None:
    ok_xpaths = [
        '//div[@data-testid="popup-controls-ok"]',
        '//div[@role="button" and @tabindex="0"]',
        '//button[contains(text(),"OK")]',
    ]
    for xpath in ok_xpaths:
        try:
            btn = driver.find_element(By.XPATH, xpath)
            btn.click()
            time.sleep(1)
            return
        except Exception:
            continue


def send_message(driver: webdriver.Chrome, phone: str, message: str) -> bool:
    encoded_message = quote(message)
    whatsapp_url = f"https://web.whatsapp.com/send?phone={phone}&text={encoded_message}"

    for attempt in range(2):
        try:
            driver.get(whatsapp_url)
            break
        except WebDriverException as nav_err:
            if attempt == 0 and "ERR_CONNECTION_TIMED_OUT" in str(nav_err):
                print("    Network timeout, retrying in 10s...")
                time.sleep(10)
                continue
            raise

    deadline = time.time() + 15
    while time.time() < deadline:
        if _is_invalid_number_popup(driver):
            _dismiss_invalid_popup(driver)
            return False

        for xpath in (
            '//span[@data-icon="send"]',
            '//button[@data-testid="compose-btn-send"]',
            '//span[@data-testid="send"]',
            '//button[@aria-label="Send"]',
        ):
            btns = driver.find_elements(By.XPATH, xpath)
            if btns:
                time.sleep(5)
                try:
                    btns[0].click()
                except Exception:
                    driver.execute_script("arguments[0].click();", btns[0])
                time.sleep(3)
                return True
        time.sleep(2)

    input_box_xpaths = [
        '//div[@data-testid="conversation-compose-box-input"]',
        '//div[@contenteditable="true"][@data-tab="10"]',
        '//footer//div[@contenteditable="true"]',
    ]
    for xpath in input_box_xpaths:
        try:
            input_box = driver.find_element(By.XPATH, xpath)
            time.sleep(3)
            input_box.send_keys(Keys.ENTER)
            time.sleep(2)
            return True
        except NoSuchElementException:
            continue

    if _is_invalid_number_popup(driver):
        _dismiss_invalid_popup(driver)
    return False


def status_column_index(sheet) -> int:
    """Status column found from the header row, never hardcoded, so a reordered sheet cannot corrupt data."""
    headers = sheet.row_values(1)
    if "Status" not in headers:
        raise SystemExit("Sheet header has no 'Status' column. Run scraper_v2 ensure_header first.")
    return headers.index("Status") + 1


def main() -> None:
    sheet, records = connect_sheet(SHEET_NAME)
    total_leads = len(records)
    status_col = status_column_index(sheet)

    print(f"\nTotal {total_leads} leads mili hain.")
    start_input = input("Kahan se shuru karna hai? (e.g. 1): ").strip()
    end_input = input(f"Kahan tak bhejna hai? (e.g. {total_leads}): ").strip()

    start_idx = int(start_input) if start_input.isdigit() else 1
    end_idx = int(end_input) if end_input.isdigit() else total_leads
    # v2: clamp the range instead of aborting on an out-of-range end row.
    start_idx = max(1, min(start_idx, total_leads)) if total_leads else 1
    end_idx = max(start_idx, min(end_idx, total_leads)) if total_leads else 0
    approved = [r for r in records[start_idx - 1:end_idx] if str(r.get("Status", "")).strip().lower() == "approved"]
    print(f"\n{len(approved)} row(s) marked 'Approved' in this range will be sent. Others will be skipped.")
    confirm = input("Type YES to send to the Approved rows only: ").strip()
    if confirm != "YES":
        print("Aborted by user. Nothing was sent.")
        return

    print("\nStarting Chrome (previous instances will be killed automatically)...")
    driver = create_driver()

    try:
        print("Opening WhatsApp Web...")
        driver.get("https://web.whatsapp.com/")

        print("Waiting for WhatsApp to load (up to 45s)...")
        time.sleep(10)

        ready = False
        for _ in range(7):
            ready = wait_for_whatsapp_ready(driver)
            if ready:
                break
            time.sleep(5)

        if not ready:
            print("\nWhatsApp not ready yet — you may need to scan the QR code.")
            print("Waiting 30 more seconds for manual QR scan...")
            time.sleep(30)
            ready = wait_for_whatsapp_ready(driver)

        if ready:
            print("WhatsApp is ready. Sending messages...\n")
        else:
            print("WhatsApp still not detected, but will attempt sending anyway...\n")

        for i in range(start_idx - 1, end_idx):
            row = records[i]
            actual_row_in_sheet = i + 2

            business_name = str(row.get("Business Name", "")).strip()
            raw_phone = row.get("Phone", "")
            current_status = str(row.get("Status", "")).strip()
            
            # --- NAYI CHANGING YAHAN HAI ---
            # Hum directly Google Sheet se wo lamba wala URL utha rahe hain jo scraper ne banaya tha.
            # *Note: Apni Google Sheet mein tasalli kar lein ke URL walay column ka naam "URL" hai.
            sheet_generated_url = str(row.get("URL", "")).strip() 

            # v2 APPROVAL GATE: only rows explicitly marked "Approved" in the sheet are sent.
            # "Pending" rows are drafts, never auto-sent. "Sent" / "Send clicked" rows are skipped.
            if current_status.lower() != "approved":
                print(f"[{actual_row_in_sheet}] Status is '{current_status}', not 'Approved'. Skipping...")
                continue

            formatted_phone = format_pakistani_phone(raw_phone)
            if not formatted_phone:
                print(f"[{actual_row_in_sheet}] Invalid number for '{business_name}'.")
                sheet.update_cell(actual_row_in_sheet, status_col, "Invalid Number")
                continue

            # Agar kisi wajah se sheet mein URL nahi hai, toh basic fallback URL banayega
            if not sheet_generated_url:
                base_vercel_url = "https://dental-clinic-nine-tau.vercel.app/"
                clean_name = quote(business_name)
                clean_address = quote(str(row.get("Address", "")).strip())
                lat = str(row.get("Latitude", "")).strip()
                lng = str(row.get("Longitude", "")).strip()
                
                final_demo_url = (
                    f"{base_vercel_url}?client={clean_name}"
                    f"&phone={formatted_phone}"
                    f"&address={clean_address}"
                    f"&lat={lat}"
                    f"&long={lng}"
                )
            else:
                final_demo_url = sheet_generated_url

            message = build_message(business_name, final_demo_url)

            print(f"[{actual_row_in_sheet}/{end_idx}] Sending to '{business_name}' ({formatted_phone})...")

            try:
                success = send_message(driver, formatted_phone, message)

                if success:
                    # v2: "Send clicked" only means the send button was clicked, NOT confirmed delivery.
                    print(f"  Send clicked for '{business_name}' (delivery not confirmed)")
                    sheet.update_cell(actual_row_in_sheet, status_col, "Send clicked")
                else:
                    print(f"  '{business_name}' WhatsApp par nahi hai.")
                    sheet.update_cell(actual_row_in_sheet, status_col, "Not on WhatsApp")

            except TimeoutException:
                print(f"  '{business_name}' timeout — not on WhatsApp.")
                sheet.update_cell(actual_row_in_sheet, status_col, "Not on WhatsApp")
                time.sleep(5)
                continue

            except Exception as exc:
                print(f"  Error for '{business_name}': {exc}")
                sheet.update_cell(actual_row_in_sheet, status_col, "Error")
                time.sleep(5)
                continue

            delay = random.randint(30, 60)  # v2: slower pacing lowers the number-ban risk
            print(f"  Waiting {delay}s...\n")
            time.sleep(delay)

    finally:
        try:
            driver.quit()
        except Exception:
            pass
        print("\nTask completed.")


if __name__ == "__main__":
    main()