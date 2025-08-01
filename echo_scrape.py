# echo_scrape.py
# Version: 0.5.0
# Last Updated: 2025-07-28

import platform
import csv
import sys
from pathlib import Path
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
import time
import json
import ftplib
import os
import openpyxl
import re

if getattr(sys, 'frozen', False):
    base_path = Path(sys.argv[0]).resolve().parent
else:
    base_path = Path(__file__).resolve().parent

config_path = base_path / "config.txt"
chromedriver_filename = ""

if not config_path.exists():
    sys.exit("Error: config.txt is missing.")

# Load configuration
with open("config.txt", "r") as config_file:
    config = json.load(config_file)

# Input and output files
input_file_name = config.get("input_file")
if not input_file_name:
    sys.exit("Error: 'input_file' is not specified in config.txt.")
input_file = base_path / input_file_name
if not input_file.exists():
    sys.exit("Error: Input file '{input_file_name}' does not exist.")

# FTP details
ftp_host = config.get("ftp_host", "None").replace("ftp://", "")
ftp_port = config.get("ftp_port", 21)
ftp_username = config.get("ftp_username", "")
ftp_password = config.get("ftp_password", "")
ftp_directory = config.get("ftp_directory", "/")
overwrite_existing = config.get("overwrite_existing", True)

output_file_name = config.get("output_file", "output.csv")
output_file = base_path / output_file_name
output_path = Path(output_file)

is_xlsx = output_file_name.endswith(".xlsx")

max_rows = config.get("max_rows", "all")

if max_rows != "all":
    try:
        max_rows = int(max_rows)
    except ValueError:
        sys.exit("Error: 'max_rows' must be an integer or 'all'.")
else:
    max_rows = None # This will allow processing all rows if it's "all"

# Base URL for scraping
base_url = "https://commerce.echo-usa.com/catalogsearch/result/?q="

# Set up Selenium WebDriver
options = webdriver.ChromeOptions()
headless_mode = config.get("headless_mode", False)
if headless_mode:
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")

if platform.system() == "Windows":
    chromedriver_filename = "chromedriver.exe"
else:
    chromedriver_filename = "chromedriver"

chromedriver_path = base_path / chromedriver_filename
if not chromedriver_path.exists():
    sys.exit("Error: {chromedriver_filename} is missing at {chromedriver_path}.")

driver_service = Service(str(chromedriver_path))
driver = webdriver.Chrome(service=driver_service, options=options)

# Log in to the website
login_url = config["login_url"]
username = config["username"]
password = config["password"]

wait = WebDriverWait(driver, 20)
driver.get(login_url)
wait.until(EC.presence_of_element_located((By.NAME, "identifier"))).send_keys(username)
wait.until(EC.presence_of_element_located((By.NAME, "credentials.passcode"))).send_keys(password)
wait.until(EC.presence_of_element_located((By.NAME, "credentials.passcode"))).send_keys(Keys.RETURN)
time.sleep(10)  # Allow time for login

# Read the input file
with open(input_file, "r", encoding="utf-8") as csvfile:
    reader = csv.reader(csvfile)
    rows = list(reader)

output_header = ["MFG", "Type", "Subtype", "Item Code", "Item Description", "Retail", "Qty on Hand", "Qty on Order", "RSV Qty", "cost"]
# Open the output file for writing
if is_xlsx:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(output_header)
else:
    csvfile = open(output_file, "w", newline="", encoding="utf-8")
    writer = csv.writer(csvfile)
    writer.writerow(output_header)

