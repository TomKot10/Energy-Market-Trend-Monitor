import json
import re
import time
import html
from collections import Counter
from datetime import datetime, UTC
from urllib.parse import urljoin, urlparse

import requests
import pandas as pd
from bs4 import BeautifulSoup


SECTION_URL = "https://www.wnp.pl/energia/"
MAX_ARTICLES = 5
REQUEST_TIMEOUT = 25

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:3b"

OUTPUT_JSON = "trend_report_wnp_ollama.json"
OUTPUT_CSV = "trend_report_wnp_ollama.csv"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Connection": "keep-alive",
}

BAD_GENERIC_TOPICS = {
    "energia", "rynek", "branża", "artykuł", "newsy", "sektor", "business", "unknown"
}

BAD_GENERIC_TRENDS = {
    "energia", "rynek", "branża", "artykuły", "newsy", "unknown"
}

POLISH_STOPWORDS = {
    "i", "oraz", "a", "w", "z", "na", "do", "o", "od", "po", "za", "dla", "że",
    "to", "ten", "ta", "te", "tych", "tym", "tę", "który", "która", "które",
    "jak", "czy", "ale", "już", "się", "nie", "jest", "są", "był", "była", "były",
    "ma", "miał", "miała", "mieć", "tak", "też", "jego", "jej", "ich", "przez",
    "pod", "nad", "między", "przy", "we", "ze", "u", "niż", "lub", "ani", "więc",
    "bo", "gdy", "kiedy", "których", "którym", "którego", "której", "firma",
    "spółka", "spółki", "polska", "polsce", "wnp", "roku", "lat", "mln", "mld",
    "tys", "orlen", "arp", "osge", "pej", "pge", "eu", "ue", "aci", "europe",
    "projekt", "projekcie", "projekty", "artykuł", "artykułu", "zdaniem", "według",
    "oraz", "który", "która", "które", "będzie", "mogą", "może", "został", "została",
    "podpisano", "ważną", "sytuacji", "sytuacja", "dotyczą", "dotyczy", "latami",
    "przez", "około", "nawet", "bardzo", "także", "tak", "tym", "tych", "jego",
}

TOPIC_KEYWORDS = {
    "atom": "rozwój energetyki jądrowej",
    "jądrow": "rozwój energetyki jądrowej",
    "smr": "rozwój małych reaktorów jądrowych",
    "reaktor": "rozwój energetyki jądrowej",
    "węgl": "przyszłość aktywów węglowych",
    "blackout": "bezpieczeństwo dostaw energii",
    "lotnisk": "bezpieczeństwo dostaw paliw",
    "paliwo lotnicze": "bezpieczeństwo dostaw paliw",
    "orlen": "bezpieczeństwo dostaw paliw",
    "gaz": "rola gazu w transformacji",
    "oze": "rozwój niskoemisyjnych źródeł energii",
    "magazyn": "elastyczność i bezpieczeństwo systemu",
}


def clean_text(text: str) -> str:
    if not text:
        return "unknown"
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if text else "unknown"


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


def cleanup_sentence(text: str) -> str:
    text = normalize_whitespace(text)
    text = text.replace("rynk mocy", "rynku mocy")
    text = text.replace("Złóż węglowe", "złoża węgla")
    text = text.replace("may skrywać", "mogą skrywać")
    text = text.replace("co jest pozytywnym dla projektu", "co może przyspieszyć realizację projektu")
    text = text.replace("miliony złotych strat", "wysokie koszty dla gospodarki")
    text = text.replace("małej atomu", "małego atomu")
    text = text.replace("polski atom", "energetyka jądrowa w Polsce")
    return text.strip()


def shorten_to_sentences(text: str, max_sentences: int = 2, max_chars: int = 420) -> str:
    text = cleanup_sentence(text)
    parts = re.split(r"(?<=[.!?])\s+", text)
    parts = [p.strip() for p in parts if p.strip()]
    if not parts:
        return "unknown"

    out = []
    total = 0
    for p in parts:
        if len(out) >= max_sentences:
            break
        if total + len(p) > max_chars and out:
            break
        out.append(p)
        total += len(p)

    result = " ".join(out).strip()
    return result[:max_chars] if result else "unknown"


