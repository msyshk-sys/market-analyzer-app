import streamlit as st
import yfinance as yf
import requests
import json
import hashlib
import re
import time
import email.utils
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup
import trafilatura

st.set_page_config(page_title="Market Dashboard", layout="wide")
st.title("🌍 Global Market Dashboard")

JST = timezone(timedelta(hours=+9), "JST")
UTC = timezone.utc

US_MORNING_HOUR = 7   # 米国3指数・先物/商品の早朝更新
JP_CLOSE_HOUR = 17    # 日本株・先物/商品の17時更新
MAX_ARTICLE_CHARS = 3500
MAX_NEWS_PER_ASSET = 2

INDEX_US = {
    "S&P 500": "^GSPC",
    "NY Dow": "^DJI",
    "NASDAQ": "^IXIC",
}
INDEX_JP = {
    "日経平均": "^N225",
    "TOPIX": "1306.T",
}
COMMODITIES_FUTURES = {
    "金": "GC=F",
    "銀": "SI=F",
    "原油 (WTI)": "CL=F",
    "日経平均先物": "NIY=F",
}

RAW_JSON_URL = "https://raw.githubusercontent.com/msyshk-sys/market-analyzer-app/main/industry_themes.json"


def _slot_us(now_jst: datetime) -> str:
    d = now_jst.date()
    if now_jst.hour < US_MORNING_HOUR:
        d = d - timedelta(days=1)
    return f"US_{d.isoformat()}_0700"


def _slot_jp(now_jst: datetime) -> str:
    d = now_jst.date()
    if now_jst.hour < JP_CLOSE_HOUR:
        d = d - timedelta(days=1)
    return f"JP_{d.isoformat()}_1700"


def _slot_com(now_jst: datetime) -> str:
    d = now_jst.date()
    h = now_jst.hour
    if h >= JP_CLOSE_HOUR:
        return f"COM_{d.isoformat()}_1700"
    if h >= US_MORNING_HOUR:
        return f"COM_{d.isoformat()}_0700"
    d = d - timedelta(days=1)
    return f"COM_{d.isoformat()}_1700"


@st.cache_data(show_spinner=False)
def fetch_data_for_slot(tickers_dict, slot_id, force_nonce=""):
    _ = slot_id, force_nonce  # cacheキーに含めるため
    data = {}
    for name, ticker in tickers_dict.items():
        try:
            hist = yf.Ticker(ticker).history(period="5d")
            if len(hist) >= 2:
                current_price = hist["Close"].iloc[-1]
                previous_price = hist["Close"].iloc[-2]
                change_amt = current_price - previous_price
                change_pct = (change_amt / previous_price) * 100
                last_date = hist.index[-1].astimezone(JST).strftime("%Y-%m-%d %H:%M")
                data[name] = {
                    "Price": round(float(current_price), 2),
                    "Change": round(float(change_amt), 2),
                    "Change %": round(float(change_pct), 2),
                    "Last Updated": last_date,
                }
            else:
                data[name] = {"Price": "N/A", "Change": "N/A", "Change %": "N/A", "Last Updated": "N/A"}
        except Exception:
            data[name] = {"Price": "Error", "Change": "Error", "Change %": "Error", "Last Updated": "Error"}
    return data


@st.cache_data(ttl=3600)
def load_global_data():
    try:
        response = requests.get(RAW_JSON_URL, timeout=20)
        if response.status_code == 200:
            return response.json()
        st.error("データの取得に失敗しました。")
        return None
    except Exception as e:
        st.error(f"エラー: {e}")
        return None


def _parse_rfc2822_to_utc(dt_str):
    try:
        d = email.utils.parsedate_to_datetime(dt_str)
        if d.tzinfo is None:
            d = d.replace(tzinfo=UTC)
        return d.astimezone(UTC)
    except Exception:
        return None


def _is_within_24h(pub_dt_utc):
    if pub_dt_utc is None:
        return False
    return (datetime.now(UTC) - pub_dt_utc) <= timedelta(hours=24)


def _read_rss_items(feed_url, max_items=20):
    try:
        r = requests.get(feed_url, timeout=20)
        r.raise_for_status()
        root = ET.fromstring(r.text)
    except Exception:
        return []

    out = []
    for item in root.findall(".//item"):
        title = item.findtext("title", default="")
        link = item.findtext("link", default="")
        pub = item.findtext("pubDate", default="")
        pub_dt = _parse_rfc2822_to_utc(pub)
        if _is_within_24h(pub_dt):
            out.append({"title": title, "link": link, "pubDate": pub})
        if len(out) >= max_items:
            break
    return out


def _keyword_hit(text, keywords):
    t = (text or "").lower()
    return any(k.lower() in t for k in keywords)


def _google_news_24h(query, max_items=5):
    url = f"https://news.google.com/rss/search?q={quote_plus(query + ' when:24h')}&hl=ja&gl=JP&ceid=JP:ja"
    return _read_rss_items(url, max_items=max_items)


