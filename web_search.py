# web_search.py
# ─────────────────────────────────────────────────────────────────────────────
# This file handles everything related to searching the web for topic explanations
#
# WHAT THIS FILE DOES:
# 1. Takes a CS topic (e.g. "Binary Search")
# 2. Searches DuckDuckGo automatically for the best explanation
# 3. Picks the best URL from results (prefers GFG, Wikipedia, etc.)
# 4. Scrapes the page content using BeautifulSoup
# 5. Cleans and returns the relevant text
#
# WHY DUCKDUCKGO?
# - Free, no API key needed
# - Returns good CS results
# - No rate limiting issues for small usage
#
# FLOW:
# topic → DuckDuckGo search → pick best URL → scrape page → clean text → return
# ─────────────────────────────────────────────────────────────────────────────

import time
import re
import requests
from typing import Optional
from bs4 import BeautifulSoup
from ddgs import DDGS

# ── Trusted CS sources — ranked by preference ────────────────────────────────
# Agent 2 will prefer these sites in this order
PREFERRED_SOURCES = [
    "geeksforgeeks.org",
    "wikipedia.org",
    "programiz.com",
    "tutorialspoint.com",
    "javatpoint.com",
    "cs.stanford.edu",
    "brilliant.org",
    "w3schools.com",
    "educative.io",
    "leetcode.com",
]

# ── Request headers — pretend to be a browser ────────────────────────────────
# Some sites block requests that don't have browser headers
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ── Max characters to return per topic ───────────────────────────────────────
MAX_CONTENT_LENGTH = 4000


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1: Search DuckDuckGo for a topic
# ─────────────────────────────────────────────────────────────────────────────
def search_web(topic: str, max_results: int = 8) -> list:
    """
    Search DuckDuckGo for a CS topic
    Returns list of results with title, url, snippet

    We add "computer science explanation tutorial" to the query
    to get educational results instead of random pages
    """
    # Build a good search query
    query = f"{topic} computer science explanation tutorial"
    print(f"  🔍 Searching: '{query}'")

    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title"  : r.get("title", ""),
                    "url"    : r.get("href",  ""),
                    "snippet": r.get("body",  ""),
                })
        print(f"  ✅ Found {len(results)} search results")
    except Exception as e:
        print(f"  ❌ DuckDuckGo search failed: {e}")

    return results


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2: Pick the best URL from search results
# ─────────────────────────────────────────────────────────────────────────────
def pick_best_url(results: list) -> Optional[str]:
    """
    Pick the most reliable URL from search results
    Priority order: GFG > Wikipedia > Programiz > others

    Strategy:
    1. First try to find a result from PREFERRED_SOURCES in order
    2. If none found, return the first result URL
    """
    if not results:
        return None

    # Try preferred sources in priority order
    for preferred in PREFERRED_SOURCES:
        for result in results:
            url = result.get("url", "")
            if preferred in url:
                print(f"  ⭐ Preferred source found: {preferred}")
                return url

    # Fallback: return first result
    first_url = results[0].get("url", "")
    print(f"  📎 Using first result: {first_url[:60]}...")
    return first_url


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3: Scrape the page content
# ─────────────────────────────────────────────────────────────────────────────
def scrape_page(url: str) -> str:
    """
    Fetch and extract clean text from a URL
    Uses BeautifulSoup to parse HTML and extract readable content

    Handles different page structures:
    - GFG: extracts article body
    - Wikipedia: extracts main content
    - Others: extracts all paragraph text
    """
    print(f"  🌐 Scraping: {url[:70]}...")

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=10,              # 10 second timeout
            allow_redirects=True
        )
        response.raise_for_status()  # raise error for 4xx/5xx
    except requests.exceptions.Timeout:
        print(f"   Timeout scraping {url[:50]}")
        return ""
    except requests.exceptions.RequestException as e:
        print(f"   Request failed: {e}")
        return ""

    # Parse HTML
    soup = BeautifulSoup(response.text, "html.parser")

    # ── Remove unwanted elements ──────────────────────────────────────────────
    # These add noise to the content
    for tag in soup(["script", "style", "nav", "footer", "header",
                     "aside", "advertisement", "iframe", "noscript",
                     ".ads", "#ads", ".cookie-banner"]):
        tag.decompose()

    # ── Try site-specific extractors first ────────────────────────────────────
    text = ""

    # GeeksForGeeks — main article is in div.article-body
    if "geeksforgeeks.org" in url:
        article = soup.find("div", {"class": "article-body"})
        if not article:
            article = soup.find("div", {"class": "text"})
        if article:
            text = article.get_text(separator="\n")

    # Wikipedia — main content is in div#mw-content-text
    elif "wikipedia.org" in url:
        content = soup.find("div", {"id": "mw-content-text"})
        if content:
            # Remove citation numbers like [1], [2]
            text = content.get_text(separator="\n")
            text = re.sub(r'\[\d+\]', '', text)

    # Programiz
    elif "programiz.com" in url:
        article = soup.find("div", {"class": "programiz-content"})
        if not article:
            article = soup.find("article")
        if article:
            text = article.get_text(separator="\n")

    # ── Generic fallback — extract all paragraphs ─────────────────────────────
    if not text.strip():
        # Try article tag first
        article = soup.find("article")
        if article:
            text = article.get_text(separator="\n")
        else:
            # Extract all paragraphs
            paragraphs = soup.find_all("p")
            text = "\n".join(p.get_text() for p in paragraphs)

    # ── Also extract code blocks (important for CS topics) ───────────────────
    code_blocks = soup.find_all(["pre", "code"])
    code_text   = ""
    for block in code_blocks[:3]:   # max 3 code blocks
        code = block.get_text().strip()
        if len(code) > 20:          # skip tiny code snippets
            code_text += f"\n[CODE EXAMPLE]\n{code}\n"

    text = text + "\n" + code_text if code_text else text

    print(f"   Scraped {len(text)} characters")
    return text


