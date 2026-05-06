import streamlit as st
import requests
import json
from github import Github
from datetime import datetime

QUANTS_API_KEY = st.secrets["JQUANTS_API_KEY"]
GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
REPO_NAME = "msyshk-sys/market-analyzer-app"
FILE_PATH = "industry_themes.json"

def push_to_github(json_data):
    g = Github(GITHUB_TOKEN)
    repo = g.get_repo(REPO_NAME)
    content = json.dumps(json_data, ensure_ascii=False, indent=2)
    try:
        contents = repo.get_contents(FILE_PATH)
        repo.update_file(
            path=FILE_PATH,
            message=f"Update industry data: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            content=content,
            sha=contents.sha,
            branch="main"
        )
    except Exception:
        repo.create_file(path=FILE_PATH, message="Initial data", content=content, branch="main")

def fetch_and_format_jquants():
    headers = {"x-api-key": st.secrets["JQUANTS_API_KEY"]}
    url = "https://api.jquants.com/v2/equities/master"

    all_rows = []
    pagination_key = None

    while True:
        params = {}
        if pagination_key:
            params["pagination_key"] = pagination_key

        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        payload = resp.json()

        rows = payload.get("data", [])
        all_rows.extend(rows)

        pagination_key = payload.get("pagination_key")
        if not pagination_key:
            break

    sector_map = {}
    for r in all_rows:
        s33 = r.get("S33")
        s33nm = r.get("S33Nm")
        code = r.get("Code")
        name = r.get("CoName")

        if not s33 or s33 == "-":
            continue

        key = (s33, s33nm)
        sector_map.setdefault(key, []).append({"code": code, "name": name})

    theme_list = [
        {"sector_code": s33, "sector_name": s33nm, "stocks": stocks}
        for (s33, s33nm), stocks in sector_map.items()
    ]

    return {
        "updated_at": datetime.now().isoformat(),
        "themes": theme_list
    }

st.title("⚙️ データ更新設定")

if st.button("J-Quantsのデータを最新にしてGitHubに保存"):
    with st.spinner("処理中..."):
        try:
            new_data = fetch_and_format_jquants()
            push_to_github(new_data)
            st.success("GitHub上のマスターデータを更新しました！")
        except Exception as e:
            st.error(f"エラーが発生しました: {e}")
