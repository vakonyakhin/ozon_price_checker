import asyncio
import re
from typing import Optional, Tuple
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium_stealth import stealth
from webdriver_manager.chrome import ChromeDriverManager

# --- Selectors ---

OZON_SELECTORS = {
    "price_xpaths": [
        "//span[contains(@class, 'tsHeadline600Large')]",
        "//*[contains(text(), 'С Ozon картой')]/preceding-sibling::*",
        "/html/body/div[1]/div/div[1]/div[3]/div[3]/div[2]/div/div/div[1]/div[3]/div[1]/div[1]/div/div/div[1]/div[1]/button/span/div/div[1]/div/span",
        "//span[contains(text(), '₽')]",
    ],
    "price_css": [
        "span.tsHeadline600Large",
        'div[data-widget="webAddToCart"] span',
        "div[data-widget='webPrice'] span",
        "span[data-test-id='price-block-current-price']",
        ".lp4.l6p",
        ".pl.p-lg",
    ],
    "name_css": "h1.pdp_bg9.tsHeadline550Medium",
}

# Селекторы, предоставленные пользователем, с небольшой адаптацией для надежности
WB_SELECTORS = {
    "price_css": "h2[class*='mo-typography_color_danger']",
    "name_css": "h3[class*='productTitle']",
}


def _get_selenium_driver():
    """Настраивает и возвращает экземпляр драйвера Selenium."""
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    )
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--lang=ru-RU")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    service = ChromeService(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def _clean_price(price_text: str) -> Optional[float]:
    """Очищает строку с ценой, оставляя только цифры."""
    if not price_text:
        return None
    cleaned_price = re.sub(r"[^\d]", "", price_text)
    return float(cleaned_price) if cleaned_price else None


def _get_product_name_bs(page_source: str, selector: str) -> Optional[str]:
    """Извлекает название продукта с помощью BeautifulSoup."""
    soup = BeautifulSoup(page_source, "html.parser")
    name_element = soup.select_one(selector)
    return name_element.text.strip() if name_element else None


async def get_price(url: str) -> Optional[Tuple[float, str]]:
    """
    Асинхронно получает цену и название товара, определяя сайт по URL.
    """
    hostname = urlparse(url).hostname
    if not hostname:
        return None, None

    if "ozon.ru" in hostname:
        return await get_ozon_price(url)
    elif "wildberries.ru" in hostname:
        return await get_wb_price(url)
    else:
        print(f"Сайт не поддерживается: {hostname}")
        return None, None


async def get_ozon_price(url: str) -> Optional[Tuple[float, str]]:
    """Асинхронно получает цену и название товара со страницы Ozon."""
    loop = asyncio.get_running_loop()

    def scrape():
        price_text = None
        product_name = None
        driver = _get_selenium_driver()
        try:
            stealth(
                driver,
                languages=["ru-RU", "ru"],
                vendor="Google Inc.",
                platform="Win32",
                webgl_vendor="Intel Inc.",
                renderer="Intel Iris OpenGL Engine",
                fix_hairline=True,
            )
            driver.get(url)
            wait = WebDriverWait(driver, 15)
            wait.until(
                EC.presence_of_element_located((By.XPATH, "//span[contains(text(), '₽')]"))
            )

            page_source = driver.page_source
            product_name = _get_product_name_bs(page_source, OZON_SELECTORS["name_css"])

            # Поиск цены по XPath
            for xpath in OZON_SELECTORS["price_xpaths"]:
                try:
                    elements = driver.find_elements(By.XPATH, xpath)
                    for element in elements:
                        if element.text and "₽" in element.text:
                            price_text = element.text
                            break
                except Exception:
                    continue
                if price_text:
                    break
            
            # Поиск цены по CSS, если XPath не сработал
            if not price_text:
                for selector in OZON_SELECTORS["price_css"]:
                    try:
                        elements = driver.find_elements(By.CSS_SELECTOR, selector)
                        for element in elements:
                            if element.text and "₽" in element.text:
                                price_text = element.text
                                break
                    except Exception:
                        continue
                    if price_text:
                        break
            
            if price_text:
                return _clean_price(price_text), product_name, None
            else:
                return None, None, driver.page_source

        finally:
            driver.quit()

    price, product_name, page_source_on_failure = await loop.run_in_executor(None, scrape)
    
    if page_source_on_failure:
        debug_path = "ozon_page_source.html"
        with open(debug_path, "w", encoding="utf-8") as f:
            f.write(page_source_on_failure)
        print(f"❌ Цена Ozon не найдена. HTML сохранен в '{debug_path}'.")

    return price, product_name


async def get_wb_price(url: str) -> Optional[Tuple[float, str]]:
    """Асинхронно получает цену и название товара со страницы Wildberries."""
    loop = asyncio.get_running_loop()

    def scrape():
        driver = _get_selenium_driver()
        try:
            stealth(driver, languages=["ru-RU", "ru"], vendor="Google Inc.", platform="Win32")
            driver.get(url)
            wait = WebDriverWait(driver, 15)
            
            # Ждем появления цены и названия
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, WB_SELECTORS["price_css"])))
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, WB_SELECTORS["name_css"])))

            page_source = driver.page_source
            soup = BeautifulSoup(page_source, "html.parser")

            price_element = soup.select_one(WB_SELECTORS["price_css"])
            price_text = price_element.text if price_element else None

            name_element = soup.select_one(WB_SELECTORS["name_css"])
            product_name = name_element.text.strip() if name_element else None

            return _clean_price(price_text), product_name, None
        
        except Exception as e:
            print(f"Ошибка при парсинге WB {url}: {e}")
            return None, None, driver.page_source
        finally:
            driver.quit()

    price, product_name, page_source_on_failure = await loop.run_in_executor(None, scrape)

    if page_source_on_failure:
        debug_path = "wb_page_source.html"
        with open(debug_path, "w", encoding="utf-8") as f:
            f.write(page_source_on_failure)
        print(f"❌ Цена WB не найдена. HTML сохранен в '{debug_path}'.")

    return price, product_name