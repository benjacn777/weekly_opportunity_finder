import os
import re
import json
import time
import html
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
import yagmail
import yaml

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/119.0 Safari/537.36"
)
TIMEOUT = 15

# ------------------------- config -------------------------

@dataclass
class Config:
    to: str | None
    from_name: str
    roles: list[str]
    keywords: list[str]
    uk_only: bool
    prefer_london: bool
    per_site: int
    total: int
    sources: list[str]
    generic_sites: list[str]

def load_config(path: str = "config.yaml") -> Config:
    if not os.path.exists(path):
        raise RuntimeError("config.yaml not found. Please add it at repo root.")

    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    email_to = (cfg.get("email", {}) or {}).get("to") or None
    from_name = (cfg.get("email", {}) or {}).get("from_name") or "Weekly Opportunity Finder"

    roles = cfg.get("roles", [])
    keywords = [k.strip().lower() for k in cfg.get("keywords", []) if k.strip()]
    loc = cfg.get("location", {}) or {}
    uk_only = bool(loc.get("include_uk_only", True))
    prefer_london = bool(loc.get("prefer_london", True))

    limits = cfg.get("limits", {}) or {}
    per_site = int(limits.get("per_site", 8))
    total = int(limits.get("total", 25))

    sources = cfg.get("sources", ["findaphd", "jobs_ac_uk", "psychedelic_alpha", "nature_careers", "euraxess", "generic_sites"])
    generic_sites = cfg.get("generic_sites", []) or []

    return Config(
        to=email_to,
        from_name=from_name,
        roles=roles,
        keywords=keywords,
        uk_only=uk_only,
        prefer_london=prefer_london,
        per_site=per_site,
        total=total,
        sources=sources,
        generic_sites=generic_sites,
    )

# ------------------------- utils -------------------------

def http_get(url: str) -> str | None:
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        return r.text
    except requests.RequestException:
        return None

def text_matches_keywords(text: str, keywords: list[str]) -> list[str]:
    t = text.lower()
    return [k for k in keywords if k in t]

def looks_uk(location_text: str) -> bool:
    t = (location_text or "").lower()
    return any(x in t for x in [
        "uk","united kingdom","england","scotland","wales","northern ireland",
        "london","oxford","cambridge","manchester","edinburgh","glasgow","bristol",
        "leeds","birmingham","sheffield"])

def london_bias_score(location_text: str) -> int:
    return 1 if ("london" in (location_text or "").lower()) else 0

def dedupe(items, key=lambda x: x["link"]):
    seen = set()
    out = []
    for it in items:
        k = key(it)
        if k and k not in seen:
            seen.add(k)
            out.append(it)
    return out

def week_label_london(now_utc: datetime) -> str:
    dt_ldn = now_utc.astimezone(ZoneInfo("Europe/London"))
    monday = dt_ldn - timedelta(days=dt_ldn.weekday())
    return monday.strftime("Week of %d %b %Y")

# ------------------------- models -------------------------

from typing import List
@dataclass
class Item:
    source: str
    title: str
    org: str
    location: str
    deadline: str
    link: str
    matched_keywords: List[str]

# ------------------------- scrapers (existing) -------------------------

def scrape_findaphd(cfg: Config) -> list[Item]:
    results: list[Item] = []
    base = "https://www.findaphd.com"
    for kw in cfg.keywords:
        q = urllib.parse.quote_plus(kw)
        url = f"{base}/phds/united-kingdom/?Keywords={q}"
        html_text = http_get(url)
        if not html_text: continue
        soup = BeautifulSoup(html_text, "html.parser")
        cards = soup.select("article, .result, .search-result, .project-result, li") or soup.find_all("a")
        for node in cards:
            a = node.find("a") if hasattr(node, "find") else (node if getattr(node, "name", "")=="a" else None)
            if not a: continue
            href = a.get("href") or ""
            if not href or "phds" not in href.lower(): continue
            link = href if href.startswith("http") else (base + href)
            title = a.get_text(" ", strip=True) or ""
            if len(title) < 6: continue
            context_text = node.get_text(" ", strip=True) if hasattr(node,"get_text") else title
            matched = text_matches_keywords(context_text + " " + title, cfg.keywords)
            if not matched: continue
            m = re.search(r"(London|Oxford|Cambridge|Bristol|Manchester|Edinburgh|Glasgow|Birmingham|Leeds|UK|United Kingdom)", context_text, flags=re.I)
            loc = m.group(0) if m else "United Kingdom"
            if cfg.uk_only and not looks_uk(loc): continue
            m2 = re.search(r"(University|King’s College|King's College|Imperial|UCL|KCL|Oxford|Cambridge)[^|,–-]*", context_text, flags=re.I)
            org = (m2.group(0).strip() if m2 else "FindAPhD listing")
            results.append(Item("FindAPhD", title, org, loc, "(see listing)", link, matched))
            if len(results) >= cfg.per_site: break
        time.sleep(0.6)
    return results