# Process each row in the input file
processed_rows = 0
for row in rows:
    if max_rows is not None and processed_rows >= max_rows:
        break

    if len(row) >= 7:  # Ensure the row has enough columns
        key = row[6]  # Column 7 (index 6)

        if key.startswith("ECH~") or key.startswith("BIL~"):
            search_text = key.split("~", 1)[1].strip()  # Extract text after the ~
            search_url = f"{base_url}\"{search_text}\""
            print(search_url)

            try:
                # Fetch the page content
                driver.get(search_url)
                soup = BeautifulSoup(driver.page_source, "html.parser")
                
                # Check if the "Product Not Found" message is displayed
                not_found_message = soup.find("div", class_="message notice")
                if not_found_message and "We could not find anything for" in not_found_message.text:
                    print(f"Product not found for search: {search_text}")
                    subtype = "Product Not Found"
                    
                    # Fill in other fields with defaults or empty values
                    mfg = ""
                    item_code = f"{key[:3]}  {search_text}"
                    item_description = ""
                    retail = 0.0
                    qty_on_hand = "0"
                    qty_on_order = "0"
                    rsv_qty = config.get("rsv_qty", 5)
                    cost = 0.0
                    
                    output_data = [mfg, "", subtype, item_code, item_description, retail, qty_on_hand, qty_on_order, rsv_qty, cost]
                    # Write the row to the output file
                    if is_xlsx:
                        sheet.append(output_data)
                    else:
                        writer.writerow(output_data)
                        
                    processed_rows += 1
                    continue

                # Find the first result link if product is found
                first_result = soup.find("a", class_="product-item-link")
                if first_result and first_result['href']:
                    first_result_url = first_result['href']
                    print(f"Navigating to the first result: {first_result_url}")
                    
                    driver.get(first_result_url)
                    soup = BeautifulSoup(driver.page_source, "html.parser")
                    
                # Extract the data
                mfg = soup.find("td", {"data-th": "Brand"})
                mfg = mfg.text.strip() if mfg else ""

                item_code = f"{key[:3]}  {search_text}"

                item_description = soup.find("div", {"itemprop": "name"})
                item_description = item_description.text.strip() if item_description else ""

                retail = soup.find("span", {"data-price-type": "oldPrice"})
                if retail:
                    retail = re.search(r"\d+\.\d+", retail.text)
                    retail = float(retail.group()) if retail else 0.00
                else:
                    retail = 0.0

                qty_on_hand = soup.find("div", class_="product-info-stock-sku")
                if qty_on_hand:
                    warehouse_qty_div = qty_on_hand.find_next("div", text=lambda text: text and "Warehouse Qty:" in text)
                    if warehouse_qty_div:
                        qty_on_hand = warehouse_qty_div.text.split("Warehouse Qty:")[1].strip()
                    else:
                        qty_on_hand = "0"
                else:
                    qty_on_hand = "0"

                qty_on_order = "0"
                rsv_qty = config.get("rsv_qty", 5)

                cost = soup.find("span", {"data-price-type": "finalPrice"})
                if cost:
                    cost = re.search(r"\d+\.\d+", cost.text)
                    cost = float(cost.group()) if cost else 0.0
                else:
                    cost = 0.0

                output_data = [mfg, "", "", item_code, item_description, retail, qty_on_hand, qty_on_order, rsv_qty, cost]
                # Write the row to the output file
                if is_xlsx:
                    sheet.append(output_data)
                else:
                    writer.writerow(output_data)

                # Increment the processed row counter
                processed_rows += 1

            except Exception as e:
                print(f"Error processing {search_url}: {e}")

# Close the browser
driver.quit()

if is_xlsx:
    workbook.save(output_file)
else:
    csvfile.close()

# FTP upload logic (only after scraping is complete)
if ftp_host != "None" and ftp_host != "":
    try:
        ftp = ftplib.FTP()
        ftp.connect(ftp_host, ftp_port)
        ftp.login(ftp_username, ftp_password)
        
        ftp.cwd(ftp_directory)
        
        if not overwrite_existing:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            ftp_upload_file = f"{output_path.stem}_{timestamp}{output_path.suffix}"
        else:
            ftp_upload_file = output_file
        
        with open(output_file, "rb") as file:
            ftp.storbinary(f"STOR {os.path.basename(ftp_upload_file)}", file)
            
        ftp.quit()
        print(f"File {ftp_upload_file} uploaded to FTP server at {ftp_host}{ftp_directory}")
    except Exception as e:
        print(f"Error uploading to FTP: {e}")
else:
    print(f"File saved locally as {output_file}")
