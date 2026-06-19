#!/usr/bin/env python3
"""
Génère docs/index.html avec météo, news et cinémas pour Annecy.
Lancé par GitHub Actions toutes les 30 min, pousse sur GitHub Pages.
"""

import json
import urllib.request
import urllib.error
import os
import re
from datetime import datetime, timezone, timedelta

# ── Timezone ──────────────────────────────────────────────────────────────────
PARIS_TZ = timezone(timedelta(hours=2))  # CEST (heure d'été)
now = datetime.now(PARIS_TZ)

# Coordonnées d'Annecy
LAT = 45.8992
LON = 6.1294

# ── Helpers ───────────────────────────────────────────────────────────────────
def fetch_json(url, headers=None):
    h = {"User-Agent": "Annecy-Dashboard/1.0", "Accept": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.loads(r.read().decode())

def fetch_html(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Accept-Encoding": "identity",
    })
    with urllib.request.urlopen(req, timeout=12) as r:
        return r.read().decode("utf-8", errors="replace")

def wmo_icon(code):
    if code == 0:   return "☀️"
    if code <= 2:   return "🌤️"
    if code == 3:   return "☁️"
    if code <= 48:  return "🌫️"
    if code <= 67:  return "🌧️"
    if code <= 77:  return "❄️"
    if code <= 82:  return "🌦️"
    return "⛈️"

def wmo_desc(code):
    m = {
        0: "Ciel dégagé", 1: "Peu nuageux", 2: "Partiellement nuageux",
        3: "Couvert", 45: "Brouillard", 48: "Brouillard givrant",
        51: "Bruine légère", 53: "Bruine modérée", 55: "Bruine dense",
        61: "Pluie légère", 63: "Pluie modérée", 65: "Forte pluie",
        71: "Neige légère", 73: "Neige modérée", 75: "Forte neige",
        80: "Averses légères", 81: "Averses", 82: "Averses violentes",
        95: "Orage", 99: "Orage violent",
    }
    return m.get(code, "Conditions inconnues")

# ── Météo air (Open-Meteo, gratuit, sans clé) ─────────────────────────────────
def get_meteo():
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={LAT}&longitude={LON}"
            f"&current=temperature_2m,weathercode,apparent_temperature"
            f"&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"
            f"&timezone=Europe%2FParis&forecast_days=1"
        )
        d = fetch_json(url)
        cur = d["current"]
        day = d["daily"]
        code = cur["weathercode"]
        return {
            "ok": True,
            "temp": round(cur["temperature_2m"]),
            "feels": round(cur["apparent_temperature"]),
            "tmax": round(day["temperature_2m_max"][0]),
            "tmin": round(day["temperature_2m_min"][0]),
            "rain_pct": day["precipitation_probability_max"][0] or 0,
            "icon": wmo_icon(code),
            "desc": wmo_desc(code),
        }
    except Exception as e:
        print(f"  Erreur météo: {e}")
        return {"ok": False}

# ── Température du lac d'Annecy (données publiques Haute-Savoie) ──────────────
def get_lac_temp():
    """
    Source: API Open-Meteo Marine (lac intérieur approx) ou station Météo-France.
    On utilise l'API Open-Meteo lake_surface_temperature si disponible,
    sinon on scrape la page de mesure de lac.
    """
    try:
        # Open-Meteo n'a pas de données lac direct — on scrape meteolac.fr
        url = "https://www.meteolac.com/lac-d-annecy"
        raw = fetch_html(url)
        # Chercher la température de surface
        m = re.search(r'(\d{1,2}[,\.]\d)\s*°C', raw)
        if m:
            temp_str = m.group(1).replace(",", ".")
            return {"ok": True, "temp": float(temp_str)}
    except Exception as e:
        print(f"  Lac (meteolac): {e}")

    # Fallback: données hydro Eau France (station lac Annecy)
    try:
        url = (
            "https://hubeau.eaufrance.fr/api/v1/temperature/chronique"
            "?code_station=V2224010&fields=resultat_obs,date_debut_obs"
            "&size=1&sort=desc"
        )
        d = fetch_json(url)
        obs = d.get("data", [])
        if obs:
            temp = obs[0].get("resultat_obs")
            if temp is not None:
                return {"ok": True, "temp": round(float(temp), 1)}
    except Exception as e:
        print(f"  Lac (hubeau): {e}")

    return {"ok": False}

