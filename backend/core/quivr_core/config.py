import os
from enum import Enum
from typing import Dict, List, Optional

import yaml
from megaparse.config import MegaparseConfig

from quivr_core.base_config import QuivrBaseConfig
from quivr_core.processor.splitter import SplitterConfig


class DefaultRerankers(str, Enum):
    COHERE = "cohere"
    JINA = "jina"

    @property
    def default_model(self) -> str:
        # Mapping of suppliers to their default models
        return {
            self.COHERE: "rerank-multilingual-v3.0",
            self.JINA: "jina-reranker-v2-base-multilingual",
        }[self]


class DefaultLLMs(str, Enum):
    OPENAI = "openai"
    AZURE = "azure"
    ANTHROPIC = "anthropic"
    META = "meta"
    MISTRAL = "mistral"


class LLMConfig(QuivrBaseConfig):
    context: int | None = None
    tokenizer_hub: str | None = None


class LLMModelConfig:
    _model_defaults: Dict[DefaultLLMs, Dict[str, LLMConfig]] = {
        DefaultLLMs.OPENAI: {
            "gpt-4o": LLMConfig(context=128000, tokenizer_hub="Xenova/gpt-4o"),
            "gpt-4o-mini": LLMConfig(context=128000, tokenizer_hub="Xenova/gpt-4o"),
            "gpt-4-turbo": LLMConfig(context=128000, tokenizer_hub="Xenova/gpt-4"),
            "gpt-4": LLMConfig(context=8192, tokenizer_hub="Xenova/gpt-4"),
            "gpt-3.5-turbo": LLMConfig(
                context=16385, tokenizer_hub="Xenova/gpt-3.5-turbo"
            ),
            "text-embedding-3-large": LLMConfig(
                context=8191, tokenizer_hub="Xenova/text-embedding-ada-002"
            ),
            "text-embedding-3-small": LLMConfig(
                context=8191, tokenizer_hub="Xenova/text-embedding-ada-002"
            ),
            "text-embedding-ada-002": LLMConfig(
                context=8191, tokenizer_hub="Xenova/text-embedding-ada-002"
            ),
        },
        DefaultLLMs.ANTHROPIC: {
            "claude-3.5-sonnet": LLMConfig(
                context=200000, tokenizer_hub="Xenova/claude-tokenizer"
            ),
            "claude-3-opus": LLMConfig(
                context=200000, tokenizer_hub="Xenova/claude-tokenizer"
            ),
            "claude-3-sonnet": LLMConfig(
                context=200000, tokenizer_hub="Xenova/claude-tokenizer"
            ),
            "claude-3-haiku": LLMConfig(
                context=200000, tokenizer_hub="Xenova/claude-tokenizer"
            ),
            "claude-2.1": LLMConfig(
                context=200000, tokenizer_hub="Xenova/claude-tokenizer"
            ),
            "claude-2.0": LLMConfig(
                context=100000, tokenizer_hub="Xenova/claude-tokenizer"
            ),
            "claude-instant-1.2": LLMConfig(
                context=100000, tokenizer_hub="Xenova/claude-tokenizer"
            ),
        },
        DefaultLLMs.META: {
            "llama-3.1": LLMConfig(
                context=128000, tokenizer_hub="Xenova/Meta-Llama-3.1-Tokenizer"
            ),
            "llama-3": LLMConfig(
                context=8192, tokenizer_hub="Xenova/llama3-tokenizer-new"
            ),
            "llama-2": LLMConfig(context=4096, tokenizer_hub="Xenova/llama2-tokenizer"),
            "code-llama": LLMConfig(
                context=16384, tokenizer_hub="Xenova/llama-code-tokenizer"
            ),
        },
        DefaultLLMs.MISTRAL: {
            "mistral-large": LLMConfig(
                context=128000, tokenizer_hub="Xenova/mistral-tokenizer-v3"
            ),
            "mistral-nemo": LLMConfig(
                context=128000, tokenizer_hub="Xenova/Mistral-Nemo-Instruct-Tokenizer"
            ),
            "codestral": LLMConfig(
                context=32000, tokenizer_hub="Xenova/mistral-tokenizer-v3"
            ),
        },
    }

    @classmethod
    def get_model_config(
        cls, supplier: DefaultLLMs, model_name: str
    ) -> Optional[LLMConfig]:
        """Retrieve the LLMConfig (context and tokenizer_hub) for a given supplier and model."""
        supplier_defaults = cls._model_defaults.get(supplier)
        if not supplier_defaults:
            return None

        # Use startswith logic for matching model names
        for key, config in supplier_defaults.items():
            if model_name.startswith(key):
                return config

        return None


class LLMEndpointConfig(QuivrBaseConfig):
    supplier: DefaultLLMs = DefaultLLMs.OPENAI
    model: str = "gpt-3.5-turbo-0125"
    context_length: int | None = None
    tokenizer_hub: str | None = None
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    max_input_tokens: int = 2000
    max_output_tokens: int = 2000
    temperature: float = 0.7
    streaming: bool = True

    def __init__(self, **data):
        super().__init__(**data)
        # Automatically set context_length and tokenizer_hub based on the supplier and model
        model_config = LLMModelConfig.get_model_config(self.supplier, self.model)
        if model_config:
            self.context_length = model_config.context
            self.tokenizer_hub = model_config.tokenizer_hub


# Cannot use Pydantic v2 field_validator because of conflicts with pydantic v1 still in use in LangChain
class RerankerConfig(QuivrBaseConfig):
    supplier: DefaultRerankers | None = None
    model: str | None = None
    top_n: int = 5
    api_key: str | None = None

    def __init__(self, **data):
        super().__init__(**data)  # Call Pydantic's BaseModel init
        self.validate_model()  # Automatically call external validation

    def validate_model(self):
        # If model is not provided, get default model based on supplier
        if self.model is None and self.supplier is not None:
            self.model = self.supplier.default_model

        # Check if the corresponding API key environment variable is set
        if self.supplier:
            api_key_var = f"{self.supplier.upper()}_API_KEY"
            self.api_key = os.getenv(api_key_var)

            if self.api_key is None:
                raise ValueError(
                    f"The API key for supplier '{self.supplier}' is not set. "
                    f"Please set the environment variable: {api_key_var}"
                )


class RetrievalConfig(QuivrBaseConfig):
    reranker_config: RerankerConfig = RerankerConfig()
    llm_config: LLMEndpointConfig = LLMEndpointConfig()
    max_history: int = 10
    max_files: int = 20
    prompt: str | None = None


class ParserConfig(QuivrBaseConfig):
    splitter_config: SplitterConfig = SplitterConfig()
    megaparse_config: MegaparseConfig = MegaparseConfig()


class IngestionConfig(QuivrBaseConfig):
    parser_config: ParserConfig = ParserConfig()


class NodeConfig(QuivrBaseConfig):
    name: str
    config: QuivrBaseConfig  # This can be any config like RerankerConfig or LLMEndpointConfig
    links: List[str]  # List of names of other nodes this node links to


class AssistantConfig(QuivrBaseConfig):
    retrieval_config: RetrievalConfig = RetrievalConfig()
    ingestion_config: IngestionConfig = IngestionConfig()


class WorkflowConfig(QuivrBaseConfig):
    nodes: Dict[str, NodeConfig]

    @classmethod
    def from_yaml(cls, file_path: str):
        with open(file_path, "r") as stream:
            config_data = yaml.safe_load(stream)

        # Parsing the nodes from YAML
        nodes_data = config_data.pop("nodes")
        nodes = {node["name"]: NodeConfig(**node) for node in nodes_data}

        return cls(nodes=nodes, **config_data)
