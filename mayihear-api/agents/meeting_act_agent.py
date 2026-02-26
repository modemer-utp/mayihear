from datetime import date

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, START, END

from agents.states.meeting_act_state import MeetingActState, MeetingActOutputState
from agents.utilities import config, model_init, helper
from application.utilities.pricing import compute_cost
from domain.models.output.meeting_act_result import MeetingActResult
from domain.models.output.token_usage import TokenUsage


class _UsageCallback(BaseCallbackHandler):
    """Captures token usage from the LLM response via callback."""

    def __init__(self):
        self.input_tokens = 0
        self.output_tokens = 0

    def on_llm_end(self, response: LLMResult, **kwargs):
        for generations in response.generations:
            for gen in generations:
                msg = getattr(gen, "message", None)
                meta = getattr(msg, "usage_metadata", None) if msg else None
                if meta:
                    self.input_tokens = meta.get("input_tokens", 0)
                    self.output_tokens = meta.get("output_tokens", 0)


class MeetingActAgent:

    def __init__(self):
        self.model, self.model_name = model_init.model_inicialization(
            config.MEETING_ACT_SELECTED_MODEL,
            config.MEETING_ACT_TEMPERATURE,
            config.MEETING_ACT_MAX_TOKENS
        )
        self.chain_inicialization()
        self.graph_inicialization()

    def chain_inicialization(self):
        prompt_content = helper.read_prompt_file("generate_meeting_act.prompt")
        system_prompt, human_prompt = prompt_content.split(config.PROMPT_DIVISOR)

        template = ChatPromptTemplate.from_messages([
            ("system", system_prompt.strip()),
            ("human", human_prompt.strip())
        ])

        self.chain = template | self.model.with_structured_output(MeetingActResult)

    def graph_inicialization(self):
        builder = StateGraph(MeetingActState, output=MeetingActOutputState)
        builder.add_node("generate_meeting_act", self._generate_meeting_act_node)
        builder.add_edge(START, "generate_meeting_act")
        builder.add_edge("generate_meeting_act", END)
        self.graph = builder.compile()

    def _generate_meeting_act_node(self, state: MeetingActState) -> dict:
        usage_cb = _UsageCallback()
        result: MeetingActResult = self.chain.invoke(
            {
                "user_context": state["user_context"] or "No se proporcionó contexto adicional.",
                "transcript": state["transcript"],
                "today_date": state["today_date"]
            },
            config={"callbacks": [usage_cb]}
        )

        if result is None:
            raise ValueError(
                "El modelo no pudo generar el acta estructurada. "
                "La transcripción puede ser demasiado corta o el modelo no devolvió JSON válido."
            )

        usage = TokenUsage(
            model=self.model_name,
            input_tokens=usage_cb.input_tokens,
            output_tokens=usage_cb.output_tokens,
            total_tokens=usage_cb.input_tokens + usage_cb.output_tokens,
            estimated_cost_usd=compute_cost(
                self.model_name,
                usage_cb.input_tokens,
                usage_cb.output_tokens,
                audio_input=False
            )
        )

        return {"meeting_act_result": result.model_copy(update={"usage": usage})}

    def invoke(self, transcript: str, user_context: str) -> MeetingActResult:
        today = date.today().strftime("%d/%m/%Y")
        state = MeetingActState(
            transcript=transcript,
            user_context=user_context,
            today_date=today
        )
        output = self.graph.invoke(state)
        return output["meeting_act_result"]
