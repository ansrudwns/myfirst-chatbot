import streamlit as st
import os
import arxiv
from openai import AzureOpenAI
from dotenv import load_dotenv

# 1. 환경 변수 로드
load_dotenv()

# Streamlit 페이지 설정
st.set_page_config(page_title="Paper Mate", page_icon="🎓")
st.title("🎓 Paper Mate: 논문 검색 & 인용 도우미")
st.caption("관심 주제를 입력하면 ArXiv에서 논문을 찾아 요약 및 APA 인용구를 생성해 줍니다.")

# 2. Azure OpenAI 클라이언트 설정
# .env 파일에 환경변수가 설정되어 있어야 합니다.
client = AzureOpenAI(
    api_key=os.getenv("AZURE_OAI_KEY"),
    api_version="2024-05-01-preview",
    azure_endpoint=os.getenv("AZURE_OAI_ENDPOINT")
)

# --- [핵심 기능] ArXiv 논문 검색 함수 ---
def search_arxiv(query, max_results=3):
    """
    ArXiv에서 논문을 검색하고 LLM에게 넘겨줄 텍스트 데이터를 구성합니다.
    """
    # 관련성 순으로 정렬하여 검색
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.Relevance
    )
    
    results_text = []
    
    for result in search.results():
        # 저자 리스트 정리 (최대 3명까지만 표시하고 et al. 처리 등은 LLM에게 맡김)
        authors = ", ".join([author.name for author in result.authors])
        
        # 발행일 (년도 추출용)
        published_year = result.published.strftime("%Y")
        
        # LLM에게 전달할 구조화된 텍스트
        paper_data = f"""
        [Paper ID: {result.entry_id}]
        - Title: {result.title}
        - Authors: {authors}
        - Published Year: {published_year}
        - Abstract: {result.summary.replace(chr(10), " ")} 
        - PDF Link: {result.pdf_url}
        """
        results_text.append(paper_data)
    
    return "\n\n".join(results_text)

# 3. 세션 상태 초기화 (대화 기록 유지)
if "messages" not in st.session_state:
    st.session_state.messages = []
    
    # 시스템 프롬프트: AI의 역할을 정의합니다.
    st.session_state.messages.append({
        "role": "system",
        "content": """
        당신은 연구자들을 돕는 '논문 요약 및 인용 전문가'입니다.
        사용자가 주제를 입력하면 검색된 논문 데이터(Context)를 바탕으로 아래 형식에 맞춰 답변하세요.
        
        --- 답변 형식 ---
        
        ### 1. [논문 제목] (발행년도)
        * **핵심 요약:** (Abstract 내용을 바탕으로 한국어로 3문장 이내 핵심 요약)
        * **APA Citation:** (제공된 저자, 연도, 제목을 사용하여 완벽한 APA 스타일 인용구 작성)
        * **PDF 링크:** (제공된 PDF Link URL 표시)
        
        --- (여러 논문일 경우 반복) ---
        
        [주의사항]
        - 검색된 결과가 없으면 솔직하게 없다고 말하세요.
        - APA 스타일 작성 시 저자 이름 표기법(Last, F. M.)을 정확히 지키세요.
        - 요약은 반드시 '한국어'로 작성하세요.
        """
    })

# 4. 화면에 기존 대화 내용 출력
for message in st.session_state.messages:
    if message["role"] != "system": # 시스템 메시지는 화면에 숨김
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

# 5. 사용자 입력 처리
if prompt := st.chat_input("논문 주제를 입력하세요 (예: RAG, Transformer, Quantum Computing)"):
    
    # (1) 사용자 메시지 화면 표시
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    # (2) 로딩 및 처리
    with st.spinner(f"🔎 '{prompt}' 관련 논문을 검색하고 분석 중입니다..."):
        try:
            # ArXiv 검색 수행
            search_context = search_arxiv(prompt)
            
            if not search_context:
                assistant_reply = "검색 결과가 없습니다. 다른 키워드(영어 추천)로 다시 시도해 보세요."
            else:
                # LLM에게 보낼 메시지 구성 (검색 결과 + 사용자 질문)
                full_prompt = f"""
                사용자가 '{prompt}'에 대한 논문을 찾고 있습니다.
                아래 검색된 논문 데이터를 바탕으로 시스템 프롬프트의 형식에 맞춰 답변해주세요.
                
                [검색된 논문 데이터]
                {search_context}
                """
                
                # 대화 내역 복사 (시스템 메시지 포함)
                messages_for_api = [
                    {"role": m["role"], "content": m["content"]}
                    for m in st.session_state.messages
                ]
                
                # 마지막 메시지는 검색 데이터가 포함된 프롬프트로 교체 (실제 API 전송용)
                # 주의: session_state에는 원본 질문만 저장하고, API에는 데이터를 섞어 보냅니다.
                messages_for_api.append({"role": "user", "content": full_prompt})

                # API 호출
                response = client.chat.completions.create(
                    model="gpt-4o-mini", # 배포명(Deployment Name) 확인 필수!
                    messages=messages_for_api
                )
                assistant_reply = response.choices[0].message.content

            # (3) AI 응답 화면 표시
            with st.chat_message("assistant"):
                st.markdown(assistant_reply)

            # (4) 대화 기록 저장
            st.session_state.messages.append({"role": "assistant", "content": assistant_reply})
            
        except Exception as e:
            st.error(f"오류가 발생했습니다: {str(e)}")
