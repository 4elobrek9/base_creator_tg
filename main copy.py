# -*- coding: utf-8 -*-
import os
import time
import sqlite3
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from rich.console import Console
from rich.panel import Panel

console = Console()
DB_NAME = "deep_parsed_users.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_name TEXT,
            display_name TEXT,
            username TEXT,
            phone TEXT,
            bio TEXT,
            user_id TEXT,
            UNIQUE(group_name, user_id)
        )
    """)
    conn.commit()
    return conn

def setup_browser():
    chrome_options = Options()
    profile_path = os.path.join(os.getcwd(), "chrome_profile")
    chrome_options.add_argument(f"user-data-dir={profile_path}")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "const newProto = navigator.__proto__; delete newProto.webdriver; navigator.__proto__ = newProto;"
    })
    return driver

def safe_get_text(driver, xpath, timeout=4):
    try:
        element = WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.XPATH, xpath)))
        return element.text.strip()
    except:
        return "n/a"

def deep_parse_members(driver, conn, group_title):
    cursor = conn.cursor()
    console.print(f"[bold green]Парсим участников: {group_title}[/bold green]")
    
    last_count = 0
    scroll_attempts = 0
    while scroll_attempts < 8:
        # ТОЧНЫЙ селектор из tg2.html — список участников в правой колонке
        members = driver.find_elements(By.XPATH,
            "//div[contains(@class,'search-super-content-members')]//a[contains(@class,'chatlist-chat') and contains(@class,'row-clickable')]")
        
        if len(members) == last_count:
            scroll_attempts += 1
        else:
            scroll_attempts = 0
        
        for i in range(last_count, len(members)):
            try:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", members[i])
                time.sleep(0.8)
                members[i].click()
                time.sleep(1.8)
                
                # НОВЫЕ XPath из актуального профиля (tg2.html)
                d_name = safe_get_text(driver, "//div[contains(@class,'profile-name')]//span[contains(@class,'peer-title')] | //div[contains(@class,'profile-title')]//h3")
                u_name = safe_get_text(driver, "//div[contains(@class,'profile-subtitle')] | //div[contains(@class,'username')]")
                bio   = safe_get_text(driver, "//div[contains(@class,'profile-description')] | //div[contains(@class,'bio')] | //div[contains(@class,'row-title') and contains(@class,'pre-wrap')]")
                phone = safe_get_text(driver, "//div[contains(@class,'profile-content')]//div[contains(text(),'+')]")
                
                u_id = u_name if u_name != "n/a" else d_name
                
                # Защита от случайного парсинга статистики группы
                if "members" in u_name.lower() or "online" in u_name.lower():
                    webdriver.ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                    continue
                
                cursor.execute("""
                    INSERT OR IGNORE INTO users 
                    (group_name, display_name, username, phone, bio, user_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (group_title, d_name, u_name, phone, bio, u_id))
                conn.commit()
                
                console.print(f"[cyan]✓ Спарсили:[/cyan] {d_name} | @{u_name if u_name != 'n/a' else '—'}")
                
                webdriver.ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                time.sleep(0.7)
            except:
                continue
        
        last_count = len(members)
        if members:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", members[-1])
        time.sleep(2)

def scroll_chat_list(driver):
    try:
        container = driver.find_element(By.CSS_SELECTOR, ".scrollable.scrollable-y.chatlist-parts, .scrollable.scrollable-y")
        driver.execute_script("arguments[0].scrollTop += 1400;", container)
        return True
    except:
        driver.execute_script("window.scrollBy(0, 1400);")
        return False

def main():
    console.print(Panel.fit("[bold cyan]TG DEEP BROWSER PARSER v2.6[/bold cyan]\n"
                            "Точные селекторы из твоего tg2.html", border_style="cyan"))
    
    conn = init_db()
    driver = setup_browser()
    
    try:
        driver.get("https://web.telegram.org/k/")
        console.print("[yellow]✅ Браузер открыт. Залогинься и дождись загрузки.[/yellow]")
        input("\nНажми Enter, когда готов...")
        time.sleep(6)
        
        processed_groups = set()
        scroll_attempts = 0
        
        while True:
            chats = driver.find_elements(By.XPATH,
                "//a[contains(@class,'chatlist-chat') and contains(@class,'row-clickable')]")
            
            console.print(f"[dim]Видно чатов: {len(chats)}[/dim]")
            new_found = False
            
            for chat in chats:
                try:
                    peer_id = chat.get_attribute("data-peer-id") or ""
                    if not peer_id.startswith("-"):
                        continue
                    
                    chat_text = chat.text.lower()
                    if any(w in chat_text for w in ["bot", "subscriber", "channel", "канал", "подписчик", "подписчиков"]):
                        continue
                    
                    title_el = chat.find_element(By.XPATH, ".//span[contains(@class,'peer-title')]")
                    group_title = title_el.text.strip()
                    
                    if not group_title or group_title in processed_groups:
                        continue
                    
                    new_found = True
                    processed_groups.add(group_title)
                    
                    console.print(f"[magenta]>>> Заходим в группу: {group_title} (ID: {peer_id})[/magenta]")
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", chat)
                    chat.click()
                    time.sleep(1.7)
                    
                    # Открываем инфо группы
                    header = WebDriverWait(driver, 6).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, ".chat-info, .ChatInfo, .chat-header"))
                    )
                    header.click()
                    time.sleep(2)
                    
                    # Переключаемся на вкладку "Участники"
                    try:
                        members_btn = WebDriverWait(driver, 4).until(
                            EC.element_to_be_clickable((By.XPATH, "//div[contains(text(),'Участники') or contains(text(),'Members')]"))
                        )
                        members_btn.click()
                        time.sleep(1.5)
                    except:
                        pass
                    
                    deep_parse_members(driver, conn, group_title)
                    
                    webdriver.ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                    time.sleep(1.2)
                    
                except:
                    continue
            
            if not new_found:
                scroll_attempts += 1
                if scroll_attempts > 15:
                    console.print(f"[yellow]Больше групп не найдено (обработано {len(processed_groups)}). Завершаем.[/yellow]")
                    break
                console.print(f"[dim]Прокрутка чатов... (попытка {scroll_attempts}/15)[/dim]")
                scroll_chat_list(driver)
                time.sleep(3.5)
    
    except Exception as e:
        console.print(f"[bold red]Ошибка: {e}[/bold red]")
    finally:
        driver.quit()
        conn.close()
        console.print("[bold green]✅ Парсинг завершён! Данные в deep_parsed_users.db[/bold green]")

if __name__ == "__main__":
    main()