def scrape_jobs_ac_uk(cfg: Config) -> list[Item]:
    results: list[Item] = []
    base = "https://www.jobs.ac.uk"
    for kw in cfg.keywords:
        q = urllib.parse.quote_plus(kw)
        url = f"{base}/search/?keywords={q}&location=United%20Kingdom"
        html_text = http_get(url)
        if not html_text: continue
        soup = BeautifulSoup(html_text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/job/" not in href: continue
            link = href if href.startswith("http") else (base + href)
            title = a.get_text(" ", strip=True)
            if not title or len(title) < 6: continue
            parent = a.find_parent(["article","li","div"]) or a
            context = parent.get_text(" ", strip=True)
            matched = text_matches_keywords((title + " " + context), cfg.keywords)
            if not matched: continue
            m = re.search(r"(London|Oxford|Cambridge|Manchester|Edinburgh|Glasgow|Birmingham|Leeds|Bristol|UK|United Kingdom)", context, flags=re.I)
            loc = m.group(0) if m else "United Kingdom"
            if cfg.uk_only and not looks_uk(loc): continue
            m2 = re.search(r"(University|NHS|King’s College|King's College|Imperial|UCL|KCL|Oxford|Cambridge|Institute|Trust)[^|,–-]*", context, flags=re.I)
            org = (m2.group(0).strip() if m2 else "jobs.ac.uk listing")
            results.append(Item("jobs.ac.uk", title, org, loc, "(see listing)", link, matched))
            if len(results) >= cfg.per_site: break
        time.sleep(0.6)
    return results

def scrape_psychedelic_alpha(cfg: Config) -> list[Item]:
    results: list[Item] = []
    base = "https://jobs.psychedelicalpha.com"
    for kw in cfg.keywords:
        q = urllib.parse.quote_plus(kw)
        url = f"{base}/jobs?search={q}"
        html_text = http_get(url)
        if not html_text: continue
        soup = BeautifulSoup(html_text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not href.startswith("/jobs"): continue
            link = href if href.startswith("http") else (base + href)
            title = a.get_text(" ", strip=True)
            if not title or len(title) < 5: continue
            parent = a.find_parent(["article","li","div"]) or a
            context = parent.get_text(" ", strip=True)
            matched = text_matches_keywords((title + " " + context), cfg.keywords)
            if not matched: continue
            m = re.search(r"(London|UK|United Kingdom|Remote)", context, flags=re.I)
            loc = m.group(0) if m else ("United Kingdom" if "uk" in context.lower() else "Remote/Unknown")
            if cfg.uk_only and not looks_uk(loc): continue
            m2 = re.search(r"(University|Institute|Ltd|Limited|PLC|Biotech|Research|Clinic|Centre|Center)[^|,–-]*", context, flags=re.I)
            org = (m2.group(0).strip() if m2 else "Psychedelic Alpha")
            results.append(Item("Psychedelic Alpha", title, org, loc, "(see listing)", link, matched))
            if len(results) >= cfg.per_site: break
        time.sleep(0.6)
    return results

# ------------------------- NEW scrapers -------------------------

def scrape_nature_careers(cfg: Config) -> list[Item]:
    """
    Nature Careers (jobs.nature.com) – keyword search scoped to UK.
    """
    results: list[Item] = []
    base = "https://jobs.nature.com"
    for kw in cfg.keywords:
        q = urllib.parse.quote_plus(kw)
        url = f"{base}/jobs/united-kingdom/?keywords={q}"
        html_text = http_get(url)
        if not html_text: continue
        soup = BeautifulSoup(html_text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not (href.startswith("/job/") or "/job/" in href): continue
            link = href if href.startswith("http") else (base + href)
            title = a.get_text(" ", strip=True)
            if not title or len(title) < 5: continue
            parent = a.find_parent(["article","li","div"]) or a
            context = parent.get_text(" ", strip=True)
            matched = text_matches_keywords(title + " " + context, cfg.keywords)
            if not matched: continue
            # infer org/location
            mloc = re.search(r"(London|Oxford|Cambridge|Manchester|Edinburgh|Glasgow|Bristol|Leeds|UK|United Kingdom)", context, flags=re.I)
            loc = mloc.group(0) if mloc else "United Kingdom"
            if cfg.uk_only and not looks_uk(loc): continue
            morg = re.search(r"(University|Institute|King’s College|King's College|Imperial|UCL|KCL|Oxford|Cambridge|NHS|Trust|Ltd|Limited|Biotech)[^|,–-]*", context, flags=re.I)
            org = (morg.group(0).strip() if morg else "Nature Careers")
            results.append(Item("Nature Careers", title, org, loc, "(see listing)", link, matched))
            if len(results) >= cfg.per_site: break
        time.sleep(0.6)
    return results

def scrape_euraxess(cfg: Config) -> list[Item]:
    """
    EURAXESS UK – keyword search scoped to UK.
    """
    results: list[Item] = []
    base = "https://euraxess.ec.europa.eu"
    for kw in cfg.keywords:
        q = urllib.parse.quote_plus(kw)
        url = f"{base}/jobs/search?keywords={q}&f%5B0%5D=country%3AUnited%20Kingdom"
        html_text = http_get(url)
        if not html_text: continue
        soup = BeautifulSoup(html_text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/jobs/" not in href: continue
            link = href if href.startswith("http") else (base + href)
            title = a.get_text(" ", strip=True)
            if not title or len(title) < 6: continue
            parent = a.find_parent(["article","li","div"]) or a
            context = parent.get_text(" ", strip=True)
            matched = text_matches_keywords(title + " " + context, cfg.keywords)
            if not matched: continue
            mloc = re.search(r"(London|Oxford|Cambridge|Manchester|Edinburgh|Glasgow|Bristol|Leeds|UK|United Kingdom)", context, flags=re.I)
            loc = mloc.group(0) if mloc else "United Kingdom"
            if cfg.uk_only and not looks_uk(loc): continue
            morg = re.search(r"(University|Institute|King’s College|King's College|Imperial|UCL|KCL|Oxford|Cambridge|NHS|Trust|Ltd|Limited|Biotech)[^|,–-]*", context, flags=re.I)
            org = (morg.group(0).strip() if morg else "EURAXESS")
            results.append(Item("EURAXESS", title, org, loc, "(see listing)", link, matched))
            if len(results) >= cfg.per_site: break
        time.sleep(0.6)
    return results

# ------------------------- Generic anchor harvester -------------------------

def scrape_generic_sites(cfg: Config) -> list[Item]:
    """
    Very general-purpose: fetch each URL from config.generic_sites, collect anchors that look like jobs,
    and filter by keywords + UK.
    """
    results: list[Item] = []
    for site in cfg.generic_sites:
        html_text = http_get(site)
        if not html_text: continue
        soup = BeautifulSoup(html_text, "html.parser")
        base = "{uri.scheme}://{uri.netloc}".format(uri=urllib.parse.urlparse(site))

        anchors = soup.find_all("a", href=True)
        count = 0
        for a in anchors:
            href = a["href"].strip()
            text = a.get_text(" ", strip=True)
            if len(text) < 5: continue
            # heuristics: look for typical job-ish paths/words
            if not any(s in href.lower() for s in ["/job", "vacanc", "opportunit", "careers", "/positions", "/recruit", "/jobs"]):
                continue

            link = href if href.startswith("http") else urllib.parse.urljoin(base, href)
            parent = a.find_parent(["article","li","div","tr"]) or a
            context = parent.get_text(" ", strip=True)
            matched = text_matches_keywords((text + " " + context), cfg.keywords)
            if not matched: continue

            # org/location inference
            org_guess = urllib.parse.urlparse(site).netloc
            mloc = re.search(r"(London|Oxford|Cambridge|Manchester|Edinburgh|Glasgow|Bristol|Leeds|UK|United Kingdom|Remote)", context, flags=re.I)
            loc = mloc.group(0) if mloc else ("United Kingdom" if "uk" in context.lower() or ".ac.uk" in org_guess else "Unknown/Remote")
            if cfg.uk_only and not looks_uk(loc): continue

            results.append(Item("Generic", text, org_guess, loc, "(see listing)", link, matched))
            count += 1
            if count >= cfg.per_site:
                break
        time.sleep(0.6)
    return results

# ------------------------- aggregator -------------------------

def gather_results(cfg: Config) -> list[Item]:
    items: list[Item] = []

    if "findaphd" in cfg.sources:
        items.extend(scrape_findaphd(cfg))
    if "jobs_ac_uk" in cfg.sources:
        items.extend(scrape_jobs_ac_uk(cfg))
    if "psychedelic_alpha" in cfg.sources:
        items.extend(scrape_psychedelic_alpha(cfg))
    if "nature_careers" in cfg.sources:
        items.extend(scrape_nature_careers(cfg))
    if "euraxess" in cfg.sources:
        items.extend(scrape_euraxess(cfg))
    if "generic_sites" in cfg.sources and cfg.generic_sites:
        items.extend(scrape_generic_sites(cfg))

    items = dedupe(items, key=lambda it: it.link)
    items.sort(key=lambda it: (-london_bias_score(it.location), -len(it.matched_keywords), it.source))
    if cfg.total and len(items) > cfg.total:
        items = items[: cfg.total]
    return items

# ------------------------- email rendering -------------------------

def build_quick_links(cfg: Config):
    kws = "+".join(urllib.parse.quote_plus(k) for k in cfg.keywords[:4])
    links = []
    links.append(("FindAPhD (UK) – keywords", f"https://www.findaphd.com/phds/united-kingdom/?Keywords={kws}"))
    links.append(("jobs.ac.uk (UK) – keywords", f"https://www.jobs.ac.uk/search/?keywords={kws}&location=United%20Kingdom"))
    links.append(("Nature Careers (UK) – keywords", f"https://jobs.nature.com/jobs/united-kingdom/?keywords={kws}"))
    links.append(("EURAXESS (UK) – keywords", f"https://euraxess.ec.europa.eu/jobs/search?keywords={kws}&f%5B0%5D=country%3AUnited%20Kingdom"))
    links.append(("Psychedelic Alpha – keywords", f"https://jobs.psychedelicalpha.com/jobs?search={kws}"))
    links.append(("LinkedIn Jobs (UK) – keywords", f"https://www.linkedin.com/jobs/search/?keywords={kws}&location=United%20Kingdom"))
    links.append(("Indeed (UK) – keywords", f"https://uk.indeed.com/jobs?q={kws}&l=United+Kingdom"))
    return links

def build_html_email(items: list[Item], week_label: str, cfg: Config) -> tuple[str, str]:
    quick_links = build_quick_links(cfg)
    parts = []
    parts.append(f"""
<h2>🎓 Weekly Opportunities</h2>
<p>Hi Benja,</p>
<p>Here are this week’s new <b>PhD, RA, and industry</b> roles in neuro/brain imaging (UK focus{", prioritising London" if cfg.prefer_london else ""}):</p>
""")
    total = 0
    for it in items:
        total += 1
        parts.append(f"""
<hr>
<h3>🔎 {html.escape(it.title)} – {html.escape(it.org)}</h3>
<p><strong>Source:</strong> {html.escape(it.source)}<br>
<strong>Location:</strong> {html.escape(it.location)}<br>
<strong>Deadline:</strong> {html.escape(it.deadline)}<br>
<strong>Keywords matched:</strong> {", ".join(html.escape(k) for k in sorted(set(it.matched_keywords)))}<br>
<a href="{html.escape(it.link)}">View listing</a></p>
""")
    if total == 0:
        parts.append("<p><i>No matching listings found this week via automated scraping.</i></p>")
    london_hits = sum(1 for it in items if "london" in (it.location or "").lower())
    parts.append(f"""
<hr>
<p><b>Summary</b><br>
- {total} opportunities this week<br>
- {london_hits} in London</p>
""")
    parts.append("<hr><h3>🧭 One-click searches</h3><ul>")
    for label, url in quick_links:
        parts.append(f'<li><a href="{html.escape(url)}">{html.escape(label)}</a></li>')
    parts.append("</ul><p>Best,<br>Your Weekly Opportunity Finder</p>")
    subject = f"🎓 Weekly Opportunities in Neuro/Brain Imaging – {week_label}"
    return subject, "\n".join(parts)

# ------------------------- send -------------------------

def send_email(subject: str, html_body: str, cfg: Config):
    email_user = os.environ.get("EMAIL_USERNAME")
    email_pass = os.environ.get("EMAIL_PASSWORD")
    if not email_user or not email_pass:
        raise RuntimeError("Missing EMAIL_USERNAME or EMAIL_PASSWORD environment variables.")
    to = cfg.to or email_user
    yag = yagmail.SMTP(user=email_user, password=email_pass)
    yag.send(to=to, subject=subject, contents=html_body)

# ------------------------- main -------------------------

def main():
    cfg = load_config()
    now_utc = datetime.now(timezone.utc)
    wl = week_label_london(now_utc)
    items = gather_results(cfg)
    subject, html_body = build_html_email(items, wl, cfg)
    send_email(subject, html_body, cfg)
    print(f"Sent weekly email with {len(items)} items across {len(set(i.source for i in items))} sources.")

if __name__ == "__main__":
    main()