def fetch_html(url: str) -> str:
    response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.text


def is_valid_article_url(url: str, section_url: str) -> bool:
    if not url:
        return False

    parsed = urlparse(url)
    if parsed.netloc not in {"www.wnp.pl", "wnp.pl"}:
        return False
    if not parsed.path.endswith(".html"):
        return False

    section_path = urlparse(section_url).path.strip("/")
    if section_path and f"/{section_path}/" not in parsed.path:
        return False

    return True


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def extract_article_links_from_section(section_url: str, limit: int = 5) -> list[str]:
    html_doc = fetch_html(section_url)
    soup = BeautifulSoup(html_doc, "lxml")

    raw_links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        absolute_url = urljoin(section_url, href)
        if is_valid_article_url(absolute_url, section_url):
            raw_links.append(canonicalize_url(absolute_url))

    unique_links = []
    seen = set()

    for link in raw_links:
        if link in seen:
            continue

        slug = urlparse(link).path.lower()
        duplicate_hit = False

        for existing in unique_links:
            existing_slug = urlparse(existing).path.lower()
            if slug == existing_slug or slug in existing_slug or existing_slug in slug:
                duplicate_hit = True
                break

        if not duplicate_hit:
            seen.add(link)
            unique_links.append(link)

        if len(unique_links) == limit:
            break

    if len(unique_links) < limit:
        raise ValueError(f"Znaleziono tylko {len(unique_links)} unikalnych artykułów w sekcji {section_url}.")

    return unique_links[:limit]


def extract_meta_content(soup: BeautifulSoup, property_name: str):
    tag = soup.find("meta", attrs={"property": property_name})
    if tag and tag.get("content"):
        return clean_text(tag["content"])
    return None


def extract_name_meta(soup: BeautifulSoup, name: str):
    tag = soup.find("meta", attrs={"name": name})
    if tag and tag.get("content"):
        return clean_text(tag["content"])
    return None


def extract_article_data(article_url: str) -> dict:
    html_doc = fetch_html(article_url)
    soup = BeautifulSoup(html_doc, "lxml")

    title = (
        extract_meta_content(soup, "og:title")
        or (soup.title.get_text(strip=True) if soup.title else None)
        or "unknown"
    )

    published_at = (
        extract_meta_content(soup, "article:published_time")
        or extract_name_meta(soup, "date")
        or datetime.now(UTC).isoformat()
    )

    paragraphs = []
    candidate_selectors = [
        "article p",
        ".article p",
        ".articleBody p",
        ".article-content p",
        ".content p",
        ".txt p",
        ".main-content p",
        ".news-content p",
    ]

    for selector in candidate_selectors:
        found = soup.select(selector)
        if found:
            for p in found:
                text = clean_text(p.get_text(" ", strip=True))
                if text != "unknown" and len(text) > 40:
                    paragraphs.append(text)
            if len(paragraphs) >= 3:
                break

    if len(paragraphs) < 3:
        for p in soup.find_all("p"):
            text = clean_text(p.get_text(" ", strip=True))
            if text != "unknown" and len(text) > 40:
                paragraphs.append(text)

    blacklist_phrases = [
        "zobacz również",
        "czytaj także",
        "reklama",
        "newsletter",
        "partnerem serwisu",
        "więcej informacji",
        "polityka prywatności",
        "zapisz się",
        "wideo",
    ]

    filtered = []
    for p in paragraphs:
        p_lower = p.lower()
        if not any(phrase in p_lower for phrase in blacklist_phrases):
            filtered.append(p)

    article_text = " ".join(filtered[:4]).strip()
    if not article_text:
        article_text = "unknown"

    article_text = normalize_whitespace(article_text)[:1800]

    return {
        "title": cleanup_sentence(title),
        "source": "WNP",
        "url": article_url,
        "published_at": published_at,
        "article_text": article_text,
    }


def fetch_latest_articles_from_wnp(section_url: str, limit: int = 5) -> list[dict]:
    links = extract_article_links_from_section(section_url, limit=limit)

    articles = []
    seen_urls = set()

    for link in links:
        try:
            article_data = extract_article_data(link)
            if article_data["url"] in seen_urls:
                continue
            seen_urls.add(article_data["url"])
            articles.append(article_data)
            time.sleep(0.8)
        except Exception as e:
            print(f"Nie udało się pobrać artykułu: {link}\nBłąd: {e}")

    if len(articles) < limit:
        raise ValueError(f"Udało się pobrać tylko {len(articles)} pełnych i unikalnych artykułów, potrzebne jest {limit}.")

    return articles[:limit]


