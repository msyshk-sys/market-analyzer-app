import streamlit as st
import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta, timezone

st.set_page_config(page_title="Market Dashboard", layout="wide")
st.title("🌍 Global Market Dashboard")

# 日本時間のタイムゾーンを設定
JST = timezone(timedelta(hours=+9), 'JST')

# --- ティッカーシンボルの定義 ---
# yfinanceで使われるシンボルです
INDEX_US = {
    "S&P 500": "^GSPC",
    "NY Dow": "^DJI",
    "NASDAQ": "^IXIC"
}
INDEX_JP = {
    "日経平均": "^N225",
    "TOPIX": "1306.T" # TOPIX連動ETF(野村)で代用。純粋な指数は取得しづらいため
}
COMMODITIES_FUTURES = {
    "金": "GC=F",
    "銀": "SI=F",
    "原油 (WTI)": "CL=F",
    "日経平均先物": "NIY=F" # USD建てCME日経先物
}

# --- データ取得関数（キャッシュを活用） ---
# ttl（Time To Live）を設定して、一定時間ごとに再取得するようにします。
# 実際には「指定時間に更新」を厳密にやるのは複雑になるため、
# 実用上は「数時間おきにキャッシュを破棄する」のが最も簡単です。
# ここでは例として、3時間（10800秒）ごとに新しいデータを取得するように設定しています。
@st.cache_data(ttl=10800)
def fetch_data(tickers_dict):
    data = {}
    for name, ticker in tickers_dict.items():
        try:
            # 過去5日分のデータを取得（休場日対策のため多めに取得）
            hist = yf.Ticker(ticker).history(period="5d")
            if len(hist) >= 2:
                # 最新の終値
                current_price = hist['Close'].iloc[-1]
                # 1つ前の終値
                previous_price = hist['Close'].iloc[-2]
                
                # 変化額と変化率
                change_amt = current_price - previous_price
                change_pct = (change_amt / previous_price) * 100
                
                # 直近の取引日
                last_date = hist.index[-1].astimezone(JST).strftime('%Y-%m-%d %H:%M')

                data[name] = {
                    "Price": round(current_price, 2),
                    "Change": round(change_amt, 2),
                    "Change %": round(change_pct, 2),
                    "Last Updated": last_date
                }
            else:
                data[name] = {"Price": "N/A", "Change": "N/A", "Change %": "N/A", "Last Updated": "N/A"}
        except Exception as e:
            st.warning(f"{name} のデータ取得に失敗しました。")
            data[name] = {"Price": "Error", "Change": "Error", "Change %": "Error", "Last Updated": "Error"}
    return data

# --- データ表示UI ---

st.write(f"最終アクセス確認時刻: {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')}")
st.info("データはアクセス時に取得されます（キャッシュ有効時は高速表示）。実際の取引時間とはズレがある場合があります。")

# 1. 米国株エリア
st.subheader("🇺🇸 米国市場 (US Equities)")
us_data = fetch_data(INDEX_US)
cols_us = st.columns(len(us_data))
for i, (name, metrics) in enumerate(us_data.items()):
    with cols_us[i]:
        # st.metricを使うと、上昇(緑)・下落(赤)が自動でわかりやすく表示されます
        if metrics["Price"] != "N/A" and metrics["Price"] != "Error":
             st.metric(
                label=name, 
                value=f"{metrics['Price']}", 
                delta=f"{metrics['Change']} ({metrics['Change %']}%)"
             )
             st.caption(f"Updated: {metrics['Last Updated']}")

st.divider()

# 2. 日本株エリア
st.subheader("🇯🇵 日本市場 (JP Equities)")
jp_data = fetch_data(INDEX_JP)
cols_jp = st.columns(max(len(jp_data), 3)) # 最低3列にしてレイアウトを整える
for i, (name, metrics) in enumerate(jp_data.items()):
    with cols_jp[i]:
        if metrics["Price"] != "N/A" and metrics["Price"] != "Error":
             st.metric(
                label=name, 
                value=f"{metrics['Price']}", 
                delta=f"{metrics['Change']} ({metrics['Change %']}%)"
             )
             st.caption(f"Updated: {metrics['Last Updated']}")

st.divider()

# 3. コモディティ・先物エリア
st.subheader("🛢️ コモディティ・先物 (Commodities & Futures)")
com_data = fetch_data(COMMODITIES_FUTURES)
cols_com = st.columns(len(com_data))
for i, (name, metrics) in enumerate(com_data.items()):
    with cols_com[i]:
        if metrics["Price"] != "N/A" and metrics["Price"] != "Error":
             st.metric(
                label=name, 
                value=f"{metrics['Price']}", 
                delta=f"{metrics['Change']} ({metrics['Change %']}%)"
             )
             st.caption(f"Updated: {metrics['Last Updated']}")


st.divider() # 区切り線
st.subheader("💬 マーケットAIアシスタント (準備中)")

# 会話履歴の初期化
if "messages" not in st.session_state:
    st.session_state.messages = []

# 入力ボックス
if prompt := st.chat_input("何でも聞いてください"):
    # ユーザーの入力を画面に表示
    with st.chat_message("user"):
        st.write(prompt)
    
    # AIの返答（今は仮のテキスト）を画面に表示
    with st.chat_message("assistant"):
        st.write(f"「{prompt}」ですね。AI連携機能は現在開発中です！")