# ─────────────────────────────────────────────────────────────────────────────
# STEP 4: Clean scraped text
# ─────────────────────────────────────────────────────────────────────────────
def clean_scraped_text(text: str) -> str:
    """
    Clean raw scraped text:
    - Remove excessive whitespace
    - Remove very short lines (menu items, breadcrumbs)
    - Remove lines that are just numbers or symbols
    - Limit total length
    """
    if not text:
        return ""

    lines   = text.split('\n')
    cleaned = []

    for line in lines:
        stripped = line.strip()

        # Skip empty lines
        if not stripped:
            continue

        # Skip very short lines (likely menu items, page numbers)
        if len(stripped) < 20:
            continue

        # Skip lines that are mostly numbers/symbols
        alpha_ratio = sum(c.isalpha() for c in stripped) / len(stripped)
        if alpha_ratio < 0.3:
            continue

        cleaned.append(stripped)

    # Join and limit length
    result = "\n".join(cleaned)

    # Remove excessive newlines
    result = re.sub(r'\n{3,}', '\n\n', result)

    # Limit to MAX_CONTENT_LENGTH characters
    if len(result) > MAX_CONTENT_LENGTH:
        result = result[:MAX_CONTENT_LENGTH] + "\n...[content truncated]"

    return result.strip()


# ─────────────────────────────────────────────────────────────────────────────
# STEP 5: Get snippet from search results as fallback
# ─────────────────────────────────────────────────────────────────────────────
def get_snippets_as_fallback(results: list, topic: str) -> str:
    """
    If scraping fails, combine the snippets from search results
    Not as good as full page, but better than nothing
    """
    if not results:
        return f"No web results found for {topic}"

    snippets = []
    for r in results[:4]:    # use top 4 results
        title   = r.get("title",   "")
        snippet = r.get("snippet", "")
        url     = r.get("url",     "")
        if snippet:
            snippets.append(f"Source: {title}\n{snippet}\nURL: {url}")

    combined = "\n\n".join(snippets)
    print(f"   Using {len(snippets)} snippets as fallback")
    return combined


