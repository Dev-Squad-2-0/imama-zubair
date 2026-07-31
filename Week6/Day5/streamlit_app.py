"""
streamlit_app.py

Week 6 Day 5, Task 3 (optional): a minimal chat UI for the AFL assistant,
so it's demoable instead of only callable via curl.

Run with:
    streamlit run streamlit_app.py

Needs afl_langgraph_agent.py, predict.py, afl_chat_agent.py, the models/
folder, and the two feature CSVs in the same directory (same as the API).
"""

import streamlit as st
import afl_langgraph_agent as ag

st.set_page_config(page_title="AFL Assistant", page_icon="assets/icons8-afl-48.png")



st.title("AFL Assistant")
st.caption("Hi there! Ask about AFL teams, players, matches, and stats. I can also make predictions about upcoming matches! :D")

if "conversation_id" not in st.session_state:
    import uuid
    st.session_state.conversation_id = str(uuid.uuid4())

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

user_input = st.chat_input("Ask an AFL question... :3")

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        with st.spinner("Bouncing the ball..."):
            out = ag.run_turn(user_input, thread_id=st.session_state.conversation_id)

        st.write("Goal! Here is your answer:")

        st.markdown(out["final_response"])
        with st.expander("Debug info"):
            st.write("Intent:", out.get("intent"))
            st.write("Latency (ms):", out.get("latency_ms"))
            st.write("Tools called:", out.get("tools_called"))
            st.write("Token usage:", out.get("token_usage"))
            if out.get("tool_result"):
                st.json(out["tool_result"])

    st.session_state.messages.append({"role": "assistant", "content": out["final_response"]})
