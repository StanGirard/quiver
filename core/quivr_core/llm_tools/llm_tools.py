from typing import Any, Dict, Type, Union

from quivr_core.llm_tools.entity import ToolWrapper
from quivr_core.llm_tools.other_tools import (
    OtherTools,
)
from quivr_core.llm_tools.summarization_tool import (
    SummarizationTools,
)
from quivr_core.llm_tools.web_search_tools import (
    WebSearchTools,
)

TOOLS_CATEGORIES = {
    WebSearchTools.name: WebSearchTools,
    SummarizationTools.name: SummarizationTools,
    OtherTools.name: OtherTools,
}

# Register all ToolsList enums
TOOLS_LISTS = {
    **{tool.value: tool for tool in WebSearchTools.tools},
    **{tool.value: tool for tool in SummarizationTools.tools},
    **{tool.value: tool for tool in OtherTools.tools},
}


class LLMToolFactory:
    @staticmethod
    def create_tool(tool_name: str, config: Dict[str, Any]) -> Union[ToolWrapper, Type]:
        for category, tools_class in TOOLS_CATEGORIES.items():
            if tool_name in tools_class.tools:
                return tools_class.create_tool(tool_name, config)
            elif tool_name.lower() == category and tools_class.default_tool:
                return tools_class.create_tool(tools_class.default_tool, config)
        raise ValueError(f"Tool {tool_name} is not supported.")
