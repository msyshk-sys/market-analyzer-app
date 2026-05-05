import streamlit as st

st.title("金融マーケット分析アプリ")
st.write("Hello World! ここに市場データが表示される予定です。")

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
