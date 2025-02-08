import asyncio
import logging
from collections import OrderedDict
from typing import (
    Annotated,
    Any,
    AsyncGenerator,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
    Type,
    TypedDict,
)
from uuid import UUID, uuid4

import openai
from langchain.retrievers import ContextualCompressionRetriever
from langchain_cohere import CohereRerank
from langchain_community.document_compressors import JinaRerank
from langchain_core.callbacks import Callbacks
from langchain_core.documents import BaseDocumentCompressor, Document
from langchain_core.messages import BaseMessage
from langchain_core.messages.ai import AIMessageChunk
from langchain_core.prompts.base import BasePromptTemplate
from langchain_core.vectorstores import VectorStore
from langfuse.callback import CallbackHandler
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Send
from pydantic import BaseModel, Field

from quivr_core.llm import LLMEndpoint
from quivr_core.llm_tools.llm_tools import LLMToolFactory
from quivr_core.rag.entities.chat import ChatHistory
from quivr_core.rag.entities.config import DefaultRerankers, NodeConfig, RetrievalConfig
from quivr_core.rag.entities.models import (
    ParsedRAGChunkResponse,
    QuivrKnowledge,
    RAGResponseMetadata,
)
from quivr_core.rag.prompts import custom_prompts
from quivr_core.rag.utils import (
    LangfuseService,
    collect_tools,
    combine_documents,
    format_file_list,
    get_chunk_metadata,
    parse_chunk_response,
)

logger = logging.getLogger("quivr_core")

langfuse_service = LangfuseService()
langfuse_handler = langfuse_service.get_handler()


class SplittedInput(BaseModel):
    instructions_reasoning: Optional[str] = Field(
        default=None,
        description="The reasoning that leads to identifying the user instructions to the system",
    )
    instructions: Optional[str] = Field(
        default=None, description="The instructions to the system"
    )

    tasks_reasoning: Optional[str] = Field(
        default=None,
        description="The reasoning that leads to identifying the explicit or implicit user tasks and questions",
    )
    task_list: Optional[List[str]] = Field(
        default_factory=lambda: ["No explicit or implicit tasks found"],
        description="The list of standalone, self-contained tasks or questions.",
    )


class TasksCompletion(BaseModel):
    is_task_completable_reasoning: Optional[str] = Field(
        default=None,
        description="The reasoning that leads to identifying whether the user task or question can be completed using the provided context and chat history BEFORE any tool is used.",
    )

    is_task_completable: bool = Field(
        description="Whether the user task or question can be completed using the provided context and chat history BEFORE any tool is used.",
    )

    tool_reasoning: Optional[str] = Field(
        default=None,
        description="The reasoning that leads to identifying the tool that shall be used to complete the task.",
    )
    tool: Optional[str] = Field(
        description="The tool that shall be used to complete the task.",
    )


class FinalAnswer(BaseModel):
    reasoning_answer: str = Field(
        description="The step-by-step reasoning that led to the final answer"
    )
    answer: str = Field(description="The final answer to the user tasks/questions")

    all_tasks_completed: bool = Field(
        description="Whether all tasks/questions have been successfully answered/completed or not. "
        " If the final answer to the user is 'I don't know' or 'I don't have enough information' or 'I'm not sure', "
        " this variable should be 'false'"
    )


class UpdatedPromptAndTools(BaseModel):
    prompt_reasoning: Optional[str] = Field(
        default=None,
        description="The step-by-step reasoning that leads to the updated system prompt",
    )
    prompt: Optional[str] = Field(default=None, description="The updated system prompt")

    tools_reasoning: Optional[str] = Field(
        default=None,
        description="The reasoning that leads to activating and deactivating the tools",
    )
    tools_to_activate: Optional[List[str]] = Field(
        default_factory=list, description="The list of tools to activate"
    )
    tools_to_deactivate: Optional[List[str]] = Field(
        default_factory=list, description="The list of tools to deactivate"
    )


class UserTaskEntity(BaseModel):
    id: UUID
    definition: str
    docs: List[Document] = Field(default_factory=list)
    completable: bool = Field(
        default=False, description="Whether the task has been completed or not"
    )
    tool: Optional[str] = Field(
        default=None, description="The tool that shall be used to complete the task"
    )

    def has_tool(self) -> bool:
        return bool(self.tool)

    def is_completable(self) -> bool:
        return self.completable


