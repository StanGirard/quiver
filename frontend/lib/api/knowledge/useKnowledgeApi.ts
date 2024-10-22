import { UUID } from "crypto";

import { useAxios } from "@/lib/hooks";
import {
  AddFolderData,
  AddKnowledgeFileData,
  AddKnowledgeUrlData,
} from "@/lib/types/Knowledge";

import {
  addFolder,
  addKnowledgeFile,
  addKnowledgeUrl,
  deleteKnowledge,
  DeleteKnowledgeInputProps,
  generateSignedUrlKnowledge,
  getAllBrainKnowledge,
  GetAllKnowledgeInputProps,
  getFiles,
  linkKnowledgeToBrains,
  patchKnowledge,
  unlinkKnowledgeFromBrains,
} from "./knowledge";

import { KMSElement } from "../sync/types";

// eslint-disable-next-line @typescript-eslint/explicit-module-boundary-types
export const useKnowledgeApi = () => {
  const { axiosInstance } = useAxios();

  return {
    getAllBrainKnowledge: async (props: GetAllKnowledgeInputProps) =>
      getAllBrainKnowledge(props, axiosInstance),
    deleteKnowledge: async (props: DeleteKnowledgeInputProps) =>
      deleteKnowledge(props, axiosInstance),
    generateSignedUrlKnowledge: async (props: { knowledgeId: UUID }) =>
      generateSignedUrlKnowledge(props, axiosInstance),
    getFiles: async (parentId: UUID | null) =>
      getFiles(parentId, axiosInstance),
    addFolder: async (addFolderData: AddFolderData) =>
      addFolder(addFolderData, axiosInstance),
    addKnowledgeFile: async (
      addKnowledgeData: AddKnowledgeFileData,
      file: File
    ) => addKnowledgeFile(addKnowledgeData, file, axiosInstance),
    addKnowledgeUrl: async (addKnowledgeData: AddKnowledgeUrlData) =>
      addKnowledgeUrl(addKnowledgeData, axiosInstance),
    patchKnowledge: async (knowledgeId: UUID, parent_id: UUID | null) =>
      patchKnowledge(knowledgeId, axiosInstance, parent_id),
    linkKnowledgeToBrains: async (knowledge: KMSElement, brainIds: UUID[]) =>
      linkKnowledgeToBrains(knowledge, brainIds, axiosInstance),
    unlinkKnowledgeFromBrains: async (knowledge_id: UUID, brainIds: UUID[]) =>
      unlinkKnowledgeFromBrains(knowledge_id, brainIds, axiosInstance),
  };
};