# ── News Annecy (flux RSS Le Dauphiné Libéré) ─────────────────────────────────
def get_news():
    try:
        import feedparser
        # RSS Le Dauphiné Libéré - édition Annecy
        feeds = [
            "https://www.ledauphine.com/haute-savoie/annecy/rss",
            "https://www.ledauphine.com/haute-savoie/rss",
        ]
        articles = []
        seen_titles = set()
        for feed_url in feeds:
            try:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries[:8]:
                    title = entry.get("title", "").strip()
                    link = entry.get("link", "").strip()
                    summary = entry.get("summary", "").strip()
                    # Nettoyer le résumé HTML
                    summary = re.sub(r'<[^>]+>', '', summary)
                    summary = summary[:140].strip()
                    if summary and not summary.endswith('.'):
                        summary = summary.rsplit(' ', 1)[0] + '…'
                    if title and title not in seen_titles and link:
                        seen_titles.add(title)
                        articles.append({
                            "title": title,
                            "link": link,
                            "summary": summary,
                        })
            except Exception as e:
                print(f"  RSS {feed_url}: {e}")

        if articles:
            print(f"  News: {len(articles)} articles")
            return {"ok": True, "articles": articles[:10]}
        return {"ok": False, "articles": []}
    except Exception as e:
        print(f"  Erreur news: {e}")
        return {"ok": False, "articles": []}

# ── Cinémas Annecy (Allocine scraping) ───────────────────────────────────────
def get_cinemas():
    """
    Scrape Allocine pour les séances du jour à Annecy.
    URL: https://www.allocine.fr/seance/ville-15106/
    """
    try:
        date_str = now.strftime("%Y-%m-%d")
        url = f"https://www.allocine.fr/seance/ville-15106/jour-{date_str}/"
        raw = fetch_html(url)
        print(f"  Cinémas: page reçue ({len(raw)} chars)")

        cinemas = []
        seen_cinemas = set()

        # Trouver chaque bloc cinéma
        # Structure Allocine: <div class="theater-title"><a ...>Nom cinéma</a></div>
        # puis les films dans <div class="movie-title"><a ...>Titre</a></div>

        # Séparer par bloc cinéma
        cinema_blocks = re.split(r'<section[^>]*class="[^"]*theater[^"]*"', raw)

        for block in cinema_blocks[1:]:  # skip avant le premier cinéma
            # Nom du cinéma
            cinema_match = re.search(r'<h2[^>]*class="[^"]*theater-name[^"]*"[^>]*>.*?<a[^>]*>([^<]+)</a>', block, re.DOTALL)
            if not cinema_match:
                cinema_match = re.search(r'class="[^"]*theater-name[^"]*"[^>]*>([^<]{3,60})', block)
            if not cinema_match:
                continue

            cinema_name = cinema_match.group(1).strip()
            if cinema_name in seen_cinemas:
                continue
            seen_cinemas.add(cinema_name)

            # Films dans ce cinéma
            films = []
            seen_films = set()
            film_matches = re.findall(r'class="[^"]*movie-title[^"]*"[^>]*>.*?<a[^>]*>([^<]{2,80})</a>', block, re.DOTALL)
            for title in film_matches:
                title = title.strip()
                if title and title not in seen_films and len(title) > 2:
                    seen_films.add(title)
                    films.append(title)

            if films:
                cinemas.append({"cinema": cinema_name, "films": films})

        # Fallback: chercher directement les titres de films si structure différente
        if not cinemas:
            print("  Cinémas: structure non reconnue, tentative fallback offi.fr")
            return get_cinemas_offi()

        print(f"  Cinémas: {len(cinemas)} cinéma(s) trouvé(s)")
        for c in cinemas:
            print(f"    {c['cinema']}: {c['films']}")
        return {"ok": True, "cinemas": cinemas}

    except Exception as e:
        print(f"  Erreur cinémas Allocine: {e}")
        return get_cinemas_offi()