def build_system_prompt() -> str:
    return """
Jesteś analitykiem rynku energii przygotowującym krótką analizę dla dużej firmy energetycznej.

Masz przeanalizować 5 artykułów i zwrócić WYŁĄCZNIE poprawny JSON.

Zasady:
1. Używaj tylko informacji z wejścia.
2. Nie używaj wiedzy zewnętrznej.
3. Nie wymyślaj faktów.
4. Jeśli czegoś nie da się ustalić, wpisz "unknown".
5. Nie zwracaj żadnego tekstu poza JSON.
6. Summary ma mieć maksymalnie 2 zdania.
7. Explanation ma mieć maksymalnie 2 zdania.
8. Business implication ma mieć maksymalnie 2 zdania.
9. Trend name nie może być ogólnym słowem typu "energia", "rynek", "branża".

Dla każdego artykułu:
- zachowaj title, source, url, published_at dokładnie jak w wejściu
- keywords: 3 do 6 konkretnych słów kluczowych
- sentiment: positive, neutral albo negative
- main_topic: konkretny temat artykułu, nie ogólny
- summary: krótko i rzeczowo

Dla trendu:
- trend_name: krótki i konkretny
- explanation: co się dzieje i dlaczego to ważne
- business_implication: co firma powinna zrobić

Zwróć tylko JSON.
""".strip()


def token_candidates(text: str) -> list[str]:
    text = normalize_whitespace(text.lower())
    text = re.sub(r"[^a-ząćęłńóśźż0-9\s-]", " ", text)
    text = re.sub(r"\s+", " ", text)

    words = text.split()
    tokens = []

    for i, w in enumerate(words):
        if len(w) >= 4 and w not in POLISH_STOPWORDS:
            tokens.append(w)

        if i < len(words) - 1:
            bg = f"{words[i]} {words[i+1]}"
            if all(len(x) >= 3 for x in bg.split()) and not any(x in POLISH_STOPWORDS for x in bg.split()):
                tokens.append(bg)

    return tokens


def infer_keywords_from_article(fallback: dict, max_items: int = 4) -> list[str]:
    title = fallback.get("title", "")
    text = fallback.get("article_text", "")
    joined = f"{title} {text}"

    manual_priority = [
        ("smr", "SMR"),
        ("bwrx-300", "BWRX-300"),
        ("atom", "mały atom"),
        ("jądrow", "energetyka jądrowa"),
        ("reaktor", "reaktory jądrowe"),
        ("blackout", "blackout"),
        ("bloków węgl", "bloki węglowe"),
        ("węgla", "złoża węgla"),
        ("paliwo lotnicze", "paliwo lotnicze"),
        ("lotnisk", "lotniska"),
        ("ormuz", "cieśnina Ormuz"),
        ("bezpieczeństwo", "bezpieczeństwo dostaw"),
        ("nowelizac", "nowelizacja przepisów"),
        ("inwestycj", "inwestycje energetyczne"),
    ]

    found = []
    low = joined.lower()

    for trigger, label in manual_priority:
        if trigger in low and label not in found:
            found.append(label)

    counts = Counter(token_candidates(joined))
    for token, _ in counts.most_common(15):
        pretty = token.strip()
        if pretty in POLISH_STOPWORDS:
            continue
        if len(pretty) < 4:
            continue
        if pretty not in found:
            found.append(pretty)
        if len(found) >= max_items:
            break

    if len(found) < 3:
        title_words = [w for w in re.findall(r"[A-Za-zĄąĆćĘęŁłŃńÓóŚśŹźŻż0-9-]+", title) if len(w) >= 4]
        for w in title_words:
            w_clean = cleanup_sentence(w)
            if w_clean.lower() not in {x.lower() for x in found} and w_clean.lower() not in POLISH_STOPWORDS:
                found.append(w_clean)
            if len(found) >= max_items:
                break

    found = [cleanup_sentence(x) for x in found if x and x.lower() != "unknown"]
    found = list(dict.fromkeys(found))

    if len(found) < 3:
        defaults = ["energetyka", "inwestycje", "bezpieczeństwo"]
        for d in defaults:
            if d not in found:
                found.append(d)

    return found[:max_items]


