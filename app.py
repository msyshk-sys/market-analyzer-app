import streamlit as st
import yfinance as yf
import requests
import json
import os
import hashlib
import re
import email.utils
import xml.etree.ElementTree as ET
import time
from urllib.parse import quote_plus
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup
import trafilatura

st.set_page_config(page_title="Market Dashboard", layout="wide")
st.title("🌍 Global Market Dashboard")

JST = timezone(timedelta(hours=+9), "JST")
UTC = timezone.utc

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
MAX_ARTICLE_CHARS = 16000


@st.cache_data(ttl=10800)
def fetch_data(tickers_dict):
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
            st.warning(f"{name} のデータ取得に失敗しました。")
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


def fetch_factor_news_24h(symbol_name, max_items=4):
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
    for i in range(5):  # 最大5回
        try:
            r = requests.post(url, json=body, timeout=120)
            if r.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"{r.status_code} retryable", response=r)
            r.raise_for_status()
            j = r.json()
            return j["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            last_err = e
            time.sleep(min(2 ** i, 16))  # 1,2,4,8,16秒

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
        raw_items = fetch_factor_news_24h(asset, max_items=4)
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


def generate_commentary_if_updated(rows):
    fp_src = json.dumps(
        sorted([(r["name"], r["price"], r["change_pct"], r["last_updated"]) for r in rows]),
        ensure_ascii=False,
    )
    fp = hashlib.sha256(fp_src.encode("utf-8")).hexdigest()

    if st.session_state.get("market_fp") == fp and st.session_state.get("gemini_commentary"):
        return st.session_state["gemini_commentary"]

    movers = [r for r in rows if abs(r["change_pct"]) >= 1.0]
    target_assets = _target_assets_for_fulltext(movers)
    news_bundle = _build_enriched_news_for_assets(target_assets)
    now_jst = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")

    prompt = f"""
あなたは市場ストラテジスト。次の market_moves と news_items だけを使って分析してください。
必ず日本語、必ずJSONで回答。
根拠のない断定は禁止。ニュースにない事実の創作は禁止。

実行時刻(JST): {now_jst}
market_moves:
{json.dumps(rows, ensure_ascii=False)}

movers(abs(change)>=1%):
{json.dumps(movers, ensure_ascii=False)}

news_items(過去24時間):
{json.dumps(news_bundle, ensure_ascii=False)}

出力JSONスキーマ:
{{
  "impacted_assets": [
    {{
      "asset": "string",
      "move_summary": "string",
      "key_facts": ["ニュース本文で確認できる事実を最大3件"],
      "causal_links": [
        {{
          "hypothesis": "事実→価格変動の因果仮説",
          "confidence": "high|medium|low",
          "evidence_news_ids": ["N1","N2"]
        }}
      ]
    }}
  ],
  "consensus_now": {{
    "short_term_consensus": "string",
    "medium_long_term_consensus": "string",
    "changed_by_today": true,
    "why": "string"
  }},
  "uncertainty": {{
    "data_gaps": ["不足情報"],
    "low_confidence_points": ["確度の低い論点"]
  }}
}}

重要ルール:
- 「事実」と「推論」を分離すること
- 推論には必ず evidence_news_ids を付けること
- 根拠不足は判断保留と明記すること
"""

    try:
        text = _gemini_generate(prompt)
        st.session_state["gemini_commentary_last_ok"] = text
    except Exception as e:
        text = st.session_state.get(
            "gemini_commentary_last_ok",
            json.dumps({
                "error": f"Gemini分析の取得に失敗しました: {e}",
                "impacted_assets": [],
                "consensus_now": {},
                "uncertainty": {}
            }, ensure_ascii=False, indent=2)
        )

    st.session_state["market_fp"] = fp
    st.session_state["gemini_commentary"] = text
    return text


st.write(f"最終アクセス確認時刻: {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')}")
st.info("データはアクセス時に取得されます（キャッシュ有効時は高速表示）。")

us_data = fetch_data(INDEX_US)
jp_data = fetch_data(INDEX_JP)
com_data = fetch_data(COMMODITIES_FUTURES)

rows = build_market_rows(us_data, jp_data, com_data)
commentary = generate_commentary_if_updated(rows)

st.subheader("🧠 Gemini 市場解説")
st.code(commentary, language="json")
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