def get_cinemas_offi():
    """Fallback: scrape offi.fr pour les cinémas d'Annecy."""
    try:
        # Page cinémas Annecy sur offi.fr
        date_str = now.strftime("%Y-%m-%d")
        cinemas_offi = [
            {"name": "Pathé Annecy",         "id": "cinema-pathe-annecy-3"},
            {"name": "Le Splendid",            "id": "cinema-le-splendid-annecy"},
            {"name": "Cinéma La Turbine",      "id": "cinema-la-turbine"},
        ]

        cinemas = []
        for c in cinemas_offi:
            try:
                url = f"https://www.offi.fr/cinema/{c['id']}.html?date={date_str}"
                raw = fetch_html(url)
                films = []
                seen = set()
                # Extraire titres de films
                blocs = re.split(r'</?h[23][^>]*>', raw)
                mots_ignorer = ["programme", "réservation", "accueil", "cinéma",
                                "cookies", "connexion", "prochainement", "newsletter"]
                for bloc in blocs:
                    m = re.search(r'<a[^>]*>([^<]{2,70})</a>', bloc)
                    if not m:
                        continue
                    titre = m.group(1).strip()
                    if any(mot in titre.lower() for mot in mots_ignorer):
                        continue
                    if len(titre) < 3 or len(titre) > 70:
                        continue
                    if titre not in seen:
                        seen.add(titre)
                        films.append(titre)
                if films:
                    cinemas.append({"cinema": c["name"], "films": films[:8]})
            except Exception as e:
                print(f"    offi.fr {c['name']}: {e}")

        if cinemas:
            return {"ok": True, "cinemas": cinemas}

        # Dernier fallback: page générale Annecy
        raw = fetch_html(f"https://www.allocine.fr/seance/ville-15106/")
        films = []
        seen = set()
        for m in re.finditer(r'data-title="([^"]{2,80})"', raw):
            t = m.group(1).strip()
            if t not in seen:
                seen.add(t)
                films.append(t)
        if films:
            return {"ok": True, "cinemas": [{"cinema": "Annecy", "films": films[:10]}]}

        return {"ok": False, "cinemas": []}
    except Exception as e:
        print(f"  Erreur cinémas offi: {e}")
        return {"ok": False, "cinemas": []}

# ── Génération HTML ────────────────────────────────────────────────────────────
def meteo_html(meteo, lac):
    if not meteo.get("ok"):
        return '<div class="error">Météo indisponible</div>'

    lac_html = ""
    if lac.get("ok"):
        lac_html = f'''
        <div class="lac-block">
          <span class="lac-icon">🏊</span>
          <span class="lac-label">Lac d'Annecy</span>
          <span class="lac-temp">{lac["temp"]}°C</span>
        </div>'''
    else:
        lac_html = '<div class="lac-block lac-na"><span class="lac-icon">🏊</span><span class="lac-label">Température du lac</span><span class="lac-temp">N/D</span></div>'

    return f"""
    <div class="meteo-main">
      <div class="meteo-icon">{meteo['icon']}</div>
      <div class="meteo-temp-block">
        <div class="meteo-temp">{meteo['temp']}<sup>°C</sup></div>
        <div class="meteo-desc">{meteo['desc']}</div>
        <div class="meteo-feels">Ressenti {meteo['feels']}°</div>
      </div>
      <div class="meteo-minmax">
        <div class="temp-max">▲ {meteo['tmax']}°</div>
        <div class="temp-min">▼ {meteo['tmin']}°</div>
        <div class="meteo-rain">🌧 {meteo['rain_pct']}%</div>
      </div>
    </div>
    {lac_html}"""

def news_html(news):
    if not news.get("ok") or not news.get("articles"):
        return '<div class="error">Actualités indisponibles</div>'
    rows = []
    for a in news["articles"]:
        title = a["title"].replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
        link = a["link"]
        summary = a.get("summary", "")
        rows.append(f"""
        <a class="news-item" href="{link}" target="_blank" rel="noopener">
          <div class="news-title">{title}</div>
          {"<div class='news-summary'>" + summary + "</div>" if summary else ""}
        </a>""")
    return '<div class="news-list">' + "".join(rows) + '</div>'

def cinemas_html(data):
    if not data.get("ok") or not data.get("cinemas"):
        return '<div class="error">Programmes cinéma indisponibles</div>'
    html = ""
    for c in data["cinemas"]:
        html += f'<div class="cinema-name">🎭 {c["cinema"]}</div>'
        for film in c["films"]:
            html += f'<div class="cinema-film">🎬 {film}</div>'
    return '<div class="cinema-list">' + html + '</div>'

