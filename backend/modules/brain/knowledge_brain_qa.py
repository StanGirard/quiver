import json
from typing import AsyncIterable, List, Optional
from uuid import UUID

from langchain.callbacks.streaming_aiter import AsyncIteratorCallbackHandler
from logger import get_logger
from models import BrainSettings
from modules.brain.entity.brain_entity import BrainEntity
from modules.brain.qa_interface import QAInterface
from modules.brain.rags.quivr_rag import QuivrRAG
from modules.brain.rags.rag_interface import RAGInterface
from modules.brain.service.brain_service import BrainService
from modules.brain.service.utils.format_chat_history import format_chat_history
from modules.brain.service.utils.get_prompt_to_use_id import get_prompt_to_use_id
from modules.chat.controller.chat.utils import (
    find_model_and_generate_metadata,
    update_user_usage,
)
from modules.chat.dto.chats import ChatQuestion, Sources
from modules.chat.dto.inputs import CreateChatHistory
from modules.chat.dto.outputs import GetChatHistoryOutput
from modules.chat.service.chat_service import ChatService
from modules.prompt.service.get_prompt_to_use import get_prompt_to_use
from modules.upload.service.generate_file_signed_url import generate_file_signed_url
from modules.user.service.user_usage import UserUsage
from pydantic import BaseModel, ConfigDict
from pydantic_settings import BaseSettings

logger = get_logger(__name__)
QUIVR_DEFAULT_PROMPT = "Your name is Quivr. You're a helpful assistant.  If you don't know the answer, just say that you don't know, don't try to make up an answer."


brain_service = BrainService()
chat_service = ChatService()


def is_valid_uuid(uuid_to_test, version=4):
    """
    Check if a given string is a valid UUID.

    Args:
        uuid_to_test (str): The string to be checked.
        version (int, optional): The version of UUID to be checked against. Defaults to 4.

    Returns:
        bool: True if the string is a valid UUID, False otherwise.
    """
    try:
        uuid_obj = UUID(uuid_to_test, version=version)
    except ValueError:
        return False

    return str(uuid_obj) == uuid_to_test

def filter_documents(documents, citations):
    """
    Filter documents based on provided citations.
    
    Args:
        documents (list): The list of documents to be filtered.
        citations (list): The list of indices of the documents to be included in the filtered list.
        
    Returns:
        list: The filtered list of documents.
    """
    if citations is None:
        return documents
    return [doc for index, doc in enumerate(documents) if index in citations]

def get_or_generate_url(doc, brain_id, url_cache):
    """
    Retrieve or generate a new URL for the given document.

    Args:
        doc (dict): The document for which to retrieve or generate a URL.
        brain_id (str): The ID of the brain containing the document.
        url_cache (dict): A dictionary to cache previously generated URLs.

    Returns:
        str: The URL for the given document. If a URL is already cached for the document, it is retrieved from the cache. Otherwise, a new URL is generated or retrieved from the `generate_file_signed_url` function, and it is stored in the cache before returning.

    Note:
        - The `doc` parameter is expected to be a dictionary with the following keys:
            - `file_name` (str): The name of the document file.
            - `is_url` (bool): Indicates whether the document is a URL or not.
            - `original_file_name` (str, optional): The original URL of the document if it is a URL.
        - If the `doc` parameter is a URL document, the `original_file_name` key is used as the source URL.
        - If the `doc` parameter is not a URL document, the `generate_file_signed_url` function is called to generate a signed URL for the document. If a URL is successfully generated, it is used as the source URL. Otherwise, an empty string is used.
        - The generated or retrieved URL is stored in the `url_cache` dictionary for future retrieval.

    """
    file_path = f"{brain_id}/{doc['file_name']}"
    if file_path in url_cache:
        return url_cache[file_path]

    if doc['is_url']:
        source_url = doc['original_file_name']
    else:
        generated_url = generate_file_signed_url(file_path)
        source_url = generated_url.get("signedURL", "") if generated_url else ""

    url_cache[file_path] = source_url
    return source_url