def infer_topic_from_text(title: str, keywords: list[str], summary: str) -> str:
    joined = f"{title} {' '.join(keywords)} {summary}".lower()

    if "smr" in joined or "mały atom" in joined or "reaktor" in joined:
        return "rozwój małych reaktorów jądrowych w Polsce"
    if "atom" in joined or "jądrow" in joined:
        return "inwestycje jądrowe w Polsce"
    if "blackout" in joined or "bloków węgl" in joined or "rynku mocy" in joined:
        return "przyszłość bloków węglowych po 2028 roku"
    if "lotnisk" in joined or "paliwo lotnicze" in joined or "ormuz" in joined:
        return "bezpieczeństwo dostaw paliwa lotniczego"
    if "złoża węgla" in joined or "węgla" in joined or "poszukiwania" in joined:
        return "rola krajowych zasobów węgla"
    return "transformacja sektora energii w Polsce"


def infer_trend_from_articles(articles: list[dict]) -> tuple[str, str, str]:
    text_blob = " ".join(
        " ".join(a.get("keywords", [])) + " " + a.get("main_topic", "") + " " + a.get("summary", "")
        for a in articles
    ).lower()

    counter = Counter()
    for trigger, label in TOPIC_KEYWORDS.items():
        if trigger in text_blob:
            counter[label] += 1

    if not counter:
        trend_name = "przyspieszenie transformacji energetycznej"
    else:
        trend_name = counter.most_common(1)[0][0]

    if "jądrow" in trend_name or "smr" in trend_name:
        explanation = (
            "W analizowanych artykułach widać wyraźny nacisk na rozwój projektów jądrowych i ułatwienia dla nowych inwestycji w tym obszarze. "
            "Jednocześnie sektor nadal mierzy się z wyzwaniami dotyczącymi bezpieczeństwa dostaw i przebudowy miksu energetycznego."
        )
        implication = (
            "Firma energetyczna powinna przyspieszyć budowę portfela inwestycji w nowe źródła, szczególnie projekty jądrowe, "
            "oraz łączyć je z analizą bezpieczeństwa systemu i zmian regulacyjnych."
        )
        return "przyspieszenie transformacji energetycznej", explanation, implication

    if "węgl" in trend_name or "blackout" in trend_name:
        explanation = (
            "Artykuły pokazują rosnące napięcie między potrzebą utrzymania bezpieczeństwa dostaw energii a ograniczaniem roli najstarszych aktywów węglowych. "
            "To zwiększa presję na szybkie przygotowanie alternatywnych źródeł mocy i scenariuszy transformacji."
        )
        implication = (
            "Firma energetyczna powinna przygotować scenariusze wygaszania najbardziej ryzykownych aktywów węglowych "
            "oraz zwiększyć inwestycje w źródła i rozwiązania wzmacniające stabilność systemu."
        )
        return "bezpieczeństwo dostaw i transformacja", explanation, implication

    explanation = (
        "Artykuły wskazują, że polski sektor energii jednocześnie inwestuje w nowe technologie i mierzy się z ryzykami związanymi z bezpieczeństwem dostaw oraz przyszłością dotychczasowych aktywów. "
        "To pokazuje, że transformacja energetyczna staje się coraz pilniejszym procesem strategicznym."
    )
    implication = (
        "Firma energetyczna powinna równolegle rozwijać inwestycje w nowe źródła energii oraz wzmacniać analizy bezpieczeństwa systemu, paliw i infrastruktury krytycznej."
    )
    return "przyspieszenie transformacji energetycznej", explanation, implication


def ensure_required_top_fields(result: dict) -> dict:
    if not isinstance(result, dict):
        result = {}

    result["source"] = "WNP"
    result["section_url"] = SECTION_URL
    result["scrape_timestamp"] = datetime.now(UTC).isoformat()

    if "articles" not in result or not isinstance(result["articles"], list):
        result["articles"] = []

    if "cross_article_trend" not in result or not isinstance(result["cross_article_trend"], dict):
        result["cross_article_trend"] = {}

    trend = result["cross_article_trend"]
    trend.setdefault("trend_name", "unknown")
    trend.setdefault("explanation", "unknown")
    trend.setdefault("business_implication", "unknown")

    return result


