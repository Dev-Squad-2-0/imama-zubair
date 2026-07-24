"""
CrewAI proposal team, reusing the role-design pattern from Day 4
(Researcher / Analyst / Communicator -> here: Research Agent / Solution
Architect / Proposal Writer). Runs as Process.sequential, called as one
node inside the LangGraph workflow in graph.py.
"""
import os
from crewai import Agent, Task, Crew, Process, LLM
from tools import company_lookup, service_lookup, calculator

MODEL = "coder"

llm = LLM(
    model=MODEL,
    api_key=os.getenv("API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL")
)

# print(llm.call("Say hello"))

def build_agents():
    research_agent = Agent(
        role="Client Research Agent",
        goal="Gather everything relevant about the prospective client — industry, size, "
             "known history with Web3Geeks, and their stated project needs.",
        backstory=(
            "You are a business development researcher at Web3Geeks. You pull whatever "
            "background exists on a lead before anyone writes a word of proposal. You "
            "report facts only, you don't recommend services or write persuasive copy."
        ),
        tools=[company_lookup],
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )

    solution_architect = Agent(
        role="Solution Architect",
        goal="Match the client's needs to the right Web3Geeks services and build a "
             "costed, timeline-aware solution outline.",
        backstory=(
            "You are a solutions architect who has scoped dozens of Web3 engagements. "
            "You think in services, timelines, and budgets — you don't write customer-facing "
            "prose, you produce a structured plan the writer can turn into a proposal."
        ),
        tools=[service_lookup, calculator],
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )

    proposal_writer = Agent(
        role="Proposal Writer",
        goal="Turn the architect's solution outline into a polished, client-ready proposal document.",
        backstory=(
            "You are a proposal writer who turns technical scoping into something a "
            "non-technical founder or CTO will actually want to read and sign. You never "
            "invent services or prices that weren't in the architect's outline."
        ),
        tools=[],
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )

    return research_agent, solution_architect, proposal_writer


def build_crew(company_name: str, project_description: str, budget_range_usd: str, timeline_weeks: int):
    research_agent, solution_architect, proposal_writer = build_agents()

    research_task = Task(
        description=(
            f"The lead is '{company_name}'. Their stated project: '{project_description}'. "
            f"Use the Company Lookup tool to check if we have prior CRM history on them. "
            "Summarize what's known: industry, company size, any prior relationship with "
            "Web3Geeks, and restate their project need in your own words. If the lookup "
            "returns 'not found', explicitly say this is a new lead and rely on the project "
            "description alone."
        ),
        expected_output=(
            "A short brief (5-8 sentences) covering: company background (or 'new lead' if unknown), "
            "and a plain restatement of what they're asking for."
        ),
        agent=research_agent,
    )

    architecture_task = Task(
        description=(
            f"Budget range: {budget_range_usd}. Desired timeline: {timeline_weeks} weeks. "
            "Using the research brief, call Service Catalog Lookup with query='all' to see every "
            "available service, then select 1-3 services that best match the client's need and "
            "industry. Use the Calculator tool to sum the total price of your selected services "
            "and to check the total against the client's budget range. Also sum the duration_weeks "
            "of selected services to compare against the client's desired timeline."
        ),
        expected_output=(
            "A markdown table with columns: service_name, price_usd, duration_weeks, reason. "
            "Followed by two lines: 'Total price: $X' and 'Total duration: Y weeks', and one line "
            "flagging whether the total fits the stated budget and timeline (yes/no + why)."
        ),
        agent=solution_architect,
        context=[research_task],
    )

    writing_task = Task(
        description=(
            f"Write a client-ready proposal for {company_name} based on the architect's solution "
            "table. Structure: greeting, 1-paragraph understanding of their need, a services section "
            "(service name, what it delivers, price) mirroring the architect's numbers exactly, a total "
            "investment line, an estimated timeline line, and a closing call-to-action. Do not invent "
            "services or prices not present in the architect's table."
        ),
        expected_output=(
            "A complete proposal document in markdown with these exact section headers: "
            "'## Understanding your needs', '## Proposed services', '## Investment & timeline', "
            "'## Next steps'. Under Proposed services, list each service as a bullet with its price."
        ),
        agent=proposal_writer,
        context=[architecture_task],
    )

    crew = Crew(
        agents=[research_agent, solution_architect, proposal_writer],
        tasks=[research_task, architecture_task, writing_task],
        process=Process.sequential,
        verbose=True,
    )
    return crew


def run_proposal_crew(company_name: str, project_description: str, budget_range_usd: str, timeline_weeks: int):
    """Runs the crew and returns (proposal_text, token_usage_dict)."""
    crew = build_crew(company_name, project_description, budget_range_usd, timeline_weeks)
    result = crew.kickoff()
    usage = result.token_usage
    usage_dict = {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
        "successful_requests": usage.successful_requests,
    }
    return str(result), usage_dict