def create_source_object(doc, source_type, source_url):
    """
    Create and return a Sources object for the given document.

    Parameters:
        doc (dict): The document for which to create the Sources object. It should have the following keys:
            - 'file_name' (str): The name of the document file.
            - 'original_file_name' (str, optional): The original URL of the document if it is a URL.
            - 'page_content' (str): The content of the document page.
        source_type (str): The type of the source. It should be either 'file' or 'url'.
        source_url (str): The URL of the source.

    Returns:
        Sources: The created Sources object.

    """
    return Sources(
        name=doc['file_name'],
        type=source_type,
        source_url=source_url,
        original_file_name=doc['file_name'] if source_type == 'file' else doc['original_file_name'],
        citation=doc['page_content']
    )

def generate_source(source_documents, brain_id, citations: List[int] = None):
    """
    Generate a list of Sources objects based on the given source documents and brain ID.

    Parameters:
        source_documents (list): A list of source documents. Each document should be a dictionary with the following keys:
            - 'file_name' (str): The name of the document file.
            - 'original_file_name' (str, optional): The original URL of the document if it is a URL.
            - 'page_content' (str): The content of the document page.
            - 'is_url' (bool): Indicates whether the document is a URL.
        brain_id (str): The ID of the brain.
        citations (list[int], optional): A list of citation indices to filter the source documents. Defaults to None.

    Returns:
        list[Sources]: A list of Sources objects representing the generated sources. Each Sources object has the following attributes:
            - name (str): The name of the source.
            - type (str): The type of the source. It is either 'file' or 'url'.
            - source_url (str): The URL of the source.
            - original_file_name (str): The original file name of the source. It is empty if the source is a URL.
            - citation (str): The citation of the source.

    """
    # Initialize an empty list for sources
    sources_list: List[Sources] = []

    # Initialize a dictionary for storing generated URLs
    generated_urls = {}

    if not source_documents:
        logger.info("No source documents provided.")
        return sources_list

    logger.info(f"Citations: {citations}")
    unique_docs = filter_documents(source_documents, citations)

    for doc in unique_docs:
        source_url = get_or_generate_url(doc, brain_id, generated_urls)
        source_type = "url" if doc["is_url"] else "file"
        sources_list.append(create_source_object(doc, source_type, source_url))

    return sources_list

