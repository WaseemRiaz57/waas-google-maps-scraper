import os
import random
import re
import shutil
import time
from pathlib import Path
from urllib.parse import quote

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

SHEET_NAME = "Leads_Data"
CHROME_PROFILE_DIR = str(Path(__file__).resolve().parent / "chrome_profile")

def connect_sheet(sheet_name: str):
    print("Connecting to Google Sheet...")
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
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

def create_driver() -> webdriver.Chrome:
    _clean_chrome_locks(CHROME_PROFILE_DIR)
    options = webdriver.ChromeOptions()
    options.add_argument(f"user-data-dir={CHROME_PROFILE_DIR}")
    options.add_argument("--start-maximized")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--remote-allow-origins=*")
    options.page_load_strategy = "eager" 

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options,
    )
    return driver

def format_pakistani_phone(raw_phone) -> str:
    phone = str(raw_phone).strip()
    if phone.upper() == "N/A" or not phone:
        return ""
    phone = re.sub(r"\D", "", phone)
    if phone.startswith("92"): return "+" + phone
    if phone.startswith("03"): return "+92" + phone[1:]
    if phone.startswith("3") and len(phone) == 10: return "+92" + phone
    return "+" + phone if phone else ""

def build_message(business_name: str, dynamic_url: str) -> str:
    # Highly Converting Bilingual Outreach Message for SiteSphere
    return (
        f"Hello from SiteSphere! 👋\n\n"
        f"*--- Professional Notice ---*\n"
        f"We noticed '{business_name}' has a great reputation on Google Maps, but you are currently missing a professional website. In today's digital age, a website is essential to build trust and convert Google searchers into paying customers.\n\n"
        f"To show you the potential, we have designed a premium, custom website demo specifically for your business.\n\n"
        f"🚀 *How This Website Grows Your Business:*\n"
        f"• *Direct WhatsApp Booking:* Customers can book appointments or place orders directly to your WhatsApp with one click.\n"
        f"• *Live Google Maps Integration:* Helps new clients navigate exactly to your shop/clinic without getting lost.\n"
        f"• *Brand Trust:* A professional online presence makes you stand out from local competitors.\n\n"
        f"We can fully customize the colors, logos, pictures, and services according to your exact requirements.\n\n"
        f"👉 *View your custom demo here:* \n{dynamic_url}\n\n"
        f"---------------------------------\n\n"
        f"*--- Urdu Version ---*\n"
        f"Assalam o Alaikum! Hum SiteSphere ki taraf se baat kar rahe hain. Main ne dekha ke Google Maps par aapka business kaafi acha hai, lekin aapki koi official website nahi hai. Aaj kal naye customers dukan par aane se pehle Google par website zaroor check karte hain taake unhe tasalli ho sake.\n\n"
        f"Aapke business ko ek 'Brand' banane ke liye hum ne ek Demo Website design ki hai. Is website ke sab se bare fayde yeh hain:\n\n"
        f"✅ *WhatsApp Booking System:* Customer website se direct aapke WhatsApp par appointment ya order bhej sakega.\n"
        f"✅ *Live Location & Map:* Aapki dukan ka exact rasta website par hoga taake customer asani se pohnch sake.\n"
        f"✅ *100% Customization:* Is website mein aapki dukan ki asli tasweerein, logo aur colors aapki marzi ke mutabiq lagaye jayenge.\n\n"
        f"👉 *Apni demo website check karne ke liye is link par click karein:* \n{dynamic_url}\n\n"
        f"Agar aap is professional setup ko apne asli domain (jaise .com ya .pk) par live karna chahte hain, toh is message ka reply karein. Shukriya!"
    )

def main() -> None:
    sheet, records = connect_sheet(SHEET_NAME)
    total_leads = len(records)
    
    print(f"\n✅ Total {total_leads} leads mili hain.")
    start_input = input("Kahan se shuru karna hai? (e.g. 1): ").strip()
    end_input = input(f"Kahan tak bhejna hai? (e.g. {total_leads}): ").strip()

    start_idx = int(start_input) if start_input.isdigit() else 1
    end_idx = int(end_input) if end_input.isdigit() else total_leads

    driver = create_driver()
    wait = WebDriverWait(driver, 25)

    try:
        print("Opening WhatsApp Web...")
        driver.get("https://web.whatsapp.com/")
        time.sleep(15)

        for i in range(start_idx - 1, end_idx):
            row = records[i]
            actual_row_in_sheet = i + 2 
            
            business_name = str(row.get("Business Name", "")).strip()
            raw_phone = row.get("Phone", "")
            current_status = str(row.get("Status", "")).strip()
            
            # --- NEW: Extracting Address and Coordinates ---
            raw_address = str(row.get("Address", "Contact us for location")).strip()
            lat = str(row.get("Latitude", "")).strip()
            lng = str(row.get("Longitude", "")).strip()

            if current_status.lower() == "sent":
                print(f"[{actual_row_in_sheet}] Already Sent to '{business_name}'. Skipping...")
                continue

            formatted_phone = format_pakistani_phone(raw_phone)
            if not formatted_phone:
                print(f"[{actual_row_in_sheet}] Invalid number for '{business_name}'.")
                sheet.update_cell(actual_row_in_sheet, 6, "Invalid Number")
                continue

            # --- DYNAMIC URL RE-BUILDING WITH ADDRESS & MAP DATA ---
            base_vercel_url = "https://dental-clinic-nine-tau.vercel.app/"
            clean_name = quote(business_name)
            clean_address = quote(raw_address)
            
            final_demo_url = (
                f"{base_vercel_url}?client={clean_name}"
                f"&phone={formatted_phone}"
                f"&address={clean_address}"
                f"&lat={lat}"
                f"&long={lng}"
            )

            message = build_message(business_name, final_demo_url)
            encoded_message = quote(message)
            whatsapp_url = f"https://web.whatsapp.com/send?phone={formatted_phone}&text={encoded_message}"

            print(f"[{actual_row_in_sheet}/{end_idx}] Attempting: '{business_name}'...")

            try:
                driver.get(whatsapp_url)
                send_button = wait.until(
                    EC.presence_of_element_located((By.XPATH, '//span[@data-icon="send"]'))
                )
                
                time.sleep(4) # Link preview wait
                driver.execute_script("arguments[0].click();", send_button)
                
                print(f"✅ Message sent to {business_name}")
                sheet.update_cell(actual_row_in_sheet, 6, "Sent") 
                time.sleep(random.randint(15, 25))

            except TimeoutException:
                print(f"❌ '{business_name}' is not on WhatsApp or timed out.")
                sheet.update_cell(actual_row_in_sheet, 6, "Not on WhatsApp")
                continue
            except Exception as exc:
                print(f"⚠️ Error: {exc}")
                continue

    finally:
        driver.quit()
        print("\n🎉 Task Completed.")

if __name__ == "__main__":
    main()