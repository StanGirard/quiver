import operator
from enum import Enum
from typing import Annotated, Any, Dict, List, Literal, TypedDict

from langchain.chains.combine_documents.reduce import (
    acollapse_docs,
    split_list_of_docs,
)
from langchain_core.documents import Document
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langgraph.constants import Send
from langgraph.graph import END, START, StateGraph

from quivr_core.llm_tools.entity import ToolRegistry, ToolsCategory, ToolWrapper

# This code is Widely inspired by https://python.langchain.com/docs/tutorials/summarization/

default_map_prompt = "Write a concise summary of the following:\\n\\n{context}"

default_reduce_prompt = """
The following is a set of summaries:
{docs}
Take these and distill it into a final, consolidated summary
of the main themes.
"""


class SummaryToolsList(str, Enum):
    MAPREDUCE = "map_reduce"


# This will be the overall state of the main graph.
# It will contain the input document contents, corresponding
# summaries, and a final summary.
class OverallState(TypedDict):
    # Notice here we use the operator.add
    # This is because we want combine all the summaries we generate
    # from individual nodes back into one list - this is essentially
    # the "reduce" part
    contents: List[str]
    summaries: Annotated[list, operator.add]
    collapsed_summaries: List[Document]
    final_summary: str


# This will be the state of the node that we will "map" all
# documents to in order to generate summaries
class SummaryState(TypedDict):
    content: str


class MPSummarizeTool:
    def __init__(
        self,
        llm: BaseChatModel,
        token_max: int = 8000,
        map_prompt: str = default_map_prompt,
        reduce_prompt: str = default_reduce_prompt,
    ):
        self.map_prompt = ChatPromptTemplate.from_messages([("system", map_prompt)])
        self.reduce_prompt = ChatPromptTemplate([("human", reduce_prompt)])
        self.llm = llm
        self.token_max = token_max

    def length_function(self, documents: List[Document]) -> int:
        """Get number of tokens for input contents."""
        return sum(self.llm.get_num_tokens(doc.page_content) for doc in documents)

    # Here we generate a summary, given a document
    async def generate_summary(self, state: SummaryState):
        prompt = self.map_prompt.invoke(state["content"])
        response = await self.llm.ainvoke(prompt)
        return {"summaries": [response.content]}

    # Here we define the logic to map out over the documents
    # We will use this an edge in the graph
    def map_summaries(self, state: OverallState):
        # We will return a list of `Send` objects
        # Each `Send` object consists of the name of a node in the graph
        # as well as the state to send to that node
        return [
            Send("generate_summary", {"content": content})
            for content in state["contents"]
        ]

    def collect_summaries(self, state: OverallState):
        return {
            "collapsed_summaries": [Document(summary) for summary in state["summaries"]]
        }

    async def _reduce(self, input: list) -> str:
        prompt = self.reduce_prompt.invoke(input)
        response = await self.llm.ainvoke(prompt)
        return response.content

    # Add node to collapse summaries
    async def collapse_summaries(self, state: OverallState):
        doc_lists = split_list_of_docs(
            state["collapsed_summaries"], self.length_function, self.token_max
        )
        results = []
        for doc_list in doc_lists:
            results.append(await acollapse_docs(doc_list, self._reduce))

        return {"collapsed_summaries": results}

    # This represents a conditional edge in the graph that determines
    # if we should collapse the summaries or not
    def should_collapse(
        self,
        state: OverallState,
    ) -> Literal["collapse_summaries", "generate_final_summary"]:
        num_tokens = self.length_function(state["collapsed_summaries"])
        if num_tokens > self.token_max:
            return "collapse_summaries"
        else:
            return "generate_final_summary"

    # Here we will generate the final summary
    async def generate_final_summary(self, state: OverallState):
        response = await self._reduce(state["collapsed_summaries"])
        return {"final_summary": response}

    def build(self):
        summary_graph = StateGraph(OverallState)

        summary_graph.add_node(
            "generate_summary", self.generate_summary
        )  # same as before
        summary_graph.add_node("collect_summaries", self.collect_summaries)
        summary_graph.add_node("collapse_summaries", self.collapse_summaries)
        summary_graph.add_node("generate_final_summary", self.generate_final_summary)

        # Edges:
        summary_graph.add_conditional_edges(
            START, self.map_summaries, ["generate_summary"]
        )
        summary_graph.add_edge("generate_summary", "collect_summaries")
        summary_graph.add_conditional_edges("collect_summaries", self.should_collapse)
        summary_graph.add_conditional_edges("collapse_summaries", self.should_collapse)
        summary_graph.add_edge("generate_final_summary", END)

        return summary_graph.compile()


def create_summary_tool(config: Dict[str, Any]):
    summary_tool = MPSummarizeTool(
        config.get("map_prompt", None),
        config.get("reduce_prompt", None),
        config.get("llm", None),
        config.get("token_max", None),
    )

    def format_input(task: str) -> Dict[str, Any]:
        return {"query": task}

    def format_output(response: Any) -> List[Document]:
        return [
            Document(
                page_content=d["content"],
            )
            for d in response
        ]

    return ToolWrapper(summary_tool, format_input, format_output)


# Initialize the registry and register tools
summarization_tool_registry = ToolRegistry()
summarization_tool_registry.register_tool(
    SummaryToolsList.MAPREDUCE, create_summary_tool
)


def create_summarization_tool(tool_name: str, config: Dict[str, Any]) -> ToolWrapper:
    return summarization_tool_registry.create_tool(tool_name, config)


SummarizationTools = ToolsCategory(
    name="Summarization",
    description="Tools for summarizing documents",
    tools=[SummaryToolsList.MAPREDUCE],
    default_tool=SummaryToolsList.MAPREDUCE,
    create_tool=create_summarization_tool,
)
