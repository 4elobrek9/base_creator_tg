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
        el = WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.XPATH, xpath)))
        text = el.text.strip()
        return text if text else "n/a"
    except:
        return "n/a"

def deep_parse_members(driver, conn, group_title):
    cursor = conn.cursor()
    console.print(f"[bold green]Парсим участников: {group_title}[/bold green]")
    
    last_count = 0
    no_new_attempts = 0
    total_parsed = 0
    
    while no_new_attempts < 7:
        try:
            members = driver.find_elements(By.CSS_SELECTOR,
                ".search-super-content-members .ListItem, "
                ".search-super-content-members .chatlist-chat, "
                ".search-super-content-members .row-clickable, "
                ".search-super-content-members a[href^='#']"
            )
            
            console.print(f"[dim]Найдено элементов в списке участников: {len(members)}[/dim]")
            
            if len(members) == last_count:
                no_new_attempts += 1
            else:
                no_new_attempts = 0
            
            for i in range(last_count, len(members)):
                try:
                    member = members[i]
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", member)
                    time.sleep(0.45)
                    
                    driver.execute_script("arguments[0].click();", member)
                    time.sleep(0.9)
                    
                    # Ждём открытия профиля
                    WebDriverWait(driver, 6).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, ".profile-name, .peer-title-inner"))
                    )
                    time.sleep(0.5)
                    
                    # === ИМЯ — теперь берём только из профиля (не глобальный "Telegram") ===
                    d_name = safe_get_text(driver,
                        "//div[contains(@class,'profile-name')]//span[contains(@class,'peer-title') or contains(@class,'peer-title-inner')]"
                        " | //span[contains(@class,'peer-title-inner') and ancestor::div[contains(@class,'profile-name') or contains(@class,'profile-avatars-info')]]"
                    )
                    
                    # Если всё равно пусто — берём текст из самого элемента списка (запасной вариант)
                    if not d_name or d_name == "Telegram":
                        d_name = safe_get_text(driver, ".//span[contains(@class,'peer-title')]")  # fallback
                    
                    # USERNAME
                    u_name = safe_get_text(driver,
                        "//div[contains(@class,'row-subtitle') and contains(.,'Username')]/preceding-sibling::div[@class='row-title']"
                        " | //div[@class='row-title' and following-sibling::div[contains(.,'Username')]]"
                        " | //span[starts-with(normalize-space(.),'@')]"
                    )
                    
                    # BIO
                    bio = safe_get_text(driver,
                        "//div[contains(@class,'profile-description') or contains(@class,'bio') or contains(@class,'about') or contains(@class,'pre-wrap')]"
                    )
                    
                    # PHONE
                    phone_raw = safe_get_text(driver, "//*[starts-with(normalize-space(text()),'+')]")
                    phone = phone_raw if phone_raw.startswith('+') and len(phone_raw.replace(' ','').replace('-','')) >= 11 else "n/a"
                    
                    u_id = u_name if u_name != "n/a" else d_name
                    
                    # === УБРАЛИ СКИП "Telegram" ===
                    # Теперь сохраняем всё, даже если имя "Telegram" (редко, но бывает)
                    
                    cursor.execute("""
                        INSERT OR IGNORE INTO users 
                        (group_name, display_name, username, phone, bio, user_id)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (group_title, d_name, u_name, phone, bio, u_id))
                    conn.commit()
                    
                    total_parsed += 1
                    bio_short = (bio[:65] + "...") if len(bio) > 65 else bio
                    console.print(f"[cyan]✓ {total_parsed} | {d_name} | @{u_name} | phone: {phone} | bio: {bio_short}[/cyan]")
                    
                    # Закрываем профиль
                    webdriver.ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                    time.sleep(0.35)
                    webdriver.ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                    time.sleep(0.45)
                    
                except Exception as e:
                    console.print(f"[red]Ошибка на участнике {i+1}: {str(e)[:80]}[/red]")
                    webdriver.ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                    time.sleep(0.6)
                    continue
            
            last_count = len(members)
            
            # Скролл участников
            try:
                container = driver.find_element(By.CSS_SELECTOR, ".search-super-content-members .scrollable-y, .scrollable.scrollable-y")
                driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", container)
            except:
                driver.execute_script("window.scrollBy(0, 2000);")
            time.sleep(0.8)
        
        except Exception as e:
            console.print(f"[yellow]Ошибка в цикле: {str(e)[:80]}[/yellow]")
            time.sleep(1.5)
    
    console.print(f"[green]Готово! Спарсили {total_parsed} участников[/green]")

def scroll_chat_list(driver):
    try:
        container = driver.find_element(By.CSS_SELECTOR, ".scrollable.scrollable-y.chatlist-parts, .scrollable.scrollable-y")
        driver.execute_script("arguments[0].scrollTop += 1400;", container)
        return True
    except:
        driver.execute_script("window.scrollBy(0, 1400);")
        return False

def main():
    console.print(Panel.fit("[bold cyan]TG DEEP BROWSER PARSER v2.7[/bold cyan]\n"
                            "Фикс username, phone и bio (по твоему последнему профилю)", border_style="cyan"))
    
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
            chats = driver.find_elements(By.CSS_SELECTOR,
                "a.chatlist-chat.row-clickable"
            )
            
            console.print(f"[dim]Видно чатов: {len(chats)}[/dim]")
            new_found = False
            
            for chat in chats:
                try:
                    peer_id = chat.get_attribute("data-peer-id") or ""
                    if not peer_id.startswith("-"):
                        continue
                    
                    title_el = chat.find_element(By.CSS_SELECTOR, ".peer-title")
                    group_title = title_el.text.strip()
                    
                    if not group_title or group_title in processed_groups:
                        continue
                    
                    new_found = True
                    processed_groups.add(group_title)
                    
                    console.print(f"[magenta]>>> Заходим в группу: {group_title} (ID: {peer_id})[/magenta]")
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", chat)
                    chat.click()
                    time.sleep(1.8)
                    
                    header = WebDriverWait(driver, 7).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, ".chat-info, .ChatInfo, .chat-header"))
                    )
                    header.click()
                    time.sleep(2.2)
                    
                    try:
                        members_btn = WebDriverWait(driver, 4).until(
                            EC.element_to_be_clickable((By.XPATH, "//*[contains(text(),'Участники') or contains(text(),'Members')]"))
                        )
                        members_btn.click()
                        time.sleep(1.6)
                    except:
                        pass
                    
                    deep_parse_members(driver, conn, group_title)
                    
                    webdriver.ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                    time.sleep(1.3)
                    
                except:
                    continue
            
            if not new_found:
                scroll_attempts += 1
                if scroll_attempts > 15:
                    console.print(f"[yellow]Завершаем (обработано {len(processed_groups)} групп).[/yellow]")
                    break
                console.print(f"[dim]Прокрутка... (попытка {scroll_attempts}/15)[/dim]")
                scroll_chat_list(driver)
                time.sleep(3.8)
    
    except Exception as e:
        console.print(f"[bold red]Ошибка: {e}[/bold red]")
    finally:
        driver.quit()
        conn.close()
        console.print("[bold green]✅ Готово! Данные в deep_parsed_users.db[/bold green]")

if __name__ == "__main__":
    main()