# ─────────────────────────────────────────────────────────────────────────────
# MAIN FUNCTION: Get web explanation for a topic
# This is what Agent 2 calls
# ─────────────────────────────────────────────────────────────────────────────
def get_web_explanation(topic: str) -> dict:
    """
    Full pipeline: Search → Pick URL → Scrape → Clean → Return

    Returns a dict with:
    - topic:   the topic searched
    - content: the explanation text
    - source:  which website was used
    - url:     the actual URL scraped
    - success: True/False
    """
    print(f"\n Getting web explanation for: '{topic}'")

    # Step 1: Search
    results = search_web(topic)

    if not results:
        return {
            "topic"  : topic,
            "content": f"Could not find web results for '{topic}'",
            "source" : "none",
            "url"    : "",
            "success": False
        }

    # Step 2: Pick best URL
    best_url = pick_best_url(results)

    # Identify source name for display
    source = "web"
    for preferred in PREFERRED_SOURCES:
        if best_url and preferred in best_url:
            source = preferred.replace(".org", "").replace(".com", "")
            break

    # Step 3: Scrape
    raw_text = ""
    if best_url:
        raw_text = scrape_page(best_url)
        # Small delay to be polite to servers
        time.sleep(0.5)

    # Step 4: Clean
    if raw_text and len(raw_text.strip()) > 100:
        content = clean_scraped_text(raw_text)
    else:
        # Fallback to snippets if scraping failed
        print(f"   Scraping failed or too little content, using snippets")
        content = get_snippets_as_fallback(results, topic)
        source  = "search snippets"
        best_url = ""

    print(f"   Got {len(content)} chars from {source}")

    return {
        "topic"  : topic,
        "content": content,
        "source" : source,
        "url"    : best_url or "",
        "success": len(content) > 50
    }


# ─────────────────────────────────────────────────────────────────────────────
# BATCH FUNCTION: Get explanations for multiple topics
# Called by Agent 2 for all topics found in the PDF
# ─────────────────────────────────────────────────────────────────────────────
def get_web_explanations_for_topics(topics: list) -> dict:
    """
    Get web explanations for a list of topics
    Returns dict: {topic_name: explanation_dict}

    Adds delay between requests to avoid rate limiting
    """
    print(f"\n Getting web explanations for {len(topics)} topics...")
    results = {}

    for i, topic in enumerate(topics):
        print(f"\n  [{i+1}/{len(topics)}] Topic: {topic}")
        explanation = get_web_explanation(topic)
        results[topic] = explanation

        # Delay between topics to avoid hitting rate limits
        if i < len(topics) - 1:
            time.sleep(1)

    successful = sum(1 for r in results.values() if r["success"])
    print(f"\n Web search complete: {successful}/{len(topics)} topics found")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# FORMAT: Convert results to readable text for Agent 2 output
# ─────────────────────────────────────────────────────────────────────────────
def format_web_results(results: dict) -> str:
    """
    Format web search results into clean readable text
    This becomes Agent 2's output stored in SQLite
    """
    if not results:
        return "No web results available."

    formatted = []
    for topic, data in results.items():
        section  = f"## {topic}\n"
        section += f"**Source:** {data.get('source', 'web')}\n\n"
        section += data.get("content", "No content available")
        section += "\n\n" + "─" * 50
        formatted.append(section)

    return "\n\n".join(formatted)


# ─────────────────────────────────────────────────────────────────────────────
# QUICK TEST — run this file directly
# python web_search.py
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(" Testing web_search.py...")

    # Test single topic
    result = get_web_explanation("Binary Search algorithm")

    print(f"\n📊 Result:")
    print(f"  Topic:   {result['topic']}")
    print(f"  Source:  {result['source']}")
    print(f"  URL:     {result['url'][:60]}...")
    print(f"  Success: {result['success']}")
    print(f"  Content preview:\n{result['content'][:400]}...")

    # Test batch
    print("\n" + "="*50)
    print("Testing batch search...")
    topics  = ["Recursion", "Stack data structure"]
    results = get_web_explanations_for_topics(topics)

    for topic, data in results.items():
        print(f"\n {topic}: {len(data['content'])} chars from {data['source']}")

    # Test formatting
    formatted = format_web_results(results)
    print(f"\n Formatted output preview:\n{formatted[:300]}...")

    print("\n web_search.py tests complete!")