def build_html(meteo, lac, news, cinemas):
    MOIS_FR = ["janvier","février","mars","avril","mai","juin",
               "juillet","août","septembre","octobre","novembre","décembre"]
    JOURS_FR = ["Lundi","Mardi","Mercredi","Jeudi","Vendredi","Samedi","Dimanche"]

    jour = JOURS_FR[now.weekday()]
    date_str = f"{now.day}\u202f{MOIS_FR[now.month-1]}\u202f{now.strftime('%Y')}"
    heure_str = f"{now.strftime('%H')}h{now.strftime('%M')}"

    # Prochaine mise à jour (slots 00 et 30)
    m = now.minute
    next_slot = 30 if m < 30 else 60
    next_min = next_slot - m

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
  <meta http-equiv="refresh" content="1800">
  <title>Annecy · Dashboard</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Mono:wght@300;400;500&family=Syne:wght@400;500;600;700&display=swap');

    :root {{
      --bg:#0d0d0f; --surface:#141416; --surface2:#1a1a1d;
      --border:rgba(255,255,255,0.07); --border2:rgba(255,255,255,0.12);
      --text:#f0ede6; --muted:#6b6860;
      --accent:#e8d5a3; --accent2:#7ec8c8;
      --green:#4eba8a; --red:#e05c5c; --orange:#e8923a; --blue:#5b9bd5;
    }}

    * {{ box-sizing:border-box; margin:0; padding:0 }}
    html {{ -webkit-text-size-adjust:100% }}
    body {{
      font-family:'Syne',sans-serif;
      background:var(--bg); color:var(--text);
      min-height:100vh;
      padding: env(safe-area-inset-top,16px) 14px env(safe-area-inset-bottom,16px);
    }}

    /* ── Header ── */
    .header {{
      display:flex; align-items:center; justify-content:space-between;
      margin-bottom:18px; padding-bottom:12px;
      border-bottom:1px solid var(--border);
    }}
    .header-title {{ font-family:'DM Mono',monospace; font-size:20px; letter-spacing:.05em }}
    .header-sub {{ font-family:'DM Mono',monospace; font-size:10px; color:var(--muted); margin-top:3px; letter-spacing:.04em }}
    .header-time {{ font-family:'DM Mono',monospace; font-size:20px; text-align:right }}
    .header-date {{ font-family:'DM Mono',monospace; font-size:10px; color:var(--muted); margin-top:3px; text-align:right }}

    /* ── Grid ── */
    .grid {{
      display:grid;
      grid-template-columns:1fr 1fr;
      gap:10px; max-width:900px;
    }}
    @media(max-width:500px) {{ .grid {{ grid-template-columns:1fr }} }}

    .card {{
      background:var(--surface); border:1px solid var(--border);
      border-radius:12px; padding:14px; overflow:hidden;
    }}
    .card.full {{ grid-column:1/-1 }}

    .card-label {{
      font-family:'DM Mono',monospace; font-size:8px;
      letter-spacing:.18em; color:var(--muted); text-transform:uppercase;
      margin-bottom:12px;
      display:flex; align-items:center; gap:6px;
    }}
    .card-label::after {{ content:''; flex:1; height:1px; background:var(--border) }}

    /* ── Météo ── */
    .meteo-main {{
      display:flex; align-items:center; gap:14px;
      margin-bottom:12px;
    }}
    .meteo-icon {{ font-size:48px; line-height:1; flex-shrink:0 }}
    .meteo-temp-block {{ flex:1 }}
    .meteo-temp {{
      font-family:'DM Serif Display',serif; font-size:48px; line-height:1;
    }}
    .meteo-temp sup {{
      font-size:20px; vertical-align:super;
      color:var(--muted); font-family:'Syne',sans-serif; font-weight:400;
    }}
    .meteo-desc {{ font-size:13px; font-weight:600; margin-top:4px; color:var(--accent) }}
    .meteo-feels {{ font-size:11px; color:var(--muted); margin-top:2px }}
    .meteo-minmax {{
      display:flex; flex-direction:column; gap:4px;
      font-family:'DM Mono',monospace; font-size:14px;
      align-items:flex-end; flex-shrink:0;
    }}
    .temp-max {{ color:var(--orange); font-weight:600 }}
    .temp-min {{ color:var(--accent2); font-weight:600 }}
    .meteo-rain {{ color:var(--blue); font-size:12px }}

    .lac-block {{
      display:flex; align-items:center; gap:8px;
      padding:8px 12px; border-radius:8px;
      background:rgba(126,200,200,0.08); border:1px solid rgba(126,200,200,0.15);
    }}
    .lac-icon {{ font-size:20px }}
    .lac-label {{ font-size:12px; color:var(--muted); flex:1 }}
    .lac-temp {{
      font-family:'DM Serif Display',serif; font-size:24px;
      color:var(--accent2);
    }}
    .lac-na .lac-temp {{ color:var(--muted); font-size:16px }}

    /* ── News ── */
    .news-list {{
      display:flex; flex-direction:column; gap:0;
      max-height:380px; overflow-y:auto;
    }}
    .news-list::-webkit-scrollbar {{ width:4px }}
    .news-list::-webkit-scrollbar-thumb {{ background:var(--border2); border-radius:2px }}

    .news-item {{
      display:block; text-decoration:none; color:inherit;
      padding:9px 0;
      border-bottom:1px solid var(--border);
      transition:background .15s;
    }}
    .news-item:last-child {{ border-bottom:none }}
    .news-item:hover {{ background:var(--surface2); margin:0 -14px; padding:9px 14px; border-radius:4px }}
    .news-title {{
      font-size:13px; font-weight:600; line-height:1.4;
      color:var(--text);
    }}
    .news-summary {{
      font-size:11px; color:var(--muted); margin-top:3px; line-height:1.4;
    }}

    /* ── Cinémas ── */
    .cinema-list {{ display:flex; flex-direction:column; gap:4px }}
    .cinema-name {{
      font-family:'DM Mono',monospace; font-size:9px;
      color:var(--accent); letter-spacing:.12em; text-transform:uppercase;
      margin-top:10px; margin-bottom:4px;
      padding-bottom:4px; border-bottom:1px solid var(--border);
    }}
    .cinema-name:first-child {{ margin-top:0 }}
    .cinema-film {{
      font-size:13px; font-weight:500; color:var(--text);
      padding:4px 0; border-bottom:1px solid var(--border);
    }}
    .cinema-film:last-of-type {{ border-bottom:none }}

    /* ── Erreur ── */
    .error {{ color:var(--red); font-size:11px; font-family:'DM Mono',monospace; padding:4px 0 }}

    /* ── Footer ── */
    .footer {{
      margin-top:16px; max-width:900px;
      display:flex; justify-content:space-between; align-items:center;
    }}
    .footer-info {{ font-family:'DM Mono',monospace; font-size:9px; color:var(--muted); letter-spacing:.04em }}
  </style>
