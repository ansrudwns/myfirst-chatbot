import streamlit as st
import os
import arxiv
import sqlite3
import uuid
from datetime import datetime
from openai import AzureOpenAI
from dotenv import load_dotenv

# 1. 환경 변수 로드
load_dotenv()

# Streamlit 페이지 설정
st.set_page_config(page_title="Paper Mate Pro", page_icon="📚", layout="wide")

# 2. Azure OpenAI 클라이언트 설정
client = AzureOpenAI(
    api_key=os.getenv("AZURE_OAI_KEY"),
    api_version="2024-05-01-preview",
    azure_endpoint=os.getenv("AZURE_OAI_ENDPOINT")
)

# --- [데이터베이스 관리 함수] ---
DB_NAME = "chat_history.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            title TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            role TEXT,
            content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(session_id) REFERENCES sessions(id)
        )
    ''')
    conn.commit()
    conn.close()

def create_session(title="새로운 대화"):
    session_id = str(uuid.uuid4())
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # 한국 시간 표시를 위해 포맷팅
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    final_title = title
    c.execute("INSERT INTO sessions (id, title, created_at) VALUES (?, ?, ?)", 
              (session_id, final_title, timestamp))
    conn.commit()
    conn.close()
    return session_id

def update_session_title(session_id, new_title):
    """세션 제목을 변경합니다."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE sessions SET title = ? WHERE id = ?", (new_title, session_id))
    conn.commit()
    conn.close()

def get_session_info(session_id):
    """특정 세션의 정보를 가져옵니다."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT title, created_at FROM sessions WHERE id = ?", (session_id,))
    row = c.fetchone()
    conn.close()
    return row if row else ("알 수 없음", "")

def save_message(session_id, role, content):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)", 
              (session_id, role, content))
    conn.commit()
    conn.close()

def get_messages(session_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT role, content FROM messages WHERE session_id = ? ORDER BY id ASC", (session_id,))
    rows = c.fetchall()
    conn.close()
    return [{"role": row[0], "content": row[1]} for row in rows]

def get_all_sessions():
    """모든 세션을 최신순으로 가져옵니다 (날짜 포함)."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, title, created_at FROM sessions ORDER BY created_at DESC")
    sessions = c.fetchall()
    conn.close()
    return sessions

# --- [신규 기능] 검색어 번역 함수 ---
def translate_to_english_keyword(user_query):
    """
    사용자의 입력(한글 등)을 ArXiv 검색에 최적화된 '영어 키워드'로 변환합니다.
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a research assistant. Convert the user's query into concise English keywords suitable for searching academic papers on ArXiv. Return ONLY the keywords, no other text."},
                {"role": "user", "content": user_query}
            ]
        )
        english_keyword = response.choices[0].message.content.strip()
        return english_keyword
    except Exception:
        return user_query # 오류 시 원본 그대로 사용

# --- [ArXiv 검색 함수] ---
def search_arxiv(query, max_results=3):
    try:
        client = arxiv.Client()
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.Relevance
        )
        
        results = list(client.results(search))
        
        if not results:
            return None, 0 # 결과 텍스트 없음, 개수 0

        results_text = []
        for result in results:
            authors = ", ".join([author.name for author in result.authors])
            published_year = result.published.strftime("%Y")
            
            paper_data = f"""
            [Paper ID: {result.entry_id}]
            - Title: {result.title}
            - Authors: {authors}
            - Published Year: {published_year}
            - Abstract: {result.summary.replace(chr(10), " ")} 
            - PDF Link: {result.pdf_url}
            """
            results_text.append(paper_data)
        
        return "\n\n".join(results_text), len(results)

    except Exception as e:
        st.error(f"ArXiv 검색 오류: {e}")
        return None, 0

# --- [메인 앱 로직] ---

init_db()

# 세션 상태 관리
if "current_session_id" not in st.session_state:
    st.session_state.current_session_id = None

# --- [사이드바] ---
with st.sidebar:
    st.title("🗂️ 대화 관리")
    
    if st.button("➕ 새 대화 시작", use_container_width=True):
        new_id = create_session()
        st.session_state.current_session_id = new_id
        st.rerun()
    
    st.divider()

    # [기능 추가] 현재 대화 제목 수정 기능
    if st.session_state.current_session_id:
        current_title, _ = get_session_info(st.session_state.current_session_id)
        with st.expander("✏️ 현재 대화 제목 수정"):
            new_title_input = st.text_input("새 제목 입력", value=current_title)
            if st.button("변경 저장", use_container_width=True):
                update_session_title(st.session_state.current_session_id, new_title_input)
                st.rerun()
        st.divider()

    st.subheader("🕒 최근 대화 목록")
    sessions = get_all_sessions()
    
    # [기능 추가] 목록에 날짜/시간 표시
    for s_id, s_title, s_date in sessions:
        # 버튼 라벨에 날짜 포함 (작은 글씨 효과는 줄바꿈으로 처리)
        label = f"{s_title}\nTime: {s_date}"
        if st.button(label, key=s_id, use_container_width=True):
            st.session_state.current_session_id = s_id
            st.rerun()

# --- [메인 화면] ---

# 초기 세션 설정
if not st.session_state.current_session_id:
    if sessions:
        st.session_state.current_session_id = sessions[0][0]
    else:
        st.session_state.current_session_id = create_session()

# 현재 세션 정보 가져오기
session_title, session_date = get_session_info(st.session_state.current_session_id)
st.title(f"🎓 {session_title}")
st.caption(f"생성일: {session_date} | Paper Mate Pro")

current_messages = get_messages(st.session_state.current_session_id)

for msg in current_messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("한글로 주제를 입력해도 자동으로 찾아줍니다 (예: 대규모 언어 모델)"):
    
    st.chat_message("user").markdown(prompt)
    save_message(st.session_state.current_session_id, "user", prompt)

    with st.spinner(f"🌏 '{prompt}'을(를) 영어로 변환하여 검색 중입니다..."):
        try:
            # 1. [기능 추가] 한글 -> 영어 키워드 변환
            english_query = translate_to_english_keyword(prompt)
            st.toast(f"검색어 변환: {english_query}") # 사용자에게 변환된 키워드를 살짝 보여줌 (Toast)

            # 2. ArXiv 검색 실행 (변환된 영어 키워드로)
            search_context, paper_count = search_arxiv(english_query)
            
            if not search_context:
                assistant_reply = f"'{english_query}'(으)로 검색했으나 결과가 없습니다. 다른 키워드를 시도해 보세요."
            else:
                full_prompt = f"""
                사용자가 '{prompt}'(영어 변환: {english_query})에 대한 논문을 찾고 있습니다.
                
                [지시사항]
                1. 아래 [검색된 논문 데이터]에는 **총 {paper_count}개의 논문**이 있습니다.
                2. 반드시 **{paper_count}개 논문 모두**에 대해 각각 답변을 작성하세요.
                3. 한국어로 요약하고, APA 인용에 **반드시 URL을 포함**하세요.
                
                [검색된 논문 데이터]
                {search_context}
                
                --- 답변 형식 (반복) ---
                ### [번호]. [논문 제목] (연도)
                * **핵심 요약:** (한국어 3문장)
                * **APA Citation:** (저자. (연도). 제목. *ArXiv*. URL)
                * **PDF 링크:** (URL)
                ---
                """
                
                messages_for_api = [{"role": "system", "content": "당신은 논문 검색 및 인용 전문가입니다."}]
                messages_for_api.extend(current_messages)
                messages_for_api.append({"role": "user", "content": full_prompt})

                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages_for_api
                )
                assistant_reply = response.choices[0].message.content

            with st.chat_message("assistant"):
                st.markdown(assistant_reply)
            
            save_message(st.session_state.current_session_id, "assistant", assistant_reply)
            
        except Exception as e:
            st.error(f"오류가 발생했습니다: {e}")