class UserTasks:
    def __init__(self, task_definitions: List[str] | None = None):
        self.user_tasks = {}
        if task_definitions:
            for definition in task_definitions:
                id = uuid4()
                self.user_tasks[id] = UserTaskEntity(
                    id=id, definition=definition, docs=[]
                )

    def __iter__(self):
        return iter(self.user_tasks.values())

    def set_docs(self, id: UUID, docs: List[Document]):
        if self.user_tasks:
            if id in self.user_tasks:
                self.user_tasks[id].docs = docs
            else:
                raise ValueError(f"Task with id {id} not found")

    def set_definition(self, id: UUID, definition: str):
        if self.user_tasks:
            if id in self.user_tasks:
                self.user_tasks[id].definition = definition
            else:
                raise ValueError(f"Task with id {id} not found")

    def set_completion(self, id: UUID, completable: bool):
        if self.user_tasks:
            if id in self.user_tasks:
                self.user_tasks[id].completable = completable
            else:
                raise ValueError(f"Task with id {id} not found")

    def set_tool(self, id: UUID, tool: str):
        if self.user_tasks:
            if id in self.user_tasks:
                self.user_tasks[id].tool = tool
            else:
                raise ValueError(f"Task with id {id} not found")

    def __call__(self, id: UUID) -> UserTaskEntity:
        return self.user_tasks[id]

    def has_tasks(self) -> bool:
        return bool(self.user_tasks)

    def has_non_completable_tasks(self) -> bool:
        return bool(self.non_completable_tasks)

    @property
    def non_completable_tasks(self) -> List[UserTaskEntity]:
        return [task for task in self.user_tasks.values() if not task.is_completable()]

    @property
    def completable_tasks(self) -> List[UserTaskEntity]:
        return [task for task in self.user_tasks.values() if task.is_completable()]

    @property
    def ids(self) -> List[UUID]:
        return list(self.user_tasks.keys())

    @property
    def definitions(self) -> List[str]:
        return [task.definition for task in self.user_tasks.values()]

    @property
    def docs(self) -> List[Document]:
        # Return the concatenation of all docs
        return [doc for task in self.user_tasks.values() for doc in task.docs]


class AgentState(TypedDict):
    # The add_messages function defines how an update should be processed
    # Default is to replace. add_messages says "append"
    messages: Annotated[Sequence[BaseMessage], add_messages]
    reasoning: List[str]
    chat_history: ChatHistory
    files: str
    tasks: UserTasks
    instructions: str
    tool: str


class IdempotentCompressor(BaseDocumentCompressor):
    def compress_documents(
        self,
        documents: Sequence[Document],
        query: str,
        callbacks: Optional[Callbacks] = None,
    ) -> Sequence[Document]:
        """
        A no-op document compressor that simply returns the documents it is given.

        This is a placeholder until a more sophisticated document compression
        algorithm is implemented.
        """
        return documents


