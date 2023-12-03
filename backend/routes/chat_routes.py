import os
from typing import List, Optional
from uuid import UUID
from venv import logger

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from llm.qa_base import QABaseBrainPicking
from llm.qa_headless import HeadlessQA
from middlewares.auth import AuthBearer, get_current_user
from models import Chat, ChatQuestion, UserUsage, get_supabase_db
from models.databases.supabase.chats import QuestionAndAnswer
from modules.brain.service.brain_service import BrainService
from modules.notification.service.notification_service import NotificationService
from modules.user.entity.user_identity import UserIdentity
from repository.chat import (
    ChatUpdatableProperties,
    CreateChatProperties,
    create_chat,
    get_chat_by_id,
    get_user_chats,
    update_chat,
)
from repository.chat.add_question_and_answer import add_question_and_answer
from repository.chat.get_chat_history_with_notifications import (
    ChatItem,
    get_chat_history_with_notifications,
)
from routes.chat.factory import get_chat_strategy
from routes.chat.utils import (
    check_user_requests_limit,
    delete_chat_from_db,
)

chat_router = APIRouter()

notification_service = NotificationService()
brain_service = BrainService()


@chat_router.get("/chat/healthz", tags=["Health"])
async def healthz():
    return {"status": "ok"}


# get all chats
@chat_router.get("/chat", dependencies=[Depends(AuthBearer())], tags=["Chat"])
async def get_chats(current_user: UserIdentity = Depends(get_current_user)):
    """
    Retrieve all chats for the current user.

    - `current_user`: The current authenticated user.
    - Returns a list of all chats for the user.

    This endpoint retrieves all the chats associated with the current authenticated user. It returns a list of chat objects
    containing the chat ID and chat name for each chat.
    """
    chats = get_user_chats(str(current_user.id))
    return {"chats": chats}


# delete one chat
@chat_router.delete(
    "/chat/{chat_id}", dependencies=[Depends(AuthBearer())], tags=["Chat"]
)
async def delete_chat(chat_id: UUID):
    """
    Delete a specific chat by chat ID.
    """
    supabase_db = get_supabase_db()
    notification_service.remove_chat_notifications(chat_id)

    delete_chat_from_db(supabase_db=supabase_db, chat_id=chat_id)
    return {"message": f"{chat_id}  has been deleted."}


# update existing chat metadata
@chat_router.put(
    "/chat/{chat_id}/metadata", dependencies=[Depends(AuthBearer())], tags=["Chat"]
)
async def update_chat_metadata_handler(
    chat_data: ChatUpdatableProperties,
    chat_id: UUID,
    current_user: UserIdentity = Depends(get_current_user),
) -> Chat:
    """
    Update chat attributes
    """

    chat = get_chat_by_id(chat_id)  # pyright: ignore reportPrivateUsage=none
    if str(current_user.id) != chat.user_id:
        raise HTTPException(
            status_code=403,  # pyright: ignore reportPrivateUsage=none
            detail="You should be the owner of the chat to update it.",  # pyright: ignore reportPrivateUsage=none
        )
    return update_chat(chat_id=chat_id, chat_data=chat_data)


# create new chat
@chat_router.post("/chat", dependencies=[Depends(AuthBearer())], tags=["Chat"])
async def create_chat_handler(
    chat_data: CreateChatProperties,
    current_user: UserIdentity = Depends(get_current_user),
):
    """
    Create a new chat with initial chat messages.
    """

    return create_chat(user_id=current_user.id, chat_data=chat_data)


# stream new question response from chat
@chat_router.post(
    "/chat/{chat_id}/question/stream",
    dependencies=[
        Depends(
            AuthBearer(),
        ),
    ],
    tags=["Chat"],
)
async def create_stream_question_handler(
    request: Request,
    chat_question: ChatQuestion,
    chat_id: UUID,
    current_user: UserIdentity = Depends(get_current_user),
) -> StreamingResponse:
    brain_id: UUID = UUID(os.getenv("VT_BRAIN_ID"))
    chat_question.brain_id = brain_id
    chat_instance = get_chat_strategy(brain_id)
    chat_instance.validate_authorization(user_id=current_user.id, brain_id=brain_id)

    user_daily_usage = UserUsage(
        id=current_user.id,
        email=current_user.email,
    )

    user_settings = user_daily_usage.get_user_settings()

    # Retrieve chat model (temperature, max_tokens, model)
    if (
        not chat_question.model
        or chat_question.temperature is None
        or not chat_question.max_tokens
    ):
        fallback_model = "gpt-3.5-turbo"
        fallback_temperature = 0
        fallback_max_tokens = 256

        if brain_id:
            brain = brain_service.get_brain_by_id(brain_id)
            if brain:
                fallback_model = brain.model or fallback_model
                fallback_temperature = brain.temperature or fallback_temperature
                fallback_max_tokens = brain.max_tokens or fallback_max_tokens

        chat_question.model = chat_question.model or fallback_model
        chat_question.temperature = chat_question.temperature or fallback_temperature
        chat_question.max_tokens = chat_question.max_tokens or fallback_max_tokens

    try:
        logger.info(f"Streaming request for {chat_question.model}")
        check_user_requests_limit(current_user)
        gpt_answer_generator: HeadlessQA | QABaseBrainPicking
        # TODO check if model is in the list of models available for the user

        gpt_answer_generator = chat_instance.get_answer_generator(
            chat_id=str(chat_id),
            max_tokens=chat_question.max_tokens,
            temperature=chat_question.temperature,  # type: ignore
            streaming=True,
            prompt_id=chat_question.prompt_id,
            brain_id=str(brain_id),
            user_id=current_user.id,
        )

        return StreamingResponse(
            gpt_answer_generator.generate_stream(chat_id, chat_question),
            media_type="text/event-stream",
        )

    except HTTPException as e:
        raise e


# get chat history
@chat_router.get(
    "/chat/{chat_id}/history", dependencies=[Depends(AuthBearer())], tags=["Chat"]
)
async def get_chat_history_handler(
    chat_id: UUID,
) -> List[ChatItem]:
    # TODO: RBAC with current_user
    return get_chat_history_with_notifications(chat_id)


@chat_router.post(
    "/chat/{chat_id}/question/answer",
    dependencies=[Depends(AuthBearer())],
    tags=["Chat"],
)
async def add_question_and_answer_handler(
    chat_id: UUID,
    question_and_answer: QuestionAndAnswer,
) -> Optional[Chat]:
    """
    Add a new question and anwser to the chat.
    """
    return add_question_and_answer(chat_id, question_and_answer)
