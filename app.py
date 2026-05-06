import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import json
import os
import hashlib
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus
from datetime import datetime, timedelta, timezone


st.set_page_config(page_title="Market Dashboard", layout="wide")
st.title("🌍 Global Market Dashboard")

# 日本時間のタイムゾーンを設定
JST = timezone(timedelta(hours=+9), "JST")

# --- ティッカーシンボルの定義 ---
INDEX_US = {
    "S&P 500": "^GSPC",
    "NY Dow": "^DJI",
    "NASDAQ": "^IXIC"
}
INDEX_JP = {
    "日経平均": "^N225",
    "TOPIX": "1306.T"  # TOPIX連動ETF(野村)で代用
}
COMMODITIES_FUTURES = {
    "金": "GC=F",
    "銀": "SI=F",
    "原油 (WTI)": "CL=F",
    "日経平均先物": "NIY=F"
}

RAW_JSON_URL = "https://raw.githubusercontent.com/msyshk-sys/market-analyzer-app/main/industry_themes.json"


@st.cache_data(ttl=3600)
def load_data():
    raw_url = "https://raw.githubusercontent.com/ユーザー名/リポジトリ名/main/industry_themes.json"

    try:
        response = requests.get(raw_url, timeout=20)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass

    if os.path.exists("industry_themes.json"):
        with open("industry_themes.json", "r", encoding="utf-8") as f:
            return json.load(f)

    return {"updated_at": "データ未取得", "themes": []}


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
                    "Last Updated": last_date
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


def _google_news_rss(query, max_items=3):
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=ja&gl=JP&ceid=JP:ja"
    r = requests.get(url, timeout=20)
    r.raise_for_status()

    root = ET.fromstring(r.text)
    items = []
    for item in root.findall("./channel/item")[:max_items]:
        items.append({
            "title": item.findtext("title", default=""),
            "link": item.findtext("link", default=""),
            "pubDate": item.findtext("pubDate", default="")
        })
    return items


def _gemini_generate(prompt):
    api_key = st.secrets["GEMINI_API_KEY"]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3}
    }
    r = requests.post(url, json=body, timeout=60)
    r.raise_for_status()
    j = r.json()
    return j["candidates"][0]["content"]["parts"][0]["text"]


def build_market_rows(*datasets):
    rows = []
    for d in datasets:
        for name, m in d.items():
            if isinstance(m.get("Change %"), (int, float)):
                rows.append({
                    "name": name,
                    "price": m["Price"],
                    "change_pct": m["Change %"],
                    "change_amt": m["Change"],
                    "last_updated": m["Last Updated"]
                })
    return rows


def generate_commentary_if_updated(rows):
    fp_src = json.dumps(
        sorted([(r["name"], r["price"], r["change_pct"], r["last_updated"]) for r in rows]),
        ensure_ascii=False
    )
    fp = hashlib.sha256(fp_src.encode("utf-8")).hexdigest()

    if st.session_state.get("market_fp") == fp and st.session_state.get("gemini_commentary"):
        return st.session_state["gemini_commentary"]

    movers = [r for r in rows if abs(r["change_pct"]) >= 1.0]
    today = datetime.now(JST).strftime("%Y-%m-%d")

    news_bundle = {}
    for r in movers:
        q = f'{r["name"]} 相場 ニュース after:{today} before:{today}'
        try:
            news_bundle[r["name"]] = _google_news_rss(q, max_items=3)
        except Exception:
            news_bundle[r["name"]] = []

    prompt = f"""
あなたは市場ストラテジストです。以下データをもとに日本語で簡潔に分析してください。

日付: {today}
市場データ:
{json.dumps(rows, ensure_ascii=False)}

ニュース候補:
{json.dumps(news_bundle, ensure_ascii=False)}

必ず次を出力してください:
1. 1%以上変動した指数・商品の列挙（上昇/下落、%）
2. 各変動の要因ニュース（候補ベース、断定しすぎない）
3. 現在の資金フロー（どこに資金が向かっているか）
4. 短期コンセンサス
5. 中長期コンセンサスへの影響有無
"""

    try:
        text = _gemini_generate(prompt)
    except Exception as e:
        text = f"Gemini分析の取得に失敗しました: {e}"

    st.session_state["market_fp"] = fp
    st.session_state["gemini_commentary"] = text
    return text


# -----------------------------
# データ取得
# -----------------------------
st.write(f"最終アクセス確認時刻: {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')}")
st.info("データはアクセス時に取得されます（キャッシュ有効時は高速表示）。実際の取引時間とはズレがある場合があります。")

us_data = fetch_data(INDEX_US)
jp_data = fetch_data(INDEX_JP)
com_data = fetch_data(COMMODITIES_FUTURES)

# -----------------------------
# Gemini解説（指数テーブルより上）
# -----------------------------
rows = build_market_rows(us_data, jp_data, com_data)
commentary = generate_commentary_if_updated(rows)

st.subheader("🧠 Gemini 市場解説")
st.markdown(commentary)
st.divider()

# -----------------------------
# 指数表示
# -----------------------------
st.subheader("🇺🇸 米国市場 (US Equities)")
cols_us = st.columns(len(us_data))
for i, (name, metrics) in enumerate(us_data.items()):
    with cols_us[i]:
        if metrics["Price"] not in ["N/A", "Error"]:
            st.metric(
                label=name,
                value=f"{metrics['Price']}",
                delta=f"{metrics['Change']} ({metrics['Change %']}%)"
            )
            st.caption(f"Updated: {metrics['Last Updated']}")

st.divider()

st.subheader("🇯🇵 日本市場 (JP Equities)")
cols_jp = st.columns(max(len(jp_data), 3))
for i, (name, metrics) in enumerate(jp_data.items()):
    with cols_jp[i]:
        if metrics["Price"] not in ["N/A", "Error"]:
            st.metric(
                label=name,
                value=f"{metrics['Price']}",
                delta=f"{metrics['Change']} ({metrics['Change %']}%)"
            )
            st.caption(f"Updated: {metrics['Last Updated']}")

st.divider()

st.subheader("🛢️ コモディティ・先物 (Commodities & Futures)")
cols_com = st.columns(len(com_data))
for i, (name, metrics) in enumerate(com_data.items()):
    with cols_com[i]:
        if metrics["Price"] not in ["N/A", "Error"]:
            st.metric(
                label=name,
                value=f"{metrics['Price']}",
                delta=f"{metrics['Change']} ({metrics['Change %']}%)"
            )
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
