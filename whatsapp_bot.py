import os
import random
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import quote

import gspread
from oauth2client.service_account import ServiceAccountCredentials
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
CHROME_PROFILE_DIR = str(Path(__file__).resolve().parent / "chrome_profile")


def connect_sheet(sheet_name: str):
    print("Connecting to Google Sheet...")
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
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


def _kill_chrome_processes() -> None:
    for proc in ("chrome.exe", "chromedriver.exe"):
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", proc],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass
    time.sleep(2)


def create_driver() -> webdriver.Chrome:
    _kill_chrome_processes()
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
    return (
        f"Hello from SiteSphere!\n\n"
        f"We noticed '{business_name}' has a great reputation on Google Maps, but currently lacks a professional website. A website is essential to build trust and convert searchers into customers.\n\n"
        f"We have designed a premium, custom website demo specifically for your business. It includes:\n"
        f"\u2022 Direct WhatsApp Booking\n"
        f"\u2022 Live Google Maps Integration\n"
        f"\u2022 Complete Customization (Logo, Colors, Images)\n\n"
        f"View your custom demo here: \n{dynamic_url}\n\n"
        f"Assalam o Alaikum! Hum SiteSphere ki taraf se baat kar rahe hain. Aapke business ko ek 'Brand' banane ke liye hum ne ek custom Demo Website design ki hai.\n\n"
        f"Aap apni demo website is link par check kar sakte hain:\n{dynamic_url}\n\n"
        f"Agar aap is professional setup ko apne asli domain (jaise .com ya .pk) par live karna chahte hain, toh is message ka reply karein. Shukriya!"
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


def main() -> None:
    sheet, records = connect_sheet(SHEET_NAME)
    total_leads = len(records)

    print(f"\nTotal {total_leads} leads mili hain.")
    start_input = input("Kahan se shuru karna hai? (e.g. 1): ").strip()
    end_input = input(f"Kahan tak bhejna hai? (e.g. {total_leads}): ").strip()

    start_idx = int(start_input) if start_input.isdigit() else 1
    end_idx = int(end_input) if end_input.isdigit() else total_leads

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

            if current_status.lower() == "sent":
                print(f"[{actual_row_in_sheet}] Already sent to '{business_name}'. Skipping...")
                continue

            formatted_phone = format_pakistani_phone(raw_phone)
            if not formatted_phone:
                print(f"[{actual_row_in_sheet}] Invalid number for '{business_name}'.")
                sheet.update_cell(actual_row_in_sheet, 6, "Invalid Number")
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
                    print(f"  Sent to '{business_name}'")
                    sheet.update_cell(actual_row_in_sheet, 6, "Sent")
                else:
                    print(f"  '{business_name}' WhatsApp par nahi hai.")
                    sheet.update_cell(actual_row_in_sheet, 6, "Not on WhatsApp")

            except TimeoutException:
                print(f"  '{business_name}' timeout — not on WhatsApp.")
                sheet.update_cell(actual_row_in_sheet, 6, "Not on WhatsApp")
                time.sleep(5)
                continue

            except Exception as exc:
                print(f"  Error for '{business_name}': {exc}")
                sheet.update_cell(actual_row_in_sheet, 6, "Error")
                time.sleep(5)
                continue

            delay = random.randint(20, 35)
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