from uuid import UUID

from quivr_core.models import QuivrKnowledge as Knowledge

from quivr_api.logger import get_logger
from quivr_api.modules.knowledge.dto.inputs import (
    CreateKnowledgeProperties,
    KnowledgeStatus,
)
from quivr_api.modules.knowledge.repository.knowledges import KnowledgeRepository

logger = get_logger(__name__)


class KnowledgeService:
    def __init__(self):
        self.repository = KnowledgeRepository()

    def add_knowledge(self, knowledge_to_add: CreateKnowledgeProperties):
        knowledge = self.repository.insert_knowledge(knowledge_to_add)

        return knowledge

    def get_all_knowledge(self, brain_id: UUID):
        knowledges = self.repository.get_all_knowledge_in_brain(brain_id)

        return knowledges

    def update_status_knowledge(self, knowledge_id: UUID, status: KnowledgeStatus):
        knowledge = self.repository.update_status_knowledge(knowledge_id, status)

        return knowledge

    def get_knowledge(self, knowledge_id: UUID) -> Knowledge:
        knowledge = self.repository.get_knowledge_by_id(knowledge_id)

        return knowledge

    def remove_brain_all_knowledge(self, brain_id: UUID) -> None:
        self.repository.remove_brain_all_knowledge(brain_id)

        logger.info(
            f"All knowledge in brain {brain_id} removed successfully from table"
        )

    def remove_knowledge(self, knowledge_id: UUID):
        message = self.repository.remove_knowledge_by_id(knowledge_id)

        return message
