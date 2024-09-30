import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncGenerator, List, Optional, Tuple
from uuid import UUID

from quivr_api.logger import get_logger
from quivr_api.modules.knowledge.dto.inputs import KnowledgeUpdate
from quivr_api.modules.knowledge.entity.knowledge import KnowledgeDB, KnowledgeSource
from quivr_api.modules.sync.dto.outputs import SyncProvider
from quivr_api.modules.sync.entity.sync_models import Sync, SyncFile, SyncType
from quivr_core.files.file import QuivrFile
from quivr_core.models import KnowledgeStatus

from quivr_worker.parsers.crawler import URL, extract_from_url
from quivr_worker.process.process_file import parse_qfile, store_chunks
from quivr_worker.process.utils import (
    build_qfile,
    build_sync_file,
    compute_sha1,
    skip_process,
)
from quivr_worker.utils.services import ProcessorServices

logger = get_logger("celery_worker")


class KnowledgeProcessor:
    def __init__(self, services: ProcessorServices):
        self.services = services

    async def fetch_db_knowledges_and_syncprovider(
        self,
        sync_id: int,
        user_id: UUID,
        folder_id: str | None,
    ) -> Tuple[dict[str, KnowledgeDB], List[SyncFile] | None]:
        map_knowledges_task = self.services.knowledge_service.map_syncs_knowledge_user(
            sync_id=sync_id, user_id=user_id
        )
        sync_files_task = self.services.sync_service.get_files_folder_user_sync(
            sync_id,
            user_id,
            folder_id,
        )
        return await asyncio.gather(*[map_knowledges_task, sync_files_task])  # type: ignore  # noqa: F821

    async def yield_processable_knowledge(
        self, knowledge_id: UUID
    ) -> AsyncGenerator[Tuple[KnowledgeDB, QuivrFile] | None, None]:
        """Should only yield ready to process knowledges:
        Knowledge ready to process:
            - Is either Local or Sync
            - Is in a status: PROCESSING | ERROR
            - Has an associated QuivrFile that is parsable
        """
        knowledge = await self.services.knowledge_service.get_knowledge(knowledge_id)
        if knowledge.source == KnowledgeSource.LOCAL:
            async for to_process in self._yield_local(knowledge):
                yield to_process
        elif knowledge.source in (
            KnowledgeSource.AZURE,
            KnowledgeSource.GOOGLE,
            KnowledgeSource.DROPBOX,
            KnowledgeSource.GITHUB,
            # KnowledgeSource.NOTION,
        ):
            async for to_process in self._yield_syncs(knowledge):
                yield to_process
        elif knowledge.source == KnowledgeSource.WEB:
            async for to_process in self._yield_web(knowledge):
                yield to_process
        else:
            logger.error(
                f"received knowledge : {knowledge.id} with unknown source: {knowledge.source}"
            )
            raise ValueError(f"Unknown knowledge source : {knowledge.source}")

    async def _yield_local(
        self, knowledge: KnowledgeDB
    ) -> AsyncGenerator[Tuple[KnowledgeDB, QuivrFile] | None, None]:
        if knowledge.id is None or knowledge.file_name is None:
            logger.error(f"received unprocessable local knowledge : {knowledge.id} ")
            raise ValueError(
                f"received unprocessable local knowledge : {knowledge.id} "
            )
        if knowledge.is_folder:
            yield (
                knowledge,
                QuivrFile(
                    id=knowledge.id,
                    original_filename=knowledge.file_name,
                    file_extension=knowledge.extension,
                    file_sha1="",
                    path=Path(),
                ),
            )
        else:
            file_data = await self.services.knowledge_service.storage.download_file(
                knowledge
            )
            knowledge.file_sha1 = compute_sha1(file_data)
            with build_qfile(knowledge, file_data) as qfile:
                yield (knowledge, qfile)

    async def _yield_web(
        self, knowledge_db: KnowledgeDB
    ) -> AsyncGenerator[Tuple[KnowledgeDB, QuivrFile] | None, None]:
        if knowledge_db.id is None or knowledge_db.url is None:
            logger.error(f"received unprocessable web knowledge : {knowledge_db.id} ")
            raise ValueError(
                f"received unprocessable web knowledge : {knowledge_db.id} "
            )
        crawl_website = URL(url=knowledge_db.url)
        extracted_content = await extract_from_url(crawl_website)
        extracted_content_bytes = extracted_content.encode("utf-8")
        knowledge_db.file_sha1 = compute_sha1(extracted_content_bytes)
        knowledge_db.file_size = len(extracted_content_bytes)
        with build_qfile(knowledge_db, extracted_content_bytes) as qfile:
            yield (knowledge_db, qfile)

    async def _yield_syncs(
        self, parent_knowledge: KnowledgeDB
    ) -> AsyncGenerator[Optional[Tuple[KnowledgeDB, QuivrFile]], None]:
        if parent_knowledge.id is None:
            logger.error(f"received unprocessable knowledge: {parent_knowledge.id} ")
            raise ValueError

        if parent_knowledge.file_name is None:
            logger.error(f"received unprocessable knowledge : {parent_knowledge.id} ")
            raise ValueError(
                f"received unprocessable knowledge : {parent_knowledge.id} "
            )
        if (
            parent_knowledge.sync_file_id is None
            or parent_knowledge.sync_id is None
            or parent_knowledge.source_link is None
        ):
            logger.error(
                f"unprocessable  sync knowledge : {parent_knowledge.id}. no sync_file_id"
            )
            raise ValueError(
                f"received unprocessable knowledge : {parent_knowledge.id} "
            )
        # Get associated sync
        sync = await self.services.sync_service.get_sync_by_id(parent_knowledge.sync_id)
        if sync.credentials is None:
            logger.error(
                f"can't process knowledge: {parent_knowledge.id}. sync {sync.id} has no credentials"
            )
            raise ValueError("no associated credentials")

        provider_name = SyncProvider(sync.provider.lower())
        sync_provider = self.services.syncprovider_mapping[provider_name]

        # Yield parent_knowledge as the first knowledge to process
        async with build_sync_file(
            file_knowledge=parent_knowledge,
            sync=sync,
            sync_provider=sync_provider,
            sync_file=SyncFile(
                id=parent_knowledge.sync_file_id,
                name=parent_knowledge.file_name,
                extension=parent_knowledge.extension,
                web_view_link=parent_knowledge.source_link,
                is_folder=parent_knowledge.is_folder,
                last_modified_at=parent_knowledge.updated_at,
            ),
        ) as f:
            yield f

        # Fetch children
        (
            syncfile_to_knowledge,
            sync_files,
        ) = await self.fetch_db_knowledges_and_syncprovider(
            sync_id=parent_knowledge.sync_id,
            user_id=parent_knowledge.user_id,
            folder_id=parent_knowledge.sync_file_id,
        )
        if not sync_files:
            return

        for sync_file in sync_files:
            file_knowledge = (
                await self.services.knowledge_service.create_or_link_sync_knowledge(
                    syncfile_id_to_knowledge=syncfile_to_knowledge,
                    parent_knowledge=parent_knowledge,
                    sync_file=sync_file,
                )
            )
            if file_knowledge.status == KnowledgeStatus.PROCESSED:
                continue
            async with build_sync_file(
                file_knowledge=file_knowledge,
                sync=sync,
                sync_provider=sync_provider,
                sync_file=sync_file,
            ) as f:
                yield f

    async def process_knowledge(self, knowledge_id: UUID):
        async for knowledge_tuple in self.yield_processable_knowledge(knowledge_id):
            # FIXME(@AmineDiro) : nested transaction for making
            savepoint = (
                await self.services.knowledge_service.repository.session.begin_nested()
            )
            if knowledge_tuple is None:
                continue
            knowledge, qfile = knowledge_tuple
            try:
                await self._process_inner(knowledge=knowledge, qfile=qfile)
            except Exception as e:
                await savepoint.rollback()
                logger.error(f"Error processing knowledge {knowledge_id} : {e}")
                # FIXME: This one can also fail if knowledge was deleted
                await self.services.knowledge_service.update_knowledge(
                    knowledge,
                    KnowledgeUpdate(
                        status=KnowledgeStatus.ERROR,
                    ),
                )

    async def _process_inner(self, knowledge: KnowledgeDB, qfile: QuivrFile):
        if not skip_process(knowledge):
            chunks = await parse_qfile(qfile=qfile)
            await store_chunks(
                knowledge=knowledge,
                chunks=chunks,
                vector_service=self.services.vector_service,
            )
        last_synced_at = datetime.now(timezone.utc)
        await self.services.knowledge_service.update_knowledge(
            knowledge,
            KnowledgeUpdate(
                status=KnowledgeStatus.PROCESSED,
                file_sha1=knowledge.file_sha1,
                # Update sync
                last_synced_at=last_synced_at if knowledge.sync_id else None,
            ),
        )

    async def update_outdated_syncs_files(
        self, timedelta_hour: int = 8, batch_size: int = 1000
    ):
        last_time = datetime.now(timezone.utc) - timedelta(hours=timedelta_hour)
        km_sync_files = await self.services.knowledge_service.get_outdated_syncs(
            limit_time=last_time,
            batch_size=batch_size,
            km_sync_type=SyncType.FILE,
        )
        sync_cache: dict[int, Sync] = {}
        for km in km_sync_files:
            assert km.sync_id, "can only update sync files with sync_id"
            assert km.sync_file_id, "can only update sync files with sync_file_id "
            assert (
                km.last_synced_at
            ), "can only update sync files without a last_synced_at"
            if km.sync_id in sync_cache:
                sync = sync_cache[km.sync_id]
            else:
                sync = await self.services.sync_service.get_sync_by_id(km.sync_id)
                assert sync.id
                sync_cache[sync.id] = sync

            if sync.credentials is None:
                logger.error(
                    f"can't process knowledge: {km.id}. sync {sync.id} has no credentials"
                )
                raise ValueError("no associated credentials")
            provider_name = SyncProvider(sync.provider.lower())
            sync_provider = self.services.syncprovider_mapping[provider_name]
            try:
                new_sync_file = (
                    await sync_provider.aget_files_by_id(
                        credentials=sync.credentials, file_ids=[km.sync_file_id]
                    )
                )[0]
                if (
                    new_sync_file.last_modified_at
                    and new_sync_file.last_modified_at < km.last_synced_at
                ) or new_sync_file.last_modified_at is None:
                    # Create transaction
                    #   - Create new knowledge with brains and parent like the old one
                    # _process_knowledge
                    #   - Parse it + store the chunks
                    #   - Update the knowledge
                    #   - Remove the older knowledge
                    pass
                else:
                    continue

            except FileNotFoundError:
                # Remove has been deleted
                pass