class QuivrQARAGLangGraph:
    def __init__(
        self,
        *,
        retrieval_config: RetrievalConfig,
        llm: LLMEndpoint,
        vector_store: VectorStore | None = None,
    ):
        """
        Construct a QuivrQARAGLangGraph object.

        Args:
            retrieval_config (RetrievalConfig): The configuration for the RAG model.
            llm (LLMEndpoint): The LLM to use for generating text.
            vector_store (VectorStore): The vector store to use for storing and retrieving documents.
            reranker (BaseDocumentCompressor | None): The document compressor to use for re-ranking documents. Defaults to IdempotentCompressor if not provided.
        """
        self.retrieval_config = retrieval_config
        self.vector_store = vector_store
        self.llm_endpoint = llm

        self.graph = None

    def get_reranker(self, **kwargs):
        # Extract the reranker configuration from self
        config = self.retrieval_config.reranker_config

        # Allow kwargs to override specific config values
        supplier = kwargs.pop("supplier", config.supplier)
        model = kwargs.pop("model", config.model)
        top_n = kwargs.pop("top_n", config.top_n)
        api_key = kwargs.pop("api_key", config.api_key)

        if supplier == DefaultRerankers.COHERE:
            reranker = CohereRerank(
                model=model, top_n=top_n, cohere_api_key=api_key, **kwargs
            )
        elif supplier == DefaultRerankers.JINA:
            reranker = JinaRerank(
                model=model, top_n=top_n, jina_api_key=api_key, **kwargs
            )
        else:
            reranker = IdempotentCompressor()

        return reranker

    def get_retriever(self, **kwargs):
        """
        Returns a retriever that can retrieve documents from the vector store.

        Returns:
            VectorStoreRetriever: The retriever.
        """
        if self.vector_store:
            retriever = self.vector_store.as_retriever(**kwargs)
        else:
            raise ValueError("No vector store provided")

        return retriever

    def routing(self, state: AgentState) -> List[Send]:
        """
        The routing function for the RAG model.

        Args:
            state (AgentState): The current state of the agent.

        Returns:
            dict: The next state of the agent.
        """

        msg = custom_prompts.SPLIT_PROMPT.format(
            user_input=state["messages"][0].content,
        )

        response: SplittedInput

        try:
            structured_llm = self.llm_endpoint._llm.with_structured_output(
                SplittedInput, method="json_schema"
            )
            response = structured_llm.invoke(msg)

        except openai.BadRequestError:
            structured_llm = self.llm_endpoint._llm.with_structured_output(
                SplittedInput
            )
            response = structured_llm.invoke(msg)

        send_list: List[Send] = []

        instructions = (
            response.instructions
            if response.instructions
            else self.retrieval_config.prompt
        )

        if instructions:
            send_list.append(Send("edit_system_prompt", {"instructions": instructions}))
        elif response.task_list:
            chat_history = state["chat_history"]
            send_list.append(
                Send(
                    "filter_history",
                    {
                        "chat_history": chat_history,
                        "tasks": UserTasks(response.task_list),
                    },
                )
            )

        return send_list

    def routing_split(self, state: AgentState):
        response: SplittedInput = self.invoke_structured_output(
            custom_prompts.SPLIT_PROMPT.format(
                chat_history=state["chat_history"].to_list(),
                user_input=state["messages"][0].content,
            ),
            SplittedInput,
        )

        instructions = response.instructions or self.retrieval_config.prompt
        tasks = UserTasks(response.task_list) if response.task_list else None

        if instructions:
            return [
                Send(
                    "edit_system_prompt",
                    {**state, "instructions": instructions, "tasks": tasks},
                )
            ]
        elif tasks:
            return [Send("filter_history", {**state, "tasks": tasks})]

        return []

    def update_active_tools(self, updated_prompt_and_tools: UpdatedPromptAndTools):
        if updated_prompt_and_tools.tools_to_activate:
            for tool in updated_prompt_and_tools.tools_to_activate:
                for (
                    validated_tool
                ) in self.retrieval_config.workflow_config.validated_tools:
                    if tool == validated_tool.name:
                        self.retrieval_config.workflow_config.activated_tools.append(
                            validated_tool
                        )

        if updated_prompt_and_tools.tools_to_deactivate:
            for tool in updated_prompt_and_tools.tools_to_deactivate:
                for (
                    activated_tool
                ) in self.retrieval_config.workflow_config.activated_tools:
                    if tool == activated_tool.name:
                        self.retrieval_config.workflow_config.activated_tools.remove(
                            activated_tool
                        )

    def edit_system_prompt(self, state: AgentState) -> AgentState:
        user_instruction = state["instructions"]
        prompt = self.retrieval_config.prompt
        available_tools, activated_tools = collect_tools(
            self.retrieval_config.workflow_config
        )
        inputs = {
            "instruction": user_instruction,
            "system_prompt": prompt if prompt else "",
            "available_tools": available_tools,
            "activated_tools": activated_tools,
        }

        msg = custom_prompts.UPDATE_PROMPT.format(**inputs)

        response: UpdatedPromptAndTools = self.invoke_structured_output(
            msg, UpdatedPromptAndTools
        )

        self.update_active_tools(response)
        self.retrieval_config.prompt = response.prompt

        reasoning = [response.prompt_reasoning] if response.prompt_reasoning else []
        reasoning += [response.tools_reasoning] if response.tools_reasoning else []

        return {**state, "messages": [], "reasoning": reasoning}

    def filter_history(self, state: AgentState) -> AgentState:
        """
        Filter out the chat history to only include the messages that are relevant to the current question

        Takes in a chat_history= [HumanMessage(content='Qui est Chloé ? '),
        AIMessage(content="Chloé est une salariée travaillant pour l'entreprise Quivr en tant qu'AI Engineer,
        sous la direction de son supérieur hiérarchique, Stanislas Girard."),
        HumanMessage(content='Dis moi en plus sur elle'), AIMessage(content=''),
        HumanMessage(content='Dis moi en plus sur elle'),
        AIMessage(content="Désolé, je n'ai pas d'autres informations sur Chloé à partir des fichiers fournis.")]
        Returns a filtered chat_history with in priority: first max_tokens, then max_history where a Human message and an AI message count as one pair
        a token is 4 characters
        """

        chat_history = state["chat_history"]
        total_tokens = 0
        total_pairs = 0
        _chat_id = uuid4()
        _chat_history = ChatHistory(chat_id=_chat_id, brain_id=chat_history.brain_id)
        for human_message, ai_message in reversed(list(chat_history.iter_pairs())):
            # TODO: replace with tiktoken
            message_tokens = self.llm_endpoint.count_tokens(
                human_message.content
            ) + self.llm_endpoint.count_tokens(ai_message.content)
            if (
                total_tokens + message_tokens
                > self.retrieval_config.llm_config.max_context_tokens
                or total_pairs >= self.retrieval_config.max_history
            ):
                break
            _chat_history.append(human_message)
            _chat_history.append(ai_message)
            total_tokens += message_tokens
            total_pairs += 1

        return {**state, "chat_history": _chat_history}

    ### Nodes
    async def rewrite(self, state: AgentState) -> AgentState:
        """
        Transform the query to produce a better question.

        Args:
            state (messages): The current state

        Returns:
            dict: The updated state with re-phrased question
        """

        if "tasks" in state and state["tasks"]:
            tasks = state["tasks"]
        else:
            tasks = UserTasks([state["messages"][0].content])

        # Prepare the async tasks for all user tsks
        async_jobs = []
        for task_id in tasks.ids:
            msg = custom_prompts.CONDENSE_TASK_PROMPT.format(
                chat_history=state["chat_history"].to_list(),
                task=tasks(task_id).definition,
            )

            model = self.llm_endpoint._llm
            # Asynchronously invoke the model for each question
            async_jobs.append((model.ainvoke(msg), task_id))

        # Gather all the responses asynchronously
        responses = (
            await asyncio.gather(*(jobs[0] for jobs in async_jobs))
            if async_jobs
            else []
        )
        task_ids = [jobs[1] for jobs in async_jobs] if async_jobs else []

        # Replace each question with its condensed version
        for response, task_id in zip(responses, task_ids, strict=False):
            tasks.set_definition(task_id, response.content)

        return {**state, "tasks": tasks}

    def filter_chunks_by_relevance(self, chunks: List[Document], **kwargs):
        config = self.retrieval_config.reranker_config
        relevance_score_threshold = kwargs.get(
            "relevance_score_threshold", config.relevance_score_threshold
        )

        if relevance_score_threshold is None:
            return chunks

        filtered_chunks = []
        for chunk in chunks:
            if config.relevance_score_key not in chunk.metadata:
                logger.warning(
                    f"Relevance score key {config.relevance_score_key} not found in metadata, cannot filter chunks by relevance"
                )
                filtered_chunks.append(chunk)
            elif (
                chunk.metadata[config.relevance_score_key] >= relevance_score_threshold
            ):
                filtered_chunks.append(chunk)

        return filtered_chunks

    async def tool_routing(self, state: AgentState):
        tasks = state["tasks"]
        if not tasks.has_tasks():
            return [Send("generate_rag", state)]

        validated_tools, _ = collect_tools(self.retrieval_config.workflow_config)

        async_jobs = []
        for task_id in tasks.ids:
            input = {
                "chat_history": state["chat_history"].to_list(),
                "tasks": tasks(task_id).definition,
                "context": combine_documents(tasks(task_id).docs),
                "activated_tools": validated_tools,
            }

            msg = custom_prompts.TOOL_ROUTING_PROMPT.format(**input)
            async_jobs.append(
                (self.ainvoke_structured_output(msg, TasksCompletion), task_id)
            )

        responses: List[TasksCompletion] = (
            await asyncio.gather(*(jobs[0] for jobs in async_jobs))
            if async_jobs
            else []
        )
        task_ids = [jobs[1] for jobs in async_jobs] if async_jobs else []

        for response, task_id in zip(responses, task_ids, strict=False):
            tasks.set_completion(task_id, response.is_task_completable)
            if not response.is_task_completable and response.tool:
                tasks.set_tool(task_id, response.tool)

        send_list: List[Send] = []

        payload = {**state, "tasks": tasks}

        if tasks.has_non_completable_tasks():
            send_list.append(Send("run_tool", payload))
        else:
            send_list.append(Send("generate_rag", payload))

        return send_list

    async def run_tool(self, state: AgentState) -> AgentState:
        # if tool not in [
        #     t.name for t in self.retrieval_config.workflow_config.activated_tools
        # ]:
        #     raise ValueError(f"Tool {tool} not activated")

        tasks = state["tasks"]

        # Prepare the async tasks for all questions
        async_jobs = []
        for task_id in tasks.ids:
            if not tasks(task_id).is_completable() and tasks(task_id).has_tool():
                tool = tasks(task_id).tool
                tool_wrapper = LLMToolFactory.create_tool(tool, {})
                formatted_input = tool_wrapper.format_input(tasks(task_id).definition)
                async_jobs.append((tool_wrapper.tool.ainvoke(formatted_input), task_id))

        # Gather all the responses asynchronously
        responses = (
            await asyncio.gather(*(jobs[0] for jobs in async_jobs))
            if async_jobs
            else []
        )
        task_ids = [jobs[1] for jobs in async_jobs] if async_jobs else []

        for response, task_id in zip(responses, task_ids, strict=False):
            _docs = tool_wrapper.format_output(response)
            _docs = self.filter_chunks_by_relevance(_docs)
            tasks.set_docs(task_id, _docs)

        return {**state, "tasks": tasks}

    async def retrieve(self, state: AgentState) -> AgentState:
        """
        Retrieve relevent chunks

        Args:
            state (messages): The current state

        Returns:
            dict: The retrieved chunks
        """
        if "tasks" in state:
            tasks = state["tasks"]
        else:
            tasks = UserTasks([state["messages"][0].content])

        if not tasks.has_tasks():
            return {**state}

        kwargs = {
            "search_kwargs": {
                "k": self.retrieval_config.k,
            }
        }  # type: ignore
        base_retriever = self.get_retriever(**kwargs)

        kwargs = {"top_n": self.retrieval_config.reranker_config.top_n}  # type: ignore
        reranker = self.get_reranker(**kwargs)

        compression_retriever = ContextualCompressionRetriever(
            base_compressor=reranker, base_retriever=base_retriever
        )
        # Prepare the async tasks for all questions
        async_jobs = []
        for task_id in tasks.ids:
            # Create a tuple of the retrieval task and task_id
            async_jobs.append(
                (compression_retriever.ainvoke(tasks(task_id).definition), task_id)
            )

        # Gather all the responses asynchronously
        responses = (
            await asyncio.gather(*(task[0] for task in async_jobs))
            if async_jobs
            else []
        )
        task_ids = [task[1] for task in async_jobs] if async_jobs else []

        # Process responses and associate docs with tasks
        for response, task_id in zip(responses, task_ids, strict=False):
            _docs = self.filter_chunks_by_relevance(response)
            tasks.set_docs(task_id, _docs)  # Associate docs with the specific task

        return {**state, "tasks": tasks}

    async def dynamic_retrieve(self, state: AgentState) -> AgentState:
        """
        Retrieve relevent chunks

        Args:
            state (messages): The current state

        Returns:
            dict: The retrieved chunks
        """

        MAX_ITERATIONS = 3

        if "tasks" in state:
            tasks = state["tasks"]
        else:
            tasks = UserTasks([state["messages"][0].content])

        if not tasks or not tasks.has_tasks():
            return {**state}

        k = self.retrieval_config.k
        top_n = self.retrieval_config.reranker_config.top_n
        number_of_relevant_chunks = top_n
        i = 1

        while number_of_relevant_chunks == top_n and i <= MAX_ITERATIONS:
            top_n = self.retrieval_config.reranker_config.top_n * i
            kwargs = {"top_n": top_n}
            reranker = self.get_reranker(**kwargs)

            k = max([top_n * 2, self.retrieval_config.k])
            kwargs = {"search_kwargs": {"k": k}}  # type: ignore
            base_retriever = self.get_retriever(**kwargs)

            if i > 1:
                logging.info(
                    f"Increasing top_n to {top_n} and k to {k} to retrieve more relevant chunks"
                )

            compression_retriever = ContextualCompressionRetriever(
                base_compressor=reranker, base_retriever=base_retriever
            )

            # Prepare the async tasks for all questions
            async_jobs = []
            for task_id in tasks.ids:
                # Asynchronously invoke the model for each question
                async_jobs.append(
                    (compression_retriever.ainvoke(tasks(task_id).definition), task_id)
                )

            # Gather all the responses asynchronously
            responses = (
                await asyncio.gather(*(jobs[0] for jobs in async_jobs))
                if async_jobs
                else []
            )
            task_ids = [jobs[1] for jobs in async_jobs] if async_jobs else []

            _n = []
            for response, task_id in zip(responses, task_ids, strict=False):
                _docs = self.filter_chunks_by_relevance(response)
                _n.append(len(_docs))
                tasks.set_docs(task_id, _docs)

            docs = tasks.docs
            if not docs:
                break

            context_length = self.get_rag_context_length(state, docs)
            if context_length >= self.retrieval_config.llm_config.max_context_tokens:
                logging.warning(
                    f"The context length is {context_length} which is greater than "
                    f"the max context tokens of {self.retrieval_config.llm_config.max_context_tokens}"
                )
                break

            number_of_relevant_chunks = max(_n)
            i += 1

        return {**state, "tasks": tasks}

    def retrieve_all_chunks_from_file(self, file_id: UUID) -> List[Document]:
        retriever = self.get_retriever()
        return retriever.get_by_ids(ids=[file_id])

    def _sort_docs_by_relevance(self, docs: List[Document]) -> List[Document]:
        return sorted(
            docs,
            key=lambda x: x.metadata[
                self.retrieval_config.reranker_config.relevance_score_key
            ],
            reverse=True,
        )

    async def retrieve_full_documents_context(self, state: AgentState) -> AgentState:
        if "tasks" in state:
            tasks = state["tasks"]
        else:
            tasks = UserTasks([state["messages"][0].content])

        if not tasks.has_tasks():
            return {**state}

        docs = tasks.docs if tasks else []

        relevant_knowledge = {}
        for doc in docs:
            knowledge_id = doc.metadata["knowledge_id"]
            similarity_score = doc.metadata.get("similarity", 0)
            if knowledge_id in relevant_knowledge:
                relevant_knowledge[knowledge_id]["count"] += 1
                relevant_knowledge[knowledge_id]["max_similarity_score"] = max(
                    relevant_knowledge[knowledge_id]["max_similarity_score"],
                    similarity_score,
                )
                relevant_knowledge[knowledge_id]["chunk_index"] = max(
                    doc.metadata["chunk_index"],
                    relevant_knowledge[knowledge_id]["chunk_index"],
                )
            else:
                relevant_knowledge[knowledge_id] = {
                    "count": 1,
                    "max_similarity_score": similarity_score,
                    "chunk_index": doc.metadata["chunk_index"],
                }

        top_n = min(3, len(relevant_knowledge))
        # FIXME: Tweak this to return the most relevant knowledges
        top_knowledge_ids = OrderedDict(
            sorted(
                relevant_knowledge.items(),
                key=lambda x: (
                    x[1]["max_similarity_score"],
                    x[1]["count"],
                ),
                reverse=True,
            )[:top_n]
        )

        logger.info(f"Top knowledge IDs: {top_knowledge_ids}")

        _docs = []

        assert hasattr(
            self.vector_store, "get_vectors_by_knowledge_id"
        ), "Vector store must have method 'get_vectors_by_knowledge_id', this is an enterprise only feature"

        for knowledge_id in top_knowledge_ids:
            _docs.append(
                await self.vector_store.get_vectors_by_knowledge_id(  # type: ignore
                    knowledge_id,
                    end_index=relevant_knowledge[knowledge_id]["chunk_index"],
                )
            )

        tasks.set_docs(
            id=tasks.ids[0], docs=_docs
        )  # FIXME If multiple IDs is not handled.

        return {**state, "tasks": tasks}

    def get_rag_context_length(self, state: AgentState, docs: List[Document]) -> int:
        final_inputs = self._build_rag_prompt_inputs(state, docs)
        msg = custom_prompts.RAG_ANSWER_PROMPT.format(**final_inputs)
        return self.llm_endpoint.count_tokens(msg)

    def reduce_rag_context(
        self,
        state: AgentState,
        inputs: Dict[str, Any],
        prompt: BasePromptTemplate,
        max_context_tokens: int | None = None,
    ) -> Tuple[AgentState, Dict[str, Any]]:
        MAX_ITERATIONS = 20
        SECURITY_FACTOR = 0.85
        iteration = 0

        tasks = state["tasks"] if "tasks" in state else None
        docs = tasks.docs if tasks else []
        msg = prompt.format(**inputs)
        n = self.llm_endpoint.count_tokens(msg)

        max_context_tokens = (
            max_context_tokens
            if max_context_tokens
            else self.retrieval_config.llm_config.max_context_tokens
        )

        # Get token counts for each doc in each task
        if tasks:
            task_token_counts = {}
            for task_id in tasks.ids:
                doc_tokens = [
                    self.llm_endpoint.count_tokens(doc.page_content)
                    for doc in tasks(task_id).docs
                ]
                task_token_counts[task_id] = {
                    "docs": doc_tokens,
                    "total": sum(doc_tokens),
                }

        while n > max_context_tokens * SECURITY_FACTOR:
            chat_history = inputs["chat_history"] if "chat_history" in inputs else []

            if len(chat_history) > 0:
                inputs["chat_history"] = chat_history[2:]
            elif tasks:
                longest_task_id = max(
                    task_token_counts.items(), key=lambda x: x[1]["total"]
                )[0]

                # Remove last doc from that task
                if task_token_counts[longest_task_id]["docs"]:
                    removed_tokens = task_token_counts[longest_task_id]["docs"].pop()
                    task_token_counts[longest_task_id]["total"] -= removed_tokens
                    tasks.set_docs(longest_task_id, tasks(longest_task_id).docs[:-1])
            else:
                logging.warning(
                    f"Not enough context to reduce. The context length is {n} "
                    f"which is greater than the max context tokens of {max_context_tokens}"
                )
                break

            docs = tasks.docs if tasks else []
            inputs["context"] = combine_documents(docs)

            msg = prompt.format(**inputs)
            n = self.llm_endpoint.count_tokens(msg)

            iteration += 1
            if iteration > MAX_ITERATIONS:
                logging.warning(
                    f"Attained the maximum number of iterations ({MAX_ITERATIONS})"
                )
                break

        return {**state, "tasks": tasks}, inputs

    def bind_tools_to_llm(self, node_name: str):
        if self.llm_endpoint.supports_func_calling():
            tools = self.retrieval_config.workflow_config.get_node_tools(node_name)
            if tools:  # Only bind tools if there are any available
                return self.llm_endpoint._llm.bind_tools(tools, tool_choice="any")
        return self.llm_endpoint._llm

    def generate_zendesk_rag(self, state: AgentState) -> AgentState:
        tasks = state["tasks"]
        docs = tasks.docs if tasks else []
        messages = state["messages"]
        user_task = messages[0].content
        inputs = {
            "similar_tickets": docs,
            "client_query": user_task,
        }

        msg = custom_prompts.ZENDESK_TEMPLATE_PROMPT.format(**inputs)
        llm = self.bind_tools_to_llm(self.generate_zendesk_rag.__name__)
        response = llm.invoke(msg)

        return {**state, "messages": [response]}

    def generate_rag(self, state: AgentState) -> AgentState:
        tasks = state["tasks"]
        docs = tasks.docs if tasks else []
        inputs = self._build_rag_prompt_inputs(state, docs)
        state, inputs = self.reduce_rag_context(
            state, inputs, custom_prompts.RAG_ANSWER_PROMPT
        )

        msg = custom_prompts.RAG_ANSWER_PROMPT.format(**inputs)
        llm = self.bind_tools_to_llm(self.generate_rag.__name__)
        response = llm.invoke(msg)

        return {**state, "messages": [response]}

    def generate_chat_llm(self, state: AgentState) -> AgentState:
        """
        Generate answer

        Args:
            state (messages): The current state

        Returns:
            dict: The updated state with re-phrased question
        """
        messages = state["messages"]
        user_task = messages[0].content

        # Prompt
        prompt = self.retrieval_config.prompt

        final_inputs = {}
        final_inputs["task"] = user_task
        final_inputs["custom_instructions"] = prompt if prompt else "None"
        final_inputs["chat_history"] = state["chat_history"].to_list()

        # LLM
        llm = self.llm_endpoint._llm

        state, reduced_inputs = self.reduce_rag_context(
            state, final_inputs, custom_prompts.CHAT_LLM_PROMPT
        )

        msg = custom_prompts.CHAT_LLM_PROMPT.format(**reduced_inputs)

        # Run
        response = llm.invoke(msg)
        return {**state, "messages": [response]}

    def build_chain(self):
        """
        Builds the langchain chain for the given configuration.

        Returns:
            Callable[[Dict], Dict]: The langchain chain.
        """
        if not self.graph:
            self.graph = self.create_graph()

        return self.graph

    def create_graph(self):
        workflow = StateGraph(AgentState)
        self.final_nodes = []

        self._build_workflow(workflow)

        return workflow.compile()

    def _build_workflow(self, workflow: StateGraph):
        for node in self.retrieval_config.workflow_config.nodes:
            if node.name not in [START, END]:
                workflow.add_node(node.name, getattr(self, node.name))

        for node in self.retrieval_config.workflow_config.nodes:
            self._add_node_edges(workflow, node)

    def _add_node_edges(self, workflow: StateGraph, node: NodeConfig):
        if node.edges:
            for edge in node.edges:
                workflow.add_edge(node.name, edge)
                if edge == END:
                    self.final_nodes.append(node.name)
        elif node.conditional_edge:
            routing_function = getattr(self, node.conditional_edge.routing_function)
            workflow.add_conditional_edges(
                node.name, routing_function, node.conditional_edge.conditions
            )
            if END in node.conditional_edge.conditions:
                self.final_nodes.append(node.name)
        else:
            raise ValueError("Node should have at least one edge or conditional_edge")

    async def answer_astream(
        self,
        question: str,
        history: ChatHistory,
        list_files: list[QuivrKnowledge],
        metadata: dict[str, str] = {},
    ) -> AsyncGenerator[ParsedRAGChunkResponse, ParsedRAGChunkResponse]:
        """
        Answer a question using the langgraph chain and yield each chunk of the answer separately.
        """
        concat_list_files = format_file_list(
            list_files, self.retrieval_config.max_files
        )
        conversational_qa_chain = self.build_chain()

        rolling_message = AIMessageChunk(content="")
        docs: list[Document] | None = None
        previous_content = ""

        async for event in conversational_qa_chain.astream_events(
            {
                "messages": [("user", question)],
                "chat_history": history,
                "files": concat_list_files,
            },
            version="v1",
            config={"metadata": metadata, "callbacks": [langfuse_handler]},
        ):
            node_name = self._extract_node_name(event)

            if self._is_final_node_with_docs(event):
                tasks = event["data"]["output"]["tasks"]
                docs = tasks.docs if tasks else []

            if self._is_final_node_and_chat_model_stream(event):
                chunk = event["data"]["chunk"]
                rolling_message, new_content, previous_content = parse_chunk_response(
                    rolling_message,
                    chunk,
                    self.llm_endpoint.supports_func_calling(),
                    previous_content,
                )

                if new_content:
                    chunk_metadata = get_chunk_metadata(rolling_message, docs)
                    if node_name:
                        chunk_metadata.workflow_step = node_name
                    yield ParsedRAGChunkResponse(
                        answer=new_content, metadata=chunk_metadata
                    )
            else:
                if node_name:
                    yield ParsedRAGChunkResponse(
                        answer="",
                        metadata=RAGResponseMetadata(workflow_step=node_name),
                    )

        # Yield final metadata chunk
        yield ParsedRAGChunkResponse(
            answer="",
            metadata=get_chunk_metadata(rolling_message, docs),
            last_chunk=True,
        )

    def _is_final_node_with_docs(self, event: dict) -> bool:
        return (
            "output" in event["data"]
            and event["data"]["output"] is not None
            and "tasks" in event["data"]["output"]
            and event["metadata"]["langgraph_node"] in self.final_nodes
        )

    def _is_final_node_and_chat_model_stream(self, event: dict) -> bool:
        return (
            event["event"] == "on_chat_model_stream"
            and "langgraph_node" in event["metadata"]
            and event["metadata"]["langgraph_node"] in self.final_nodes
        )

    def _extract_node_name(self, event: dict) -> str:
        if "metadata" in event and "langgraph_node" in event["metadata"]:
            name = event["metadata"]["langgraph_node"]
            for node in self.retrieval_config.workflow_config.nodes:
                if node.name == name:
                    if node.description:
                        return node.description
                    else:
                        return node.name
        return ""

    async def ainvoke_structured_output(
        self, prompt: str, output_class: Type[BaseModel]
    ) -> Any:
        try:
            structured_llm = self.llm_endpoint._llm.with_structured_output(
                output_class, method="json_schema"
            )
            return await structured_llm.ainvoke(prompt)
        except openai.BadRequestError:
            structured_llm = self.llm_endpoint._llm.with_structured_output(output_class)
            return await structured_llm.ainvoke(prompt)

    def invoke_structured_output(
        self, prompt: str, output_class: Type[BaseModel]
    ) -> Any:
        try:
            structured_llm = self.llm_endpoint._llm.with_structured_output(
                output_class, method="json_schema"
            )
            return structured_llm.invoke(prompt)
        except openai.BadRequestError:
            structured_llm = self.llm_endpoint._llm.with_stuctured_output(output_class)
            return structured_llm.invoke(prompt)

    def _build_rag_prompt_inputs(
        self, state: AgentState, docs: List[Document] | None
    ) -> Dict[str, Any]:
        """Build the input dictionary for RAG_ANSWER_PROMPT.

        Args:
            state: Current agent state
            docs: List of documents or None

        Returns:
            Dictionary containing all inputs needed for RAG_ANSWER_PROMPT
        """
        messages = state["messages"]
        user_task = messages[0].content
        files = state["files"]
        prompt = self.retrieval_config.prompt
        # available_tools, _ = collect_tools(self.retrieval_config.workflow_config)

        return {
            "context": combine_documents(docs) if docs else "None",
            "task": user_task,
            "rephrased_task": state["tasks"].definitions if state["tasks"] else "None",
            "custom_instructions": prompt if prompt else "None",
            "files": files if files else "None",
            "chat_history": state["chat_history"].to_list(),
            # "reasoning": state["reasoning"] if "reasoning" in state else "None",
            # "tools": available_tools,
        }
