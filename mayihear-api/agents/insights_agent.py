from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, START, END

from agents.states.insights_state import InsightsState, InsightsOutputState
from agents.utilities import config, model_init, helper
from domain.models.output.insights_result import InsightsResult


class InsightsAgent:

    def __init__(self):
        self.model, self.model_name = model_init.model_inicialization(
            config.INSIGHTS_SELECTED_MODEL,
            config.INSIGHTS_TEMPERATURE,
            config.INSIGHTS_MAX_TOKENS
        )
        self.chain_inicialization()
        self.graph_inicialization()

    def chain_inicialization(self):
        prompt_content = helper.read_prompt_file("generate_insights.prompt")
        system_prompt, human_prompt = prompt_content.split(config.PROMPT_DIVISOR)

        template = ChatPromptTemplate.from_messages([
            ("system", system_prompt.strip()),
            ("human", human_prompt.strip())
        ])

        self.chain = template | self.model.with_structured_output(InsightsResult)

    def graph_inicialization(self):
        builder = StateGraph(InsightsState, output=InsightsOutputState)
        builder.add_node("generate_insights", self._generate_insights_node)
        builder.add_edge(START, "generate_insights")
        builder.add_edge("generate_insights", END)
        self.graph = builder.compile()

    def _generate_insights_node(self, state: InsightsState) -> dict:
        result = self.chain.invoke({
            "user_context": state["user_context"] or "No specific context provided.",
            "transcript": state["transcript"]
        })
        return {"insights_result": result}

    def invoke(self, transcript: str, user_context: str) -> InsightsResult:
        state = InsightsState(transcript=transcript, user_context=user_context)
        output = self.graph.invoke(state)
        return output["insights_result"]