def normalize_keywords(keywords, fallback: dict) -> list[str]:
    cleaned = []
    seen = set()

    if isinstance(keywords, list):
        for k in keywords:
            k = cleanup_sentence(str(k)).strip(" .,-")
            if not k:
                continue
            if len(k) < 3:
                continue
            k_low = k.lower()
            if k_low in {"energia", "rynek", "branża", "artykuł", "unknown"}:
                continue
            if k_low not in seen:
                seen.add(k_low)
                cleaned.append(k)

    if len(cleaned) < 3:
        inferred = infer_keywords_from_article(fallback, max_items=4)
        for k in inferred:
            k_low = k.lower()
            if k_low not in seen:
                seen.add(k_low)
                cleaned.append(k)

    cleaned = cleaned[:6]
    while len(cleaned) < 3:
        cleaned.append("bezpieczeństwo")

    return cleaned


def ensure_article_shape(article: dict, fallback: dict) -> dict:
    if not isinstance(article, dict):
        article = {}

    fixed = {
        "title": cleanup_sentence(article.get("title", fallback["title"])),
        "source": article.get("source", fallback["source"]),
        "url": article.get("url", fallback["url"]),
        "published_at": article.get("published_at", fallback["published_at"]),
        "keywords": normalize_keywords(article.get("keywords", []), fallback),
        "sentiment": article.get("sentiment", "neutral"),
        "main_topic": cleanup_sentence(article.get("main_topic", "unknown")),
        "summary": shorten_to_sentences(article.get("summary", "unknown"), max_sentences=2, max_chars=420),
    }

    if fixed["sentiment"] not in {"positive", "neutral", "negative"}:
        fixed["sentiment"] = "neutral"

    if fixed["main_topic"].strip().lower() in BAD_GENERIC_TOPICS or fixed["main_topic"].strip() == "":
        fixed["main_topic"] = infer_topic_from_text(fixed["title"], fixed["keywords"], fixed["summary"])

    if fixed["summary"] == "unknown":
        fixed["summary"] = shorten_to_sentences(fallback.get("article_text", "unknown"), max_sentences=2, max_chars=420)

    return fixed


def repair_result(result: dict, input_articles: list[dict]) -> dict:
    result = ensure_required_top_fields(result)

    output_articles = result.get("articles", [])
    repaired_articles = []
    used_urls = set()

    for fallback in input_articles:
        matched = None
        for article in output_articles:
            if isinstance(article, dict) and article.get("url") == fallback["url"] and fallback["url"] not in used_urls:
                matched = article
                used_urls.add(fallback["url"])
                break

        repaired_articles.append(ensure_article_shape(matched, fallback))

    result["articles"] = repaired_articles

    trend = result["cross_article_trend"]
    trend["trend_name"] = cleanup_sentence(str(trend.get("trend_name", "unknown")))
    trend["explanation"] = shorten_to_sentences(trend.get("explanation", "unknown"), max_sentences=2, max_chars=420)
    trend["business_implication"] = shorten_to_sentences(trend.get("business_implication", "unknown"), max_sentences=2, max_chars=420)

    inferred_name, inferred_expl, inferred_impl = infer_trend_from_articles(repaired_articles)

    if trend["trend_name"].strip().lower() in BAD_GENERIC_TRENDS or trend["trend_name"].strip() == "":
        trend["trend_name"] = inferred_name

    if trend["explanation"].lower() == "unknown" or any(
        bad in trend["explanation"].lower()
        for bad in ["servery co 14 dni", "odwiedza nasze servery", "pojawiło się 5 artykułów", "pojawily sie 5 artykulow"]
    ):
        trend["explanation"] = inferred_expl

    if trend["business_implication"].lower() == "unknown":
        trend["business_implication"] = inferred_impl

    return result


