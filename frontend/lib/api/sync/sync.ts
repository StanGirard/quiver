import { AxiosInstance } from "axios";
import { UUID } from "crypto";

import { ActiveSync, KMSElement, OpenedConnection, Sync } from "./types";

const createFilesSettings = (files: KMSElement[]) =>
  files.filter((file) => !file.is_folder).map((file) => file.sync_file_id);

const createFoldersSettings = (files: KMSElement[]) =>
  files.filter((file) => file.is_folder).map((file) => file.sync_file_id);

export const syncGoogleDrive = async (
  name: string,
  axiosInstance: AxiosInstance
): Promise<{ authorization_url: string }> => {
  return (
    await axiosInstance.post<{ authorization_url: string }>(
      `/sync/google/authorize?name=${name}`
    )
  ).data;
};

export const syncSharepoint = async (
  name: string,
  axiosInstance: AxiosInstance
): Promise<{ authorization_url: string }> => {
  return (
    await axiosInstance.post<{ authorization_url: string }>(
      `/sync/azure/authorize?name=${name}`
    )
  ).data;
};

export const syncDropbox = async (
  name: string,
  axiosInstance: AxiosInstance
): Promise<{ authorization_url: string }> => {
  return (
    await axiosInstance.post<{ authorization_url: string }>(
      `/sync/dropbox/authorize?name=${name}`
    )
  ).data;
};

export const syncNotion = async (
  name: string,
  axiosInstance: AxiosInstance
): Promise<{ authorization_url: string }> => {
  return (
    await axiosInstance.post<{ authorization_url: string }>(
      `/sync/notion/authorize?name=${name}`
    )
  ).data;
};

export const getUserSyncs = async (
  axiosInstance: AxiosInstance
): Promise<Sync[]> => {
  return (await axiosInstance.get<Sync[]>("/sync")).data;
};

export const getSyncFiles = async (
  axiosInstance: AxiosInstance,
  userSyncId: number,
  folderId?: string
): Promise<KMSElement[]> => {
  const url = folderId
    ? `/sync/${userSyncId}/files?user_sync_id=${userSyncId}&folder_id=${folderId}`
    : `/sync/${userSyncId}/files?user_sync_id=${userSyncId}`;

  return (await axiosInstance.get<KMSElement[]>(url)).data;
};

export const syncFiles = async (
  axiosInstance: AxiosInstance,
  openedConnection: OpenedConnection,
  brainId: UUID
): Promise<void> => {
  return (
    await axiosInstance.post<void>(`/sync/active`, {
      name: openedConnection.name,
      syncs_user_id: openedConnection.user_sync_id,
      settings: {
        files: createFilesSettings(openedConnection.selectedFiles),
        folders: createFoldersSettings(openedConnection.selectedFiles),
      },
      brain_id: brainId,
    })
  ).data;
};

export const updateActiveSync = async (
  axiosInstance: AxiosInstance,
  openedConnection: OpenedConnection
): Promise<void> => {
  return (
    await axiosInstance.put<void>(`/sync/active/${openedConnection.id}`, {
      name: openedConnection.name,
      settings: {
        files: createFilesSettings(openedConnection.selectedFiles),
        folders: createFoldersSettings(openedConnection.selectedFiles),
      },
      last_synced: openedConnection.last_synced,
    })
  ).data;
};

export const deleteActiveSync = async (
  axiosInstance: AxiosInstance,
  syncId: number
): Promise<void> => {
  await axiosInstance.delete<void>(`/sync/active/${syncId}`);
};

export const getActiveSyncs = async (
  axiosInstance: AxiosInstance
): Promise<ActiveSync[]> => {
  return (await axiosInstance.get<ActiveSync[]>(`/sync/active`)).data;
};

export const deleteUserSync = async (
  axiosInstance: AxiosInstance,
  syncId: number
): Promise<void> => {
  return (await axiosInstance.delete<void>(`/sync/${syncId}`)).data;
};
