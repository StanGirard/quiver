import asyncio
import os
from typing import List, Tuple

import pytest
import pytest_asyncio
import sqlalchemy
from quivr_api.modules.brain.entity.brain_entity import Brain, BrainType
from quivr_api.modules.knowledge.dto.inputs import KnowledgeStatus
from quivr_api.modules.knowledge.entity.knowledge import KnowledgeDB
from quivr_api.modules.knowledge.entity.knowledge_brain import KnowledgeBrain
from quivr_api.modules.knowledge.repository.knowledges import KnowledgeRepository
from quivr_api.modules.knowledge.service.knowledge_service import KnowledgeService
from quivr_api.vector.entity.vector import Vector
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

pg_database_base_url = "postgres:postgres@localhost:54322/postgres"

TestData = Tuple[Brain, List[KnowledgeDB]]


@pytest.fixture(scope="session")
def event_loop(request: pytest.FixtureRequest):
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def async_engine():
    engine = create_async_engine(
        "postgresql+asyncpg://" + pg_database_base_url,
        echo=True if os.getenv("ORM_DEBUG") else False,
        future=True,
        pool_pre_ping=True,
        pool_size=10,
        pool_recycle=0.1,
    )
    yield engine


@pytest_asyncio.fixture()
async def session(async_engine):
    async with async_engine.connect() as conn:
        await conn.begin()
        await conn.begin_nested()
        async_session = AsyncSession(conn, expire_on_commit=False)

        @sqlalchemy.event.listens_for(
            async_session.sync_session, "after_transaction_end"
        )
        def end_savepoint(session, transaction):
            if conn.closed:
                return
            if not conn.in_nested_transaction():
                conn.sync_connection.begin_nested()

        yield async_session


@pytest_asyncio.fixture()
async def test_data(session: AsyncSession) -> TestData:
    # Brain data
    brain_1 = Brain(
        name="test_brain",
        description="this is a test brain",
        brain_type=BrainType.integration,
    )

    knowledge_brain_1 = KnowledgeDB(
        file_name="test_file_1",
        mime_type="txt",
        status="UPLOADED",
        source="test_source",
        source_link="test_source_link",
        file_size=100,
        file_sha1="test_sha1",
        brains=[brain_1],
    )

    knowledge_brain_2 = KnowledgeDB(
        file_name="test_file_2",
        mime_type="txt",
        status="UPLOADED",
        source="test_source",
        source_link="test_source_link",
        file_size=100,
        file_sha1="test_sha2",
        brains=[],
    )

    session.add(brain_1)
    session.add(knowledge_brain_1)
    session.add(knowledge_brain_2)
    await session.commit()
    return brain_1, [knowledge_brain_1, knowledge_brain_2]


@pytest.mark.asyncio
async def test_insert_knowledge(session: AsyncSession, test_data: TestData):
    brain, knowledges = test_data
    assert brain.brain_id

    new_knowledge = KnowledgeDB(
        file_name="test_file_3",
        mime_type="txt",
        status="UPLOADED",
        source="test_source",
        source_link="test_source_link",
        file_size=100,
        file_sha1="test_sha3",
        brains=[brain],
    )
    repo = KnowledgeRepository(session)
    created_knowledge = await repo.insert_knowledge(new_knowledge, brain.brain_id)
    assert created_knowledge.id
    knowledge = await repo.get_knowledge_by_id(created_knowledge.id)
    assert knowledge.file_name == new_knowledge.file_name


@pytest.mark.asyncio
async def test_updates_knowledge_status(session: AsyncSession, test_data: TestData):
    brain, knowledges = test_data
    assert brain.brain_id
    assert knowledges[0].id
    repo = KnowledgeRepository(session)
    await repo.update_status_knowledge(knowledges[0].id, KnowledgeStatus.ERROR)
    knowledge = await repo.get_knowledge_by_id(knowledges[0].id)
    assert knowledge.status == KnowledgeStatus.ERROR


@pytest.mark.asyncio
async def test_update_knowledge_source_link(session: AsyncSession, test_data: TestData):
    brain, knowledges = test_data
    assert brain.brain_id
    assert knowledges[0].id
    repo = KnowledgeRepository(session)
    await repo.update_source_link_knowledge(knowledges[0].id, "new_source_link")
    knowledge = await repo.get_knowledge_by_id(knowledges[0].id)
    assert knowledge.source_link == "new_source_link"


