"""
afl_chat_agent.py

LangChain/LangGraph AFL chat agent.

Provides:
- AFL-only system prompt
- Structured retrieval tools
- Conversation memory
- Scope guardrails
- Ready-to-use agent

Import this with:

    from afl_chat_agent import agent
"""

import joblib
import pandas as pd

from langchain_core.tools import tool
from langchain_core.messages import SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

# ------------------------------------------------------------------
# LOAD DATA
# ------------------------------------------------------------------

player = pd.read_csv("player_match_features_v1_2026-07-27.csv")
team = pd.read_csv("team_match_features_v1_2026-07-27.csv")

player["match_date"] = pd.to_datetime(player["match_date"])
team["match_date"] = pd.to_datetime(team["match_date"])



#-------------------------------------------------------------------
#LLM
#-------------------------------------------------------------------

MODEL = "smart"

from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model=MODEL,
    base_url=os.environ["BASE_URL"],
    api_key=os.environ["API_KEY"],
)

# ------------------------------------------------------------------
# SYSTEM PROMPT
# ------------------------------------------------------------------

SYSTEM_PROMPT = """
You are an AFL (Australian Football League) assistant.

You only answer questions about:
- AFL teams
- AFL players
- AFL matches
- AFL statistics
- AFL history
- AFL rules

Never answer questions about other sports, general trivia,
coding, recipes, weather, politics or unrelated topics.

Never invent statistics.
Always use the provided tools whenever a user asks for numbers.

If the information cannot be found, clearly say so instead of guessing.

Politely refuse off-topic requests and redirect the conversation back to AFL.
"""

# ------------------------------------------------------------------
# TOOLS
# ------------------------------------------------------------------

@tool
def get_player_recent_stats(player_name: str):
    """Returns a player's latest rolling AFL statistics."""

    rows = player[
        player["player_name"].str.lower() == player_name.lower()
    ].sort_values("match_date")

    if rows.empty:
        return f"No player named '{player_name}' found."

    r = rows.iloc[-1]

    return {
        "player_name": r["player_name"],
        "team": r["team"],
        "match_date": str(r["match_date"].date()),
        "avg_disposals_last5": r["avg_disposals_last5"],
        "avg_goals_last5": r["avg_goals_last5"],
        "avg_fantasy_last5": r["avg_fantasy_last5"],
    }


@tool
def get_head_to_head(team_a: str, team_b: str):
    """Returns the historical head-to-head record between two AFL teams."""

    games = team[
        (
            (team["team_name"] == team_a)
            & (team["opponent"] == team_b)
        )
    ]

    if games.empty:
        return f"No matches found between {team_a} and {team_b}."

    wins = (games["result"] == "W").sum()
    losses = (games["result"] == "L").sum()
    draws = (games["result"] == "D").sum()

    return {
        "team": team_a,
        "opponent": team_b,
        "matches": len(games),
        "wins": int(wins),
        "losses": int(losses),
        "draws": int(draws),
    }

tools = [
    get_player_recent_stats,
    get_head_to_head,
]

# ------------------------------------------------------------------
# MEMORY
# ------------------------------------------------------------------

memory = MemorySaver()

# ------------------------------------------------------------------
# AGENT
# ------------------------------------------------------------------

agent = create_react_agent(
    model=llm,
    tools=tools,
    checkpointer=memory,
)

# ------------------------------------------------------------------
# HELPER FUNCTION
# ------------------------------------------------------------------

config = {
    "configurable": {
        "thread_id": "afl-chat"
    }
}


def chat(message: str):
    """
    Send one message to the AFL agent.
    """

    response = agent.invoke(
        {
            "messages": [
                SystemMessage(content=SYSTEM_PROMPT),
                {
                    "role": "user",
                    "content": message,
                },
            ]
        },
        config=config,
    )

    return response["messages"][-1].content