def _reuters_ir_feed_urls():
    url = "https://ir.thomsonreuters.com/rss-feeds"
    try:
        html = requests.get(url, timeout=20).text
    except Exception:
        return []

    candidates = re.findall(r'href="([^"]+)"', html)
    urls = []
    for u in candidates:
        u_low = u.lower()
        if "rss" in u_low or u_low.endswith(".xml"):
            if u.startswith("/"):
                u = "https://ir.thomsonreuters.com" + u
            elif not (u.startswith("http://") or u.startswith("https://")):
                continue
            urls.append(u)
    return list(dict.fromkeys(urls))


def fetch_factor_news_24h(symbol_name, max_items=MAX_NEWS_PER_ASSET):
    alias = {
        "S&P 500": ["s&p 500", "sp500", "米国株", "アメリカ株"],
        "NY Dow": ["dow", "ダウ", "米国株", "アメリカ株"],
        "NASDAQ": ["nasdaq", "ナスダック", "ハイテク株"],
        "日経平均": ["日経平均", "nikkei", "日本株"],
        "TOPIX": ["topix", "東証", "日本株"],
        "金": ["金", "gold", "先物"],
        "銀": ["銀", "silver", "先物"],
        "原油 (WTI)": ["wti", "原油", "oil", "先物"],
        "日経平均先物": ["日経平均先物", "cme nikkei", "先物"],
    }
    kws = alias.get(symbol_name, [symbol_name])
    collected = []

    yahoo_url = "https://news.yahoo.co.jp/rss/topics/business.xml"
    for it in _read_rss_items(yahoo_url, max_items=40):
        if _keyword_hit(it["title"], kws):
            collected.append({**it, "source": "Yahoo RSS"})
        if len(collected) >= max_items:
            return collected

    investing_candidates = [
        "https://www.investing.com/rss/news.rss",
        "https://www.investing.com/rss/market_overview.rss",
    ]
    for feed in investing_candidates:
        for it in _read_rss_items(feed, max_items=40):
            if _keyword_hit(it["title"], kws):
                collected.append({**it, "source": "Investing RSS"})
            if len(collected) >= max_items:
                return collected

    for feed in _reuters_ir_feed_urls()[:8]:
        for it in _read_rss_items(feed, max_items=40):
            if _keyword_hit(it["title"], kws):
                collected.append({**it, "source": "Reuters RSS"})
            if len(collected) >= max_items:
                return collected

    q = f"{symbol_name} 相場 ニュース"
    for it in _google_news_24h(q, max_items=12):
        collected.append({**it, "source": "Google News"})
        if len(collected) >= max_items:
            return collected

    return collected[:max_items]


def _extract_article_text(url: str) -> str:
    try:
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            txt = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
            if txt:
                return txt[:MAX_ARTICLE_CHARS]
    except Exception:
        pass

    try:
        html = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"}).text
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.extract()
        txt = " ".join(soup.stripped_strings)
        return txt[:MAX_ARTICLE_CHARS]
    except Exception:
        return ""


def _target_assets_for_fulltext(movers):
    if movers:
        return [m["name"] for m in movers]
    return ["S&P 500", "NY Dow", "NASDAQ", "日経平均"]