@pytest.mark.asyncio
async def test_remove_knowledge_from_brain(session: AsyncSession, test_data: TestData):
    brain, knowledges = test_data
    assert brain.brain_id
    assert knowledges[0].id
    repo = KnowledgeRepository(session)
    knowledge = await repo.remove_knowledge_from_brain(knowledges[0].id, brain.brain_id)
    assert brain.brain_id not in [
        b.brain_id for b in await knowledge.awaitable_attrs.brains
    ]


@pytest.mark.asyncio
async def test_cascade_remove_knowledge_by_id(
    session: AsyncSession, test_data: TestData
):
    brain, knowledges = test_data
    assert brain.brain_id
    assert knowledges[0].id
    repo = KnowledgeRepository(session)
    await repo.remove_knowledge_by_id(knowledges[0].id)
    with pytest.raises(NoResultFound):
        await repo.get_knowledge_by_id(knowledges[0].id)

    query = select(KnowledgeBrain).where(
        KnowledgeBrain.knowledge_id == knowledges[0].id
    )
    result = await session.exec(query)
    knowledge_brain = result.first()
    assert knowledge_brain is None

    query = select(Vector).where(Vector.knowledge_id == knowledges[0].id)
    result = await session.exec(query)
    vector = result.first()
    assert vector is None


@pytest.mark.asyncio
async def test_remove_all_knowledges_from_brain(
    session: AsyncSession, test_data: TestData
):
    brain, knowledges = test_data
    assert brain.brain_id

    # supabase_client = get_supabase_client()
    # db = supabase_client
    # storage = db.storage.from_("quivr")

    # storage.upload(f"{brain.brain_id}/test_file_1", b"test_content")

    repo = KnowledgeRepository(session)
    service = KnowledgeService(repo)
    await repo.remove_all_knowledges_from_brain(brain.brain_id)
    knowledges = await service.get_all_knowledge_in_brain(brain.brain_id)
    assert len(knowledges) == 0

    # response = storage.list(path=f"{brain.brain_id}")
    # assert response == []
    # FIXME @aminediro &chloedia raise an error when trying to interact with storage UnboundLocalError: cannot access local variable 'response' where it is not associated with a value


@pytest.mark.asyncio
async def test_duplicate_sha1_knowledge(session: AsyncSession, test_data: TestData):
    brain, knowledges = test_data
    assert brain.brain_id
    assert knowledges[0].id
    repo = KnowledgeRepository(session)
    knowledge = KnowledgeDB(
        file_name="test_file_2",
        mime_type="txt",
        status="UPLOADED",
        source="test_source",
        source_link="test_source_link",
        file_size=100,
        file_sha1="test_sha1",
        brains=[brain],
    )

    with pytest.raises(IntegrityError):  # FIXME: Should raise IntegrityError
        await repo.insert_knowledge(knowledge, brain.brain_id)


@pytest.mark.asyncio
async def test_add_knowledge_to_brain(session: AsyncSession, test_data: TestData):
    brain, knowledges = test_data
    assert brain.brain_id
    assert knowledges[1].id
    repo = KnowledgeRepository(session)
    await repo.link_to_brain(knowledges[1].id, brain.brain_id)
    knowledge = await repo.get_knowledge_by_id(knowledges[1].id)
    brains_of_knowledge = [b.brain_id for b in await knowledge.awaitable_attrs.brains]
    assert brain.brain_id in brains_of_knowledge

    query = select(KnowledgeBrain).where(
        KnowledgeBrain.knowledge_id == knowledges[0].id
        and KnowledgeBrain.brain_id == brain.brain_id
    )
    result = await session.exec(query)
    knowledge_brain = result.first()
    assert knowledge_brain


# Knowledge Service
@pytest.mark.asyncio
async def test_get_knowledge_in_brain(session: AsyncSession, test_data: TestData):
    brain, knowledges = test_data
    assert brain.brain_id
    repo = KnowledgeRepository(session)
    service = KnowledgeService(repo)
    list_knowledge = await service.get_all_knowledge_in_brain(brain.brain_id)
    assert len(list_knowledge) == 1
    brains_of_knowledge = [
        b.brain_id for b in await knowledges[0].awaitable_attrs.brains
    ]
    assert list_knowledge[0].id == knowledges[0].id
    assert list_knowledge[0].file_name == knowledges[0].file_name
    assert brain.brain_id in brains_of_knowledge
