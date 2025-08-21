import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo  # built-in in Python 3.11+
import yagmail

def london_week_label(dt_utc: datetime) -> str:
    """Return 'Week of DD Mon YYYY' using Europe/London time."""
    london = ZoneInfo("Europe/London")
    dt_ldn = dt_utc.astimezone(london)
    # Normalize to Monday of this week for a stable label
    monday = dt_ldn - timedelta(days=dt_ldn.weekday())
    return monday.strftime("Week of %d %b %Y")

def build_html_email(week_label: str) -> str:
    # --- Dummy sample opportunities (replace later with real scraped data) ---
    items = [
        {
            "emoji": "🧠",
            "title": "Research Assistant – fMRI & Drug Studies",
            "org": "King’s College London",
            "deadline": "12 Sept 2025",
            "location": "London, UK",
            "keywords": ["fMRI", "drug", "neuroimaging"],
            "link": "https://example.com/kcl-ra"
        },
        {
            "emoji": "🎓",
            "title": "PhD in Ultra-High Field MRI",
            "org": "UCL Institute of Child Health",
            "deadline": "20 Sept 2025",
            "location": "London, UK",
            "keywords": ["MRI", "ultra high field", "brain"],
            "link": "https://example.com/ucl-phd"
        },
        {
            "emoji": "💼",
            "title": "Neuroscience Data Scientist – Psychedelic Imaging",
            "org": "London Biotech",
            "deadline": "28 Sept 2025",
            "location": "London, UK",
            "keywords": ["psychedelic", "neuro", "brain"],
            "link": "https://example.com/industry-role"
        },
    ]

    total = len(items)
    london_count = sum("London" in it["location"] for it in items)
    matched_keywords = sorted({kw for it in items for kw in it["keywords"]})

    # Build HTML
    parts = []
    parts.append(f"""
<h2>🎓 Weekly Opportunities</h2>
<p>Hi Benja,</p>
<p>Here are this week’s new <b>PhD, RA, and industry</b> roles in neuroimaging/brain research (UK focus, prioritising London):</p>
""")

    for it in items:
        parts.append(f"""
<hr>
<h3>{it["emoji"]} {it["title"]} – {it["org"]}</h3>
<p><strong>Deadline:</strong> {it["deadline"]}<br>
<strong>Location:</strong> {it["location"]}<br>
<strong>Keywords matched:</strong> {", ".join(it["keywords"])}<br>
<a href="{it["link"]}">View listing</a></p>
""")

    parts.append(f"""
<hr>
<p><b>Summary:</b><br>
- {total} opportunities this week<br>
- {london_count} in London<br>
- Keywords matched: {", ".join(matched_keywords)}</p>

<p>Best,<br>
Your Weekly Opportunity Finder</p>
""")

    html = "\n".join(parts)
    subject = f"🎓 Weekly Opportunities in Neuroimaging & Brain Research – {week_label}"
    return subject, html

def main():
    # Read email creds from environment (set as GitHub Secrets)
    email_user = os.environ.get("EMAIL_USERNAME")
    email_pass = os.environ.get("EMAIL_PASSWORD")
    if not email_user or not email_pass:
        raise RuntimeError("Missing EMAIL_USERNAME or EMAIL_PASSWORD environment variables.")

    # Recipient: send to yourself for now
    recipient = email_user

    # Build content
    week_label = london_week_label(datetime.utcnow())
    subject, html_body = build_html_email(week_label)

    # Send
    yag = yagmail.SMTP(user=email_user, password=email_pass)
    yag.send(to=recipient, subject=subject, contents=html_body)

    # Minimal, non-sensitive log line
    print("HTML preview email sent successfully.")

if __name__ == "__main__":
    main()
