from playwright.sync_api import sync_playwright
import pandas as pd
import re
import json
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# 🔑 GOOGLE SHEETS SETUP
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds = ServiceAccountCredentials.from_json_keyfile_name("creds.json", scope)
client = gspread.authorize(creds)

sheet = client.open("flipkart scraping").sheet1  # your sheet name


def get_fsn(url):
    match = re.search(r'pid=([A-Z0-9]+)', url)
    return match.group(1) if match else None


def clean_price(text):
    if not text:
        return None
    text = text.replace("â‚¹", "₹").replace(",", "")
    match = re.search(r'\d+', text)
    return int(match.group()) if match else None


def scrape(page, url):
    page.goto(url, timeout=60000)

    # close login popup
    try:
        page.locator("button:has-text('✕')").click(timeout=3000)
    except:
        pass

    page.wait_for_timeout(3000)

    data = {
        "FSN": get_fsn(url),
        "Link": url
    }

    # =========================================
    # JSON DATA (SAFE)
    # =========================================
    json_text = page.locator("#jsonLD").inner_text()
    json_data = json.loads(json_text)[0]

    data["Title"] = json_data.get("name")
    data["Images"] = ", ".join(json_data.get("image", []))

    price = json_data.get("offers", {}).get("price")
    data["Selling Price"] = int(price) if price else None

    rating_data = json_data.get("aggregateRating", {})
    data["Rating"] = rating_data.get("ratingValue")
    data["Rating Count"] = rating_data.get("ratingCount")

    # =========================================
    # ✅ MRP + DISCOUNT (VISIBLE PRICE BLOCK)
    # =========================================
    data["MRP"] = None
    data["Discount %"] = None

    try:
        # grab all visible text containing ₹
        price_texts = page.locator("span").all_inner_texts()

        for txt in price_texts:
            # Example: "70% ₹4,612 ₹1,380"
            if "₹" in txt and "," in txt:
                values = re.findall(r"₹([\d,]+)", txt)

                if len(values) >= 2:
                    # second value is usually MRP
                    data["MRP"] = int(values[0].replace(",", ""))
                    break

    except:
        pass

    # Discount %
    try:
        discount_texts = page.locator("span").all_inner_texts()

        for txt in discount_texts:
            match = re.search(r"(\d+)%", txt)
            if match:
                data["Discount %"] = int(match.group(1))
                break

    except:
        pass

    # =========================================
    # COUPON
    # =========================================
    try:
        html = page.content()
        data["Coupon"] = "Available" if "Coupon" in html else "Not available"
    except:
        data["Coupon"] = "Not available"

    # =========================================
    # OTHER FIELDS
    # =========================================
    html = page.content()

    data["Deals Tag"] = "Available" if "Bank Offer" in html else "Not available"
    data["A+ Content"] = "Available" if "Product Description" in html else "Not available"

    return data

# 🔁 MAIN
df = pd.read_csv("input.csv")

results = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()

    for i, row in df.iterrows():
        url = row["link"]

        print(f"{i+1}/{len(df)} → Scraping")

        try:
            data = scrape(page, url)
            results.append(data)

        except Exception as e:
            print("Error:", e)

        time.sleep(2)  # avoid blocking

    browser.close()

# Convert to DataFrame
final_df = pd.DataFrame(results)

final_df = final_df.fillna("")
# 💾 Save locally
final_df.to_csv("output.csv", index=False)

# 🚀 Upload to Google Sheets
sheet.clear()
sheet.update([final_df.columns.values.tolist()] + final_df.values.tolist())

print("✅ Done! Data pushed to Google Sheets")