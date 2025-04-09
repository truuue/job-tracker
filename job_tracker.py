import requests
from bs4 import BeautifulSoup
from notion_client import Client
from dotenv import load_dotenv
import os
import re
from datetime import datetime, timedelta
import time
import random
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

notion = Client(auth=NOTION_TOKEN)

KEYWORDS_REGEX = [
    r"(?i)\b(développeur|developpeur|developer)\b.*\b(full-?stack)\b",
    r"(?i)\b(développeur|developpeur|developer)\b.*\b(front-?end)\b",
    r"(?i)\b(développeur|developpeur|developer)\b.*\b(back-?end)\b",
    r"(?i)\b(react(\.?js)?)\b",
    r"(?i)\b(next(\.?js)?)\b",
    r"(?i)\b(node(\.?js)?)\b",
    r"(?i)\b(golang)\b",
    r"(?i)\b(ux/?ui|ui|ux)\b",
    r"(?i)\b(développeur|developpeur|developer)\b.*\b(logiciel)\b",
    r"(?i)\b(ingénieur|ingenieur)\b.*\b(web)\b",
]

LOCATION_REGEX = [
    r"(?i)(remote)\b",
    r"(?i)(télétravail|teletravail)\b",
    r"(?i)(toulouse)\b",
    r"(?i)(occitanie)\b",
    r"(?i)(hybride)\b",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1"
}


def compute_score(title: str, location: str) -> int:
    score = 0
    text = f"{title.lower()} {location.lower()}"
    for pattern in KEYWORDS_REGEX + LOCATION_REGEX:
        if re.search(pattern, text):
            score += 1
    return score


def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # Mode headless
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--lang=fr-FR")
    chrome_options.add_argument(f"user-agent={HEADERS['User-Agent']}")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver


def fetch_indeed_offers(keyword, location):
    url = f"https://fr.indeed.com/emplois?q={keyword.replace(' ', '+')}&l={location.replace(' ', '+')}&lang=fr"
    print(f"Recherche sur l'URL : {url}")
    driver = None

    try:
        driver = setup_driver()
        driver.get(url)

        try:
            # Attendre que les offres soient chargées
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "div.job_seen_beacon"))
            )
        except Exception as e:
            print(f"Aucune offre trouvée pour {keyword} à {location}")
            return []

        # Petit délai pour s'assurer que tout est chargé
        time.sleep(3)

        # Faire défiler la page pour charger plus de contenu
        last_height = driver.execute_script(
            "return document.body.scrollHeight")
        while True:
            driver.execute_script(
                "window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            new_height = driver.execute_script(
                "return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

        # Utiliser BeautifulSoup pour parser le HTML
        soup = BeautifulSoup(driver.page_source, "html.parser")
        results = []

        jobs = soup.select("div.job_seen_beacon")
        print(f"Nombre d'offres trouvées : {len(jobs)}")

        for job in jobs:
            try:
                title = job.select_one(".jobTitle").get_text(
                    strip=True) if job.select_one(".jobTitle") else ""
                company = job.select_one("[data-testid='company-name']").get_text(
                    strip=True) if job.select_one("[data-testid='company-name']") else "Non spécifié"
                location = job.select_one("[data-testid='text-location']").get_text(
                    strip=True) if job.select_one("[data-testid='text-location']") else ""

                link_elem = job.select_one("h2.jobTitle a")
                link = "https://fr.indeed.com" + \
                    link_elem["href"] if link_elem and "href" in link_elem.attrs else ""

                if title and link:
                    score = compute_score(title, location)
                    results.append({
                        "title": title,
                        "company": company,
                        "location": location,
                        "link": link,
                        "source": "Indeed",
                        "score": score
                    })
            except Exception as e:
                print(f"Erreur lors du parsing d'une offre : {str(e)}")
                continue

        return results

    except Exception as e:
        print(f"Erreur lors de la recherche : {str(e)}")
        return []

    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass


def insert_offer_to_notion(offer):
    notion.pages.create(
        parent={"database_id": DATABASE_ID},
        properties={
            "Title": {"title": [{"text": {"content": offer["title"]}}]},
            "Company": {"rich_text": [{"text": {"content": offer["company"]}}]},
            "Location": {"rich_text": [{"text": {"content": offer["location"]}}]},
            "Link": {"url": offer["link"]},
            "Source": {"select": {"name": offer["source"]}},
            "Date ajoutée": {"date": {"start": datetime.today().isoformat()}},
            "Score": {"rich_text": [{"text": {"content": str(offer["score"])}}]},
        }
    )


def get_existing_links():
    links = []
    has_more = True
    next_cursor = None

    while has_more:
        response = notion.databases.query(
            database_id=DATABASE_ID,
            start_cursor=next_cursor
        )
        for page in response["results"]:
            link = page["properties"].get("Link", {}).get("url")
            if link:
                links.append(link)
        has_more = response.get("has_more", False)
        next_cursor = response.get("next_cursor")

    return links


def clean_old_offers():
    print("Nettoyage des anciennes offres...")
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()

    has_more = True
    next_cursor = None
    deleted_count = 0

    while has_more:
        response = notion.databases.query(
            database_id=DATABASE_ID,
            start_cursor=next_cursor,
            filter={
                "property": "Date ajoutée",
                "date": {
                    "before": week_ago
                }
            }
        )

        for page in response["results"]:
            try:
                notion.pages.update(
                    page_id=page["id"],
                    archived=True  # Ceci "supprime" la page dans Notion
                )
                deleted_count += 1
            except Exception as e:
                print(f"Erreur lors de la suppression d'une offre : {str(e)}")

        has_more = response["has_more"]
        next_cursor = response["next_cursor"] if response["has_more"] else None

    print(f"{deleted_count} offres anciennes supprimées.")


def main():
    all_offers = []
    for keyword in ["developpeur", "react", "node", "golang", "ux/ui"]:
        for location in ["remote", "toulouse"]:
            offers = fetch_indeed_offers(keyword, location)
            all_offers.extend(offers)

    existing_links = get_existing_links()
    new_offers = [offer for offer in all_offers if offer["link"]
                  not in existing_links]

    for offer in new_offers:
        insert_offer_to_notion(offer)
        print(
            f"Ajouté : {offer['title']} @ {offer['company']} (Score: {offer['score']})")

    print(f"{len(new_offers)} nouvelles offres ajoutées.")

    # Nettoyer les anciennes offres après l'ajout des nouvelles
    clean_old_offers()


if __name__ == "__main__":
    main()
