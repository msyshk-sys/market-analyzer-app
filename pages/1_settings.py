import streamlit as st
import jquantsapi
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
    cli = jquantsapi.ClientV2(api_key=QUANTS_API_KEY)
    df = cli.get_listed_info()

    theme_list = []
    for (s33_code, s33_name), group in df.groupby(["Sector33Code", "Sector33CodeName"]):
        if s33_code == "-":
            continue
        stocks = [{"code": r["Code"], "name": r["CompanyName"]} for _, r in group.iterrows()]
        theme_list.append({"sector_code": s33_code, "sector_name": s33_name, "stocks": stocks})

    return {"updated_at": datetime.now().isoformat(), "themes": theme_list}

st.title("⚙️ データ更新設定")

if st.button("J-Quantsのデータを最新にしてGitHubに保存"):
    with st.spinner("処理中..."):
        try:
            new_data = fetch_and_format_jquants()
            push_to_github(new_data)
            st.success("GitHub上のマスターデータを更新しました！")
        except Exception as e:
            st.error(f"エラーが発生しました: {e}")