class KnowledgeBrainQA(BaseModel, QAInterface):
    """
    Main class for the Brain Picking functionality.
    It allows to initialize a Chat model, generate questions and retrieve answers using ConversationalRetrievalChain.
    It has two main methods: `generate_question` and `generate_stream`.
    One is for generating questions in a single request, the other is for generating questions in a streaming fashion.
    Both are the same, except that the streaming version streams the last message as a stream.
    Each have the same prompt template, which is defined in the `prompt_template` property.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Instantiate settings
    brain_settings: BaseSettings = BrainSettings()

    # Default class attributes
    model: str = "gpt-3.5-turbo-0125"  # pyright: ignore reportPrivateUsage=none
    temperature: float = 0.1
    chat_id: str = None  # pyright: ignore reportPrivateUsage=none
    brain_id: str = None  # pyright: ignore reportPrivateUsage=none
    max_tokens: int = 2000
    max_input: int = 2000
    streaming: bool = False
    knowledge_qa: Optional[RAGInterface] = None
    brain: Optional[BrainEntity] = None
    user_id: str = None
    user_email: str = None
    user_usage: Optional[UserUsage] = None
    user_settings: Optional[dict] = None
    models_settings: Optional[List[dict]] = None
    metadata: Optional[dict] = None

    callbacks: List[AsyncIteratorCallbackHandler] = (
        None  # pyright: ignore reportPrivateUsage=none
    )

    prompt_id: Optional[UUID] = None

    def __init__(
        self,
        brain_id: str,
        chat_id: str,
        streaming: bool = False,
        prompt_id: Optional[UUID] = None,
        metadata: Optional[dict] = None,
        user_id: str = None,
        user_email: str = None,
        cost: int = 100,
        **kwargs,
    ):
        super().__init__(
            brain_id=brain_id,
            chat_id=chat_id,
            streaming=streaming,
            **kwargs,
        )
        self.prompt_id = prompt_id
        self.user_id = user_id
        self.user_email = user_email
        self.user_usage = UserUsage(
            id=user_id,
            email=user_email,
        )
        self.brain = brain_service.get_brain_by_id(brain_id)

        self.user_settings = self.user_usage.get_user_settings()

        # Get Model settings for the user
        self.models_settings = self.user_usage.get_model_settings()
        self.increase_usage_user()
        self.knowledge_qa = QuivrRAG(
            model=self.brain.model if self.brain.model else self.model,
            brain_id=brain_id,
            chat_id=chat_id,
            streaming=streaming,
            max_input=self.max_input,
            max_tokens=self.max_tokens,
            **kwargs,
        )

    @property
    def prompt_to_use(self):
        if self.brain_id and is_valid_uuid(self.brain_id):
            return get_prompt_to_use(UUID(self.brain_id), self.prompt_id)
        else:
            return None

    @property
    def prompt_to_use_id(self) -> Optional[UUID]:
        # TODO: move to prompt service or instruction or something
        if self.brain_id and is_valid_uuid(self.brain_id):
            return get_prompt_to_use_id(UUID(self.brain_id), self.prompt_id)
        else:
            return None

    def increase_usage_user(self):
        # Raises an error if the user has consumed all of of his credits

        update_user_usage(
            usage=self.user_usage,
            user_settings=self.user_settings,
            cost=self.calculate_pricing(),
        )

    def calculate_pricing(self):

        model_to_use = find_model_and_generate_metadata(
            self.chat_id,
            self.brain.model,
            self.user_settings,
            self.models_settings,
        )
        self.model = model_to_use.name
        self.max_input = model_to_use.max_input
        self.max_tokens = model_to_use.max_output
        user_choosen_model_price = 1000

        for model_setting in self.models_settings:
            if model_setting["name"] == self.model:
                user_choosen_model_price = model_setting["price"]

        return user_choosen_model_price

    def generate_answer(
        self, chat_id: UUID, question: ChatQuestion, save_answer: bool = True
    ) -> GetChatHistoryOutput:
        conversational_qa_chain = self.knowledge_qa.get_chain()
        transformed_history, streamed_chat_history = (
            self.initialize_streamed_chat_history(chat_id, question)
        )
        metadata = self.metadata or {}
        citations = None
        answer = ""
        model_response = conversational_qa_chain.invoke(
            {
                "question": question.question,
                "chat_history": transformed_history,
                "custom_personality": (
                    self.prompt_to_use.content if self.prompt_to_use else None
                ),
            }
        )

        if self.model_compatible_with_function_calling(model=self.model):
            if model_response["answer"].tool_calls:
                citations = model_response["answer"].tool_calls[-1]["args"]["citations"]
                if citations:
                    citations = citations
                answer = model_response["answer"].tool_calls[-1]["args"]["answer"]
        else:
            answer = model_response["answer"].content
        sources = model_response["docs"] or []
        if len(sources) > 0:
            sources_list = generate_source(sources, self.brain_id, citations=citations)
            serialized_sources_list = [source.dict() for source in sources_list]
            metadata["sources"] = serialized_sources_list

        return self.save_non_streaming_answer(
            chat_id=chat_id, question=question, answer=answer, metadata=metadata
        )

    async def generate_stream(
        self, chat_id: UUID, question: ChatQuestion, save_answer: bool = True
    ) -> AsyncIterable:
        conversational_qa_chain = self.knowledge_qa.get_chain()
        transformed_history, streamed_chat_history = (
            self.initialize_streamed_chat_history(chat_id, question)
        )
        response_tokens = ""
        sources = []
        citations = []
        first = True
        async for chunk in conversational_qa_chain.astream(
            {
                "question": question.question,
                "chat_history": transformed_history,
                "custom_personality": (
                    self.prompt_to_use.content if self.prompt_to_use else None
                ),
            }
        ):
            if not streamed_chat_history.metadata:
                streamed_chat_history.metadata = {}
            if self.model_compatible_with_function_calling(model=self.model):
                if chunk.get("answer"):
                    if first:
                        gathered = chunk["answer"]
                        first = False
                    else:
                        gathered = gathered + chunk["answer"]
                        if (
                            gathered.tool_calls
                            and gathered.tool_calls[-1].get("args")
                            and "answer" in gathered.tool_calls[-1]["args"]
                        ):
                            # Only send the difference between answer and response_tokens which was the previous answer
                            answer = gathered.tool_calls[-1]["args"]["answer"]
                            difference = answer[len(response_tokens) :]
                            streamed_chat_history.assistant = difference
                            response_tokens = answer

                            yield f"data: {json.dumps(streamed_chat_history.dict())}"
                        if (
                            gathered.tool_calls
                            and gathered.tool_calls[-1].get("args")
                            and "citations" in gathered.tool_calls[-1]["args"]
                        ):
                            citations = gathered.tool_calls[-1]["args"]["citations"]
            else:
                if chunk.get("answer"):
                    response_tokens += chunk["answer"].content
                    streamed_chat_history.assistant = chunk["answer"].content
                    yield f"data: {json.dumps(streamed_chat_history.dict())}"

            if chunk.get("docs"):
                sources = chunk["docs"]

        sources_list = generate_source(sources, self.brain_id, citations)

        # Serialize the sources list
        serialized_sources_list = [source.dict() for source in sources_list]
        streamed_chat_history.metadata["sources"] = serialized_sources_list
        yield f"data: {json.dumps(streamed_chat_history.dict())}"
        self.save_answer(question, response_tokens, streamed_chat_history, save_answer)

    def initialize_streamed_chat_history(self, chat_id, question):
        history = chat_service.get_chat_history(self.chat_id)
        transformed_history = format_chat_history(history)
        brain = brain_service.get_brain_by_id(self.brain_id)

        streamed_chat_history = chat_service.update_chat_history(
            CreateChatHistory(
                **{
                    "chat_id": chat_id,
                    "user_message": question.question,
                    "assistant": "",
                    "brain_id": brain.brain_id,
                    "prompt_id": self.prompt_to_use_id,
                }
            )
        )

        streamed_chat_history = GetChatHistoryOutput(
            **{
                "chat_id": str(chat_id),
                "message_id": streamed_chat_history.message_id,
                "message_time": streamed_chat_history.message_time,
                "user_message": question.question,
                "assistant": "",
                "prompt_title": (
                    self.prompt_to_use.title if self.prompt_to_use else None
                ),
                "brain_name": brain.name if brain else None,
                "brain_id": str(brain.brain_id) if brain else None,
                "metadata": self.metadata,
            }
        )

        return transformed_history, streamed_chat_history

    def save_answer(
        self, question, response_tokens, streamed_chat_history, save_answer
    ):
        assistant = "".join(response_tokens)

        try:
            if save_answer:
                chat_service.update_message_by_id(
                    message_id=str(streamed_chat_history.message_id),
                    user_message=question.question,
                    assistant=assistant,
                    metadata=streamed_chat_history.metadata,
                )
        except Exception as e:
            logger.error("Error updating message by ID: %s", e)

    def save_non_streaming_answer(self, chat_id, question, answer, metadata):
        new_chat = chat_service.update_chat_history(
            CreateChatHistory(
                **{
                    "chat_id": chat_id,
                    "user_message": question.question,
                    "assistant": answer,
                    "brain_id": self.brain.brain_id,
                    "prompt_id": self.prompt_to_use_id,
                    "metadata": metadata,
                }
            )
        )

        return GetChatHistoryOutput(
            **{
                "chat_id": chat_id,
                "user_message": question.question,
                "assistant": answer,
                "message_time": new_chat.message_time,
                "prompt_title": (
                    self.prompt_to_use.title if self.prompt_to_use else None
                ),
                "brain_name": self.brain.name if self.brain else None,
                "message_id": new_chat.message_id,
                "brain_id": str(self.brain.brain_id) if self.brain else None,
                "metadata": metadata,
            }
        )