</head>
<body>

  <div class="header">
    <div>
      <div class="header-title">📍 Annecy</div>
      <div class="header-sub">{jour} {date_str}</div>
    </div>
    <div>
      <div class="header-time">{heure_str}</div>
      <div class="header-date">màj toutes les 30 min</div>
    </div>
  </div>

  <div class="grid">

    <!-- Météo -->
    <div class="card">
      <div class="card-label">Météo · Annecy</div>
      {meteo_html(meteo, lac)}
    </div>

    <!-- News -->
    <div class="card">
      <div class="card-label">Actualités · Annecy</div>
      {news_html(news)}
    </div>

    <!-- Cinémas -->
    <div class="card full">
      <div class="card-label">Cinémas · À l'affiche aujourd'hui</div>
      {cinemas_html(cinemas)}
    </div>

  </div>

  <div class="footer">
    <div class="footer-info">Générée le {jour.lower()} {date_str} à {heure_str}</div>
    <div class="footer-info">Prochaine mise à jour dans ~{next_min} min</div>
  </div>

</body>
</html>"""

# ── Main ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"[{now.strftime('%H:%M')}] Génération du dashboard Annecy…")

    print("  → Météo air…")
    meteo = get_meteo()
    print(f"    {meteo}")

    print("  → Température lac…")
    lac = get_lac_temp()
    print(f"    {lac}")

    print("  → News…")
    news = get_news()
    print(f"    {len(news.get('articles', []))} articles")

    print("  → Cinémas…")
    cinemas = get_cinemas()
    print(f"    {cinemas}")

    html = build_html(meteo, lac, news, cinemas)
    os.makedirs("docs", exist_ok=True)
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("  ✓ docs/index.html généré")