def validate_result(result: dict, input_articles: list[dict]) -> dict:
    result = repair_result(result, input_articles)

    if len(result["articles"]) != 5:
        raise ValueError("Model nie zwrócił 5 artykułów.")

    input_urls = sorted([a["url"] for a in input_articles])
    output_urls = sorted([a["url"] for a in result["articles"]])

    if input_urls != output_urls:
        raise ValueError("Model zwrócił inne URL niż wejściowe.")

    return result


def call_ollama_llm(articles: list[dict], max_retries: int = 3) -> dict:
    payload_for_model = {
        "source": "WNP",
        "scrape_timestamp": datetime.now(UTC).isoformat(),
        "section_url": SECTION_URL,
        "articles": articles,
    }

    prompt = (
        build_system_prompt()
        + "\n\nDane wejściowe do analizy:\n"
        + json.dumps(payload_for_model, ensure_ascii=False, indent=2)
    )

    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(
                OLLAMA_URL,
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {
                        "temperature": 0.0,
                        "num_predict": 1800,
                    }
                },
                timeout=300,
            )
            response.raise_for_status()

            data = response.json()
            raw = data.get("response", "").strip()
            if not raw:
                raise ValueError("Model nie zwrócił treści.")

            start = raw.find("{")
            end = raw.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise ValueError(f"Brak poprawnego obiektu JSON w odpowiedzi modelu: {raw[:500]}")

            raw_json = raw[start:end + 1]

            try:
                parsed = json.loads(raw_json)
            except Exception:
                print("Model zwrócił niepoprawny JSON — retry...")
                raise

            validated = validate_result(parsed, articles)
            return validated

        except Exception as e:
            last_error = e
            print(f"[Próba {attempt}/{max_retries}] Błąd odpowiedzi modelu: {e}")
            time.sleep(2)

    raise RuntimeError(f"Nie udało się uzyskać poprawnego wyniku z modelu. Ostatni błąd: {last_error}")


def save_outputs(report: dict) -> None:
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    rows = []
    for article in report.get("articles", []):
        rows.append({
            "title": article.get("title", "unknown"),
            "source": article.get("source", "unknown"),
            "url": article.get("url", "unknown"),
            "published_at": article.get("published_at", "unknown"),
            "keywords": ", ".join(article.get("keywords", [])),
            "sentiment": article.get("sentiment", "unknown"),
            "main_topic": article.get("main_topic", "unknown"),
            "summary": article.get("summary", "unknown"),
        })

    df = pd.DataFrame(rows)
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")


def print_summary(report: dict) -> None:
    print("\n=== PODSUMOWANIE ===")
    print(f"Źródło: {report.get('source', 'unknown')}")
    print(f"Sekcja: {report.get('section_url', 'unknown')}")
    print(f"Data pobrania: {report.get('scrape_timestamp', 'unknown')}\n")

    for i, article in enumerate(report.get("articles", []), start=1):
        print(f"{i}. {article.get('title', 'unknown')}")
        print(f"   URL: {article.get('url', 'unknown')}")
        print(f"   Data: {article.get('published_at', 'unknown')}")
        print(f"   Sentiment: {article.get('sentiment', 'unknown')}")
        print(f"   Main topic: {article.get('main_topic', 'unknown')}")
        print(f"   Keywords: {', '.join(article.get('keywords', []))}")
        print(f"   Summary: {article.get('summary', 'unknown')}\n")

    trend = report.get("cross_article_trend", {})
    print("=== GŁÓWNY TREND ===")
    print(trend.get("trend_name", "unknown"))
    print("\nWyjaśnienie:")
    print(trend.get("explanation", "unknown"))
    print("\nImplikacja biznesowa:")
    print(trend.get("business_implication", "unknown"))


def main():
    print(f"Pobieram najnowsze artykuły z: {SECTION_URL}")
    articles = fetch_latest_articles_from_wnp(SECTION_URL, limit=MAX_ARTICLES)

    print("Wysyłam dane do lokalnego LLM przez Ollama...")
    report = call_ollama_llm(articles)

    print("Zapisuję wyniki...")
    save_outputs(report)
    print_summary(report)

    print(f"\nZapisano JSON: {OUTPUT_JSON}")
    print(f"Zapisano CSV:  {OUTPUT_CSV}")


if __name__ == "__main__":
    main()