def _gemini_generate(prompt):
    api_key = st.secrets["GEMINI_API_KEY"]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2},
    }

    last_err = None
    for i in range(5):
        try:
            r = requests.post(url, json=body, timeout=120)
            if r.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"{r.status_code} retryable", response=r)
            r.raise_for_status()
            j = r.json()
            return j["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            last_err = e
            time.sleep(min(2 ** i, 16))
    raise last_err


def build_market_rows(*datasets):
    rows = []
    for d in datasets:
        for name, m in d.items():
            if isinstance(m.get("Change %"), (int, float)):
                rows.append(
                    {
                        "name": name,
                        "price": m["Price"],
                        "change_pct": m["Change %"],
                        "change_amt": m["Change"],
                        "last_updated": m["Last Updated"],
                    }
                )
    return rows


def _build_enriched_news_for_assets(assets):
    news_id_counter = 1
    news_bundle = {}
    for asset in assets:
        raw_items = fetch_factor_news_24h(asset, max_items=MAX_NEWS_PER_ASSET)
        enriched = []
        for it in raw_items:
            full_text = _extract_article_text(it["link"])
            enriched.append({
                "news_id": f"N{news_id_counter}",
                "asset_hint": asset,
                "title": it["title"],
                "link": it["link"],
                "pubDate": it["pubDate"],
                "source": it.get("source", ""),
                "full_text": full_text,
            })
            news_id_counter += 1
        news_bundle[asset] = enriched
    return news_bundle


def _run_gemini_analysis(rows):
    movers = [r for r in rows if abs(r["change_pct"]) >= 1.0]
    target_assets = _target_assets_for_fulltext(movers)
    news_bundle = _build_enriched_news_for_assets(target_assets)
    now_jst = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")

    prompt = f"""
あなたは市場ストラテジストです。日本語で、見出し付きの自然な文章で回答してください。
JSON形式は禁止。必要なら箇条書きを使ってください。

実行時刻(JST): {now_jst}
市場データ:
{json.dumps(rows, ensure_ascii=False)}

1%以上変動した対象:
{json.dumps(movers, ensure_ascii=False)}

ニュース候補(過去24時間・本文付き):
{json.dumps(news_bundle, ensure_ascii=False)}

出力ルール:
1. 最初に「1%以上変動した指数・商品」を上昇/下落別に列挙する。
2. その列挙結果に基づいて、各対象ごとに関連ニュースを要約する。
3. 各対象について「確認できる事実」と「推論」を分けて書く。
4. 最後に「資金フロー」「短期コンセンサス」「中長期への影響」をまとめる。
5. 根拠が弱いものは断定せず、可能性として表現する。
"""
    return _gemini_generate(prompt)


def generate_commentary_if_slot_updated(rows, slot_bundle, force=False):
    key_src = json.dumps(
        {
            "rows": sorted([(r["name"], r["price"], r["change_pct"], r["last_updated"]) for r in rows]),
            "slots": slot_bundle,
        },
        ensure_ascii=False,
    )
    key = hashlib.sha256(key_src.encode("utf-8")).hexdigest()

    if (not force) and st.session_state.get("gemini_key") == key and st.session_state.get("gemini_text"):
        return st.session_state["gemini_text"]

    try:
        text = _run_gemini_analysis(rows)
        st.session_state["gemini_text_last_ok"] = text
    except Exception as e:
        text = st.session_state.get("gemini_text_last_ok", f"Gemini分析の取得に失敗しました: {e}")

    st.session_state["gemini_key"] = key
    st.session_state["gemini_text"] = text
    return text


# -----------------------------
# UI
# -----------------------------
now_jst = datetime.now(JST)
st.write(f"最終アクセス確認時刻: {now_jst.strftime('%Y-%m-%d %H:%M:%S')}")
st.info("更新時刻ルールに応じてデータを取得します。同一スロットでは再取得しません。")

force_refresh = st.button("🔄 データとGeminiを強制更新")
force_nonce = now_jst.strftime("%Y%m%d%H%M%S") if force_refresh else ""

slot_us = _slot_us(now_jst)
slot_jp = _slot_jp(now_jst)
slot_com = _slot_com(now_jst)

us_data = fetch_data_for_slot(INDEX_US, slot_us, force_nonce)
jp_data = fetch_data_for_slot(INDEX_JP, slot_jp, force_nonce)
com_data = fetch_data_for_slot(COMMODITIES_FUTURES, slot_com, force_nonce)

rows = build_market_rows(us_data, jp_data, com_data)
slot_bundle = {"us": slot_us, "jp": slot_jp, "com": slot_com}
commentary = generate_commentary_if_slot_updated(rows, slot_bundle, force=force_refresh)

st.subheader("🧠 Gemini 市場解説")
st.markdown(commentary)
st.divider()

st.subheader("🇺🇸 米国市場 (US Equities)")
cols_us = st.columns(len(us_data))
for i, (name, metrics) in enumerate(us_data.items()):
    with cols_us[i]:
        if metrics["Price"] not in ["N/A", "Error"]:
            st.metric(label=name, value=f"{metrics['Price']}", delta=f"{metrics['Change']} ({metrics['Change %']}%)")
            st.caption(f"Updated: {metrics['Last Updated']}")

st.divider()

st.subheader("🇯🇵 日本市場 (JP Equities)")
cols_jp = st.columns(max(len(jp_data), 3))
for i, (name, metrics) in enumerate(jp_data.items()):
    with cols_jp[i]:
        if metrics["Price"] not in ["N/A", "Error"]:
            st.metric(label=name, value=f"{metrics['Price']}", delta=f"{metrics['Change']} ({metrics['Change %']}%)")
            st.caption(f"Updated: {metrics['Last Updated']}")

st.divider()

st.subheader("🛢️ コモディティ・先物 (Commodities & Futures)")
cols_com = st.columns(len(com_data))
for i, (name, metrics) in enumerate(com_data.items()):
    with cols_com[i]:
        if metrics["Price"] not in ["N/A", "Error"]:
            st.metric(label=name, value=f"{metrics['Price']}", delta=f"{metrics['Change']} ({metrics['Change %']}%)")
            st.caption(f"Updated: {metrics['Last Updated']}")

market_data = load_global_data()
if market_data:
    st.write(f"最終更新: {market_data.get('updated_at')}")

st.divider()
st.subheader("💬 マーケットAIアシスタント (準備中)")

if "messages" not in st.session_state:
    st.session_state.messages = []

if prompt := st.chat_input("何でも聞いてください"):
    with st.chat_message("user"):
        st.write(prompt)
    with st.chat_message("assistant"):
        st.write(f"「{prompt}」ですね。AI連携機能は現在開発中です！")
